"""Datasets. Every example is a dict with the same keys, whatever the source:

    question  : str
    passages  : list[str]     candidate passages (what a retriever ranks)
    relevant  : list[int]     indices into `passages` that answer the question
    answers   : list[str]     accepted answer strings
    answer_style : str        optional: "sentence" when the accepted answers are sentences
                              (MS MARCO); generated answers are then one sentence, not a few words

`toy` is built in so the whole pipeline runs offline in a second. SQuAD, MS MARCO, HotpotQA,
TriviaQA and NQ-Open have loaders (they need `pip install datasets` and a download); each
loader's docstring says what its passages and relevance mean. Datasets without passages
(TriviaQA, NQ-Open) support answer metrics only. A dataset without a loader fails loudly instead
of returning made-up data: write a `load_<name>` that maps its rows to the keys above and
register it in LOADERS. Check each dataset's license and splits before you use it.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

Example = dict[str, Any]

TOY: list[Example] = [
    {
        "question": "Which method trains a retriever without labelled pairs?",
        "passages": [
            "Contrastive learning trains a retriever without labelled pairs by treating spans "
            "of the same document as positives.",
            "Cooking pasta needs salted boiling water and about ten minutes.",
            "The football season starts in August and ends in May.",
            "Rivers carry sediment from mountains to the sea.",
        ],
        "relevant": [0],
        "answers": ["contrastive learning"],
    },
    {
        "question": "What does the reflection token decide in Self-RAG?",
        "passages": [
            "Mountains form where tectonic plates collide over millions of years.",
            "In Self-RAG a reflection token decides whether retrieval is needed for the next "
            "segment of the answer.",
            "Gardens need sunlight and regular watering.",
            "Chess openings have names such as the Sicilian Defence.",
        ],
        "relevant": [1],
        "answers": ["whether retrieval is needed"],
    },
    {
        "question": "How is recall at k computed?",
        "passages": [
            "The orchestra tuned to the oboe before the concert began.",
            "Recall at k is the share of relevant passages that appear among the top k results.",
            "Volcanoes erupt when pressure from gas and magma builds up.",
            "A good bread dough rests overnight in the fridge.",
        ],
        "relevant": [1],
        "answers": ["share of relevant passages in the top k"],
    },
    {
        "question": "Why are hard negatives used when training dense retrievers?",
        "passages": [
            "Tides follow the pull of the moon on the oceans.",
            "Hard negatives are passages that look relevant but are not, and they make a dense "
            "retriever learn finer distinctions.",
            "The marathon route crosses three bridges.",
            "Honey never spoils when it is stored sealed.",
        ],
        "relevant": [1],
        "answers": ["they make the retriever learn finer distinctions"],
    },
]


def load_toy(split: str, limit: int | None, seed: int) -> list[Example]:
    examples = [dict(e) for e in TOY]
    random.Random(seed).shuffle(examples)
    return examples[:limit]


def _rows(dataset: str, config: str | None, split: str, limit: int | None, seed: int) -> Any:
    """Rows of a Hugging Face dataset (pip install datasets), shuffled and cut to `limit`."""
    from datasets import load_dataset

    rows = (
        load_dataset(dataset, config, split=split) if config else load_dataset(dataset, split=split)
    )
    if limit:
        rows = rows.shuffle(seed=seed).select(range(min(limit, len(rows))))
    return rows


def load_squad(split: str, limit: int | None, seed: int) -> list[Example]:
    """SQuAD: each question's context is its only passage, and it is the relevant one."""
    return [
        {
            "question": r["question"],
            "passages": [r["context"]],
            "relevant": [0],
            "answers": list(r["answers"]["text"]),
        }
        for r in _rows("rajpurkar/squad", None, split, limit, seed)
    ]


NO_ANSWER = "No Answer Present."


def load_ms_marco(split: str, limit: int | None, seed: int) -> list[Example]:
    """MS MARCO v2.1: the ten candidate passages of each query, those marked `is_selected` being
    relevant. This is *re-ranking* within the candidates, not retrieval from the whole corpus.
    Queries with no selected passage are left out."""
    examples = []
    for r in _rows("microsoft/ms_marco", "v2.1", split, limit, seed):
        selected = [i for i, flag in enumerate(r["passages"]["is_selected"]) if flag]
        if not selected:
            continue
        examples.append(
            {
                "question": r["query"],
                "passages": list(r["passages"]["passage_text"]),
                "relevant": selected,
                "answers": [a for a in r["answers"] if a and a != NO_ANSWER],
                "answer_style": "sentence",  # its answers are written sentences
            }
        )
    return examples


