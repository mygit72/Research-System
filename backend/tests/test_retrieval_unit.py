"""BM25, RRF and the analyzer, checked against hand-computed values."""

from __future__ import annotations

import math
import uuid

import pytest

from app.services.retrieval.bm25 import BM25Index
from app.services.retrieval.fusion import ReciprocalRankFusion
from app.services.retrieval.service import snippet_window
from app.services.retrieval.text import analyze, fts_terms, highlight_spans, tokenize
from app.services.retrieval.types import IndexedVersion, SearchScope

# --- analyzer ---------------------------------------------------------------------------------


def test_analyzer_stems_drops_stopwords_and_splits_hyphens() -> None:
    assert analyze("Retrieving the retrieved retrievals") == ["retriev"] * 3
    assert analyze("Fine-tuning of a model") == ["fine", "tune", "model"]
    assert analyze("GPT-4 in 2023 with 7B parameters") == ["gpt", "4", "2023", "7b", "paramet"]


def test_tokens_keep_offsets_through_unicode_expansion() -> None:
    text = "Eﬃcient ﬁne-tuning"  # PDF ligatures expand under NFKC
    spans = highlight_spans(text, set(analyze("efficient fine tuning")))
    assert [text[s:e] for s, e in spans] == ["Eﬃcient ﬁne-tuning"]
    assert all(text[t.start : t.end] for t in tokenize(text))


def test_highlights_merge_adjacent_terms_only() -> None:
    text = "We use reciprocal rank fusion, not rank averaging."
    spans = highlight_spans(text, set(analyze("reciprocal rank fusion")))
    assert [text[s:e] for s, e in spans] == ["reciprocal rank fusion", "rank"]


def test_fts_terms_are_safe_for_tsquery() -> None:
    assert fts_terms("BM25 & dense | (retrieval)!") == ["bm25", "dense", "retrieval"]
    assert fts_terms("the of and") == []


# --- BM25 -------------------------------------------------------------------------------------


@pytest.fixture
def tiny() -> BM25Index:
    index = BM25Index(k1=1.2, b=0.75)
    index.add("d1", ["x", "y"])
    index.add("d2", ["x", "x", "z", "z"])
    index.add("d3", ["z"])
    return index


def test_bm25_matches_hand_computed_scores(tiny: BM25Index) -> None:
    # N=3, avgdl=7/3, df(x)=2 → IDF = ln(1 + 1.5/2.5) = ln 1.6
    assert tiny.idf("x") == pytest.approx(math.log(1.6))
    hits = {h.key: h.score for h in tiny.search(["x"], 10)}
    assert hits == {
        "d2": pytest.approx(0.538145, abs=1e-6),
        "d1": pytest.approx(0.499176, abs=1e-6),
    }
    # Multi-term queries sum per-term scores; d2 has tf=2 for both x and z.
    ranked = tiny.search(["x", "z"], 10)
    assert [h.key for h in ranked] == ["d2", "d3", "d1"]
    assert ranked[0].score == pytest.approx(1.076291, abs=1e-6)
    assert ranked[1].score == pytest.approx(0.613395, abs=1e-6)  # short doc: length norm helps
    assert ranked[0].matched_terms == {"x": 2, "z": 2}


def test_bm25_parameters_behave_as_documented(tiny: BM25Index) -> None:
    tiny.k1 = 0.0  # binary: tf no longer matters
    scores = {h.key: h.score for h in tiny.search(["x"], 10)}
    assert scores["d1"] == pytest.approx(scores["d2"])
    tiny.k1, tiny.b = 1.2, 0.0  # no length normalization: tf=2 strictly wins
    scores = {h.key: h.score for h in tiny.search(["x"], 10)}
    assert scores["d2"] > scores["d1"]
    assert tiny.search(["unknown"], 10) == []
    assert tiny.search(["x", "x"], 10)[0].score == tiny.search(["x"], 10)[0].score


