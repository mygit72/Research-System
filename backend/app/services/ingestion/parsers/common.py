"""Helpers shared by several parsers."""

from __future__ import annotations

import re

CAPTION_RE = re.compile(r"^(figure|fig\.?|table|algorithm)\s*([0-9]+|[ivxlc]+)\s*[:.|—-]", re.I)


def table_to_markdown(rows: list[list[str]]) -> str:
    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]

    def fmt(row: list[str]) -> str:
        return "| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |"

    lines = [fmt(padded[0]), "| " + " | ".join(["---"] * width) + " |"]
    lines.extend(fmt(row) for row in padded[1:])
    return "\n".join(lines)
