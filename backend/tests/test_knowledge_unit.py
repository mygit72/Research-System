"""Entity extraction, clustering, graph ranking, authors and citation matching (no DB)."""

from __future__ import annotations

import uuid
from collections import Counter
from itertools import pairwise

import networkx as nx
import numpy as np
import pytest

from app.services.knowledge import clustering as algo
from app.services.knowledge.catalog import CATALOG, EntityType
from app.services.knowledge.extract import (
    Discovered,
    Passage,
    acronym_definitions,
    build_dictionary,
    discover,
    entity_key,
    match,
)
from app.services.knowledge.graph import pagerank
from app.services.knowledge.library import (
    Paper,
    match_citations,
    merge_initials,
    person_key,
    plausible_author,
    split_affiliation,
)
from app.services.knowledge.topics import clean_name, ctfidf_terms, grounded


def P(text: str, kind: str = "experiments", page: int = 1) -> Passage:
    return Passage(text, kind, page)


# --- catalog -------------------------------------------------------------------------------------


def test_catalog_surface_forms_are_unambiguous() -> None:
    owners: dict[str, set[str]] = {}
    for entry in CATALOG:
        for surface in (entry.name, *entry.aliases):
            owners.setdefault(entity_key(surface), set()).add(entry.name)
    clashes = {k: v for k, v in owners.items() if len(v) > 1}
    assert clashes == {}


# --- discovery -----------------------------------------------------------------------------------


def test_schwartz_hearst_acronyms() -> None:
    text = (
        "We evaluate on Natural Questions (NQ) and use maximum inner product search (MIPS). "
        "We propose Low-Rank Adaptation, or LoRA, for adaptation."
    )
    found = {short: long for long, short, _ in acronym_definitions(text)}
    assert found["NQ"] == "Natural Questions"
    assert found["MIPS"] == "maximum inner product search"
    assert found["LoRA"] == "Low-Rank Adaptation"
    # A phrase whose letters happen to spell the acronym isn't a long form.
    assert acronym_definitions("To this end we collect a large new dataset (CC-NEWS).") == []


def test_discovery_finds_what_a_paper_proposes_but_not_prior_work() -> None:
    title = "ColBERT: Efficient Passage Search via Late Interaction"
    passages = [
        P("We present ColBERT, a novel ranking model that adapts deep LMs.", "abstract"),
        P(
            "We present a replication study of BERT pretraining (Devlin et al., 2019).",
            "introduction",
        ),
        P("We also present analysis on CIFAR-10 with 100 layers.", "introduction"),
    ]
    found = {d.name: d for d in discover(title, passages)}
    assert found["ColBERT"].proposed and found["ColBERT"].type == EntityType.MODEL
    assert "BERT" not in found or not found["BERT"].proposed  # followed by a citation
    assert "CIFAR-10" not in found or not found["CIFAR-10"].proposed  # datasets need "new"


def test_names_in_the_bibliography_are_not_proposed() -> None:
    passages = [P("We introduce Guanaco, a chatbot family.", "abstract")]
    assert discover("Some title", passages)[0].proposed
    cited = ["[3] A. B. Guanaco: a chatbot. arXiv:2301.00001, 2023."]
    assert not any(d.proposed for d in discover("Some title", passages, cited))


def test_dataset_phrases_need_a_name() -> None:
    passages = [
        P("We evaluate on the SciQA-2400 benchmark and the NLP benchmark."),
        P("Results on the SciQA-2400 benchmark are in Table 2."),
        P("We train on the ILSVRC-2012 ImageNet dataset."),
    ]
    names = {d.name for d in discover("t", passages) if d.type == EntityType.DATASET}
    assert "SciQA-2400" in names
    assert "NLP" not in names
    assert "ImageNet" in names  # a known dataset inside the phrase wins


# --- matching ------------------------------------------------------------------------------------


def run(passages: list[Passage], title: str = "A paper", refs: list[str] | None = None):  # type: ignore[no-untyped-def]
    found = discover(title, passages, refs or [])
    return {e.name: e for e in match(title, passages, build_dictionary(found), found)}


