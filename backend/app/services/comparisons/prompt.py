"""The overview prompt: written from the finished comparison table, citing its passages."""

from __future__ import annotations

from app.services.llm import Message
from app.services.summaries.prompt import answer_format
from app.services.summaries.spec import NOT_REPORTED, Field

SYSTEM_PROMPT = f"""You compare research papers for a researcher, using ONLY the comparison table you are given.

Rules:
- Refer to the papers as Paper A, Paper B, and so on.
- End every sentence with the numbers of the passages that support it, just before the full stop, like this: "<statement about Paper A> [2]." Use only numbers that appear in the table.
- Never add outside knowledge, and never invent numbers or results. "{NOT_REPORTED}" means the paper does not say; do not guess it.
- Write the field on its own line, starting with its label, like "OVERVIEW: …"."""


def letter(index: int) -> str:
    return chr(ord("A") + index)


def overview_messages(
    papers: list[tuple[str, int | None]],
    rows: list[tuple[str, list[str]]],
    field: Field,
) -> list[Message]:
    """papers: (title, year) in column order; rows: (row title, cell text per paper)."""
    names = "\n".join(
        f"Paper {letter(i)}: {title}" + (f" ({year})" if year else "")
        for i, (title, year) in enumerate(papers)
    )
    table = "\n".join(
        f"{title}: "
        + " | ".join(f"Paper {letter(i)}: {' '.join(text.split())}" for i, text in enumerate(cells))
        for title, cells in rows
    )
    user = (
        f"Papers compared:\n{names}\n\nComparison table (the numbers refer to passages of the "
        f"papers):\n{table}\n\nFields:\n{field.label}: {field.question}\n\n{answer_format([field])}"
    )
    return [Message("system", SYSTEM_PROMPT), Message("user", user)]
