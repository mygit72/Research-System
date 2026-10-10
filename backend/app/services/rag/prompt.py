"""Prompt construction: numbered evidence blocks + strict grounding and citation rules."""

from __future__ import annotations

from app.services.llm import INSUFFICIENT, Message
from app.services.rag.context import Evidence

# rag-v3: the citation example is a placeholder. A real-looking example sentence was copied
# into answers by the 3B model; measured on summaries (2 runs x 4 groups): placeholder 100% of
# fields cited, a meta sentence ("This sentence is backed by passage 2") only 68%.
PROMPT_VERSION = "rag-v3"

SYSTEM_PROMPT = f"""You are a research assistant. Answer the user's question using ONLY the numbered evidence passages from their papers.

Rules:
- End every sentence that states a fact with the number of the passage that supports it, placed just before the full stop, like this: "<statement from passage 2> [2]." Never start a sentence with a number. Use only numbers that appear in the evidence.
- Use only the evidence. Do not add outside knowledge, and never invent numbers, results or paper details.
- If the evidence does not answer the question, reply with exactly: "{INSUFFICIENT}" and, if useful, one sentence about what the evidence does cover.
- When several papers are involved, say which paper each point comes from.
- Be concise: a few sentences, or a short bulleted list for comparisons."""


def evidence_block(evidence: Evidence) -> str:
    result = evidence.result
    document = result.document
    year = f" ({document.year})" if document.year else ""
    section = result.chunk.section_title or "Front matter"
    return (
        f"[{evidence.number}] {document.title}{year} — {section}, p. {result.chunk.page_start}\n"
        f"{' '.join(result.chunk.text.split())}"
    )


def build_messages(
    question: str,
    evidence: list[Evidence],
    history: list[tuple[str, str]],
) -> list[Message]:
    """history: previous (question, answer) pairs, oldest first."""
    messages = [Message("system", SYSTEM_PROMPT)]
    for previous_question, previous_answer in history:
        messages.append(Message("user", previous_question))
        messages.append(Message("assistant", previous_answer))
    blocks = "\n\n".join(evidence_block(e) for e in evidence)
    messages.append(Message("user", f"Evidence:\n{blocks}\n\nQuestion: {question}"))
    return messages
