"""Step-by-step guides for the Research Project Builder.

Every step has the same shape so a user always knows where they are:

    why        what this step is for and what goes wrong without it
    actions    numbered things to do, each with the reason
    expected   what they should have when it is done
    checks     how to tell the result is good, not just present
    pitfalls   the mistakes this step invites
    yours      what is true of *their* project right now (from the saved state)

The text is written once, by hand — not generated — so it can be reviewed and tested. Only
`yours` varies, and it only restates the project's own data.
"""

from __future__ import annotations

from typing import Any

from app.models.project import ResearchProject
from app.services.projects.service import MIN_PAPERS, _steps

STEP_ORDER = ("questions", "background", "gaps", "methods", "experiments", "outline", "code")


def _a(title: str, detail: str) -> dict[str, str]:
    return {"title": title, "detail": detail}


GUIDES: dict[str, dict[str, Any]] = {
    "questions": {
        "title": "Research question",
        "why": "Everything after this answers one question. A vague question gives a vague review, "
        "unfocused experiments and a paper with no point; a sharp one tells you which papers to read, "
        "what to measure and when you are done.",
        "actions": [
            _a(
                "Write your idea in plain words",
                "Two or three sentences: what you want to build or find "
                "out and for whom. Don't polish it — the next steps sharpen it.",
            ),
            _a(
                "Ask for suggestions",
                "The system reads passages of your papers and proposes questions, "
                "each linked to the passages it builds on. Read those passages: a question you can't trace "
                "to evidence is a guess.",
            ),
            _a(
                "Pick one and rewrite it",
                "Make it answerable by an experiment: name the thing you change, "
                "the thing you measure and the setting. “Does X improve Y on Z?” beats “How can we improve Y?”.",
            ),
            _a(
                "Save it",
                "Saved questions are used by the review, the gaps search and the introduction.",
            ),
        ],
        "expected": "One question, one sentence, with a variable, a measurement and a setting.",
        "checks": [
            "Could a result make you answer “no”? If every outcome would count as yes, it isn't a question yet.",
            "Does it mention something your papers actually cover? If not, add papers before going on.",
            "Could someone else tell what you would run? If not, name the dataset or task.",
        ],
        "pitfalls": [
            "Taking the first suggestion unedited — they are starting points written by a small model.",
            "A question that is really a goal (“build a better retriever”) — goals have no finishing line.",
            "Too broad for one paper: if it needs three datasets and two methods, narrow it.",
        ],
    },
    "background": {
        "title": "Background",
        "why": "You need to know what is already known before claiming something new. The review groups "
        "your papers into themes, orders them in time and compares them, with every sentence checked "
        "against the passage it cites.",
        "actions": [
            _a(
                "Check the paper list first",
                f"A review needs several papers per theme (at least "
                f"{MIN_PAPERS} for the whole project). Add papers to the project's collection — or import "
                "them from arXiv — before you run it.",
            ),
            _a(
                "Run the review",
                "It reads each paper once (slow the first time, reused afterwards), groups "
                "them, then writes. A small local model takes minutes per paper.",
            ),
            _a(
                "Read the removed sentences",
                "Sentences nothing supports are removed and listed. Many "
                "removals means the papers don't say what the model wanted to say — that is information.",
            ),
            _a(
                "Open the sources",
                "Click citations to check the passage. Fix anything you disagree with "
                "by editing; edited text is marked “not re-checked”.",
            ),
        ],
        "expected": "A cited overview, themes, a chronology and a comparison table of your papers.",
        "checks": [
            "Does each theme paragraph mention more than one paper? One paper per theme means too few papers.",
            "Do the datasets and metrics in the comparison table match what you know of each paper?",
            "Is anything important missing? Then a paper is missing from the collection.",
        ],
        "pitfalls": [
            "Treating a short review as a failure: with few papers it is correct to say little.",
            "Copying review text into your paper unchecked — verify against the sources and cite the originals.",
            "Forgetting that the review only covers your collection, not the field.",
        ],
    },
    "gaps": {
        "title": "Gap and hypothesis",
        "why": "A paper's contribution is the gap it closes. The gap says what is missing; the hypothesis says "
        "what you expect to show, in a form an experiment can refute.",
        "actions": [
            _a(
                "Run the gaps report",
                "It lists limitations and future work the authors state (their own "
                "words) and, separately, combinations the papers haven't tried (system-generated).",
            ),
            _a(
                "Choose one gap",
                "Prefer one a small experiment can address. “Stated by the authors” gaps "
                "are the safest; system-generated ones are leads to verify.",
            ),
            _a(
                "Write the hypothesis with a number",
                "“Replacing A with B keeps accuracy within 2 points while "
                "removing the need for labels.” A threshold lets you say, at the end, whether you were right.",
            ),
            _a(
                "Check it is new",
                "Search the library and arXiv for your exact combination before investing.",
            ),
        ],
        "expected": "One chosen gap and a hypothesis that names what changes, what is measured and by how much.",
        "checks": [
            "Does the hypothesis fit the gap, and the question you chose?",
            "Is there a result that would prove it wrong?",
            "Can the experiments in step 5 test it with your datasets and metrics?",
        ],
        "pitfalls": [
            "A hypothesis that can't fail (“X will help in some cases”).",
            "Picking a gap because it sounds impressive, not because you can test it.",
            "Trusting a system-generated gap without checking that nobody has done it.",
        ],
    },
    "methods": {
        "title": "Methods",
        "why": "Reviewers ask “compared to what, on what, measured how?”. Choosing datasets, baselines and "
        "metrics from what your papers actually use makes your results comparable to theirs.",
        "actions": [
            _a(
                "Look at the counted suggestions",
                "Each name shows which papers use it. Things several papers "
                "share are the community's standard — start there.",
            ),
            _a(
                "Choose datasets",
                "At least one that the papers you compare against report on, so you can "
                "check your setup against their numbers. Check the license.",
            ),
            _a(
                "Choose baselines",
                "The strongest methods your papers report, plus a simple one. A weak "
                "baseline makes any result look good and convinces nobody.",
            ),
            _a(
                "Choose metrics",
                "The ones those papers report, so the numbers can sit in the same table.",
            ),
            _a(
                "Add your own",
                "Anything the papers don't cover can be typed in — it is yours to justify.",
            ),
        ],
        "expected": "Lists of datasets, baselines, methods and metrics, each defensible in one sentence.",
        "checks": [
            "Can you point to a paper that reports each metric on each dataset?",
            "Is at least one baseline recent and strong?",
            "Do you have the compute and licenses for all of it? Cut what you can't run.",
        ],
        "pitfalls": [
            "Choosing everything suggested — more is not better; each choice is more work to implement.",
            "Metrics that don't match the task (accuracy for a ranking problem).",
            "Names are extracted automatically and can be noisy — remove anything that isn't really used.",
        ],
    },
    "experiments": {
        "title": "Experiments",
        "why": "Turns your choices into a concrete list of runs and dates. Without it, experiments grow "
        "until the deadline arrives.",
        "actions": [
            _a(
                "Generate the plan",
                "One main comparison per dataset (your approach against the baselines), "
                "an ablation and an error analysis.",
            ),
            _a(
                "Edit it",
                "Delete what you can't afford, add what the hypothesis needs, write down the exact "
                "setup of each run (data split, model size, hyperparameters).",
            ),
            _a(
                "Set a deadline",
                "Milestones are spread backwards from it, with the most time for the main "
                "experiments and writing.",
            ),
            _a(
                "Order the work",
                "Baselines first (they validate your setup), then your approach, then "
                "ablations. Don't write the paper around results you haven't got.",
            ),
        ],
        "expected": "A list of experiments, each with goal, setup and metrics, and dated milestones.",
        "checks": [
            "Does every main comparison contain your approach and at least one baseline?",
            "Is there an ablation for each component you claim matters?",
            "Do the milestones leave time for a failed first run?",
        ],
        "pitfalls": [
            "No ablation: you can't say which part of your approach does the work.",
            "Planning for one seed — plan three so you can report the spread.",
            "Setting the deadline from what you hope, not from how long a run takes.",
        ],
    },
    "outline": {
        "title": "Paper outline",
        "why": "A paper is easier to write into a structure than from nothing, and the structure shows "
        "what is still missing before you start writing.",
        "actions": [
            _a(
                "Generate the outline",
                "The introduction is drafted from passages of your papers (cited and "
                "checked); related work comes from your review; method and experiments are scaffolds from "
                "your plan; the conclusion is a checklist.",
            ),
            _a(
                "Rewrite the introduction",
                "Context, what prior work did, the gap, your contribution — in "
                "your words. Keep the citations that are right.",
            ),
            _a(
                "Fill the scaffolds later",
                "Method and experiments need your actual work; the scaffold only "
                "restates the plan. It never invents results.",
            ),
            _a(
                "Export",
                "Markdown or Word for the plan; LaTeX with BibTeX for the outline, ready for Overleaf.",
            ),
        ],
        "expected": "A structured draft with citations, exportable to LaTeX.",
        "checks": [
            "Does the introduction end in your contribution and the gap?",
            "Does related work cover every paper that matters, not only some?",
            "Is every claim about your own work still a placeholder until you have results?",
        ],
        "pitfalls": [
            "Keeping generated text you haven't read — a small model writes plausible sentences that are "
            "sometimes wrong; the labels tell you which are checked.",
            "Citing a paper you haven't read because the draft did.",
        ],
    },
    "code": {
        "title": "Starter code",
        "why": "Between a plan and results there is code: loading data, running systems, computing metrics, "
        "keeping results. The tedious, easy-to-get-wrong parts are written and tested for you; the parts "
        "that are your research are left for you.",
        "actions": [
            _a(
                "Download and open it",
                "A small Python project: README, config, systems, metrics, data, a "
                "runner and tests.",
            ),
            _a(
                "Run the smoke test",
                "`python run_experiments.py --smoke` and `python -m pytest`. This checks the "
                "machinery on a toy dataset before you add anything.",
            ),
            _a(
                "Reproduce the baselines",
                "BM25, DPR and Contriever (and hybrid / reranked variants) run as they are, from "
                "public pretrained checkpoints; the others are stubs. Check each number against "
                "the paper's — if it is far off, suspect your setup before the paper.",
            ),
            _a(
                "Make the approach yours",
                "`YourApproach` starts as a first runnable version assembled from what you chose to "
                "build on (or a stub if nothing maps). Run it unchanged and keep the result — your "
                "idea has to beat it. Then change `rank()` where the file says “Your idea goes "
                "here”: that is the part no one can generate for you.",
            ),
            _a(
                "Check the datasets",
                "SQuAD, MS MARCO, HotpotQA, TriviaQA and NQ-Open come with loaders (`pip install "
                "datasets`); the README says what each one's passages and relevance mean. TriviaQA "
                "and NQ-Open have no passages, so only answer metrics apply to them. Any other "
                "dataset fails loudly until you write its loader.",
            ),
            _a(
                "Run the experiments",
                "Results land in results/results.csv with mean ± spread over seeds.",
            ),
        ],
        "expected": "A project whose smoke test passes today, and whose TODOs are exactly the research left.",
        "checks": [
            "Smoke test and pytest pass before you change anything.",
            "Your reproduced baselines are close to the published numbers.",
            "Your approach beats the Random sanity system by a wide margin.",
        ],
        "pitfalls": [
            "Reporting a number from a system that wasn't implemented — the runner refuses to; keep it that way.",
            "Changing the metric code to make results look better — metrics.py has hand-checked tests.",
            "Tuning on the test split.",
        ],
    },
}


