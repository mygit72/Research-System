"""Fixed launcher used inside disposable project-runner containers."""

from __future__ import annotations

import io
import os
import runpy
import site
import sys
import traceback
from pathlib import Path


class BoundedText(io.TextIOBase):
    def __init__(self, limit: int = 24_000) -> None:
        self.limit = limit
        self.parts: list[str] = []
        self.size = 0
        self.truncated = False

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        if not isinstance(text, str):
            raise TypeError("write() argument must be str")
        remaining = self.limit - self.size
        if remaining > 0:
            kept = text[:remaining]
            self.parts.append(kept)
            self.size += len(kept)
        if len(text) > remaining:
            self.truncated = True
        return len(text)

    def getvalue(self) -> str:
        suffix = "\n[output truncated]\n" if self.truncated else ""
        return "".join(self.parts) + suffix


def main() -> int:
    root = Path("/workspace")
    os.chdir(root)
    # -I -S starts Python without the current directory, environment paths or site imports.
    # Add only the submitted workspace and installed runtime packages back explicitly.
    sys.path[:] = [str(root), *sys.path, *site.getsitepackages()]
    sys.argv = [str(root / "run_experiments.py"), "--toy"]
    stdout, stderr = BoundedText(), BoundedText()
    exit_code = 0
    try:
        sys.stdout, sys.stderr = stdout, stderr
        runpy.run_path(str(root / "run_experiments.py"), run_name="__main__")
    except SystemExit as exc:
        code = exc.code
        exit_code = code if isinstance(code, int) else (0 if code is None else 1)
        if code not in (None, 0):
            print(str(code), file=stderr)
    except BaseException:  # noqa: BLE001 - keep user-code failures in the run record
        exit_code = 1
        traceback.print_exc(file=stderr)
    finally:
        sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__

    output = root / "results"
    output.mkdir(exist_ok=True)
    (output / "run.log").write_text(stdout.getvalue(), encoding="utf-8")
    (output / "run.error.log").write_text(stderr.getvalue(), encoding="utf-8")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
