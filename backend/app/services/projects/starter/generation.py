"""Answer generation: a language model writes the answer from the passages a retriever chose — the
"generation" in retrieval-augmented generation.

    generator = Generator.from_config()            # the "generator" block of config.json
    generator.answer(question, passages) -> str    # passages=[]: closed-book, the question alone
    generator.answer(question, passages, style="sentence")   # a one-sentence answer (MS MARCO)

Providers (the same two the research platform uses):

    ollama     a local model through Ollama (default qwen2.5:3b): nothing leaves your machine.
               Install it from https://ollama.com, then `ollama pull qwen2.5:3b`.
    openai     any OpenAI-compatible chat API — OpenAI, vLLM, LM Studio, a llama.cpp server. Set
               "base_url" and "model"; the key comes from the environment variable named by
               "api_key_env" (default OPENAI_API_KEY; local servers need none).

Keys are read from the environment only, never from config.json, so the config can be shared.

Every answer is cached in cache/generations.jsonl together with the prompt, the model, the token
counts and the time it took, keyed by everything that changes the output (provider, model, prompt,
settings). Rerunning an experiment, or running another seed, costs nothing; a run that stopped
half-way resumes where it was. The file is also the log: open it to see exactly what the model
was asked. Delete it to generate everything again.

Before trusting the numbers:

* Decoding is greedy (temperature 0), so an answer does not depend on the seed and the spread
  over seeds comes from retrieval alone.
* The model is told to reply with the answer alone, in a few words, or exactly "unanswerable" when
  the passages don't contain it. That suits short-answer datasets (SQuAD, NQ, TriviaQA, HotpotQA).
  An example can ask for another style: MS MARCO's loader sets "answer_style": "sentence", because
  its accepted answers are sentences (STYLES below).
* Models still add words ("The answer is Denver Broncos."), which exact match counts as wrong:
  report `contains` next to exact match (metrics.py). `clean()` below removes only what is never
  part of an answer (an "Answer:" prefix, [n] markers, a reasoning model's <think> block), and turns
  a reply that only says it can't answer ("The passages do not contain this information.") into
  "unanswerable", so abstentions are counted and a retrieval gate can act on them. Cleaning is
  applied when an answer is read, so cached replies follow changes to `clean()`.
* An answer cut off at max_tokens before any text becomes an empty answer — scored as wrong,
  logged, and counted in the summary the runner prints.
* Busy servers (HTTP 429/5xx, a dropped connection) are retried twice with a growing pause. A
  refused connection or a timeout is not retried: it means the model isn't running, or is too
  slow for `timeout`.
* `python run_experiments.py --estimate` counts the model calls and prompt tokens a run would need,
  without calling the model: check it before a run on a paid API.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent
PROMPT_VERSION = "qa-v2"  # a label for the prompts below; the cache key holds the full text anyway
ABSTAIN = "unanswerable"  # metrics.ABSTAIN
PASSAGE_WORDS = 200  # each passage is cut to this many words in the prompt (said in the prompt log)
RETRIES = 2  # extra attempts after a busy-server error
BACKOFF = 1.0  # seconds before the first retry; doubles each time (a Retry-After header wins)
RETRY_STATUSES = {429, 500, 502, 503, 504}
CHARS_PER_TOKEN = 4  # for --estimate only: a rough rule for English text
DEFAULTS: dict[str, dict[str, Any]] = {
    "ollama": {"model": "qwen2.5:3b", "base_url": "http://localhost:11434"},
    "openai": {"model": "", "base_url": "https://api.openai.com/v1"},
}

SYSTEM_RAG = (
    "Answer the question using only the numbered passages. Reply with the answer alone: a few "
    "words, no full sentence, no explanation, no passage numbers. If the passages do not contain "
    f"the answer, reply exactly: {ABSTAIN}"
)
SYSTEM_CLOSED_BOOK = (
    "Answer the question. Reply with the answer alone: a few words, no full sentence, no "
    f"explanation. If you do not know the answer, reply exactly: {ABSTAIN}"
)
SYSTEM_RAG_SENTENCE = (
    "Answer the question using only the numbered passages, in one short sentence, without "
    f"passage numbers. If the passages do not contain the answer, reply exactly: {ABSTAIN}"
)
SYSTEM_CLOSED_BOOK_SENTENCE = (
    "Answer the question in one short sentence. If you do not know the answer, reply exactly: "
    f"{ABSTAIN}"
)


@dataclass(frozen=True)
class Style:
    with_passages: str  # the system prompt when there are passages
    closed_book: str  # ... and when there are none
    min_tokens: int  # max_tokens is raised to at least this for the style


STYLES = {
    "short": Style(SYSTEM_RAG, SYSTEM_CLOSED_BOOK, 0),
    "sentence": Style(SYSTEM_RAG_SENTENCE, SYSTEM_CLOSED_BOOK_SENTENCE, 128),
}

# A reply that only says the question can't be answered. Anchored at the start of the reply and
# kept to unambiguous phrasings: "No" alone is an answer to a yes/no question, not an abstention.
_ABSTAINS = re.compile(
    r"^(?:(?:unanswerable|not answerable)[.!]?$"  # these words alone ("Unknown" can be an answer)
    r"|(?:i (?:do not|don't|cannot|can't) (?:know|answer|tell|determine)"
    r"|(?:i'm|i am) (?:not sure|unable to)"
    r"|(?:the )?(?:provided )?(?:passages?|context|text|documents?|information)"
    r" (?:does|do|did) not (?:contain|provide|mention|say|specify|state|include|give)"
    r"|(?:this|that|the answer|it) (?:is|was) not (?:mentioned|provided|stated|specified|given"
    r"|available|found|known)"
    r"|there (?:is|are) no (?:information|mention|answer|details)"
    r"|(?:it )?cannot be (?:determined|answered|found)|not enough information"
    r"|insufficient (?:information|evidence)|no answer)\b)",
    re.I,
)


class GenerationError(RuntimeError):
    """The model could not be reached, or rejected the request. The runner records the reason
    instead of a number."""


@dataclass
class Reply:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str | None = None
    model: str = ""


@dataclass
class Stats:
    generated: int = 0
    cached: int = 0
    empty: int = 0  # answers cut off before any text
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    stop_reasons: dict[str, int] = field(default_factory=dict)

    retries: int = 0
    estimated: int = 0  # --estimate: prompts that would be sent
    estimated_tokens: int = 0

    def line(self) -> str:
        if self.estimated or (Generator.estimate_only and not self.generated):
            return (
                f"would generate {self.estimated} answer(s) (~{self.estimated_tokens} prompt "
                f"tokens), {self.cached} already cached"
            )
        text = f"{self.generated} answer(s) generated, {self.cached} from the cache"
        if self.generated:
            text += (
                f"; {self.input_tokens} prompt + {self.output_tokens} answer tokens, "
                f"{self.seconds / self.generated:.1f} s per answer"
            )
        if self.empty:
            reasons = ", ".join(f"{k}: {v}" for k, v in sorted(self.stop_reasons.items()))
            text += f"; {self.empty} EMPTY (scored as wrong; stop reasons {reasons})"
        if self.retries:
            text += f"; {self.retries} retried request(s)"
        return text


# --- the prompt -------------------------------------------------------------------------------


def _clip(passage: str) -> str:
    words = passage.split()
    return " ".join(words[:PASSAGE_WORDS]) + (" …" if len(words) > PASSAGE_WORDS else "")


def _style(name: str) -> Style:
    if name not in STYLES:
        raise GenerationError(f"Unknown answer style “{name}”: use one of {', '.join(STYLES)}.")
    return STYLES[name]


def build_prompt(question: str, passages: list[str], style: str = "short") -> tuple[str, str]:
    """(system, user). With no passages the model answers from the question alone (closed-book)."""
    if not passages:
        return _style(style).closed_book, f"Question: {question.strip()}\nAnswer:"
    numbered = "\n".join(f"[{i}] {_clip(p)}" for i, p in enumerate(passages, start=1))
    return (
        _style(style).with_passages,
        f"Passages:\n{numbered}\n\nQuestion: {question.strip()}\nAnswer:",
    )


def clean(text: str) -> str:
    """The answer line, without what is never part of an answer. Nothing else is changed."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)
    text = re.sub(r"<think>.*", "", text, flags=re.S | re.I)  # cut off while still thinking
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    line = re.sub(r"^(?:final answer|answer)\s*[:\-]\s*", "", line, flags=re.I)
    line = re.sub(r"\s*\[\d+(?:\s*[,–-]\s*\d+)*\]", "", line)
    line = line.strip().strip("\"'*").strip()
    return ABSTAIN if _ABSTAINS.match(line) else line


