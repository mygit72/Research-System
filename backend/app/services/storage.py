"""File storage behind an interface (local disk now; S3-compatible later).

Keys are opaque relative paths stored on `document_versions.storage_key`;
derived artifacts (thumbnails, rendered pages) live under a per-version cache
prefix and can always be regenerated.
"""

from __future__ import annotations

import hashlib
import shutil
import uuid
from pathlib import Path
from typing import Protocol

from app.core.config import Settings


class FileStorage(Protocol):
    def save(self, source: Path, key: str) -> None: ...
    def path(self, key: str) -> Path: ...
    def delete(self, key: str) -> None: ...
    def derived_dir(self, version_id: uuid.UUID) -> Path: ...
    def delete_derived(self, version_id: uuid.UUID) -> None: ...


class LocalFileStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):  # defence against path traversal
            raise ValueError("invalid storage key")
        return path

    def save(self, source: Path, key: str) -> None:
        target = self._resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    def path(self, key: str) -> Path:
        return self._resolve(key)

    def delete(self, key: str) -> None:
        self._resolve(key).unlink(missing_ok=True)

    def derived_dir(self, version_id: uuid.UUID) -> Path:
        return self._resolve(f"derived/{version_id}")

    def delete_derived(self, version_id: uuid.UUID) -> None:
        shutil.rmtree(self.derived_dir(version_id), ignore_errors=True)


def storage_key(user_id: uuid.UUID, version_id: uuid.UUID, extension: str) -> str:
    return f"documents/{user_id}/{version_id}{extension}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


_storage: FileStorage | None = None


def get_storage(settings: Settings) -> FileStorage:
    global _storage
    if _storage is None or (
        isinstance(_storage, LocalFileStorage) and _storage.root != settings.storage_dir.resolve()
    ):
        _storage = LocalFileStorage(settings.storage_dir)
    return _storage