def test_bm25_incremental_updates_equal_a_rebuild(tiny: BM25Index) -> None:
    tiny.add("d4", ["y", "y", "q"])
    tiny.remove("d1", ["x", "y"])
    tiny.remove("d4")  # without terms: vocabulary scan
    tiny.add("d1", ["x", "y"])
    rebuilt = BM25Index()
    for key, terms in (("d1", ["x", "y"]), ("d2", ["x", "x", "z", "z"]), ("d3", ["z"])):
        rebuilt.add(key, terms)
    assert tiny.postings == rebuilt.postings
    assert tiny.lengths == rebuilt.lengths and tiny.total_length == rebuilt.total_length
    tiny.add("d1", ["q"])  # re-adding a key replaces it
    assert "x" not in {t for t, p in tiny.postings.items() if "d1" in p}


def test_bm25_filters_before_the_top_k_cut() -> None:
    index = BM25Index()
    for i in range(10):
        index.add(f"strong{i}", ["rare", "rare", "rare"])
    index.add("weak", ["rare", "filler", "filler", "filler", "filler"])
    # The only allowed passage ranks last overall but must still be returned with k=1.
    hits = index.search(["rare"], 1, allow=lambda key: key == "weak")
    assert [h.key for h in hits] == ["weak"]


def test_bm25_ties_are_deterministic() -> None:
    index = BM25Index()
    for key in ("b", "c", "a"):
        index.add(key, ["same"])
    assert [h.key for h in index.search(["same"], 3)] == ["a", "b", "c"]


# --- RRF --------------------------------------------------------------------------------------


def test_rrf_formula_and_agreement() -> None:
    fused = ReciprocalRankFusion(k=60).fuse(
        {"bm25": [("a", 12.0), ("b", 9.0), ("c", 1.0)], "dense": [("b", 0.9), ("d", 0.8)]}, 10
    )
    scores = {h.key: h.score for h in fused}
    assert scores["b"] == pytest.approx(1 / 62 + 1 / 61)  # found by both
    assert scores["a"] == pytest.approx(1 / 61)
    assert [h.key for h in fused] == ["b", "a", "d", "c"]  # agreement beats a single #1
    b = fused[0]
    assert b.contributions["bm25"].rank == 2 and b.contributions["dense"].rank == 1
    assert sum(c.contribution for c in b.contributions.values()) == pytest.approx(b.score)


def test_rrf_k_controls_top_rank_advantage() -> None:
    rankings = {
        "bm25": [("a", 1.0), ("x", 0.6), ("b", 0.5)],
        "dense": [("c", 1.0), ("y", 0.6), ("b", 0.5)],
    }
    # k=0: one first place (1/1) beats two third places (1/3 + 1/3).
    assert ReciprocalRankFusion(k=0).fuse(rankings, 5)[0].key == "a"
    # k=60: 1/61 < 2/63, so agreement between retrievers wins.
    assert ReciprocalRankFusion(k=60).fuse(rankings, 5)[0].key == "b"
    with pytest.raises(ValueError):
        ReciprocalRankFusion(k=-1).fuse(rankings, 3)


def test_rrf_ties_are_stable_and_limit_applies() -> None:
    rankings = {"bm25": [("x", 1.0)], "dense": [("y", 1.0)]}
    first = [h.key for h in ReciprocalRankFusion().fuse(rankings, 5)]
    assert first == [h.key for h in ReciprocalRankFusion().fuse(rankings, 5)] == ["x", "y"]
    assert len(ReciprocalRankFusion().fuse(rankings, 1)) == 1


# --- scope & snippets -------------------------------------------------------------------------


def test_scope_filters() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    versions = {
        uuid.uuid4(): IndexedVersion(a, None, "m"),
        uuid.uuid4(): IndexedVersion(b, None, "m"),
    }
    scope = SearchScope(
        uuid.uuid4(), versions, allowed_documents={a}, exclude_section_kinds={"references"}
    )
    assert scope.allows(a, "method") and not scope.allows(b, "method")
    assert not scope.allows(a, "references")
    assert SearchScope(uuid.uuid4(), versions, allowed_documents=set()).is_empty


def test_snippet_window_centres_on_the_densest_matches() -> None:
    text = ("filler " * 80) + "reciprocal rank fusion combines rankings " + ("tail " * 80)
    spans = highlight_spans(text, set(analyze("reciprocal rank fusion")))
    start, end = snippet_window(text, spans, size=120)
    assert end - start <= 120
    assert "reciprocal rank fusion" in text[start:end]
    assert text[start - 1] == " "  # starts on a word boundary
    assert snippet_window("short text", []) == (0, 10)
    assert snippet_window(text, [], size=100)[0] == 0
