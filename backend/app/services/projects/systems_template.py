"""Source text of the generated systems.py (see codegen.build_systems)."""

SYSTEMS_HEAD = '''"""The systems your experiments compare.

A system answers questions about an example (see data.py for its keys):

    rank(example, seed)     -> list[int]   passage indices, best first      (retrieval metrics)
    answer(example, seed)   -> str         the predicted answer              (answer metrics)
    evidence(example, seed) -> list[int]   the passages the answer was made from (groundedness)

Three kinds of system live here:

* the two sanity systems (finished): a floor, and a way to check the pipeline before anything
  else works — a real system that doesn't beat "Random" has a bug;
* systems *assembled from the finished components in components.py* (BM25, DPR, Contriever, a
  sentence-transformer, RRF fusion, a cross-encoder reranker) and, for retrieval-augmented
  generation, a language model from generation.py. They run as they are and say so in
  results.csv ("starter pipeline: ..."); they use public pretrained checkpoints, nothing is
  trained;
* TODO stubs for everything the components don't cover. A stub raises NotImplementedError and
  the runner records a "todo" row instead of a number.
"""

from __future__ import annotations

import random
import re

import components
import data
import generation


class System:
    label = ""
    note = ""  # shown in results.csv next to every number this system produces

    def prepare(self, examples: list[data.Example]) -> None:
        """Called once with the whole dataset before any example is scored."""

    def rank(self, example: data.Example, seed: int) -> list[int]:
        raise NotImplementedError(f"{self.label} has no rank() yet.")

    def answer(self, example: data.Example, seed: int) -> str:
        raise NotImplementedError(f"{self.label} has no answer() yet.")

    def evidence(self, example: data.Example, seed: int) -> list[int] | None:
        """The passages answer() used; None = not known (groundedness is then not computed)."""
        return None


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


class LexicalOverlap(System):
    """Ranks passages by words shared with the question. A weak but real baseline."""

    label = "Lexical overlap (sanity check)"

    def rank(self, example: data.Example, seed: int) -> list[int]:
        question = _words(example["question"])
        scores = [len(question & _words(p)) / (len(_words(p)) ** 0.5 or 1) for p in example["passages"]]
        return sorted(range(len(scores)), key=lambda i: (-scores[i], i))

    def answer(self, example: data.Example, seed: int) -> str:
        ranking = self.rank(example, seed)
        if not ranking:  # a dataset without passages (TriviaQA, NQ-Open): nothing to answer from
            return ""
        return components.best_sentence(example["question"], example["passages"][ranking[0]])

    def evidence(self, example: data.Example, seed: int) -> list[int]:
        return self.rank(example, seed)[:1]


class Random(System):
    """Ranks and answers at random. The floor every real system must clear."""

    label = "Random (sanity check)"

    def rank(self, example: data.Example, seed: int) -> list[int]:
        order = list(range(len(example["passages"])))
        random.Random(f"{seed}:{example['question']}").shuffle(order)
        return order

    def answer(self, example: data.Example, seed: int) -> str:
        chosen = self.evidence(example, seed)
        return example["passages"][chosen[0]].split(".")[0] if chosen else ""

    def evidence(self, example: data.Example, seed: int) -> list[int]:
        if not example["passages"]:
            return []
        return [random.Random(f"{seed}:{example['question']}").randrange(len(example["passages"]))]


class PipelineSystem(System):
    """A system made of the finished components: first-stage scorer(s), RRF fusion when there are
    several, an optional cross-encoder rerank. Answers come from the extractive reader (the
    sentence of the top passage closest to the question) or, with `generate`, from the language
    model configured in config.json ("generator"), given the top passages. No first stage and
    `generate`: the model answers from the question alone (closed-book) and nothing is ranked.

    With `gate`, retrieval is decided per question (config.json "gate"): policy "abstain" asks the
    model closed-book first and retrieves only if it says it can't answer; policy "retriever"
    retrieves only when the top first-stage score stands out (components.Pipeline.confidence).
    rank() still ranks every question, so retrieval metrics describe the retriever; evidence() is
    empty when the gate kept retrieval off, which is what the retrieval-rate metric counts."""

    stages: list[str] = []
    rerank = False
    generate = False
    gate = False
    unmapped: list[str] = []

    def __init__(self) -> None:
        # models load on first use; the generator contacts its model on the first answer
        self._pipeline = components.build(self.stages, self.rerank) if self.stages else None
        self._generator = generation.Generator.from_config() if self.generate else None
        self._gate = generation.gate_settings() if self.gate else None
        self._last: tuple = (None, None, None)  # rank() is asked for once per metric family
        self._decided: tuple = (None, None, None)  # the gate's decision for the last example

    @property
    def note(self) -> str:  # type: ignore[override]
        described = components.describe(self.stages, self.rerank, self.generate, self.gate)
        text = "starter pipeline: " + described
        if self._generator is not None:
            text += f" ({self._generator.describe()})"
        if self._gate is not None:
            text += f"; {self._gate['describe']}"
        if self.unmapped:
            text += f"; NOT implemented (no component): {', '.join(self.unmapped)}"
        return text

    @property
    def generation_stats(self) -> generation.Stats | None:
        return self._generator.stats if self._generator is not None else None

    def prepare(self, examples: list[data.Example]) -> None:
        if self._pipeline is not None:
            self._pipeline.prepare(examples)

    def rank(self, example: data.Example, seed: int) -> list[int] | None:
        if self._pipeline is None:
            return None  # closed-book: retrieval metrics don't apply
        if self._last[0] is not example or self._last[1] != seed:
            self._last = (example, seed, self._pipeline.rank(example))
        return self._last[2]

    def retrieves(self, example: data.Example, seed: int) -> bool:
        """Whether the answer to this example is made from passages: always, without a gate."""
        if self._gate is None or self._pipeline is None or self._generator is None:
            return True
        if self._decided[0] is not example or self._decided[1] != seed:
            if self._gate["policy"] == "retriever":
                retrieve = self._pipeline.confidence(example) >= self._gate["threshold"]
            else:  # "abstain": the closed-book answer is cached, so answer() reuses it for free
                style = example.get("answer_style", "short")
                closed_book = self._generator.answer(example["question"], [], style)
                retrieve = closed_book == generation.ABSTAIN
            self._decided = (example, seed, retrieve)
        return self._decided[2]

    def evidence(self, example: data.Example, seed: int) -> list[int]:
        if not self.retrieves(example, seed):
            return []
        ranking = self.rank(example, seed) or []
        return ranking[: self._generator.top_k] if self._generator is not None else ranking[:1]

    def answer(self, example: data.Example, seed: int) -> str:
        if self._generator is not None and self.stages and not example["passages"]:
            # Answering closed-book here would make this system the closed-book baseline under
            # another name. Say so instead.
            raise NotImplementedError(
                f"{self.label} answers from retrieved passages and this dataset has none "
                "(TriviaQA, NQ-Open): retrieval-augmented generation on it needs a corpus and a "
                "retriever of your own. A closed-book system still runs."
            )
        chosen = self.evidence(example, seed)
        if self._generator is not None:
            passages = [example["passages"][i] for i in chosen]
            return self._generator.answer(example["question"], passages, example.get("answer_style", "short"))
        if not chosen:
            return ""
        return components.best_sentence(example["question"], example["passages"][chosen[0]])
'''

