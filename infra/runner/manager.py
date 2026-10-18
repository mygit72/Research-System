"""Internal HTTP service that launches disposable, resource-limited code containers."""

from __future__ import annotations

import hmac
import importlib.metadata
import io
import json
import os
import re
import sys
import tarfile
import threading
import time
from typing import Any

import docker
from docker.errors import DockerException, NotFound
from docker.types import LogConfig, Ulimit
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(
    title="Research project sandbox",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
IMAGE = os.getenv("RUNNER_IMAGE", "research-project-runner:local")
TOKEN = os.getenv("RUNNER_TOKEN", "")
MAX_FILES_BYTES = 900_000
RUN_TIMEOUT_SECONDS = 40
LOG_LIMIT = 48_000
CAPACITY = threading.BoundedSemaphore(2)
ALLOWED_FILES = {
    "README.md",
    "config.json",
    "systems.py",
    "model.py",
    "components.py",
    "generation.py",
    "metrics.py",
    "data.py",
    "run_experiments.py",
    "requirements.txt",
    "test_pipeline.py",
}


class RunRequest(BaseModel):
    files: dict[str, str] = Field(min_length=1, max_length=len(ALLOWED_FILES))


def _archive(files: dict[str, str]) -> bytes:
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w") as archive:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            encoded = content.encode("utf-8")
            info.size = len(encoded)
            info.mode = 0o444
            info.uid = info.gid = 65534
            info.uname = info.gname = "nobody"
            archive.addfile(info, io.BytesIO(encoded))
    return data.getvalue()


def _read_archive_file(container: Any, path: str, limit: int = LOG_LIMIT) -> str:
    try:
        stream, _ = container.get_archive(path)
    except NotFound:
        return ""
    raw = b"".join(stream)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:*") as archive:
        member = next((item for item in archive.getmembers() if item.isfile()), None)
        if member is None:
            return ""
        handle = archive.extractfile(member)
        if handle is None:
            return ""
        content = handle.read(limit + 1)
    text = content[:limit].decode("utf-8", errors="replace")
    return text + "\n[output truncated]" if len(content) > limit else text


def _run_container(files: dict[str, str]) -> dict[str, Any]:
    client = docker.from_env(timeout=5)
    container = None
    started = time.monotonic()
    timed_out = False
    exit_code = 1
    try:
        image = client.images.get(IMAGE)
        container = client.containers.create(
            image=IMAGE,
            command=["python", "-I", "-S", "/opt/runner/execute.py"],
            working_dir="/workspace",
            user="65534:65534",
            environment={"HOME": "/tmp", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"},
            network_mode="none",
            read_only=True,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            pids_limit=64,
            mem_limit="1g",
            memswap_limit="1g",
            nano_cpus=1_000_000_000,
            ulimits=[
                Ulimit(name="nofile", soft=128, hard=256),
                Ulimit(name="fsize", soft=MAX_FILES_BYTES, hard=MAX_FILES_BYTES),
                Ulimit(name="core", soft=0, hard=0),
            ],
            tmpfs={
                "/workspace": "rw,nosuid,nodev,noexec,size=32m,uid=65534,gid=65534",
                "/tmp": "rw,nosuid,nodev,noexec,size=8m,uid=65534,gid=65534",
            },
            log_config=LogConfig(type="none"),
            init=True,
            detach=True,
        )
        if not container.put_archive("/workspace", _archive(files)):
            raise RuntimeError("Could not copy the project files into the sandbox.")
        container.start()
        deadline = started + RUN_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            container.reload()
            if container.status in {"exited", "dead"}:
                exit_code = int(container.attrs.get("State", {}).get("ExitCode", 1))
                break
            time.sleep(0.25)
        else:
            timed_out = True
            container.kill()
            container.wait(timeout=5)
            exit_code = 124
        stdout = _read_archive_file(container, "/workspace/results/run.log")
        stderr = _read_archive_file(container, "/workspace/results/run.error.log")
        summary = _read_archive_file(container, "/workspace/results/summary.md")
        results_csv = _read_archive_file(container, "/workspace/results/results.csv", 128_000)
        results_csv_truncated = results_csv.endswith("[output truncated]")
        if results_csv_truncated:
            results_csv = ""
        predictions_jsonl = ""
        try:
            config = json.loads(files["config.json"])
            main_experiment = next(
                (item for item in config.get("experiments", []) if item.get("kind") == "main"),
                None,
            )
            key = main_experiment.get("key", "") if main_experiment else "toy"
            if isinstance(key, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", key):
                predictions_jsonl = _read_archive_file(
                    container, f"/workspace/results/predictions_{key}.jsonl", 128_000
                )
        except (AttributeError, TypeError, ValueError):
            pass
        predictions_jsonl_truncated = predictions_jsonl.endswith("[output truncated]")
        if predictions_jsonl_truncated:
            predictions_jsonl = ""
        if timed_out:
            stderr = (stderr + "\n" if stderr else "") + (
                f"Run stopped after the {RUN_TIMEOUT_SECONDS}-second sandbox time limit."
            )
        return {
            "exit_code": exit_code,
            "timed_out": timed_out,
            "duration_ms": round((time.monotonic() - started) * 1000),
            "python_version": sys.version.split()[0],
            "image_digest": image.id,
            "packages": sorted(
                f"{distribution.metadata['Name']}=={distribution.version}"
                for distribution in importlib.metadata.distributions()
                if distribution.metadata.get("Name")
            ),
            "stdout": stdout,
            "stderr": stderr,
            "summary": summary,
            "results_csv": results_csv,
            "results_csv_truncated": results_csv_truncated,
            "predictions_jsonl": predictions_jsonl,
            "predictions_jsonl_truncated": predictions_jsonl_truncated,
        }
    finally:
        try:
            if container is not None:
                container.remove(force=True)
        finally:
            client.close()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/run-toy")
def run_toy(
    request: RunRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    if not TOKEN or not authorization or not hmac.compare_digest(
        authorization, f"Bearer {TOKEN}"
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not set(request.files).issubset(ALLOWED_FILES):
        raise HTTPException(status_code=422, detail="Unknown project file")
    if "run_experiments.py" not in request.files or "config.json" not in request.files:
        raise HTTPException(status_code=422, detail="Project runner files are missing")
    total_bytes = sum(len(value.encode("utf-8")) for value in request.files.values())
    if total_bytes > MAX_FILES_BYTES:
        raise HTTPException(status_code=413, detail="Project files exceed the runner limit")
    if not CAPACITY.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="The runner is busy")
    try:
        try:
            return _run_container(request.files)
        except (DockerException, RuntimeError, OSError) as exc:
            raise HTTPException(
                status_code=503,
                detail="The sandbox could not start. Check the runner image and Docker daemon.",
            ) from exc
    finally:
        CAPACITY.release()