def test_relation_depends_on_where_and_how_a_name_is_used() -> None:
    linked = run(
        [
            P("Prior work used GLUE and ImageNet extensively.", "related_work"),
            P("We evaluate on SQuAD and report F1 and exact match.", "experiments"),
            P("Our model reaches 91.0 F1 on SQuAD.", "results"),
            P("[1] P. Rajpurkar et al. SQuAD: 100,000+ questions. In EMNLP, 2016.", "references"),
        ]
    )
    assert linked["SQuAD"].relation == "uses"
    assert linked["F1"].relation == "uses" and linked["F1"].type == EntityType.METRIC
    assert linked["GLUE"].relation == "mentions"
    assert linked["SQuAD"].mentions == 2  # the bibliography entry doesn't count
    assert linked["SQuAD"].evidence[0].quote.startswith("We evaluate on SQuAD")


def test_variants_link_to_their_family_without_substring_matches() -> None:
    linked = run(
        [
            P("We fine-tune BERT-large and BERTBASE and compare with ResNet-152 features."),
            P("RoBERTa and ColBERT are other models we use in experiments."),
        ]
    )
    assert set(linked["BERT"].variants) == {"BERT-large", "BERTBASE"}
    assert linked["BERT"].mentions == 2  # not inside "RoBERTa" or "ColBERT"
    assert linked["ResNet"].variants == ["ResNet-152"]
    assert {"RoBERTa", "ColBERT"} <= set(linked)


def test_proposed_entity_and_paper_local_acronyms() -> None:
    linked = run(
        [
            P("We propose Low-Rank Adaptation, or LoRA, which freezes weights.", "abstract"),
            P("We train LoRA on Natural Questions (NQ) and report exact match on NQ."),
        ],
        title="LoRA: Low-Rank Adaptation of Large Language Models",
    )
    assert linked["LoRA"].relation == "proposes"
    # The "we propose" sentence is better evidence than the title alone.
    assert linked["LoRA"].evidence[0].quote.startswith("We propose Low-Rank Adaptation")
    assert linked["Natural Questions"].mentions == 3  # long form + "(NQ)" + "NQ"


def test_dictionary_merges_acronyms_regardless_of_order() -> None:
    bare = Discovered(EntityType.DATASET, "NQ")
    defined = Discovered(EntityType.DATASET, "Natural Questions", ["NQ"])
    for order in ([bare, defined], [defined, bare]):
        names = {e.name for e in build_dictionary(order).entries}
        assert "Natural Questions" in names and "NQ" not in names


def test_discovered_names_link_papers_that_only_mention_them() -> None:
    first = [P("We release SciQA-2400, a new benchmark of expert questions.", "abstract")]
    first += [P("Results on the SciQA-2400 benchmark are strong.", "results")]
    second = [P("We also evaluate on SciQA-2400 and report recall.", "experiments")]
    found_first = discover("A", first)
    dictionary = build_dictionary([*found_first, *discover("B", second)])
    linked = {e.name: e for e in match("B", second, dictionary, discover("B", second))}
    assert linked["SciQA-2400"].relation == "uses"
    assert linked["SciQA-2400"].source == "discovered"


# --- clustering ----------------------------------------------------------------------------------


@pytest.fixture
def blobs() -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(7)
    centres = rng.normal(size=(3, 24)) * 4
    x = np.vstack([c + rng.normal(size=(12, 24)) for c in centres])
    return x, np.repeat(np.arange(3), 12)


def same_partition(a: np.ndarray, b: np.ndarray) -> bool:
    pairs = Counter(zip(a.tolist(), b.tolist(), strict=True))
    return len(pairs) == len(set(a.tolist())) == len(set(b.tolist()))


def test_kmeans_and_agglomerative_recover_separated_groups(
    blobs: tuple[np.ndarray, np.ndarray],
) -> None:
    x, truth = blobs
    assert same_partition(algo.kmeans(x, 3).labels, truth)
    assert same_partition(algo.agglomerative(algo.cosine_distances(x), k=3), truth)
    auto = algo.auto_kmeans(x)
    assert auto.k == 3 and same_partition(auto.result.labels, truth)


