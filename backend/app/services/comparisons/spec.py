"""What a comparison table contains, and which part of each paper answers each row.

Two kinds (the brief's "paper comparison" and "methodology comparison"). Each is a
list of section groups, extracted per paper with the summaries' FieldExtractor, so
every cell is cited and checked the same way a summary is.
"""

from __future__ import annotations

from enum import StrEnum

from app.services.summaries.spec import (
    ARCHITECTURE,
    DATASET,
    LIMITATIONS,
    PROBLEM,
    RESULTS,
    Field,
    Group,
)

PROMPT_VERSION = "compare-v4"  # cell extraction: part of the per-paper cache key
OVERVIEW_PROMPT_VERSION = "overview-v2"  # recorded in generation_config
MIN_PAPERS, MAX_PAPERS = 2, 5


class ComparisonKind(StrEnum):
    PAPERS = "papers"
    METHODOLOGY = "methodology"


MODEL = Field("model", "MODEL", "Model", "Which model or approach does the paper propose or use?")
TRAINING = Field(
    "training", "TRAINING", "Training", "How is the model trained (data, objective, procedure)?"
)
EVALUATION = Field(
    "evaluation",
    "EVALUATION",
    "Evaluation",
    "How is the work evaluated, and against which baselines?",
)
METRICS = Field("metrics", "METRICS", "Metrics", "Which evaluation metrics are reported?")
COMPUTE = Field(
    "compute",
    "COMPUTE",
    "Compute",
    "What compute, hardware, model size or training cost is reported?",
)

TRAINING_DATA = Field(
    "training_data", "TRAINING_DATA", "Training data", "Which data is the model trained on?"
)
PREPROCESSING = Field(
    "preprocessing",
    "PREPROCESSING",
    "Preprocessing",
    "How is the data preprocessed (cleaning, tokenization, filtering)?",
)
OBJECTIVE = Field("objective", "OBJECTIVE", "Objective", "What is the training objective?")
LOSS = Field("loss", "LOSS", "Loss function", "Which loss function is used?")
OPTIMIZATION = Field(
    "optimization",
    "OPTIMIZATION",
    "Optimization",
    "Which optimizer and training procedure are used?",
)
HYPERPARAMETERS = Field(
    "hyperparameters",
    "HYPERPARAMETERS",
    "Hyperparameters",
    "Which hyperparameters are reported (learning rate, batch size, rank, steps)?",
)
EVALUATION_METHOD = Field(
    "evaluation_method",
    "EVALUATION_METHOD",
    "Evaluation method",
    "How is the method evaluated: benchmarks, baselines and protocol?",
)

_PAPER_GROUPS = (
    Group(
        "overview",
        "the abstract and introduction",
        ("abstract", "introduction"),
        (),
        "problem challenge task costly limited expensive",
        (PROBLEM,),
    ),
    Group(
        "method",
        "the method",
        ("method",),
        (),
        "method approach propose model architecture component layer train objective",
        (MODEL, ARCHITECTURE, TRAINING),
        ("text", "equation"),
    ),
    Group(
        "experiments",
        "the experiments and results",
        ("experiments", "results"),
        ("abstract",),
        "dataset benchmark evaluate baseline metric accuracy score result compute gpu "
        "parameters hours table",
        (DATASET, EVALUATION, METRICS, RESULTS, COMPUTE),
        ("text", "table"),
    ),
    Group(
        "outlook",
        "the limitations",
        ("limitations", "discussion", "conclusion"),
        (),
        "limitation limit only restrict assume fail",
        (LIMITATIONS,),
    ),
)

_METHODOLOGY_GROUPS = (
    Group(
        "method",
        "the method",
        ("method",),
        (),
        "architecture model layer objective loss function minimize maximize",
        (ARCHITECTURE, OBJECTIVE, LOSS),
        ("text", "equation"),
    ),
    Group(
        "training",
        "the training setup",
        ("experiments", "method"),
        (),
        "train data corpus preprocess tokenize filter optimizer adam learning rate batch "
        "epoch steps hyperparameter rank",
        (TRAINING_DATA, PREPROCESSING, OPTIMIZATION, HYPERPARAMETERS),
        ("text", "table"),
    ),
    Group(
        "evaluation",
        "the evaluation",
        ("experiments", "results"),
        (),
        "evaluate benchmark baseline protocol metric compare test split",
        (EVALUATION_METHOD,),
        ("text", "table"),
    ),
)

GROUPS: dict[ComparisonKind, tuple[Group, ...]] = {
    ComparisonKind.PAPERS: _PAPER_GROUPS,
    ComparisonKind.METHODOLOGY: _METHODOLOGY_GROUPS,
}
# Row order of the table (the brief's order).
ROWS: dict[ComparisonKind, tuple[Field, ...]] = {
    ComparisonKind.PAPERS: (
        PROBLEM, DATASET, MODEL, ARCHITECTURE, TRAINING, EVALUATION, METRICS, RESULTS,
        LIMITATIONS, COMPUTE,
    ),
    ComparisonKind.METHODOLOGY: (
        ARCHITECTURE, TRAINING_DATA, PREPROCESSING, OBJECTIVE, LOSS, OPTIMIZATION,
        HYPERPARAMETERS, EVALUATION_METHOD,
    ),
}  # fmt: skip

OVERVIEW = Field(
    "overview",
    "OVERVIEW",
    "Overview",
    "In three to five sentences: the most important differences and similarities between "
    "these papers, naming the paper each point comes from.",
)