def load_hotpot_qa(split: str, limit: int | None, seed: int) -> list[Example]:
    """HotpotQA (distractor setting): the ten context paragraphs of each question are the
    passages (title first), the paragraphs holding supporting facts are the relevant ones. As
    with MS MARCO this is ranking within the candidates, not retrieval from Wikipedia."""
    examples = []
    for r in _rows("hotpotqa/hotpot_qa", "distractor", split, limit, seed):
        titles = list(r["context"]["title"])
        supporting = set(r["supporting_facts"]["title"])
        examples.append(
            {
                "question": r["question"],
                "passages": [
                    f"{title}. {' '.join(s.strip() for s in sentences)}"
                    for title, sentences in zip(titles, r["context"]["sentences"], strict=True)
                ],
                "relevant": [i for i, title in enumerate(titles) if title in supporting],
                "answers": [r["answer"]],
            }
        )
    return examples


def load_trivia_qa(split: str, limit: int | None, seed: int) -> list[Example]:
    """TriviaQA (rc.nocontext): questions and accepted answers only, no passages — so only answer
    metrics apply; retrieval metrics need a corpus and a retriever of your own."""
    return [
        {
            "question": r["question"],
            "passages": [],
            "relevant": [],
            "answers": list(
                dict.fromkeys([*r["answer"]["aliases"], *r["answer"]["normalized_aliases"]])
            ),
        }
        for r in _rows("mandarjoshi/trivia_qa", "rc.nocontext", split, limit, seed)
    ]


def load_nq_open(split: str, limit: int | None, seed: int) -> list[Example]:
    """NQ-Open: the questions and short answers of Natural Questions, without passages — so only
    answer metrics apply. (The full Natural Questions corpus is tens of gigabytes; load it
    yourself if you need its annotated passages.)"""
    return [
        {"question": r["question"], "passages": [], "relevant": [], "answers": list(r["answer"])}
        for r in _rows("google-research-datasets/nq_open", "nq_open", split, limit, seed)
    ]


@dataclass(frozen=True)
class Loader:
    load: Callable[[str, int | None, int], list[Example]]
    note: str  # what the user should know before relying on it


LOADERS: dict[str, Loader] = {  # keys are names with case, spaces and punctuation removed
    "toy": Loader(load_toy, "built in; four questions, runs offline"),
    "squad": Loader(load_squad, "Hugging Face rajpurkar/squad; one passage per question"),
    "msmarco": Loader(
        load_ms_marco,
        "Hugging Face microsoft/ms_marco v2.1; re-ranking the 10 candidate passages per query",
    ),
    "hotpotqa": Loader(
        load_hotpot_qa,
        "Hugging Face hotpotqa/hotpot_qa distractor setting; ranking the 10 context paragraphs",
    ),
    "triviaqa": Loader(
        load_trivia_qa, "Hugging Face mandarjoshi/trivia_qa rc.nocontext; answers only, no passages"
    ),
    "naturalquestions": Loader(
        load_nq_open,
        "NQ-Open (google-research-datasets/nq_open): Natural Questions' questions and short "
        "answers, no passages",
    ),
}
ALIASES = {"nq": "naturalquestions", "nqopen": "naturalquestions", "hotpot": "hotpotqa"}

# Datasets that are often used for this kind of work, without a loader here: where to look.
# Pointers, not loaders: confirm the identifier, config, splits and field names yourself.
POINTERS = {
    "beir": "pip install beir  (https://github.com/beir-cellar/beir)",
}


def compact(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def key_of(name: str) -> str:
    return " ".join(name.lower().replace("-", " ").replace("_", " ").split())


def find_loader(name: str) -> Loader | None:
    key = compact(name)
    return LOADERS.get(ALIASES.get(key, key))


def load(
    name: str, split: str = "validation", limit: int | None = None, seed: int = 0
) -> list[Example]:
    loader = find_loader(name)
    if loader is not None:
        return loader.load(split, limit, seed)
    pointer = POINTERS.get(compact(name))
    hint = f" Where to look: {pointer}." if pointer else ""
    raise NotImplementedError(
        f"No loader for the dataset “{name}”. Write `load_{compact(name)}` in data.py "
        f"that returns examples with question / passages / relevant / answers and add it to "
        f"LOADERS.{hint}"
    )