# --- providers --------------------------------------------------------------------------------


def _post(
    url: str, body: dict[str, Any], headers: dict[str, str], timeout: float, stats: Stats
) -> Any:
    """POST JSON, return the decoded reply, retrying a busy server. HTTP errors that remain are
    re-raised as _HTTPStatus (status, body text)."""
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    for attempt in range(RETRIES + 1):
        pause = BACKOFF * 2**attempt
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error = _HTTPStatus(exc.code, exc.read().decode("utf-8", "replace")[:300])
            if exc.code not in RETRY_STATUSES or attempt == RETRIES:
                raise error from exc
            after = (exc.headers.get("Retry-After") or "").strip()
            if after.replace(".", "", 1).isdigit():
                pause = min(float(after), 30.0)
        except (urllib.error.URLError, ConnectionResetError) as exc:
            dropped = isinstance(getattr(exc, "reason", exc), ConnectionResetError)
            if not dropped or attempt == RETRIES:
                raise
        stats.retries += 1
        time.sleep(pause)
    raise AssertionError("unreachable")


class _HTTPStatus(Exception):
    def __init__(self, status: int, text: str) -> None:
        super().__init__(f"HTTP {status}: {text}")
        self.status, self.text = status, text


def _unreachable(exc: Exception) -> str:
    reason = getattr(exc, "reason", exc)
    return f"{type(reason).__name__}: {reason}" if str(reason) else type(reason).__name__


