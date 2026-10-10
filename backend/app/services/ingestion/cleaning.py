"""Deterministic text normalization applied to every extracted block.

Never used on equations: mathematical expressions are kept verbatim.
"""

from __future__ import annotations

import re
import unicodedata

_LIGATURES = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬅ": "st",
    "ﬆ": "st",
}
_LIGATURE_RE = re.compile("|".join(_LIGATURES))
# "trans-\nformer" -> "transformer" (only when a lowercase letter follows).
_HYPHEN_BREAK = re.compile(r"(\w)[-­]\s*\n\s*([a-z])")
_SOFT_HYPHEN = re.compile("­")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SPACES = re.compile(r"[ \t  -​  　]+")


def clean_text(text: str) -> str:
    """Fix ligatures, hyphenated line breaks, control chars and whitespace."""
    text = _LIGATURE_RE.sub(lambda m: _LIGATURES[m.group(0)], text)
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    text = _SOFT_HYPHEN.sub("", text)
    text = _CONTROL.sub("", text)
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Line breaks inside a block are soft wraps.
    text = re.sub(r"\s*\n\s*", " ", text)
    return _SPACES.sub(" ", text).strip()


def normalize_title(title: str) -> str:
    """Canonical form used for duplicate detection."""
    title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    title = re.sub(r"[^a-z0-9]+", " ", title.lower())
    return re.sub(r"\s+", " ", title).strip()
