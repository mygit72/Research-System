"""Server-side page rendering (PNG) for thumbnails and the document reader."""

from __future__ import annotations

from pathlib import Path

from app.services.ingestion.native import pymupdf

ALLOWED_WIDTHS = (240, 480, 800, 1200, 1600)


def snap_width(width: int) -> int:
    """Restrict render sizes to a few buckets so the cache stays small."""
    return min(ALLOWED_WIDTHS, key=lambda w: abs(w - width))


def render_page_png(pdf_path: Path, page_number: int, width: int) -> bytes:
    with pymupdf.open(pdf_path) as doc:
        if not 1 <= page_number <= doc.page_count:
            raise IndexError(page_number)
        page = doc[page_number - 1]
        scale = width / page.rect.width
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        return pixmap.tobytes("png")


def cached_page_png(pdf_path: Path, cache_dir: Path, page_number: int, width: int) -> Path:
    width = snap_width(width)
    target = cache_dir / f"page-{page_number}-w{width}.png"
    if not target.exists():
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(render_page_png(pdf_path, page_number, width))
        tmp.replace(target)  # atomic: concurrent readers never see partial files
    return target


def cached_thumbnail_png(pdf_path: Path, cache_dir: Path) -> Path:
    """Same cache contract as `cached_page_png`, for the page-1 thumbnail.

    Lets the thumbnail endpoint regenerate `thumb.png` on demand (it's a derived
    cache file, same as a rendered page) instead of 404ing whenever it's missing
    even though the original PDF it's generated from is right there.
    """
    target = cache_dir / "thumb.png"
    if not target.exists():
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(render_page_png(pdf_path, 1, 320))
        tmp.replace(target)
    return target