_ESTIMATED: dict[str, int] = {}  # --estimate: prompt → its tokens, across systems and seeds


def estimate_totals() -> tuple[int, int]:
    """--estimate: (model calls that would be made, their prompt tokens)."""
    return len(_ESTIMATED), sum(_ESTIMATED.values())


class Generator:
    """A language model answering from passages, with a cache in front of it. Construction never
    contacts the model; the first `answer()` does."""

    estimate_only = False  # set by `run_experiments.py --estimate`: count, never call

    def __init__(
        self,
        provider: str = "ollama",
        model: str = "",
        base_url: str = "",
        top_k: int = 3,
        max_tokens: int = 64,
        timeout: float = 300.0,
        cache_path: Path | None = ROOT / "cache" / "generations.jsonl",
        api_key_env: str = "",
    ) -> None:
        if provider not in DEFAULTS:
            raise GenerationError(
                f"Unknown generator provider “{provider}” in config.json: use one of "
                + ", ".join(DEFAULTS)
                + "."
            )
        self.provider = provider
        self.model = model or DEFAULTS[provider]["model"]
        if not self.model:
            raise GenerationError(
                f'Set "model" in the "generator" block of config.json for the {provider} provider.'
            )
        self.base_url = (base_url or DEFAULTS[provider]["base_url"]).rstrip("/")
        self.top_k, self.max_tokens, self.timeout = top_k, max_tokens, timeout
        self.cache_path = cache_path
        self.api_key_env = api_key_env or "OPENAI_API_KEY"
        self.stats = Stats()
        self._cache: dict[str, dict[str, Any]] = {}
        if cache_path is not None and cache_path.exists():
            for line in cache_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    record = json.loads(line)
                    self._cache[record["key"]] = record

    @classmethod
    def from_config(cls, path: Path = ROOT / "config.json") -> Generator:
        settings = _settings(path)
        known = {
            "provider",
            "model",
            "base_url",
            "top_k",
            "max_tokens",
            "timeout",
            "api_key_env",
        }
        unknown = sorted(set(settings) - known)
        if unknown:
            raise GenerationError(
                f"Unknown setting(s) in the generator block of config.json: {', '.join(unknown)}."
            )
        return cls(**settings)

    def describe(self) -> str:
        return (
            f"{self.provider}:{self.model} at {self.base_url}, top {self.top_k} passages, "
            f"prompt {PROMPT_VERSION}"
        )

    # -- answering --

    def answer(self, question: str, passages: list[str], style: str = "short") -> str:
        system, user = build_prompt(question, passages[: self.top_k], style)
        max_tokens = max(self.max_tokens, _style(style).min_tokens)
        key = self._key(system, user, max_tokens)
        record = self._cache.get(key)
        if record is not None:
            self.stats.cached += 1
            return clean(record["raw"])
        if Generator.estimate_only:
            if key not in _ESTIMATED:
                _ESTIMATED[key] = len(system + user) // CHARS_PER_TOKEN
                self.stats.estimated += 1
                self.stats.estimated_tokens += _ESTIMATED[key]
            return ABSTAIN  # as if the model declined: a gate then counts its second call too
        started = time.perf_counter()
        reply = self._call(system, user, max_tokens)
        seconds = time.perf_counter() - started
        record = {
            "key": key,
            "provider": self.provider,
            "model": reply.model or self.model,
            "prompt_version": PROMPT_VERSION,
            "system": system,
            "user": user,
            "raw": reply.text,
            "answer": clean(reply.text),
            "stop_reason": reply.stop_reason,
            "input_tokens": reply.input_tokens,
            "output_tokens": reply.output_tokens,
            "seconds": round(seconds, 3),
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        self._remember(record)
        stats = self.stats
        stats.generated += 1
        stats.seconds += seconds
        stats.input_tokens += reply.input_tokens
        stats.output_tokens += reply.output_tokens
        if not record["answer"]:
            stats.empty += 1
            reason = str(reply.stop_reason)
            stats.stop_reasons[reason] = stats.stop_reasons.get(reason, 0) + 1
        if stats.generated % 10 == 0:
            print(f"    … {stats.line()}", flush=True)
        return record["answer"]

    def _key(self, system: str, user: str, max_tokens: int) -> str:
        settings = [self.provider, self.model, self.base_url, max_tokens, system, user]
        return hashlib.sha256(json.dumps(settings).encode("utf-8")).hexdigest()

    def _remember(self, record: dict[str, Any]) -> None:
        self._cache[record["key"]] = record
        if self.cache_path is not None:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with self.cache_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _call(self, system: str, user: str, max_tokens: int) -> Reply:
        if self.provider == "ollama":
            return self._ollama(system, user, max_tokens)
        return self._openai(system, user, max_tokens)

    # -- Ollama: POST /api/chat --

    def _ollama(self, system: str, user: str, max_tokens: int) -> Reply:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "options": {"temperature": 0, "seed": 0, "num_predict": max_tokens},
        }
        try:
            data = _post(f"{self.base_url}/api/chat", body, {}, self.timeout, self.stats)
        except _HTTPStatus as exc:
            if exc.status == 404:
                raise GenerationError(
                    f"The model “{self.model}” isn't installed in Ollama. Run: ollama pull {self.model}"
                ) from exc
            raise GenerationError(f"Ollama returned an error: {exc}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise GenerationError(
                f"Can't reach Ollama at {self.base_url} ({_unreachable(exc)}). Start it (install "
                f"from https://ollama.com), then run: ollama pull {self.model}"
            ) from exc
        if data.get("error"):
            raise GenerationError(f"Ollama failed: {data['error']}")
        return Reply(
            text=(data.get("message") or {}).get("content", ""),
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
            stop_reason=data.get("done_reason"),
            model=data.get("model", self.model),
        )

    # -- OpenAI-compatible: POST /chat/completions --

    def _openai(self, system: str, user: str, max_tokens: int) -> Reply:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "temperature": 0,
            "seed": 0,
        }
        key = os.environ.get(self.api_key_env, "")
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        try:
            data = _post(
                f"{self.base_url}/chat/completions", body, headers, self.timeout, self.stats
            )
        except _HTTPStatus as exc:
            hint = f" Set {self.api_key_env}." if exc.status == 401 and not key else ""
            raise GenerationError(f"The chat API at {self.base_url} refused: {exc}.{hint}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise GenerationError(
                f"Can't reach the chat API at {self.base_url} ({_unreachable(exc)})."
            ) from exc
        choice = (data.get("choices") or [{}])[0]
        usage = data.get("usage") or {}
        return Reply(
            text=(choice.get("message") or {}).get("content") or "",
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            stop_reason=choice.get("finish_reason"),
            model=data.get("model", self.model),
        )