def _yours(
    project: ResearchProject, step: str, done: dict[str, bool], papers: int | None
) -> list[str]:
    steps = _steps(project)
    chosen = steps["methods"]["chosen"]
    notes: list[str] = []
    if step == "questions":
        notes.append(f"Your idea: “{project.idea[:160]}”")
        notes.append(
            f"Your question: “{project.question}”" if project.question else "No question saved yet."
        )
    elif step == "background":
        if papers is None:
            notes.append("No collection is linked, so papers are chosen by searching your library.")
        else:
            notes.append(
                f"The project has {papers} paper{'s' if papers != 1 else ''}"
                + (
                    "."
                    if papers >= MIN_PAPERS
                    else f" — add {MIN_PAPERS - papers}+ for a better review."
                )
            )
        notes.append("The review is " + ("ready." if done.get("background") else "not run yet."))
    elif step == "gaps":
        gap = steps["gaps"].get("chosen")
        notes.append(f"Chosen gap: {gap.get('title')}" if gap else "No gap chosen yet.")
        notes.append(
            "Your hypothesis is written." if project.hypothesis.strip() else "No hypothesis yet."
        )
    elif step == "methods":
        for label, key in (("datasets", "datasets"), ("baselines", "baselines"),
                           ("methods", "methods"), ("metrics", "metrics")):  # fmt: skip
            values = chosen.get(key) or []
            notes.append(f"{label.capitalize()}: {', '.join(values) if values else 'none chosen'}")
    elif step == "experiments":
        items = steps["experiments"]["items"]
        notes.append(
            f"{len(items)} experiment{'s' if len(items) != 1 else ''} planned."
            + (
                f" Deadline {steps['experiments']['deadline']}."
                if steps["experiments"].get("deadline")
                else " No deadline set."
            )
        )
    elif step == "outline":
        sections = steps["outline"]["sections"]
        notes.append(
            f"{len(sections)} sections drafted." if sections else "No outline drafted yet."
        )
    elif step == "code":
        missing = [n for n in ("datasets", "baselines", "metrics") if not chosen.get(n)]
        notes.append(
            "The code is generated from your plan."
            + (f" Still empty in the plan: {', '.join(missing)}." if missing else "")
        )
    return notes


def step_guide(
    project: ResearchProject, step: str, done: dict[str, bool], papers: int | None
) -> dict[str, Any]:
    guide = GUIDES[step]
    index = STEP_ORDER.index(step)
    return {
        "step": step,
        "number": index + 1,
        "of": len(STEP_ORDER),
        **guide,
        "yours": _yours(project, step, done, papers),
        "previous": STEP_ORDER[index - 1] if index else None,
        "next": STEP_ORDER[index + 1] if index + 1 < len(STEP_ORDER) else None,
    }
