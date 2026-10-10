"""Entity extraction from a paper's passages: deterministic, with evidence.

Two passes, so the result doesn't depend on the order papers were uploaded:

1. `discover()` looks only at the paper itself and finds names the catalog may not
   know: acronym definitions (Schwartz & Hearst, 2003: "Natural Questions (NQ)",
   "Low-Rank Adaptation, or LoRA"), what the paper proposes (title prefix
   "ColBERT: …", "we propose X", "a model called X", a title that starts with a
   known name) and "the X dataset / benchmark" phrases.
2. `match()` counts mentions of every known name (catalog + everything discovered in
   the user's library + this paper's own acronyms) and decides the relation:
   - **proposes**: found by discovery;
   - **uses**: mentioned in the method / experiments / results / tables or in a
     sentence like "we evaluate on …", "trained on …" (weighted score ≥ 1.5);
   - **mentions**: only in passing (introduction, related work).
   The references section never counts: a cited title is not a use.

Every relation keeps up to three evidence sentences with page and paragraph, so
the UI can show *why* a paper is linked to a dataset.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from app.services.knowledge.catalog import CATALOG, CatalogEntry, EntityType

EXTRACTOR_VERSION = "1"
MAX_EVIDENCE = 3
# Mention weights: 2 = strong section + usage cue, 1.5 = method section, 1 = strong section or
# cue, 0.25 = elsewhere, 0.1 = related work without a cue. "uses" needs this much in total.
USES_THRESHOLD = 1.5

# Sections whose mentions say "this paper uses it".
STRONG_SECTIONS = frozenset(
    {"abstract", "method", "experiments", "results", "discussion", "caption", "appendix"}
)
# Never counted: bibliography, author block, thanks.
SKIPPED_SECTIONS = frozenset({"references", "acknowledgments", "preamble"})

_CUE = re.compile(
    r"\b(?:we|our|us)\b[^.]{0,80}?\b(?:use[ds]?|using|evaluat\w*|train\w*|fine-?tun\w*|"
    r"test\w*|experiment\w*|report\w*|appl(?:y|ied|ies)|adopt\w*|follow\w*|compar\w*|"
    r"benchmark\w*|achiev\w*|obtain\w*|initiali[sz]\w*|measur\w*|run|ran|consider\w*|"
    r"focus\w*|stud(?:y|ied))\b"
    r"|\b(?:experiments?|results?|evaluat\w*|trained|tested|fine-?tuned|accuracy|scores?|"
    r"performance)\s+(?:on|with|using)\b",
    re.IGNORECASE,
)
_PROPOSE = re.compile(
    r"\b(?:we|this paper|this work|our work)\s+(?:also\s+)?"
    r"(?:propose|introduce|present|develop|design|call|name|term|dub)s?\b"
    r"|\b(?:called|named|dubbed|termed)\b",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[])")
_WORD = re.compile(r"\S+")

_DATASET_CUE = re.compile(r"\b(?:datasets?|benchmarks?|corpus|corpora|treebank|data set)\b", re.I)
_MODEL_CUE = re.compile(
    r"\b(?:network|networks|nets?|models?|transformers?|encoders?|decoders?|retrievers?|"
    r"architectures?|LMs?)\b",
    re.I,
)
_METRIC_CUE = re.compile(r"\b(?:score|rate|error|accuracy|precision|recall|gain|rank)\b", re.I)
_TASK_CUE = re.compile(
    r"\b(?:answering|translation|recognition|detection|classification|retrieval|"
    r"generation|inference|summarization|segmentation|parsing)\b",
    re.I,
)

# "Name-like": an acronym or a word with an inner capital/digit (LoRA, ColBERT, T5, NF4).
_NAME_LIKE = re.compile(r"^(?:[A-Z][A-Za-z0-9]*[A-Z0-9][A-Za-z0-9]*|[A-Z]{2,})(?:-[A-Za-z0-9]+)*$")
_CAP_STOP = frozenset(
    """A An The This That These Those Our We It In On For Of To With From By As At Each Both
    Table Figure Fig Section Appendix Eq Equation New Large Small Original Full Entire Test
    Training Train Validation Dev Same Following Other Different Several Many Most All Two
    Three First Second Final Public Standard Popular Existing Additional English Chinese
    German French Multilingual Real Synthetic Unlabeled Labeled Downstream Target Source
    Proposed Novel Raw Clean Noisy Held-out Common""".split()  # noqa: SIM905
)
# Generic words that look like names but aren't entities.
_GENERIC_NAMES = frozenset(
    """nlp ml ai cv ir qa llm llms lm lms gpu gpus tpu tpus api sota automl dl rl nn dnn
    dnns cpu cpus""".split()  # noqa: SIM905
)
_DESCRIPTOR_PREFIXES = frozenset(
    [
        "Zero-shot",
        "Few-shot",
        "One-shot",
        "Fine-grained",
        "Full",
        "Standard",
        "Official",
        "Augmented",
        "Filtered",
    ]
)
# A citation right after a name means it's someone else's work: "BERT (Devlin et al., 2019)".
_CITATION_AFTER = re.compile(
    r"^\W{0,3}\S{0,20}\s?(?:\([A-Z][^()]{0,60}\d{4}[a-z]?\)|\[\d+(?:[,–\-]\s*\d+)*\])"
)
_VARIANT_SUFFIX = (
    r"(?:[-_]?(?:base|large|small|tiny|mini|medium|xl|xxl|huge|Base|Large|Small|Tiny|BASE|"
    r"LARGE|SMALL|XL|XXL|[BLHS]/\d+|v\d+(?:\.\d+)?|\d+(?:\.\d+)?[BMK]|\d+)"
    r"|\s(?:\d+(?:\.\d+)?[BM]\b|base\b|large\b|Base\b|Large\b))?"
)


def entity_key(name: str) -> str:
    """Identity of a name across spellings: 'ResNet-50' ~ 'resnet50', 'CIFAR 10' ~ 'CIFAR-10'."""
    return re.sub(r"[^a-z0-9]+", "", name.casefold())


# --- data shapes ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Passage:
    text: str
    section_kind: str
    page: int
    section_id: str | None = None
    paragraph_index: int | None = None


@dataclass
class Evidence:
    quote: str
    page: int
    section_kind: str
    section_id: str | None
    paragraph_index: int | None
    surface: str
    strong: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "quote": self.quote,
            "page": self.page,
            "section_kind": self.section_kind,
            "section_id": self.section_id,
            "paragraph_index": self.paragraph_index,
            "surface": self.surface,
        }


@dataclass
class Discovered:
    """A name found by looking at the paper itself (not the catalog)."""

    type: EntityType
    name: str
    aliases: list[str] = field(default_factory=list)
    proposed: bool = False
    evidence: Evidence | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "type": self.type.value,
            "name": self.name,
            "aliases": self.aliases,
            "proposed": self.proposed,
            "evidence": self.evidence.as_dict() if self.evidence else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Discovered:
        ev = data.get("evidence")
        return cls(
            type=EntityType(str(data["type"])),
            name=str(data["name"]),
            aliases=[str(a) for a in data.get("aliases") or []],  # type: ignore[attr-defined]
            proposed=bool(data.get("proposed")),
            evidence=Evidence(**{**ev, "strong": True}) if isinstance(ev, dict) else None,
        )


@dataclass
class Dictionary:
    """Every name the matcher knows: catalog entries + names discovered in the library."""

    entries: list[CatalogEntry]

    @property
    def fingerprint(self) -> str:
        parts = sorted(f"{e.type}:{e.name}:{'|'.join(sorted(e.aliases))}" for e in self.entries)
        return hashlib.sha256("\n".join([EXTRACTOR_VERSION, *parts]).encode()).hexdigest()[:16]

    def surfaces(self) -> set[str]:
        return {s for e in self.entries for s in (e.name, *e.aliases)}


@dataclass
class PaperEntity:
    type: EntityType
    key: str
    name: str
    relation: str  # proposes | uses | mentions
    mentions: int
    score: float
    aliases: list[str] = field(default_factory=list)
    variants: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    source: str = "catalog"  # catalog | discovered
    info: dict[str, str] = field(default_factory=dict)


# --- sentences -----------------------------------------------------------------------------------


def _sentences(text: str) -> list[tuple[int, int]]:
    spans, start = [], 0
    for m in _SENTENCE_END.finditer(text):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(text)))
    return [(a, b) for a, b in spans if b > a]


def _quote(text: str, start: int, end: int, limit: int = 320) -> str:
    """The sentence around [start, end), trimmed to `limit` characters around the mention."""
    for a, b in _sentences(text):
        if a <= start < b:
            sentence = text[a:b].strip()
            if len(sentence) <= limit:
                return sentence
            offset = start - a
            lo = max(0, offset - limit // 2)
            hi = min(len(sentence), lo + limit)
            snippet = sentence[lo:hi].strip()
            return ("…" if lo > 0 else "") + snippet + ("…" if hi < len(sentence) else "")
    return text[max(0, start - 150) : end + 150].strip()


def _sentence_at(text: str, pos: int) -> str:
    for a, b in _sentences(text):
        if a <= pos < b:
            return text[a:b]
    return text


_REFERENCE_ENTRY = re.compile(
    r"^\s*(?:\[\d+\]|\d{1,3}\.\s)|\bet al\.|\bIn (?:Proceedings|Advances)\b|\barXiv\b|"
    r"\bpp\.\s*\d|\bpages \d+|\bvol(?:ume)?\.? \d|\b(?:Conference|Journal|Transactions) on\b"
)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")


def _looks_like_reference(text: str) -> bool:
    return len(text) < 900 and bool(_YEAR.search(text)) and bool(_REFERENCE_ENTRY.search(text))


def _skipped(passage: Passage) -> bool:
    """Bibliography entries, the author block and acknowledgments never count.

    Parsers sometimes label a whole appendix after the bibliography as "references";
    those paragraphs don't look like reference entries, so they still count.
    """
    if passage.section_kind == "references":
        return _looks_like_reference(passage.text)
    return passage.section_kind in SKIPPED_SECTIONS


# --- discovery -----------------------------------------------------------------------------------

_FRAGMENT_WORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "we",
        "our",
        "this",
        "that",
        "these",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "it",
        "its",
        "which",
        "who",
    ]
)
_PAREN_ACRONYM = re.compile(r"\(([A-Za-z][A-Za-z0-9\-]{1,14})\)")
_OR_ACRONYM = re.compile(r",?\s+or\s+([A-Z][A-Za-z0-9\-]{1,14})\b")


def _schwartz_hearst(short: str, words_before: list[str]) -> str | None:
    """Shortest long form ending right before the short form whose letters spell it.

    Classic biomedical abbreviation detection: scan both strings right to left; each
    short-form character must be found in the long form, and the first character must
    start a word.
    """
    letters = [c.lower() for c in short if c.isalnum()]
    if len(letters) < 2 or not any(c.isupper() for c in short):
        return None
    max_words = min(len(letters) + 5, len(letters) * 2)
    candidate_words = words_before[-max_words:]
    long_form = " ".join(candidate_words)
    s_index, l_index = len(letters) - 1, len(long_form) - 1
    while s_index >= 0:
        char = letters[s_index]
        while l_index >= 0 and (
            long_form[l_index].lower() != char
            or (
                s_index == 0
                and l_index > 0
                and long_form[l_index - 1].isalnum()
                and long_form[l_index - 1] != "-"
            )
        ):
            l_index -= 1
        if l_index < 0:
            return None
        s_index -= 1
        l_index -= 1
    start = long_form.rfind(" ", 0, l_index + 1) + 1
    result = long_form[start:].strip(" ,;:-")
    if not result or len(result) <= len(short) or len(result.split()) > max_words:
        return None
    if not result[0].isalpha():
        return None
    if _FRAGMENT_WORDS & {w.casefold() for w in result.split()}:
        return None  # "collect a large new dataset (CC-NEWS)" is a phrase, not a name
    return result


def acronym_definitions(text: str) -> list[tuple[str, str, int]]:
    """[(long form, short form, position)] for "Long Form (LF)" and "Long Form, or LF"."""
    found: list[tuple[str, str, int]] = []
    for pattern in (_PAREN_ACRONYM, _OR_ACRONYM):
        for m in pattern.finditer(text):
            short = m.group(1)
            if not _NAME_LIKE.match(short) and not re.match(r"^[A-Z][a-z]*[A-Z]", short):
                continue
            before = text[max(0, m.start() - 160) : m.start()]
            before = re.split(r"[.;:()\[\]]", before)[-1]
            words = before.split()
            if not words:
                continue
            long_form = _schwartz_hearst(short, words)
            if long_form:
                found.append((long_form, short, m.start()))
    return found


def _guess_type(text: str) -> EntityType | None:
    """Type from the head word of a name ("… Question Answering" is a task, but
    "Retrieval-Aware Low-rank Adaptation" is not, although it contains "Retrieval")."""
    if _DATASET_CUE.search(text):
        return EntityType.DATASET
    words = re.findall(r"[A-Za-z]+", text)
    head = words[-1] if words else ""
    if _METRIC_CUE.fullmatch(head):
        return EntityType.METRIC
    if _TASK_CUE.fullmatch(head):
        return EntityType.TASK
    if _MODEL_CUE.search(text):
        return EntityType.MODEL
    return None


_DATASET_PHRASE = re.compile(
    r"\b((?:[A-Z][\w\-./]*\s+){0,2}[A-Z][\w\-./]*)\s+(?:dataset|benchmark|corpus|data set)s?\b"
)
_TITLE_PREFIX = re.compile(r"^\s*([A-Za-z][\w\-.]{0,24}(?:\s+[\w\-.]+){0,2})\s*:\s+\S")


def _catalog_index(entries: Iterable[CatalogEntry]) -> dict[str, CatalogEntry]:
    index: dict[str, CatalogEntry] = {}
    for entry in entries:
        for surface in (entry.name, *entry.aliases):
            index.setdefault(entity_key(surface), entry)
    return index


_CATALOG_INDEX = _catalog_index(CATALOG)


def discover(
    title: str, passages: Sequence[Passage], references: Sequence[str] = ()
) -> list[Discovered]:
    """Names found in this paper alone (independent of the rest of the library).

    `references`: the parsed bibliography entries (names in cited titles are prior work).
    """
    found: dict[str, Discovered] = {}

    def add(item: Discovered) -> None:
        key = entity_key(item.name)
        if not key:
            return
        if key in found:
            existing = found[key]
            existing.proposed = existing.proposed or item.proposed
            existing.aliases = sorted(set(existing.aliases) | set(item.aliases))
            if item.proposed and item.evidence:
                existing.evidence = item.evidence
            return
        found[key] = item

    body = [p for p in passages if not _skipped(p)]
    opening = [p for p in body if p.section_kind in {"abstract", "introduction"}][:12] or body[:8]
    # Names in cited titles are prior work ("BERT: Pre-training of…" in RoBERTa's references).
    cited = " ".join(references) or " ".join(
        p.text for p in passages if p.section_kind == "references" and _looks_like_reference(p.text)
    )

    def prior_work(surface: str) -> bool:
        return (
            bool(cited)
            and re.search(rf"(?<![\w\-]){re.escape(surface)}(?![\w])", cited) is not None
        )

    # 1. Title prefix: "ColBERT: Efficient and Effective Passage Search…".
    m = _TITLE_PREFIX.match(title or "")
    if m and len(m.group(1).split()) <= 3:
        name = m.group(1).strip()
        entry = _CATALOG_INDEX.get(entity_key(name))
        add(
            Discovered(
                type=entry.type if entry else _guess_type(title) or EntityType.METHOD,
                name=entry.name if entry else name,
                proposed=True,
                evidence=Evidence(title, 1, "title", None, None, name, True),
            )
        )

    # 2. A title that starts with a known long form: "Dense Passage Retrieval for …".
    title_key = entity_key(title or "")
    for key, entry in _CATALOG_INDEX.items():
        if len(key) >= 12 and title_key.startswith(key):
            add(
                Discovered(
                    entry.type,
                    entry.name,
                    proposed=True,
                    evidence=Evidence(title, 1, "title", None, None, entry.name, True),
                )
            )

    # 3. Acronym definitions anywhere in the body.
    for passage in body:
        for long_form, short, pos in acronym_definitions(passage.text):
            entry = _CATALOG_INDEX.get(entity_key(long_form)) or _CATALOG_INDEX.get(
                entity_key(short)
            )
            if entry is None and (
                entity_key(short) in _GENERIC_NAMES or len(long_form.split()) < 2
            ):
                continue
            sentence = _sentence_at(passage.text, pos)
            kind = entry.type if entry else _guess_type(long_form)
            proposed = (
                passage in opening
                and bool(_PROPOSE.search(sentence))
                and _proposable(kind, sentence)
                and not prior_work(short)
                and not _CITATION_AFTER.match(passage.text[pos + len(short) + 2 :])
            )
            if kind is None and not proposed:
                continue
            evidence = Evidence(
                _quote(passage.text, pos, pos + len(short)),
                passage.page,
                passage.section_kind,
                passage.section_id,
                passage.paragraph_index,
                short,
                True,
            )
            name = entry.name if entry else short
            aliases = sorted({long_form, short} - {name})
            add(Discovered(kind or EntityType.METHOD, name, aliases, proposed, evidence))

    # 4. "We propose X", "a model called X" in the abstract / introduction.
    for passage in opening:
        for a, b in _sentences(passage.text):
            sentence = passage.text[a:b]
            pm = _PROPOSE.search(sentence)
            if not pm:
                continue
            rest = sentence[pm.end() :]
            if acronym_definitions(rest):
                # "We propose Retrieval-Aware Low-rank Adaptation (RALA)": the acronym step
                # already has it; reading on would find "Low-rank Adaptation" (LoRA) inside.
                continue
            name = _first_name_after(rest)
            if not name or entity_key(name) in _GENERIC_NAMES or prior_work(name):
                continue
            after = rest[rest.find(name) + len(name) :]
            if _CITATION_AFTER.match(after):
                continue
            entry = _CATALOG_INDEX.get(entity_key(name))
            kind = entry.type if entry else _guess_type(rest[:120]) or EntityType.METHOD
            if not _proposable(kind, sentence):
                continue
            add(
                Discovered(
                    type=kind,
                    name=entry.name if entry else name,
                    proposed=True,
                    evidence=Evidence(
                        _quote(passage.text, a, b),
                        passage.page,
                        passage.section_kind,
                        passage.section_id,
                        passage.paragraph_index,
                        name,
                        True,
                    ),
                )
            )

    # 5. "the Natural Questions dataset", "the BEIR benchmark".
    counts: dict[str, list[tuple[Passage, int, str]]] = defaultdict(list)
    for passage in body:
        for dm in _DATASET_PHRASE.finditer(passage.text):
            name = _dataset_name(dm.group(1))
            if name:
                counts[entity_key(name)].append((passage, dm.start(1), name))
    for hits in counts.values():
        strong = any(p.section_kind in STRONG_SECTIONS for p, _, _ in hits)
        if len(hits) < 2 and not strong:
            continue
        passage, pos, name = hits[0]
        entry = _CATALOG_INDEX.get(entity_key(name))
        if entry is not None and entry.type != EntityType.DATASET:
            continue
        add(
            Discovered(
                EntityType.DATASET,
                entry.name if entry else name,
                evidence=Evidence(
                    _quote(passage.text, pos, pos + len(name)),
                    passage.page,
                    passage.section_kind,
                    passage.section_id,
                    passage.paragraph_index,
                    name,
                    True,
                ),
            )
        )
    return list(found.values())


_NEW_RESOURCE = re.compile(
    r"\b(?:new|novel|introduce|release|collect|construct|create|build)\w*\b[^.]{0,60}"
    r"\b(?:dataset|benchmark|corpus|metric|task)\b",
    re.I,
)


def _proposable(kind: EntityType | None, sentence: str) -> bool:
    """Methods and models are proposed; a dataset / metric / task only when the sentence
    says it's new ("we release a new benchmark")."""
    if kind in (None, EntityType.METHOD, EntityType.MODEL):
        return True
    return bool(_NEW_RESOURCE.search(sentence))


