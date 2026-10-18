"""Prompt construction: numbered evidence blocks + strict grounding and citation rules."""

from __future__ import annotations

import re

from app.services.llm import Message
from app.services.rag.context import Evidence

# rag-v10: code requests get implementation guidance and an optional local coder model.
PROMPT_VERSION = "rag-v10"
PAPER_CHAT_PROMPT_VERSION = f"{PROMPT_VERSION}-paper-chat-v7"

SYSTEM_PROMPT = """You are a helpful, general-purpose assistant in a research workspace. The user can ask about any subject. You may also receive numbered passages from papers in their library; those passages can support paper-specific answers, but may be empty or unrelated.

Rules:
- Answer the user's question directly, including ordinary questions unrelated to their papers. Do not refuse a general question just because the evidence is empty or irrelevant.
- Use paper passages as sources only for claims about what a paper, its authors, or its experiments say. End each such factual sentence with the supporting passage number, like "<paper-specific statement> [2]." Use only numbers in the evidence.
- For a general answer, start with "General background (not grounded in indexed papers):" and do not attach paper citations to general knowledge.
- If a question asks what a specific paper says and the passages do not establish it, say that the relevant paper detail was not found; do not guess. Answer any general or conceptual part separately when useful.
- When several papers are involved, identify which paper supports each paper-specific point.
- Be concise unless the user asks for an explanation, walkthrough, comparison, or code."""

PAPER_CHAT_SYSTEM_PROMPT = """You are a helpful, general-purpose assistant in a research workspace. The user can ask about any subject. This conversation also has one selected paper for context; you receive numbered passages from it, which may be empty or may not cover the question.

- Claims about what the authors say, do, measure, or find must come only from the supplied passages. End every sentence containing a paper-specific fact with the supporting passage number, just before the full stop, like this: "<paper-specific statement> [2]." Use only numbers in the evidence.
- Never invent a result, citation, experimental setting, symbol definition, or author claim. If the supplied passages don't establish a paper-specific answer, say what is missing instead of guessing.
- Answer ordinary general questions directly using your general knowledge, even when they are unrelated to the paper or the supplied passages are empty. If the whole question is general, start with "General background (not grounded in the selected paper):". For a mixed question, separate the general part and label it the same way. Do not attach paper citations to general knowledge.
- If a question asks what the selected paper says and the passages do not establish it, explain that no supporting passage was found; still answer any general or conceptual part separately when useful.
- When you infer what a result or design choice means, label it as an interpretation and cite the passages it follows from.
When the user asks for explanation or depth:
- Explain the relevant idea in plain language first, then connect it to the paper's precise terminology.
- For a method or architecture, walk through the steps in order and explain what each component contributes.
- For an equation, name each symbol that the evidence defines, explain the operations and why the equation is used. Say when the paper does not define a symbol; do not guess.
- For a figure, table, or experiment, describe what it measures, the comparison being made, and what conclusion the authors draw. Preserve metric names, conditions, and caveats.
- When asked how to reproduce a result, report the stated data, split, model, training/evaluation setup, and missing details separately. Never invent a missing setting.
- Use enough detail to teach when asked to explain, derive, compare, or walk through something. Keep a direct factual answer short when that is all the user asks for.
- Carry the topic forward in follow-up questions, but re-check the paper passages and cite the new answer.
- Keep answers organized and readable. Use equations, numbered steps, or short sections when they make a complex explanation easier to follow."""

PRACTICAL_HELP_RULES = """For practical requests and follow-ups:
- Follow references such as "it" or "that" using the recent conversation. If the user says "help me build it," continue from the project just discussed instead of repeating a generic overview.
- For software and coding requests, provide a concrete first version now: state a sensible small scope, include complete code, name the file, and give the command or steps to use it. Do not answer only with a roadmap.
- Do not refuse because a task is complex, requires expertise, or has a larger full-scale version that needs more resources. Scope it to a feasible prototype, explain any real limit briefly, and begin.
- If an earlier answer contains a technical mistake, correct it briefly and continue with the corrected approach. For a GPT, explicitly use a decoder-only causal transformer with token and learned position embeddings, causal multi-head self-attention, residual feed-forward blocks, and next-token training. Do not substitute an LSTM/RNN/GRU or use an encoder-decoder architecture. Use a character vocabulary built from the sample text so token IDs stay in range.
- Be clear about what you have not executed or verified. Do not claim code ran unless it did."""

