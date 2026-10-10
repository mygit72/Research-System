"""API server for the browser end-to-end tests (frontend/e2e).

A fresh SQLite database and file store in a temporary directory, migrated with Alembic, and
the deterministic providers the API tests use: hashing embeddings, the extractive "fake"
language model and the word-overlap verifier — no model downloads, same results every run.

    python scripts/e2e_server.py            # serves on :8010

`E2E_ENV` (a JSON object of settings) changes that configuration for one run, e.g. a site
with the shared free model (frontend/playwright.free.config.ts).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
work = Path(tempfile.mkdtemp(prefix="ri-e2e-"))
os.environ.update(
    {
        "NO_ENV_FILE": "1",  # not the developer's own .env (their model, their key)
        "ENVIRONMENT": "test",
        "DATABASE_URL": f"sqlite+aiosqlite:///{(work / 'e2e.db').as_posix()}",
        "STORAGE_DIR": str(work / "files"),
        "JOB_BACKEND": "inline",
        "JWT_SECRET": "e2e-secret-e2e-secret-e2e-secret-1234",
        "RATE_LIMIT_ENABLED": "false",
        "EMBEDDING_PROVIDER": "hashing",
        "RERANKER_PROVIDER": "none",
        "LLM_PROVIDER": "fake",
        "VERIFIER_PROVIDER": "lexical",
        "SUMMARY_AUTO": "false",
        "WARM_MODELS_ON_STARTUP": "false",
        "LOG_LEVEL": "WARNING",
    }
)
os.environ.update(json.loads(os.environ.get("E2E_ENV", "{}")))
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

from alembic.config import Config  # noqa: E402

from alembic import command  # noqa: E402

command.upgrade(Config(str(BACKEND / "alembic.ini")), "head")

import uvicorn  # noqa: E402

uvicorn.run("app.main:app", host="127.0.0.1", port=int(os.environ.get("E2E_API_PORT", "8010")))
