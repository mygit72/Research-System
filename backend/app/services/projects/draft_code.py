"""Draft code step: a first attempt at the starter code's TODO stubs — `YourApproach` and any
baseline with no finished component in `starter/components.py` — written by the language model
configured in Settings → AI, grounded in passages found in the project's own papers.

This is explicitly a *draft*, not a checked result. The other language-model steps in this project
(questions, outline, reports) check every sentence against the passage it cites (NLI entailment);
code isn't a sentence an entailment checker can verify, so nothing here is checked that way. A
draft is always labelled "LLM-drafted — unverified" wherever it appears (systems.py, the README,
the API response), is never substituted for a system that already runs from finished components,
and a target the model couldn't ground in evidence — or wrote something that isn't valid Python —
is left as the ordinary TODO stub.
"""

from __future__ import annotations

import ast
import math
import re
import textwrap
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.models.project import ResearchProject
from app.services.analysis.digests import SourceBook
from app.services.analysis.writing import evidence_blocks
from app.services.llm import INSUFFICIENT, GenerationParams, Message
from app.services.projects.generate import _evidence, _writer

DRAFT_SYSTEM = f"""You write a first-draft Python implementation of a research method, using ONLY the numbered evidence passages describing it.

The target is a retrieval question-answering system: ``rank()`` orders candidate passages for a
question, and ``answer()`` returns an answer grounded in those passages. This starter project does
not implement arbitrary model architectures or training pipelines.

You are writing members of a class that already has this shape (do not redefine it):

    def rank(self, example, seed) -> list[int]:     # passage indices into example["passages"], best first
    def answer(self, example, seed) -> str:          # the predicted answer, as plain text
    def evidence(self, example, seed) -> list[int]:  # optional: the passages answer() actually used

`example["question"]` is the question, `example["passages"]` is the list of candidate passages (str).
You may call, but must not redefine: `components.BM25Scorer()` (`.score(example) -> list[float]`),
`components.rrf(rankings)` (fuses several passage-index rankings), `components.CrossEncoderScorer()`,
`components.best_sentence(question, passage)` (the passage's best-matching sentence).

Rules:
- Reply with ONLY the method definitions (`def rank(self, ...):` and `def answer(self, ...):`, and
  `def evidence(...)` if useful), indented 4 spaces as members of a class. No class line, no imports,
  no markdown fences, no prose before or after the code.
- Implement only what the evidence actually describes. Where it doesn't give enough detail to code a
  step, write a `# TODO:` comment there explaining what is missing — never invent the missing part.
- If the paper describes a method outside this retrieval question-answering interface, or does not
  give enough detail to implement either required method, reply with exactly: {INSUFFICIENT}. Do not
  return methods that contain only TODO comments, `pass` or `NotImplementedError`.
- Never fabricate a number, a dataset, a result or an implementation detail the evidence doesn't contain.
- If the evidence doesn't describe anything implementable, reply with exactly: {INSUFFICIENT}"""

MAX_EVIDENCE_PASSAGES = 6

MODEL_SYSTEM = f"""You create an educational, first-draft Python implementation of the model or method proposed in the user's research plan.

Use ONLY the numbered paper passages supplied. Tailor the implementation to the user's idea,
research question and hypothesis. Do not force the method into a retrieval rank()/answer() API.

Return a self-contained Python module implementing the core model/method. For a neural architecture,
use PyTorch and expose a clearly named torch.nn.Module; for a non-neural method, use the simplest
appropriate Python implementation. Add concise comments/docstrings that explain the paper concepts
beside the code, tensor shapes where supported, and mark every missing paper detail as a TODO.
For each important architecture choice or method, add a nearby comment in this exact form:
``# Paper evidence: [n]`` using the number of the supplied passage that supports that choice.
Use only passage numbers supplied below; label your own explanation as an inference rather than
presenting it as a paper claim.
Keep the module compact: implement the smallest useful core that demonstrates the user's research
idea, and leave unrelated pipeline/training details as TODOs. Include a tiny example only when the
evidence gives its inputs and outputs. Include no network access, file writes, subprocesses or hidden
side effects. Do not invent training settings, datasets, dimensions, numerical results, or algorithm
steps; if a size is not supported by the supplied passages, make it a required constructor argument
with no default. Do not add an `if __name__ == \"__main__\"` demo or numeric hyperparameter defaults.

If the passages don't describe the proposed method well enough to implement a meaningful core,
reply exactly `{INSUFFICIENT}`. Otherwise return only valid Python source: imports, documented class
and helpers, no Markdown fences or prose outside the code."""


def _runs(plan: Any) -> bool:
    return bool(plan.stages or plan.generate)


def stub_targets(config: dict[str, Any]) -> list[tuple[str, str]]:
    """(key, label) for every TODO stub: "approach", and each baseline with no finished
    component. A target already assembled from finished components is left alone — it runs."""
    from app.services.projects.starter import components as starter_components

    targets: list[tuple[str, str]] = []
    if not _runs(starter_components.resolve(config["builds_on"])):
        label = "the approach" + (
            f" (built on {', '.join(config['builds_on'])})" if config["builds_on"] else ""
        )
        targets.append(("approach", label))
    for name in config["baselines"]:
        if not _runs(starter_components.resolve([name])):
            targets.append((name, name))
    return targets


