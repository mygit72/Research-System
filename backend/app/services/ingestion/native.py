"""Single import point for PyMuPDF (DLL setup happens in `app/__init__.py`)."""

from __future__ import annotations

import pymupdf

pymupdf.TOOLS.mupdf_display_errors(False)  # we surface problems ourselves

__all__ = ["pymupdf"]