def _dataset_name(phrase: str) -> str | None:
    """Clean "the ILSVRC-2012 ImageNet" / "Zero-shot Vicuna" / "RE- ALNEWS" into a name."""
    phrase = re.sub(r"(\w)- (\w)", r"\1\2", phrase)  # line-break hyphenation
    tokens = phrase.split()
    while tokens and (
        tokens[0].strip(".,") in _CAP_STOP or tokens[0].strip(".,") in _DESCRIPTOR_PREFIXES
    ):
        tokens = tokens[1:]
    if not tokens:
        return None
    # A known dataset inside the phrase wins: "ILSVRC-2012 ImageNet" → ImageNet.
    for size in range(len(tokens), 0, -1):
        for start in range(0, len(tokens) - size + 1):
            entry = _CATALOG_INDEX.get(entity_key(" ".join(tokens[start : start + size])))
            if entry is not None:
                return entry.name if entry.type == EntityType.DATASET else None
    name = " ".join(tokens).strip(".,;:")
    if len(name) < 2 or name.isdigit() or name.lower() == name:
        return None
    if entity_key(name) in _GENERIC_NAMES or not re.search(r"[A-Z].*[A-Z0-9]|\s[A-Z]", name):
        return None  # "Imagenet"-style single capitalized words are too ambiguous
    return name


