"""Maintenance commands.

    python -m app.cli reindex --pending          # papers never indexed (e.g. after upgrading)
    python -m app.cli reindex --all              # e.g. after changing EMBEDDING_MODEL or chunking
    python -m app.cli reindex --all --user a@b.c
    python -m app.cli check-model                # two real requests to the server's model

Runs in-process (no API or worker needed). `reindex` reports per paper; `check-model` asks for
a chat answer and a summary section the way the app does and shows each reply, its timing and
its token counts, e.g. after setting up the shared free model.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import textwrap
import time
from dataclasses import dataclass

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import dispose_engine, get_session_factory, init_engine
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.models.document import Document, DocumentStatus, IndexStatus
from app.models.user import User
from app.services.embeddings import EmbeddingError
from app.services.indexing import index_version, mark_index_failed
from app.services.llm import GenerationParams, LLMError, LLMProvider, Message, server_provider
from app.services.summaries import spec
from app.services.summaries.prompt import Block, group_messages, parse_fields
from app.services.vectorstore import close_vector_store


async def reindex(pending_only: bool, user_email: str | None) -> int:
    settings = get_settings()
    configure_logging("WARNING", settings.log_json)
    init_engine(settings)
    factory = get_session_factory()
    failures = 0
    try:
        async with factory() as session:
            query = select(Document).where(
                Document.status == DocumentStatus.READY, Document.current_version_id.is_not(None)
            )
            if pending_only:
                query = query.where(Document.index_status != IndexStatus.INDEXED)
            if user_email:
                query = query.join(User, User.id == Document.user_id).where(
                    User.email == user_email.lower()
                )
            documents = list((await session.execute(query)).scalars())
        print(f"Indexing {len(documents)} paper(s) with {settings.embedding_model} …")
        for number, document in enumerate(documents, start=1):
            started = time.perf_counter()
            label = f"[{number}/{len(documents)}] {document.title[:60]!r}"
            assert document.current_version_id is not None
            try:
                result = await index_version(
                    factory, document.current_version_id, settings, lambda *_: None
                )
                print(
                    f"{label}: {result.chunks} passages "
                    f"({result.embedded} embedded, {result.cached} cached) "
                    f"in {time.perf_counter() - started:.1f}s"
                )
            except EmbeddingError as exc:
                failures += 1
                await mark_index_failed(factory, document.id, exc.user_message)
                print(f"{label}: FAILED {exc.user_message}")
    finally:
        close_vector_store()
        await dispose_engine()
    return 1 if failures else 0


CHECK_PASSAGES = (
    Block(
        1,
        "Abstract, p. 1",
        "Fine-tuning every parameter of a large language model is expensive. We study low-rank "
        "adapters that represent the weight update as the product of two small matrices. Across "
        "four domain adaptation tasks, rank-8 adapters match full fine-tuning within one point "
        "while training 0.4 percent of the parameters and reducing GPU memory by 60 percent.",
    ),
    Block(
        2,
        "1 Introduction, p. 1",
        "Adapting a pretrained language model to a new domain usually means updating all of its "
        "weights. For models with billions of parameters this requires large GPU clusters and "
        "produces a full copy of the model for every task. We focus on low-rank adaptation, "
        "which freezes the pretrained weights and learns a low-rank update for selected matrices.",
    ),
    Block(
        3,
        "5 Limitations, p. 6",
        "Our experiments cover models of up to seven billion parameters and English-language "
        "domains. The best rank may differ for larger models or multilingual data.",
    ),
)
CHECK_QUESTION = (
    "How much GPU memory do low-rank adapters save, and what are the limits of the study?"
)
CHECK_FIELDS = (spec.PROBLEM, spec.CONTRIBUTION, spec.LIMITATIONS)
REASONING_HELP = """\
A reasoning model can spend the whole answer budget thinking, and some hosts then put the
thinking into the answer. Turn its reasoning off or down with LLM_EXTRA_BODY, or raise
LLM_MAX_TOKENS and SUMMARY_MAX_TOKENS. For Nemotron 3 Ultra on OpenRouter this works:
  LLM_EXTRA_BODY='{"reasoning": {"enabled": false}}'"""


@dataclass(slots=True)
class _Reply:
    text: str
    stop: str | None
    tokens: tuple[int, int]
    first_seconds: float
    seconds: float


async def _ask(llm: LLMProvider, messages: list[Message], params: GenerationParams) -> _Reply:
    started = time.perf_counter()
    first: float | None = None
    parts: list[str] = []
    stop, tokens = None, (0, 0)
    async for event in llm.stream(messages, params):
        if event.text:
            first = first or time.perf_counter()
            parts.append(event.text)
        if event.done:
            stop = event.stop_reason
            tokens = (event.usage.input_tokens, event.usage.output_tokens)
    ended = time.perf_counter()
    return _Reply("".join(parts).strip(), stop, tokens, (first or ended) - started, ended - started)


def _answer_problem(reply: _Reply) -> str | None:
    if not reply.text:
        return "the reply was empty"
    if reply.stop == "length":
        return "the reply was cut off at the answer budget"
    if "[" not in reply.text:
        return "the answer cites no passage"
    return None


def _summary_problem(reply: _Reply) -> str | None:
    if not reply.text:
        return "the reply was empty"
    if reply.stop == "length":
        return "the reply was cut off at the answer budget"
    if not reply.text.lstrip("*#- ").upper().startswith(CHECK_FIELDS[0].label):
        return f"it wrote something else before the first field ({CHECK_FIELDS[0].label}:)"
    fields = parse_fields(reply.text, CHECK_FIELDS)
    missing = [f.label for f in CHECK_FIELDS if fields[f.key] == spec.NOT_REPORTED]
    return f"fields not filled in: {', '.join(missing)}" if missing else None


async def check_model() -> int:
    """Ask the server's model for a chat answer and a summary section, the way the app does
    (same prompts for the summary, same answer budgets), and say whether each came back right."""
    settings = get_settings()
    configure_logging("WARNING", settings.log_json)
    try:
        llm = server_provider(settings)
    except AppError as exc:
        print(f"Not configured: {exc.message} {exc.hint or ''}".rstrip())
        return 1
    where = settings.llm_api_base if settings.llm_provider == "openai" else settings.llm_provider
    print(f"Model: {llm.model_id} at {where}")
    passages = "\n\n".join(f"[{b.number}] {b.text}" for b in CHECK_PASSAGES)
    checks = (
        (
            "A chat answer",
            [
                Message("system", "Answer from the numbered passages only and cite them like [1]."),
                Message("user", f"Passages:\n{passages}\n\nQuestion: {CHECK_QUESTION}"),
            ],
            settings.llm_max_tokens,
            _answer_problem,
        ),
        (
            "A summary section",
            group_messages("Low-Rank Adapters", 2023, list(CHECK_PASSAGES), CHECK_FIELDS),
            settings.summary_max_tokens,
            _summary_problem,
        ),
    )
    problems = 0
    for name, messages, budget, problem_of in checks:
        print(f"\n{name} (answer budget {budget} tokens) …")
        try:
            reply = await _ask(llm, messages, GenerationParams(budget, settings.llm_temperature))
        except LLMError as exc:
            print(f"  FAILED: {exc.user_message}\n  {exc.detail or ''}")
            if exc.status == 429:
                print("  The key is rate-limited right now: wait, or check its daily limit.")
            return 1
        print(
            f"  {reply.first_seconds:.1f} s to the first words, {reply.seconds:.1f} s in all, "
            f"{reply.tokens[0]} tokens in / {reply.tokens[1]} out, stopped: {reply.stop}"
        )
        print(textwrap.indent(textwrap.shorten(reply.text, 700, placeholder=" …"), "  | "))
        problem = problem_of(reply)
        if problem:
            problems += 1
            print(f"  PROBLEM: {problem}.")
    if problems:
        print(f"\n{REASONING_HELP}")
        return 1
    print("\nBoth came back right.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    index = commands.add_parser("reindex", help="(Re)build the search index")
    scope = index.add_mutually_exclusive_group(required=True)
    scope.add_argument("--pending", action="store_true", help="only papers not yet indexed")
    scope.add_argument("--all", action="store_true", help="every ready paper")
    index.add_argument("--user", help="limit to one account (email)")
    commands.add_parser("check-model", help="ask the server's model for an answer and a summary")
    args = parser.parse_args(argv)
    if args.command == "check-model":
        return asyncio.run(check_model())
    if args.command == "reindex":
        return asyncio.run(reindex(pending_only=args.pending, user_email=args.user))
    return 2


if __name__ == "__main__":
    sys.exit(main())