def test_hdbscan_finds_groups_and_leaves_outliers_as_noise(
    blobs: tuple[np.ndarray, np.ndarray],
) -> None:
    x, truth = blobs
    outlier = -x.mean(axis=0, keepdims=True) * 3
    result = algo.hdbscan(algo.cosine_distances(np.vstack([x, outlier])), min_cluster_size=4)
    assert result.labels[-1] == algo.NOISE
    assert same_partition(result.labels[:-1], truth)
    assert len(result.stabilities) == 3


def test_matches_scikit_learn_when_available(blobs: tuple[np.ndarray, np.ndarray]) -> None:
    sklearn = pytest.importorskip("sklearn")
    from sklearn.cluster import HDBSCAN, AgglomerativeClustering
    from sklearn.metrics import adjusted_rand_score, silhouette_score

    x, _ = blobs
    rng = np.random.default_rng(3)
    x = np.vstack([x, rng.normal(size=(5, x.shape[1])) * 5])  # some noise to disagree about
    d = algo.cosine_distances(x)
    theirs = HDBSCAN(min_cluster_size=4, metric="precomputed", copy=True).fit(d).labels_
    assert adjusted_rand_score(algo.hdbscan(d, min_cluster_size=4).labels, theirs) == 1.0
    agg = AgglomerativeClustering(3, metric="precomputed", linkage="average").fit(d).labels_
    assert adjusted_rand_score(algo.agglomerative(d, k=3), agg) == 1.0
    labels = algo.kmeans(x, 3).labels
    ours = algo.silhouette(d, labels)
    assert ours == pytest.approx(silhouette_score(d, labels, metric="precomputed"))
    assert sklearn is not None


def test_agglomerative_threshold_and_pca() -> None:
    x = np.array([[1, 0], [0.99, 0.05], [0, 1], [0.05, 0.99]], dtype=float)
    labels = algo.agglomerative(algo.cosine_distances(x), threshold=0.2)
    assert labels.tolist() == [0, 0, 1, 1]
    coords = algo.pca_2d(x)
    assert coords.shape == (4, 2) and np.abs(coords).max() == pytest.approx(1.0)


def test_small_inputs_degrade_gracefully() -> None:
    x = np.eye(3)
    assert algo.hdbscan(algo.cosine_distances(x), min_cluster_size=3).labels.tolist() == [-1] * 3
    assert algo.silhouette(algo.cosine_distances(x), np.array([0, 0, 0])) is None


# --- graph / names / citations -------------------------------------------------------------------


def test_pagerank_is_a_distribution_with_the_hub_first() -> None:
    g = nx.star_graph(5)
    g.add_edge(1, 2)
    rank = pagerank(g)
    assert sum(rank.values()) == pytest.approx(1.0)
    assert max(rank, key=rank.__getitem__) == 0
    reference = nx.pagerank(g) if _has_scipy() else None
    if reference:
        assert all(rank[n] == pytest.approx(reference[n], abs=1e-4) for n in g)


def _has_scipy() -> bool:
    try:
        import scipy  # noqa: F401
    except ImportError:
        return False
    return True


def test_author_cleanup() -> None:
    title = "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding"
    assert not plausible_author("Language Understanding", title)
    assert not plausible_author("GUAGE MODELS", "LORA: LOW-RANK ADAPTATION OF LARGE LAN-")
    assert not plausible_author("Google Research", title)
    assert plausible_author("Jacob Devlin", title)
    assert plausible_author("Ludwig van Beethoven", title)
    rag = "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks"
    assert not plausible_author("Knowledge-Intensive NLP Tasks", rag)  # seen on the real RAG PDF
    assert plausible_author("Wen-tau Yih", rag) and plausible_author("Heinrich Küttler", rag)
    blob = "Facebook AI †University of Washington ‡Princeton University {vladk, plewis}@fb.com"
    assert split_affiliation(blob) == [
        "Facebook AI",
        "University of Washington",
        "Princeton University",
    ]
    keys = [person_key("Jacob Devlin"), person_key("J. Devlin"), person_key("Kenton Lee")]
    assert merge_initials(keys) == {"j devlin": "jacob devlin"}
    # Two different full names with the same initial: ambiguous, leave alone.
    assert merge_initials(["j devlin", "jacob devlin", "jane devlin"]) == {}