def _first_name_after(text: str, window: int = 12) -> str | None:
    """The first name-like token (or known catalog phrase) within `window` words."""
    words: list[str] = _WORD.findall(text)[:window]
    for i, raw in enumerate(words):
        token = raw.strip(",.;:()[]\"'“”")
        # Known multi-word names first ("Low-Rank Adaptation", "prefix-tuning").
        for size in (4, 3, 2):
            phrase = " ".join(w.strip(",.;:()[]\"'“”") for w in words[i : i + size])
            if len(phrase.split()) == size and entity_key(phrase) in _CATALOG_INDEX:
                return phrase
        if entity_key(token) in _CATALOG_INDEX and token[:1].isupper():
            return token
        if _NAME_LIKE.match(token) and token not in _CAP_STOP and len(token) <= 20:
            return token
        if token.lower() in {"which", "that", "where", "because", "while", "to"}:
            break
    return None


# --- dictionary ----------------------------------------------------------------------------------


def build_dictionary(discovered: Iterable[Discovered]) -> Dictionary:
    """Catalog + discovered names; a discovered name that matches a catalog entry joins it."""
    by_key: dict[str, CatalogEntry] = {entity_key(e.name): e for e in CATALOG}
    alias_owner = dict(_CATALOG_INDEX)
    extra_aliases: dict[str, set[str]] = defaultdict(set)
    # Definitions first ("Natural Questions (NQ)"), so a bare "NQ dataset" found in another
    # paper joins Natural Questions instead of becoming its own entity.
    items = sorted(discovered, key=lambda d: (not d.aliases, not d.proposed, d.name))
    for item in items:
        surfaces = [item.name, *item.aliases]
        owner = next(
            (alias_owner[k] for s in surfaces if (k := entity_key(s)) in alias_owner), None
        )
        if owner is None:
            owner = CatalogEntry(item.type, item.name, ())
            by_key[entity_key(item.name)] = owner
        owner_key = entity_key(owner.name)
        for s in surfaces:
            alias_owner.setdefault(entity_key(s), owner)
            # Two-letter acronyms ("CT", "EM") are too ambiguous to match library-wide; each
            # paper's own definitions are matched inside that paper only (see `match`).
            if entity_key(s) != owner_key and len(s) >= 3:
                extra_aliases[owner_key].add(s)
    entries = []
    for key, entry in by_key.items():
        aliases = _dedupe_case(set(entry.aliases) | extra_aliases.get(key, set()), entry.name)
        entries.append(CatalogEntry(entry.type, entry.name, aliases, entry.variants, entry.info))
    return Dictionary(entries)