def _strip_fences(text: str) -> str:
    """Extract a fenced code block when present and normalize its indentation.

    Models commonly return fenced code with either zero or four spaces before the first method.
    Dedenting the whole block gives validation and codegen one stable representation.
    """
    text = text.strip()
    opening = text.find("```")
    if opening >= 0:
        body_start = text.find("\n", opening)
        closing = text.find("```", body_start + 1) if body_start >= 0 else -1
        if body_start >= 0 and closing >= 0:
            text = text[body_start + 1 : closing]
    return textwrap.dedent(text).strip("\r\n")


def _validation_error(code: str) -> str | None:
    try:
        module = ast.parse("class _Draft:\n" + textwrap.indent(code, "    "))
    except SyntaxError:
        if (
            "def rank" in code
            and "def answer" in code
            and "# TODO" in code
        ):
            return (
                "The model returned TODO-only method placeholders instead of executable Python. "
                "The paper's passages may not give implementable details for this starter project's "
                "retrieval rank()/answer() interface."
            )
        return "The model's reply wasn't valid Python."
    methods = {
        node.name: node
        for node in module.body[0].body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if not {"rank", "answer"}.issubset(methods):
        return "The model didn't return both required methods: rank() and answer()."

    # A syntactically valid `pass` or NotImplementedError is still just the original TODO stub.
    # Require each required method to contain at least one executable implementation statement.
    for name in ("rank", "answer"):
        body = methods[name].body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            if isinstance(body[0].value.value, str):  # ignore a method docstring
                body = body[1:]
        if not any(
            not isinstance(node, ast.Pass)
            and not (
                isinstance(node, ast.Raise)
                and isinstance(node.exc, ast.Call)
                and isinstance(node.exc.func, ast.Name)
                and node.exc.func.id == "NotImplementedError"
            )
            for node in body
        ):
            return (
                "The paper's passages didn't give implementable details for this starter project's "
                "retrieval rank()/answer() interface, so the model returned TODO placeholders."
            )
    return None


def _valid(code: str) -> bool:
    return _validation_error(code) is None


async def _draft_one(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    project: ResearchProject,
    label: str,
) -> dict[str, Any]:
    book = SourceBook()
    query = f"{label} method algorithm {project.hypothesis}".strip()
    numbers = await _evidence(
        session_factory, settings, project, query, book, max_passages=MAX_EVIDENCE_PASSAGES
    )
    if not numbers:
        return {
            "status": "insufficient",
            "code": "",
            "sources": [],
            "note": "No passages about this were found in the project's papers.",
        }
    writer = _writer(settings, book)
    reply = await writer.generate(
        [
            Message("system", DRAFT_SYSTEM),
            Message(
                "user",
                f"Evidence:\n{evidence_blocks(book, numbers)}\n\n"
                f"Write rank() and answer() for: {label}.",
            ),
        ],
        "code",
    )
    text = _strip_fences(reply)
    sources = [book.items[n - 1] for n in numbers]
    if text.startswith(INSUFFICIENT[:40]):
        return {
            "status": "insufficient",
            "code": "",
            "sources": sources,
            "note": "The evidence doesn't describe an implementable method.",
        }
    validation_error = _validation_error(text)
    if validation_error:
        return {
            "status": "insufficient",
            "code": "",
            "sources": sources,
            "note": f"{validation_error} Showing the TODO stub instead.",
        }
    code = textwrap.indent(text, "    ")
    return {
        "status": "drafted",
        "code": code,
        "sources": sources,
        "note": "LLM-drafted from the cited passages — unverified: read it before trusting it.",
        "model": writer.model,
    }


def _model_validation_error(
    code: str, evidence: str = "", allowed_sources: list[int] | None = None
) -> str | None:
    try:
        module = ast.parse(code)
    except SyntaxError:
        return "The model's reply wasn't valid Python."
    evidence_numbers = {
        float(value.replace(",", ""))
        for value in re.findall(r"(?<![\w.])\d[\d,]*(?:\.\d+)?(?![\w]|\.\d)", evidence)
    }
    if allowed_sources is not None:
        cited_sources = [
            int(value)
            for value in re.findall(
                r"(?im)^\s*#\s*Paper evidence:\s*\[(\d+)\]", code
            )
        ]
        unsupported_sources = sorted(set(cited_sources) - set(allowed_sources))
        if unsupported_sources:
            return (
                "The model cited passage number(s) that were not supplied: "
                + ", ".join(str(number) for number in unsupported_sources)
                + "."
            )
    for node in ast.walk(module):
        if not isinstance(node, ast.Constant) or isinstance(node.value, bool):
            continue
        if isinstance(node.value, (int, float)) and abs(node.value) > 3:
            value = float(node.value)
            if not any(
                math.isclose(value, cited, rel_tol=0, abs_tol=1e-9)
                for cited in evidence_numbers
            ):
                return (
                    f"The model inserted the unsupported numeric value {node.value}. "
                    "Architecture sizes and other numeric choices must come from cited passages."
                )
    classes = [node for node in module.body if isinstance(node, ast.ClassDef)]
    if not classes:
        return "The model didn't return a model or method class."
    methods = [
        member
        for cls in classes
        for member in cls.body
        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    if not methods:
        return "The model class has no callable implementation."
    for method in methods:
        body = method.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body = body[1:]
        def placeholder(stmt: ast.stmt) -> bool:
            if not isinstance(stmt, ast.Raise):
                return False
            error = stmt.exc
            return (isinstance(error, ast.Name) and error.id == "NotImplementedError") or (
                isinstance(error, ast.Call)
                and isinstance(error.func, ast.Name)
                and error.func.id == "NotImplementedError"
            )

        if not any(not isinstance(stmt, ast.Pass) and not placeholder(stmt) for stmt in body):
            return "The model returned only placeholder methods."
    return None


async def _draft_model(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    project: ResearchProject,
) -> dict[str, Any]:
    book = SourceBook()
    focus = "\n".join(
        part for part in (
            f"Project idea: {project.idea}" if project.idea.strip() else "",
            f"Research question: {project.question}" if project.question.strip() else "",
            f"Hypothesis: {project.hypothesis}" if project.hypothesis.strip() else "",
            f"Project: {project.title}",
        ) if part
    )
    query = f"{focus}\nmodel architecture method algorithm implementation".strip()
    numbers = await _evidence(
        session_factory, settings, project, query, book, max_passages=MAX_EVIDENCE_PASSAGES
    )
    if not numbers:
        return {
            "status": "insufficient",
            "code": "",
            "sources": [],
            "note": "No passages about the project's proposed model or method were found.",
        }
    writer = _writer(settings, book)
    # A documented model module needs more room than the short report sections (450 tokens by
    # default). Keep it bounded while allowing a useful core implementation and teaching comments.
    writer.params = GenerationParams(
        max(settings.summary_max_tokens, 1600), settings.llm_temperature
    )
    request = (
        f"User's research plan:\n{focus}\n\n"
        f"Paper evidence:\n{evidence_blocks(book, numbers)}\n\n"
        "Return a compact, useful educational core that directly supports this plan. Explain "
        "the key paper concepts in the code comments and mark anything the paper leaves unspecified. "
        "For every key architecture choice, put a nearby comment in this exact form: "
        "# Paper evidence: [n], where n is one of the passage numbers above. Do not add facts or "
        "example dimensions unless the supplied passages support them."
    )
    reply = await writer.generate(
        [Message("system", MODEL_SYSTEM), Message("user", request)], "code"
    )
    text = _strip_fences(reply)
    sources = [book.items[n - 1] for n in numbers]
    if text.startswith(INSUFFICIENT[:40]):
        return {
            "status": "insufficient",
            "code": "",
            "sources": sources,
            "note": "The cited passages don't give enough implementation detail for this model or method.",
        }
    evidence_text = "\n".join(book.text(number) for number in numbers)
    error = _model_validation_error(text, evidence_text, numbers)
    if error:
        first_draft = text
        reply = await writer.generate(
            [
                Message("system", MODEL_SYSTEM),
                Message(
                    "user",
                    f"{request}\n\nYour previous draft was rejected: {error}\n\n"
                    f"Previous draft:\n{first_draft}\n\n"
                    "Revise it once. Return only valid Python source. Add at least one nearby "
                    "`# Paper evidence: [n]` comment for each important implementation choice, "
                    "using only the numbered passages above. Keep unsupported details as TODOs; "
                    "do not invent passage numbers or numeric defaults.",
                ),
            ],
            "code repair",
        )
        text = _strip_fences(reply)
        if text.startswith(INSUFFICIENT[:40]):
            return {
                "status": "insufficient",
                "code": "",
                "sources": sources,
                "note": "The cited passages don't give enough implementation detail for this model or method.",
            }
        error = _model_validation_error(text, evidence_text, numbers)
    if error:
        return {
            "status": "insufficient",
            "code": "",
            "sources": sources,
            "note": f"{error} The editable starter remains available.",
        }
    note = "Educational model draft tailored to the research plan — unverified and not run."
    if not re.search(r"(?im)^\s*#\s*Paper evidence:\s*\[\d+\]", text):
        note += " The model omitted inline passage comments; review the supplied paper passages beside the code."
    return {
        "status": "drafted",
        "code": text,
        "sources": sources,
        "note": note,
        "model": writer.model,
    }


async def draft_code(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    project: ResearchProject,
    report: Any,
) -> dict[str, Any]:
    from app.services.projects import codegen

    config = codegen.build_config(project, settings)
    targets = [("model", "the research model/method"), *stub_targets(config)]
    drafts: dict[str, Any] = {}
    for i, (key, label) in enumerate(targets):
        await report("drafting", 0.1 + 0.8 * i / len(targets), f"Drafting {label}")
        if key == "model":
            drafts[key] = await _draft_model(session_factory, settings, project)
        else:
            drafts[key] = await _draft_one(session_factory, settings, project, label)
    return {"drafts": drafts, "note": None}