def _paper(title: str, **kw: object) -> Paper:
    from app.services.ingestion.cleaning import normalize_title

    fields: dict[str, object] = {
        "id": uuid.uuid4(), "version_id": uuid.uuid4(), "title": title, "year": 2020,
        "venue": None, "doi": None, "arxiv_id": None, "authors": [], "institutions": [],
        "keywords": [], "abstract": None, "normalized_title": normalize_title(title),
        "authors_display": "", "index_status": "indexed",
    }  # fmt: skip
    fields.update(kw)
    return Paper(**fields)  # type: ignore[arg-type]


class Ref:
    def __init__(
        self, raw: str, title: str | None = None, doi: str | None = None, arxiv: str | None = None
    ):
        self.raw_text, self.title, self.doi, self.arxiv_id = raw, title, doi, arxiv


def test_citations_match_by_doi_arxiv_and_title() -> None:
    dpr = _paper(
        "Dense Passage Retrieval for Open-Domain Question Answering", arxiv_id="2004.04906v3"
    )
    rrf = _paper("Reciprocal rank fusion", doi="10.1145/1571941.1572114")
    attention = _paper("Attention Is All You Need")
    citing = _paper("A RAG paper")
    papers = {p.id: p for p in (dpr, rrf, attention, citing)}
    refs = {
        citing.id: [
            Ref(
                "[1] V. Karpukhin et al. Dense passage retrieval. arXiv:2004.04906.",
                arxiv="2004.04906",
            ),
            Ref("[2] G. Cormack. RRF. doi:10.1145/1571941.1572114", doi="10.1145/1571941.1572114"),
            Ref("[3] A. Vaswani et al. Attention is all you need. In NeurIPS, 2017."),
            Ref("[4] Someone. Attention. 2015."),  # too short to be sure
        ],
        dpr.id: [
            Ref(
                "[1] V. Karpukhin et al. Dense passage retrieval for open-domain question answering."
            )
        ],
    }
    found = {(c.citing, c.cited): c.match for c in match_citations(papers, refs)}  # type: ignore[arg-type]
    assert found == {
        (citing.id, dpr.id): "arxiv",
        (citing.id, rrf.id): "doi",
        (citing.id, attention.id): "title",
    }  # and no self-citation for DPR


def test_topic_terms_and_name_parsing() -> None:
    terms = ctfidf_terms(
        [
            ["dense retrieval with reranking", "retrieval passages reranking for retrieval"],
            ["low-rank adapters for fine-tuning", "adapters reduce fine-tuning memory adapters"],
        ]
    )
    assert terms[0][0] in {"retrieval", "reranking"} and "adapters" in terms[1]
    assert not set(terms[0]) & set(terms[1])
    assert clean_name('Topic name: "Dense_Passage_Retrieval".') == "Dense Passage Retrieval"
    reply = "\n**Parameter-efficient fine-tuning**\nExplanation…"
    assert clean_name(reply) == "Parameter-efficient fine-tuning"
    assert (
        clean_name(
            "These papers are all about how retrieval can be combined with generation models"
        )
        is None
    )

    titles = {"a": "Dense passage retrieval", "b": "ColBERT passage search", "c": "LoRA adapters"}
    retrieval = {"id": 0, "document_ids": ["a", "b"], "terms": ["retrieval"], "entities": ["BM25"]}
    adapters = {"id": 1, "document_ids": ["c"], "terms": ["adapters"], "entities": ["LoRA"]}
    both = [retrieval, adapters]
    assert grounded("Passage Retrieval", retrieval, both, titles)
    assert not grounded("Passage Retrieval", adapters, both, titles)  # a swapped name
    assert not grounded("Deep Learning", retrieval, both, titles)  # generic: nothing in common
    assert list(pairwise([1, 2])) == [(1, 2)]