def _dedupe_case(aliases: set[str], name: str) -> tuple[str, ...]:
    """Drop aliases that only differ by case from the name or a nicer-cased alias."""
    chosen: dict[str, str] = {name.casefold(): name}
    for alias in sorted(aliases, key=lambda a: (a.isupper(), a)):
        chosen.setdefault(alias.casefold(), alias)
    return tuple(sorted(a for k, a in chosen.items() if a != name))


# --- matching ------------------------------------------------------------------------------------


def _case_sensitive(surface: str, kind: EntityType) -> bool:
    """Acronyms and CamelCase ("BERT", "GloVe") and one-word model / dataset names
    ("Inception", "Alpaca": proper nouns that are also English words) must match their
    case; sentence-case names ("Reciprocal rank fusion") match in any case."""
    if any(c.isupper() for c in surface[1:]):
        return True
    if surface[:1].isupper() and " " not in surface and "-" not in surface:
        return kind in (EntityType.MODEL, EntityType.DATASET)
    return False


def _squash(text: str) -> str:
    """Lowercase with spaces and hyphens removed: 'Batch-Norm' and 'batch norm' agree."""
    return re.sub(r"[\s\-]+", "", text.casefold())


class CatalogMatcher:
    """One compiled regex per case mode; longest surface forms are tried first."""

    def __init__(
        self,
        entries: Sequence[CatalogEntry],
        local: dict[str, str] | None = None,
        text: str | None = None,
    ):
        """`text`: only compile surfaces that occur in it (a C-speed substring pre-filter;
        a paper mentions a few dozen of the hundreds of known names)."""
        haystack = _squash(text) if text is not None else None
        sensitive: list[tuple[str, CatalogEntry]] = []
        insensitive: list[tuple[str, CatalogEntry]] = []
        for entry in entries:
            for surface in {entry.name, *entry.aliases}:
                if len(surface) < 2:
                    continue
                if haystack is not None and _squash(surface) not in haystack:
                    continue
                target = sensitive if _case_sensitive(surface, entry.type) else insensitive
                target.append((surface, entry))
        if local:
            key_owner = {entity_key(s): e for e in entries for s in (e.name, *e.aliases)}
            for short, long_form in local.items():
                owner = key_owner.get(entity_key(long_form))
                if owner is not None and entity_key(short) not in _GENERIC_NAMES:
                    sensitive.append((short, owner))
        self._patterns: list[tuple[re.Pattern[str], dict[str, CatalogEntry]]] = []
        for group, flags in ((sensitive, 0), (insensitive, re.IGNORECASE)):
            if not group:
                continue
            group.sort(key=lambda item: -len(item[0]))
            lookup: dict[str, CatalogEntry] = {}
            alternatives = []
            for index, (surface, entry) in enumerate(group):
                name = f"e{index}"
                lookup[name] = entry
                body = re.escape(surface).replace(r"\ ", r"[\s\-]+")
                suffix = _VARIANT_SUFFIX if entry.variants else ""
                alternatives.append(f"(?P<{name}>{body}{suffix})")
            pattern = re.compile(
                r"(?<![\w\-])(?:" + "|".join(alternatives) + r")(?![\w])(?!-[A-Za-z])", flags
            )
            self._patterns.append((pattern, lookup))

    def find(self, text: str) -> list[tuple[int, int, str, CatalogEntry]]:
        hits: list[tuple[int, int, str, CatalogEntry]] = []
        taken: list[tuple[int, int]] = []
        for pattern, lookup in self._patterns:
            for m in pattern.finditer(text):
                start, end = m.span()
                if any(a < end and start < b for a, b in taken):
                    continue  # a longer (case-sensitive) name already covers this span
                group = m.lastgroup
                assert group is not None
                hits.append((start, end, m.group(0), lookup[group]))
                taken.append((start, end))
        hits.sort()
        return hits


