"""Claim-level verification accuracy on the original SciFact dev claims, using the
app's own NLI verifier and classification thresholds
(backend/app/services/rag/verify.py: NLIVerifier, classify()).

This is a different dataset from run_benchmark.py's BEIR SciFact conversion: BEIR's
qrels.tsv only has binary relevance judgments. The verification labels
(SUPPORT/CONTRADICT) and the cited evidence sentences live in the *original* SciFact
release (download_claims.py), keyed by claim id, which happen to be the same claim ids
as BEIR's queries.jsonl (BEIR SciFact is a repackaging of this same claim set).

Method: for every (claim, cited document) pair that has annotated evidence, the premise
is the cited evidence sentences (joined) and the hypothesis is the claim text — exactly
the (premise, hypothesis) shape verify_claims() feeds the NLI model in the app's chat
pipeline, except here the "retrieved passage" is replaced by the gold evidence sentences,
since the goal is to measure the verifier in isolation, not the upstream retrieval.
classify() maps (entailment, contradiction) probabilities to SUPPORTED / PARTIAL /
UNSUPPORTED; SUPPORTED is scored as a predicted SUPPORT, anything else as a predicted
CONTRADICT, and accuracy is measured against the gold SUPPORT/CONTRADICT label.

Caveat: classify()'s thresholds were tuned for "is this claim backed by a retrieved
passage" (a precision-leaning, mostly-English-prose decision inside a RAG pipeline), not
for the NLI task of telling SUPPORT apart from CONTRADICT — a different repurposing of
the same model than it was built for. Results here should be read as "how well the
app's existing supported/not-supported decision separates genuine support from genuine
contradiction", not as a general NLI benchmark number.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from download_claims import download  # noqa: E402
from pipeline import build_settings  # noqa: E402 (sets up sys.path to backend/app, NO_ENV_FILE)

from app.services.models.manager import model_manager  # noqa: E402
from app.services.rag.verify import NLIVerifier, classify, SUPPORTED  # noqa: E402


def load_corpus(path: Path) -> dict[str, list[str]]:
    corpus: dict[str, list[str]] = {}
    with open(path / "corpus.jsonl", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            corpus[str(row["doc_id"])] = row["abstract"]
    return corpus


def load_instances(path: Path, corpus: dict[str, list[str]]) -> list[dict]:
    """One instance per (claim, cited document with evidence): gold label + evidence text."""
    instances = []
    skipped_no_evidence = 0
    with open(path / "claims_dev.jsonl", encoding="utf-8") as f:
        for line in f:
            claim = json.loads(line)
            if not claim["evidence"]:
                skipped_no_evidence += 1  # NOT_ENOUGH_INFO: no gold evidence to test against
                continue
            for doc_id, rationales in claim["evidence"].items():
                sentences = corpus.get(doc_id)
                if sentences is None:
                    continue
                labels = {r["label"] for r in rationales}
                assert len(labels) == 1, f"mixed labels for claim {claim['id']} doc {doc_id}"
                indices = sorted({i for r in rationales for i in r["sentences"]})
                evidence_text = " ".join(sentences[i] for i in indices if i < len(sentences))
                instances.append(
                    {
                        "claim_id": claim["id"],
                        "claim": claim["claim"],
                        "doc_id": doc_id,
                        "label": labels.pop(),
                        "evidence": evidence_text,
                    }
                )
    return instances, skipped_no_evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=str(HERE / "results"))
    parser.add_argument("--qdrant-dir", default=str(HERE / "qdrant_storage"))
    args = parser.parse_args()

    data_dir = download()
    corpus = load_corpus(data_dir)
    instances, skipped = load_instances(data_dir, corpus)
    print(f"[claims] {len(instances)} (claim, evidence-doc) pairs with SUPPORT/CONTRADICT "
          f"labels; {skipped} claims skipped (NOT_ENOUGH_INFO, no gold evidence to test)")

    settings = build_settings(Path(args.qdrant_dir))
    verifier = NLIVerifier(settings.verifier_model, model_manager)
    print(f"[claims] verifier model: {verifier.name}")

    t0 = time.perf_counter()
    pairs = [(inst["evidence"], inst["claim"]) for inst in instances]
    scores = verifier.entailment(pairs)
    elapsed = time.perf_counter() - t0

    # (1) the app's actual classify() thresholds, collapsed to a binary predicted label
    # (SUPPORTED -> SUPPORT, everything else -> CONTRADICT). This is what the app really
    # does, but classify()'s thresholds were tuned to be conservative about calling a RAG
    # claim "supported" (PARTIAL and UNSUPPORTED both read as "not clearly backed"), which
    # is not the same question as "does this evidence support or contradict the claim" —
    # so a PARTIAL case here is scored as a wrong answer against CONTRADICT even though
    # the model never claimed contradiction.
    confusion = {"SUPPORT": {"SUPPORT": 0, "CONTRADICT": 0}, "CONTRADICT": {"SUPPORT": 0, "CONTRADICT": 0}}
    # (2) the verifier's raw entailment-vs-contradiction probabilities, argmax'd — isolates
    # what the underlying NLI model itself can discriminate, independent of classify()'s
    # RAG-faithfulness thresholds.
    confusion_argmax = {"SUPPORT": {"SUPPORT": 0, "CONTRADICT": 0}, "CONTRADICT": {"SUPPORT": 0, "CONTRADICT": 0}}
    correct = correct_argmax = 0
    for inst, (entail, contradict) in zip(instances, scores, strict=True):
        status = classify(entail, contradict)
        predicted = "SUPPORT" if status == SUPPORTED else "CONTRADICT"
        confusion[inst["label"]][predicted] += 1
        correct += predicted == inst["label"]

        predicted_argmax = "SUPPORT" if entail >= contradict else "CONTRADICT"
        confusion_argmax[inst["label"]][predicted_argmax] += 1
        correct_argmax += predicted_argmax == inst["label"]

    accuracy = correct / len(instances) if instances else 0.0
    accuracy_argmax = correct_argmax / len(instances) if instances else 0.0
    n_support = confusion["SUPPORT"]["SUPPORT"] + confusion["SUPPORT"]["CONTRADICT"]
    n_contradict = confusion["CONTRADICT"]["SUPPORT"] + confusion["CONTRADICT"]["CONTRADICT"]
    majority_baseline = max(n_support, n_contradict) / len(instances) if instances else 0.0

    results = {
        "dataset": "scifact (original release, claims_dev.jsonl)",
        "verifier_model": verifier.name,
        "n_instances": len(instances),
        "n_claims_skipped_not_enough_info": skipped,
        "n_support": n_support,
        "n_contradict": n_contradict,
        "majority_class_baseline_accuracy": round(majority_baseline, 4),
        "accuracy_app_classify_thresholds": round(accuracy, 4),
        "confusion_matrix_app_classify_thresholds": confusion,
        "accuracy_raw_argmax_entail_vs_contradict": round(accuracy_argmax, 4),
        "confusion_matrix_raw_argmax": confusion_argmax,
        "verify_seconds_total": round(elapsed, 1),
        "verify_ms_per_instance": round(elapsed / len(instances) * 1000, 2) if instances else 0,
    }
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "claim_verification.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