_BUILD_ACTION = re.compile(r"\b(?:build|create|implement|write|code|make|develop|scaffold|generate)\b", re.I)
_BUILD_FOLLOW_UP = re.compile(r"\b(?:it|that|this|same|continue|next step)\b", re.I)
_CODE_CONTEXT = re.compile(
    r"\b(?:code|script|python|javascript|typescript|program|software|app|website|api|"
    r"function|class|model|transformer|gpt|chatbot|algorithm|pipeline|repository|cli)\b",
    re.I,
)
_GPT_TOPIC = re.compile(r"\b(?:gpt|generative pre.?trained transformer)\b", re.I)


def is_build_request(question: str, history: list[tuple[str, str]]) -> bool:
    """Whether this turn requests software/code, including a referential follow-up."""
    previous = " ".join(previous_question for previous_question, _ in history[-4:])
    context = f"{previous} {question}"
    if not _CODE_CONTEXT.search(context):
        return False
    if _BUILD_ACTION.search(question):
        return True
    return bool(_BUILD_FOLLOW_UP.search(question) and _BUILD_ACTION.search(previous))


def _build_guidance(question: str, history: list[tuple[str, str]]) -> str:
    context = " ".join([*(q + " " + a for q, a in history), question])
    guidance = (
        "Implementation request: deliver the first small, runnable version in this answer, not "
        "another overview. Use one clearly named file, concise complete code, and a run command. "
        "For GPT-from-scratch, use Python and PyTorch unless the user requests another language. "
        "Keep it suitable for a beginner and CPU-sized when possible."
    )
    if _GPT_TOPIC.search(context):
        guidance += (
            " This is a Transformer implementation, not an RNN: include a CausalSelfAttention "
            "module with query/key/value projections and a triangular causal mask, a residual "
            "Transformer block with an MLP. The code must define self.token_embedding = nn.Embedding(...) "
            "and self.position_embedding = nn.Embedding(...), build a lower-triangular causal mask "
            "with torch.tril and actually apply it in attention, and train with x = tokens[:, :-1] "
            "and y = tokens[:, 1:] from one encoded text string. Do not use unrelated random targets. "
            "Do not use nn.LSTM, GRU, RNN, nn.TransformerEncoder, nn.TransformerDecoder, "
            "cross-attention, or an encoder-decoder. Use a tiny character-level dataset so the "
            "complete script fits on CPU. Before answering, check each requirement against the code "
            "itself; if any is missing, fix the code instead of claiming it is present. Correct any "
            "earlier mistake."
        )
    return guidance


def is_gpt_build_request(question: str, history: list[tuple[str, str]]) -> bool:
    """Whether an implementation request in this conversation is specifically about GPT."""
    context = " ".join([*(q + " " + a for q, a in history[-4:]), question])
    return is_build_request(question, history) and bool(_GPT_TOPIC.search(context))


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
    *,
    paper_chat: bool = False,
) -> list[Message]:
    """history: previous (question, answer) pairs, oldest first."""
    system = PAPER_CHAT_SYSTEM_PROMPT if paper_chat else SYSTEM_PROMPT
    system = f"{system}\n\n{PRACTICAL_HELP_RULES}"
    messages = [Message("system", system)]
    for previous_question, previous_answer in history:
        messages.append(Message("user", previous_question))
        messages.append(Message("assistant", previous_answer))
    blocks = "\n\n".join(evidence_block(e) for e in evidence)
    user_content = f"Evidence:\n{blocks}\n\nQuestion: {question}"
    if is_build_request(question, history):
        user_content += f"\n\n{_build_guidance(question, history)}"
    messages.append(Message("user", user_content))
    return messages
