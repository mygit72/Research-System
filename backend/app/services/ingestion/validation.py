"""Upload validation: size, extension allow-list, content sniffing, filename sanitization.

The extension is only a claim; the bytes must agree (a `.pdf` that is really a
ZIP or an executable is rejected). Errors carry user-facing messages.
"""

from __future__ import annotations

import re
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path

from app.core.errors import ValidationError
from app.services.ingestion.types import DocumentFormat

EXTENSIONS: dict[str, DocumentFormat] = {
    ".pdf": DocumentFormat.PDF,
    ".docx": DocumentFormat.DOCX,
    ".html": DocumentFormat.HTML,
    ".htm": DocumentFormat.HTML,
    ".md": DocumentFormat.MARKDOWN,
    ".markdown": DocumentFormat.MARKDOWN,
    ".txt": DocumentFormat.TEXT,
}

MIME_TYPES: dict[DocumentFormat, str] = {
    DocumentFormat.PDF: "application/pdf",
    DocumentFormat.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    DocumentFormat.HTML: "text/html",
    DocumentFormat.MARKDOWN: "text/markdown",
    DocumentFormat.TEXT: "text/plain",
}

ACCEPTED_FORMATS_LABEL = "PDF, DOCX, TXT, Markdown or HTML"
_HTML_HINT = re.compile(rb"<\s*(!doctype\s+html|html|head|body|p|div|h[1-6]|article)\b", re.I)


@dataclass(frozen=True, slots=True)
class ValidatedFile:
    filename: str
    format: DocumentFormat
    mime_type: str
    size: int


def sanitize_filename(name: str, max_length: int = 180) -> str:
    """Strip paths, control and reserved characters; keep the extension."""
    name = unicodedata.normalize("NFKC", name or "")
    name = re.split(r"[\\/]", name)[-1]
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C")
    name = re.sub(r'[<>:"|?*\x00]', "_", name).strip(" .")
    if not name:
        name = "document"
    stem, dot, ext = name.rpartition(".")
    if dot and len(ext) <= 10:
        return stem[: max_length - len(ext) - 1].rstrip() + "." + ext
    return name[:max_length]


def _looks_like_text(head: bytes) -> bool:
    if b"\x00" in head and not head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return False
    for encoding in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            head.decode(encoding)
            return True
        except UnicodeDecodeError:
            continue
    return False


# A .docx is a zip: a small upload can unpack to gigabytes ("zip bomb") that the parser
# would load into memory. Real papers unpack to a few MB at ratios well under 100:1.
MAX_DOCX_UNPACKED_BYTES = 200 * 1024 * 1024
MAX_DOCX_RATIO = 100


def _is_docx(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            return "word/document.xml" in archive.namelist()
    except (zipfile.BadZipFile, OSError):
        return False


def _docx_too_large(path: Path, max_unpacked: int) -> bool:
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
    unpacked = sum(m.file_size for m in members)
    worst = max((m.file_size / max(m.compress_size, 1) for m in members), default=0)
    return unpacked > max_unpacked or worst > MAX_DOCX_RATIO


def validate_upload(
    path: Path,
    original_name: str,
    max_size_bytes: int,
    max_docx_unpacked: int = MAX_DOCX_UNPACKED_BYTES,
) -> ValidatedFile:
    filename = sanitize_filename(original_name)
    extension = Path(filename).suffix.lower()
    fmt = EXTENSIONS.get(extension)
    if fmt is None:
        raise ValidationError(
            f"“{filename}” isn't a supported file type.",
            hint=f"Upload {ACCEPTED_FORMATS_LABEL} files.",
        )
    size = path.stat().st_size
    if size == 0:
        raise ValidationError(f"“{filename}” is empty.", hint="Check the file and try again.")
    if size > max_size_bytes:
        limit_mb = max_size_bytes // (1024 * 1024)
        raise ValidationError(
            f"“{filename}” is larger than the {limit_mb} MB limit.",
            hint="Try a compressed version, or ask an administrator to raise the limit.",
        )

    with path.open("rb") as handle:
        head = handle.read(8192)

    ok = {
        DocumentFormat.PDF: lambda: b"%PDF-" in head[:1024],
        DocumentFormat.DOCX: lambda: head.startswith(b"PK\x03\x04") and _is_docx(path),
        DocumentFormat.HTML: lambda: _looks_like_text(head) and bool(_HTML_HINT.search(head)),
        DocumentFormat.MARKDOWN: lambda: _looks_like_text(head),
        DocumentFormat.TEXT: lambda: _looks_like_text(head),
    }[fmt]()
    if not ok:
        raise ValidationError(
            f"“{filename}” doesn't look like a valid {fmt.value.upper()} file.",
            hint="The file may be corrupted, or its extension may not match its contents.",
        )
    if fmt == DocumentFormat.DOCX and _docx_too_large(path, max_docx_unpacked):
        raise ValidationError(
            f"“{filename}” unpacks to far more data than a document should.",
            hint="Save it again from your word processor, or upload it as a PDF.",
        )
    return ValidatedFile(filename=filename, format=fmt, mime_type=MIME_TYPES[fmt], size=size)