def match(
    title: str,
    passages: Sequence[Passage],
    dictionary: Dictionary,
    discovered: Sequence[Discovered],
) -> list[PaperEntity]:
    """Link the paper to every known entity it mentions, with relation and evidence."""
    local_acronyms: dict[str, str] = {}
    for passage in passages:
        if _skipped(passage):
            continue
        for long_form, short, _ in acronym_definitions(passage.text):
            local_acronyms.setdefault(short, long_form)
    full_text = "\n".join(p.text for p in passages if not _skipped(p))
    matcher = CatalogMatcher(dictionary.entries, local_acronyms, text=full_text)
    proposed = {entity_key(d.name): d for d in discovered if d.proposed}
    known = {entity_key(e.name): e for e in dictionary.entries}

    @dataclass
    class Tally:
        entry: CatalogEntry
        mentions: int = 0
        score: float = 0.0
        variants: set[str] = field(default_factory=set)
        evidence: list[Evidence] = field(default_factory=list)

    tallies: dict[str, Tally] = {}
    for passage in passages:
        if _skipped(passage):
            continue
        strong_section = passage.section_kind in STRONG_SECTIONS or (
            passage.section_kind == "references"  # mislabelled appendix (see `_skipped`)
        )
        for start, end, surface, entry in matcher.find(passage.text):
            key = entity_key(entry.name)
            tally = tallies.setdefault(key, Tally(entry))
            tally.mentions += 1
            cue = bool(_CUE.search(_sentence_at(passage.text, start)))
            weight = 2.0 if strong_section and cue else 1.0 if strong_section or cue else 0.25
            if passage.section_kind == "method" and weight < USES_THRESHOLD:
                weight = USES_THRESHOLD  # the method section describes what the paper does
            if passage.section_kind == "related_work" and not cue:
                weight = 0.1
            tally.score += weight
            if entry.variants and entity_key(surface) != key:
                tally.variants.add(surface.strip())
            tally.evidence.append(
                Evidence(
                    _quote(passage.text, start, end),
                    passage.page,
                    passage.section_kind,
                    passage.section_id,
                    passage.paragraph_index,
                    surface,
                    weight >= 1.0,
                )
            )

    results: list[PaperEntity] = []
    for key, tally in tallies.items():
        entry = tally.entry
        discovered_item = proposed.get(key) or next(
            (d for d in proposed.values() if key in {entity_key(a) for a in d.aliases}), None
        )
        if discovered_item is not None:
            relation = "proposes"
        elif tally.score >= USES_THRESHOLD:
            relation = "uses"
        else:
            relation = "mentions"
        # Strong sentences first, one per paragraph, document order otherwise.
        seen: set[tuple[int, int | None, str | None]] = set()
        evidence: list[Evidence] = []
        if discovered_item is not None and discovered_item.evidence is not None:
            evidence.append(discovered_item.evidence)
            seen.add(
                (
                    discovered_item.evidence.page,
                    discovered_item.evidence.paragraph_index,
                    discovered_item.evidence.section_id,
                )
            )
        for ev in sorted(tally.evidence, key=lambda e: not e.strong):
            spot = (ev.page, ev.paragraph_index, ev.section_id)
            if spot in seen:
                continue
            seen.add(spot)
            evidence.append(ev)
            if len(evidence) >= MAX_EVIDENCE:
                break
        results.append(
            PaperEntity(
                type=entry.type,
                key=key,
                name=entry.name,
                relation=relation,
                mentions=tally.mentions,
                score=round(tally.score, 2),
                aliases=sorted(set(entry.aliases)),
                variants=sorted(tally.variants)[:8],
                evidence=evidence,
                source="catalog" if key in _CATALOG_KEYS else "discovered",
                info=dict(entry.info),
            )
        )
    # Proposed names the text never repeats (e.g. only in the title) still count.
    for key, item in proposed.items():
        if key not in tallies and key in known:
            entry = known[key]
            results.append(
                PaperEntity(
                    type=entry.type,
                    key=key,
                    name=entry.name,
                    relation="proposes",
                    mentions=0,
                    score=0.0,
                    aliases=sorted(set(entry.aliases)),
                    evidence=[item.evidence] if item.evidence else [],
                    source="catalog" if key in _CATALOG_KEYS else "discovered",
                    info=dict(entry.info),
                )
            )
    results.sort(key=lambda e: (e.type, -e.score, e.name))
    return results


_CATALOG_KEYS = frozenset(entity_key(e.name) for e in CATALOG)
