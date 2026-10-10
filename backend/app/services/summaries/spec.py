"""What a summary contains, and which part of the paper answers each field.

Map step: one model call per *section group* — the fields that the same sections
answer are written together from those sections' passages (problem, motivation
and contribution come from the abstract and introduction; dataset, experiments
and results from the experiment sections; ...). Four short calls fit a small
local model's context and stay grounded, where one call over a whole paper
would either not fit or have to drop most of it.

Reduce step: the one-line takeaway is written from the drafted fields (and
cites the same passages), so it can only repeat what the summary already backs.
"""

from __future__ import annotations

from dataclasses import dataclass

PROMPT_VERSION = "summary-v7"
NOT_REPORTED = "Not reported."


@dataclass(frozen=True, slots=True)
class Field:
    key: str
    label: str  # the line label the model writes ("PROBLEM: …")
    title: str
    question: str


@dataclass(frozen=True, slots=True)
class Group:
    name: str
    detail: str  # progress text while this group is written
    section_kinds: tuple[str, ...]  # where the answers are expected
    # Short sections whose passages are put first when they exist (the abstract states
    # the headline results, which the results sections often only give as a table).
    lead_kinds: tuple[str, ...]
    query: str  # ranks passages inside the sections, and finds them if headings are missing
    fields: tuple[Field, ...]
    chunk_kinds: tuple[str, ...] = ("text",)


PROBLEM = Field("problem", "PROBLEM", "Problem", "What problem does the paper address?")
MOTIVATION = Field("motivation", "MOTIVATION", "Motivation", "Why does this problem matter?")
CONTRIBUTION = Field(
    "contribution", "CONTRIBUTION", "Key contribution", "What is new in this work?"
)
METHOD = Field("method", "METHOD", "Method", "What does the paper propose, and how does it work?")
ARCHITECTURE = Field(
    "architecture",
    "ARCHITECTURE",
    "Architecture",
    "Which models, components or algorithms are used?",
)
DATASET = Field("dataset", "DATASET", "Dataset", "Which datasets or data were used?")
EXPERIMENTS = Field(
    "experiments",
    "EXPERIMENTS",
    "Experiments",
    "What experiments or evaluations were performed, and against which baselines?",
)
RESULTS = Field(
    "results", "RESULTS", "Results", "What were the main results? Include the key numbers."
)
LIMITATIONS = Field(
    "limitations", "LIMITATIONS", "Limitations", "What limitations do the authors report?"
)
FUTURE_WORK = Field(
    "future_work", "FUTURE_WORK", "Future work", "What future work do the authors suggest?"
)
TAKEAWAY = Field(
    "takeaway",
    "TAKEAWAY",
    "One-line takeaway",
    "The single most important point of this paper, as one plain sentence.",
)

GROUPS: tuple[Group, ...] = (
    Group(
        "overview",
        "Reading the abstract and introduction",
        # Not the title/author block: as a passage it made the model answer with citations only.
        ("abstract", "introduction"),
        (),
        "problem challenge task motivation important costly limited propose introduce "
        "contribution novel new",
        (PROBLEM, MOTIVATION, CONTRIBUTION),
    ),
    Group(
        "method",
        "Reading the method",
        ("method",),
        (),
        "method approach propose model architecture framework component module layer "
        "algorithm objective train",
        (METHOD, ARCHITECTURE),
        ("text", "equation"),
    ),
    Group(
        "experiments",
        "Reading the experiments and results",
        ("experiments", "results"),
        ("abstract",),
        "dataset data benchmark evaluate experiment baseline compare result accuracy "
        "improve outperform score table",
        (DATASET, EXPERIMENTS, RESULTS),
        # Tables, not bare captions: caption-only passages ("Figure 1: Peak GPU memory.")
        # gave the model numbers to cite but nothing to say, and it looped on citations.
        ("text", "table"),
    ),
    Group(
        "outlook",
        "Reading the limitations and conclusion",
        ("limitations", "discussion", "conclusion", "future_work"),
        (),
        "limitation limit only restrict assume fail future work direction remain open",
        (LIMITATIONS, FUTURE_WORK),
    ),
)

# The brief's order: problem → … → key contribution → one-line takeaway.
FIELDS: tuple[Field, ...] = (
    PROBLEM, MOTIVATION, METHOD, ARCHITECTURE, DATASET, EXPERIMENTS, RESULTS,
    LIMITATIONS, FUTURE_WORK, CONTRIBUTION, TAKEAWAY,
)  # fmt: skip
FIELD_ORDER = {f.key: i for i, f in enumerate(FIELDS)}
# Labels models write instead of ours ("Key contribution:", "Future work:", "Takeaway:").
ALIASES = {
    "KEY_CONTRIBUTION": "contribution",
    "CONTRIBUTIONS": "contribution",
    "KEY_CONTRIBUTIONS": "contribution",
    "FUTURE_WORKS": "future_work",
    "FUTURE_DIRECTIONS": "future_work",
    "DATASETS": "dataset",
    "DATA": "dataset",
    "EXPERIMENT": "experiments",
    "RESULT": "results",
    "LIMITATION": "limitations",
    "METHODS": "method",
    "METHODOLOGY": "method",
    "ONE_LINE_TAKEAWAY": "takeaway",
    "KEY_TAKEAWAY": "takeaway",
}