APPROACH_RUNNABLE = '''

class YourApproach(PipelineSystem):
    """The system your hypothesis is about — a FIRST RUNNABLE VERSION, not your idea.

    Hypothesis: {hypothesis}
    Builds on: {builds_on}.
    Assembled from finished components: {described}.
    {unmapped_line}

    It exists so your experiments run end to end today, and so you have a working system to
    change. What makes your approach *new* is not in here: it is whatever you do differently from
    these parts. Put it in rank() or answer() below (README, step 5, has worked examples).
    """

    label = {label!r}
    stages = {stages!r}
    rerank = {rerank!r}
    generate = {generate!r}
    gate = {gate!r}
    unmapped = {unmapped!r}

    # --- Your idea goes here ---------------------------------------------------------------
    # def rank(self, example: data.Example, seed: int) -> list[int]:
    #     base = super().rank(example, seed)      # the starter pipeline's ordering
    #     return base                             # <- change how passages are scored or ordered
    #
    # def answer(self, example: data.Example, seed: int) -> str:
    #     return super().answer(example, seed)    # <- or change how the answer is produced
'''

APPROACH_STUB = '''

class YourApproach(System):
    """The system your hypothesis is about.

    Hypothesis: {hypothesis}
    {builds_on_line}
    {unmapped_line}
    """

    label = {label!r}

    def rank(self, example: data.Example, seed: int) -> list[int]:
        raise NotImplementedError(
            "TODO: implement YourApproach.rank — return passage indices, best first."
        )

    def answer(self, example: data.Example, seed: int) -> str:
        raise NotImplementedError("TODO: implement YourApproach.answer — return the answer string.")
'''

APPROACH_DRAFTED = '''

class YourApproach(System):
    """The system your hypothesis is about.

    Hypothesis: {hypothesis}
    {builds_on_line}

    *** LLM-DRAFTED — UNVERIFIED. ***
    A first attempt written by the language model configured in Settings → AI, from the passages
    below (it saw nothing else). Unlike the report sections elsewhere in this app, a block of code
    isn't a sentence an entailment checker can verify: nobody has run this. Read it, run it, and
    expect to fix it before trusting any number it produces.

    Drafted from: {source_list}
    """

    label = {label!r}

{code}
'''

BASELINE_DRAFTED = '''

class {cls}(System):
    """Baseline: {name}. {where}

    *** LLM-DRAFTED — UNVERIFIED. ***
    A first attempt written by the language model configured in Settings → AI, from the passages
    below. Not run, not checked. Read it, run it, and compare it against the paper's own reported
    numbers before trusting it as a baseline.

    Drafted from: {source_list}
    """

    label = {name!r}

{code}
'''

BASELINE_RUNNABLE = '''

class {cls}(PipelineSystem):
    """Baseline: {name}. {where}

    Implemented from finished components: {described}. These are public pretrained checkpoints, not
    models retrained as in the paper: to reproduce a paper's number, use its data and settings.
    """

    label = {name!r}
    stages = {stages!r}
    rerank = {rerank!r}
    generate = {generate!r}
    gate = {gate!r}
'''

BASELINE_STUB = '''

class {cls}(System):
    """Baseline: {name}. {where}

    No component implements it. Implement it the way those papers describe it (same data, same
    settings), or use their released code. Comparing against a weaker version of a baseline
    proves nothing.
    """

    label = {name!r}

    def rank(self, example: data.Example, seed: int) -> list[int]:
        raise NotImplementedError("TODO: implement {cls}.rank")

    def answer(self, example: data.Example, seed: int) -> str:
        raise NotImplementedError("TODO: implement {cls}.answer")
'''

SYSTEMS_TAIL = """

def build(name: str) -> System:
    if name not in REGISTRY:
        raise NotImplementedError(f"No system called “{name}”. Add a class and register it in systems.py.")
    return REGISTRY[name]()
"""
