"""Small text helpers shared by the analysis steps."""

from __future__ import annotations


def shorten(text: str, limit: int) -> str:
    """Cut at a word boundary with an ellipsis, so titles never end mid-word ("…without label")."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if " " in cut and not text[limit - 1].isspace():
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:-–—") + "…"
