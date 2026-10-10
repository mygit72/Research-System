"""Importing a folder of papers as a .zip.

Nothing in the archive is ever written to disk under its own name — entry names are used only as
display names (their last path segment) — so a name like ``../../x`` can't escape anywhere. Each
paper then goes through the ordinary upload path (type, size and content checks included).

Defences against hostile archives, because the sizes a zip declares are the sender's claim:

* at most ``MAX_ENTRIES`` papers per archive;
* a per-entry size limit and a total limit on bytes *actually read* (not on declared sizes);
* entries that expand by more than ``MAX_RATIO`` are skipped;
* password-protected entries and nested archives are skipped, never opened.

Everything left out is reported with a reason, so a missing paper never goes unexplained.
"""

from __future__ import annotations

import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import IO

from app.services.ingestion.validation import EXTENSIONS

MAX_ENTRIES = 100
MAX_RATIO = 100  # an entry that expands more than this is treated as a zip bomb
RATIO_CHECK_FROM = 1024 * 1024  # small entries compress absurdly well legitimately (e.g. text)
TOTAL_FACTOR = 20  # total bytes read at most this many times the per-file limit
CHUNK = 1024 * 256
ARCHIVES = {".zip", ".7z", ".rar", ".tar", ".gz", ".tgz"}


@dataclass
class Skipped:
    filename: str
    reason: str


def display_name(entry_name: str) -> str:
    """The file's own name: the last segment only, whatever separators the archive used."""
    return PurePosixPath(entry_name.replace("\\", "/")).name


def _extension(name: str) -> str:
    return PurePosixPath(name.lower()).suffix


def plan(
    archive: zipfile.ZipFile, per_file_limit: int
) -> tuple[list[zipfile.ZipInfo], list[Skipped]]:
    """Which entries to import, and which are left out (with why)."""
    chosen: list[zipfile.ZipInfo] = []
    skipped: list[Skipped] = []
    for info in archive.infolist():
        if info.is_dir():
            continue
        name = display_name(info.filename)
        parts = info.filename.replace("\\", "/").split("/")
        if not name or name.startswith((".", "~$")) or "__MACOSX" in parts:
            continue  # system litter, not worth a line in the report
        extension = _extension(name)
        if extension in ARCHIVES:
            skipped.append(Skipped(name, "Archives inside archives aren't opened."))
        elif extension not in EXTENSIONS:
            skipped.append(
                Skipped(name, "Not a supported file type (PDF, DOCX, HTML, Markdown, text).")
            )
        elif info.flag_bits & 0x1:
            skipped.append(Skipped(name, "Password-protected."))
        elif info.file_size > per_file_limit:
            skipped.append(Skipped(name, f"Larger than the {per_file_limit // 1024**2} MB limit."))
        elif (
            info.file_size > RATIO_CHECK_FROM
            and info.compress_size
            and info.file_size / info.compress_size > MAX_RATIO
        ):
            skipped.append(Skipped(name, "Expands suspiciously much when unpacked."))
        else:
            chosen.append(info)
    return chosen, skipped


class Budget:
    """Bytes actually read across the whole archive."""

    def __init__(self, total: int) -> None:
        self.left = total


def read_entry(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo, per_file_limit: int, budget: Budget
) -> IO[bytes] | str:
    """The entry's bytes in a spooled temp file, or the reason it was refused. Counts what is
    really read, so an entry that lies about its size still hits the limits."""
    spooled = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)  # noqa: SIM115
    size = 0
    try:
        with archive.open(info) as source:
            while chunk := source.read(CHUNK):
                size += len(chunk)
                if size > per_file_limit:
                    spooled.close()
                    return f"Larger than the {per_file_limit // 1024**2} MB limit."
                if size > budget.left:
                    spooled.close()
                    return "The archive is too large to unpack in full."
                spooled.write(chunk)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError) as exc:
        spooled.close()
        return f"Couldn't be unpacked ({exc.__class__.__name__})."
    budget.left -= size
    spooled.seek(0)
    return spooled