def _settings(path: Path, block: str = "generator") -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return dict(config.get(block) or {})


# --- the retrieval gate -----------------------------------------------------------------------

GATE_POLICIES = {
    "abstain": "the model answers closed-book first and retrieves only when it says it can't "
    "answer",
    "retriever": "retrieves only when the retriever is confident (top first-stage score at least "
    "{threshold} standard deviations above the mean of the candidates), else closed-book",
}
GATE_THRESHOLD = 2.0  # "retriever" policy: tune it on a validation split, never on the test set


def gate_settings(path: Path = ROOT / "config.json") -> dict[str, Any]:
    """The "gate" block of config.json: {"policy": "abstain" | "retriever", "threshold": float}."""
    settings = _settings(path, "gate")
    unknown = sorted(set(settings) - {"policy", "threshold"})
    if unknown:
        raise GenerationError(
            f"Unknown setting(s) in the gate block of config.json: {', '.join(unknown)}."
        )
    policy = settings.get("policy", "abstain")
    if policy not in GATE_POLICIES:
        raise GenerationError(
            f"Unknown gate policy “{policy}” in config.json: use one of {', '.join(GATE_POLICIES)}."
        )
    threshold = float(settings.get("threshold", GATE_THRESHOLD))
    return {
        "policy": policy,
        "threshold": threshold,
        "describe": f"gate: {policy} — " + GATE_POLICIES[policy].format(threshold=threshold),
    }


def describe_config(path: Path = ROOT / "config.json") -> str:
    """What `from_config` would build, for notes in results.csv. Never raises."""
    try:
        return Generator.from_config(path).describe() if path.exists() else "not configured"
    except (GenerationError, ValueError, TypeError) as exc:
        return f"misconfigured: {exc}"
