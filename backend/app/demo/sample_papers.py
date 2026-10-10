"""Synthetic research papers for tests and demo mode.

All content is original and synthetic (no copyrighted papers). PDFs are laid
out like real conference papers: two columns, arXiv margin stamp, running
header, page numbers, numbered sections, a ruled table, a figure, a numbered
equation and a reference list, so the parser is exercised realistically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.services.ingestion.native import pymupdf


@dataclass
class SamplePaper:
    title: str
    authors: list[str]
    affiliation: str
    arxiv_id: str
    category: str
    date: str  # "12 Mar 2024"
    abstract: str
    keywords: list[str]
    sections: list[tuple[str, list[str]]]  # (numbered heading, paragraphs)
    table_caption: str
    table_rows: list[list[str]]
    figure_caption: str
    equation: str
    references: list[str] = field(default_factory=list)


RETRIEVAL_PAPER = SamplePaper(
    title="Hybrid Sparse-Dense Retrieval for Scientific Question Answering",
    authors=["Maya Lindqvist", "Tomas Okafor", "Priya Raman"],
    affiliation="Department of Computer Science, Northbridge University",
    arxiv_id="2403.01234",
    category="cs.IR",
    date="12 Mar 2024",
    abstract=(
        "Retrieval-augmented generation depends on finding the right evidence. We study how "
        "lexical and dense retrievers complement each other on scientific question answering. "
        "We propose a hybrid retriever that fuses BM25 and dense rankings with reciprocal rank "
        "fusion and then applies a cross-encoder reranker. On a new benchmark of 2,400 expert "
        "questions, the hybrid system improves recall at ten by 7.3 points over the best single "
        "retriever while keeping latency under 120 milliseconds."
    ),
    keywords=["information retrieval", "hybrid search", "reranking", "question answering"],
    sections=[
        (
            "1 Introduction",
            [
                "Large language models answer questions fluently but often without grounding. "
                "Retrieval-augmented generation addresses this by conditioning generation on "
                "retrieved passages. The quality of the final answer is bounded by the quality "
                "of retrieval, which makes the retriever the most important component to get right.",
                "Scientific text is a difficult setting for retrieval. Queries mention rare "
                "technical terms, dataset names and abbreviations that dense encoders represent "
                "poorly, while paraphrased questions defeat purely lexical matching. This paper "
                "asks a simple question: when do sparse and dense retrievers fail, and can a "
                "fused ranking recover from both kinds of failure?",
                "Our contributions are threefold. First, we release a benchmark of expert-written "
                "questions with evidence annotations. Second, we analyse the failure modes of "
                "each retriever. Third, we show that rank fusion followed by reranking is a "
                "strong and simple baseline.",
            ],
        ),
        (
            "2 Related Work",
            [
                "Sparse retrieval with BM25 remains a strong baseline for keyword-heavy queries. "
                "Dense passage retrieval encodes queries and passages into a shared vector space "
                "and excels at semantic matching. Prior work combined both signals with learned "
                "interpolation weights, which require calibration of heterogeneous scores.",
                "Reciprocal rank fusion avoids calibration by combining ranks instead of scores. "
                "Cross-encoder rerankers jointly encode the query and passage and are more "
                "accurate but too slow to apply to an entire corpus.",
            ],
        ),
        (
            "3 Method",
            [
                "Given a query, we retrieve the top one hundred passages from each retriever. The "
                "two ranked lists are fused with reciprocal rank fusion, where each passage "
                "receives the sum of the reciprocal of its rank plus a constant k over all lists.",
                "The fused candidates are rescored by a cross-encoder reranker. We keep the top "
                "ten passages as context for the generator. The reranker is trained with the "
                "objective in Equation 1, a contrastive loss with in-batch negatives.",
            ],
        ),
        (
            "3.1 Training Objective",
            [
                "where s is the relevance score of the positive passage, the sum runs over the "
                "negatives in the batch, and the temperature controls the sharpness of the "
                "distribution. We train for three epochs with a learning rate of 2e-5.",
            ],
        ),
        (
            "4 Experiments",
            [
                "We evaluate on the SciQA-2400 benchmark introduced in this work and on two public "
                "datasets. We report recall at ten, mean reciprocal rank and nDCG at ten. All "
                "latencies are measured on a single consumer GPU.",
                "Table 1 summarises the main results. The hybrid retriever with reranking obtains "
                "the best score on every metric. Figure 1 shows that the gain is largest for "
                "queries that contain rare technical terms.",
            ],
        ),
        (
            "5 Results",
            [
                "Fusion alone improves recall at ten from 71.2 to 76.4. Adding the reranker raises "
                "it further to 78.5, a gain of 7.3 points over the best single retriever. The "
                "improvement is statistically significant under a paired bootstrap test.",
            ],
        ),
        (
            "6 Limitations",
            [
                "Our benchmark covers only computer science papers written in English. The "
                "reranker adds latency that may be prohibitive for very large candidate sets, "
                "and we did not study multilingual retrieval.",
            ],
        ),
        (
            "7 Conclusion",
            [
                "Sparse and dense retrievers fail on different queries. A simple fusion of their "
                "rankings followed by reranking recovers from both failure modes. Future work "
                "should explore learned fusion and multilingual scientific retrieval.",
            ],
        ),
    ],
    table_caption="Table 1: Retrieval results on SciQA-2400.",
    table_rows=[
        ["Method", "Recall@10", "MRR", "nDCG@10"],
        ["BM25", "68.9", "0.52", "0.58"],
        ["Dense", "71.2", "0.55", "0.61"],
        ["Hybrid (RRF)", "76.4", "0.59", "0.66"],
        ["Hybrid + Rerank", "78.5", "0.63", "0.70"],
    ],
    figure_caption="Figure 1: Recall gain by query type. Rare-term queries benefit most.",
    equation="L = -log exp(s_p/τ) / Σ exp(s_j/τ)      (1)",
    references=[
        "[1] A. Robertson and H. Zaragoza. The probabilistic relevance framework: BM25 and beyond. Foundations and Trends in Information Retrieval, 2009.",
        "[2] V. Karpukhin, B. Oguz, and S. Min. Dense passage retrieval for open-domain question answering. In Proceedings of EMNLP, 2020. arXiv:2004.04906.",
        "[3] G. Cormack, C. Clarke, and S. Buettcher. Reciprocal rank fusion outperforms condorcet and individual rank learning methods. In SIGIR, 2009. doi:10.1145/1571941.1572114.",
        "[4] R. Nogueira and K. Cho. Passage re-ranking with BERT. arXiv:1901.04085, 2019.",
    ],
)

LORA_PAPER = SamplePaper(
    title="Low-Rank Adapters for Efficient Domain Adaptation of Language Models",
    authors=["Chen Wei", "Laura Martins"],
    affiliation="Institute for Machine Learning, Eastlake Research Lab",
    arxiv_id="2311.04567",
    category="cs.CL",
    date="8 Nov 2023",
    abstract=(
        "Fine-tuning every parameter of a large language model is expensive. We study low-rank "
        "adapters that represent the weight update as the product of two small matrices. Across "
        "four domain adaptation tasks, rank-8 adapters match full fine-tuning within one point "
        "while training 0.4 percent of the parameters and reducing GPU memory by 60 percent."
    ),
    keywords=["parameter-efficient fine-tuning", "LoRA", "domain adaptation"],
    sections=[
        (
            "1 Introduction",
            [
                "Adapting a pretrained language model to a new domain usually means updating all "
                "of its weights. For models with billions of parameters this requires large GPU "
                "clusters and produces a full copy of the model for every task.",
                "Parameter-efficient fine-tuning methods train a small number of additional "
                "parameters instead. We focus on low-rank adaptation, which freezes the pretrained "
                "weights and learns a low-rank update for selected projection matrices.",
            ],
        ),
        (
            "2 Background",
            [
                "Adapters insert small bottleneck layers between transformer blocks. Prefix tuning "
                "learns continuous prompts. Low-rank adaptation instead reparameterizes the update "
                "of an existing weight matrix, adding no inference latency after merging.",
            ],
        ),
        (
            "3 Approach",
            [
                "For a frozen weight matrix W we learn an update B A, where B and A have rank r. "
                "Only A and B receive gradients. The update is scaled by alpha over r as shown in "
                "Equation 1, which keeps the effective learning rate stable across ranks.",
            ],
        ),
        (
            "4 Experiments",
            [
                "We adapt a 7B parameter model to biomedical, legal, financial and scientific text "
                "and evaluate on the MedQA, CaseHOLD, FiQA and SciQA-2400 datasets. Table 1 compares "
                "full fine-tuning with adapters of different ranks.",
            ],
        ),
        (
            "5 Results",
            [
                "Rank-8 adapters are within one point of full fine-tuning on all four datasets. "
                "Increasing the rank beyond 16 brings no further improvement. Figure 1 shows that "
                "memory use drops by 60 percent.",
            ],
        ),
        (
            "6 Limitations",
            [
                "We only evaluated models up to seven billion parameters and English-language "
                "domains. The optimal rank may differ for larger models or multilingual data.",
            ],
        ),
        (
            "7 Conclusion",
            [
                "Low-rank adapters are an effective and cheap way to specialize language models. "
                "Future work should study automatic rank selection per layer.",
            ],
        ),
    ],
    table_caption="Table 1: Accuracy of full fine-tuning and low-rank adapters.",
    table_rows=[
        ["Method", "Params", "MedQA", "CaseHOLD"],
        ["Full fine-tuning", "100%", "61.3", "72.8"],
        ["LoRA r=4", "0.2%", "59.8", "71.5"],
        ["LoRA r=8", "0.4%", "60.6", "72.1"],
        ["LoRA r=16", "0.8%", "60.9", "72.4"],
    ],
    figure_caption="Figure 1: Peak GPU memory during training.",
    equation="h = W_0 x + (α/r) B A x      (1)",
    references=[
        "[1] N. Houlsby, A. Giurgiu, and S. Jastrzebski. Parameter-efficient transfer learning for NLP. In ICML, 2019.",
        "[2] X. Li and P. Liang. Prefix-tuning: Optimizing continuous prompts for generation. In ACL, 2021.",
    ],
)

RAG_ADAPTER_PAPER = SamplePaper(
    title="Adapting Retrieval-Augmented Generators with Low-Rank Updates",
    authors=["Priya Raman", "Chen Wei", "Jonas Albrecht"],
    affiliation="Department of Computer Science, Northbridge University",
    arxiv_id="2406.07890",
    category="cs.CL",
    date="3 Jun 2024",
    abstract=(
        "Retrieval-augmented generation grounds answers in retrieved passages, but the generator "
        "is rarely adapted to the retriever it is paired with. We propose RALA, which fine-tunes "
        "the generator with low-rank adaptation on retrieved contexts. With a hybrid BM25 and "
        "dense retriever, RALA improves exact match on SciQA-2400 by 4.1 points while training "
        "0.3 percent of the parameters."
    ),
    keywords=["retrieval-augmented generation", "LoRA", "question answering"],
    sections=[
        (
            "1 Introduction",
            [
                "Retrieval-augmented generation (RAG) conditions a language model on passages "
                "found by a retriever. When the retriever returns noisy passages, a generator that "
                "was never trained on retrieved contexts copies irrelevant text.",
                "We propose Retrieval-Aware Low-rank Adaptation (RALA), a recipe that adapts the "
                "generator to its retriever. RALA keeps the pretrained weights frozen and trains "
                "low-rank adapters on question, retrieved context and answer triples.",
            ],
        ),
        (
            "2 Related Work",
            [
                "Hybrid sparse-dense retrieval fuses BM25 and dense rankings with reciprocal rank "
                "fusion. Low-rank adapters reduce the cost of fine-tuning large language models. "
                "We combine both lines of work.",
            ],
        ),
        (
            "3 Method",
            [
                "We retrieve ten passages per question with the hybrid retriever and train LoRA "
                "adapters of rank 8 on the query, key and value projections. The retriever stays "
                "fixed during training, so the generator learns to ignore unhelpful passages.",
            ],
        ),
        (
            "4 Experiments",
            [
                "We evaluate on the SciQA-2400 benchmark and on Natural Questions. We report exact "
                "match and F1, and compare against full fine-tuning and a frozen generator.",
            ],
        ),
        (
            "5 Results",
            [
                "RALA improves exact match on SciQA-2400 from 41.2 to 45.3 and on Natural Questions "
                "from 38.0 to 40.6. Full fine-tuning is only 0.4 points better while training all "
                "parameters.",
            ],
        ),
        (
            "6 Conclusion",
            [
                "Adapting the generator to its retriever is cheap with low-rank updates and "
                "consistently improves grounded question answering.",
            ],
        ),
    ],
    table_caption="Table 1: Exact match on SciQA-2400 and Natural Questions.",
    table_rows=[
        ["Generator", "Trained params", "SciQA-2400", "NQ"],
        ["Frozen", "0%", "41.2", "38.0"],
        ["Full fine-tuning", "100%", "45.7", "41.0"],
        ["RALA (LoRA r=8)", "0.3%", "45.3", "40.6"],
    ],
    figure_caption="Figure 1: Exact match as the number of retrieved passages grows.",
    equation="h = W_0 x + B A x      (1)",
    references=[
        "[1] M. Lindqvist, T. Okafor, and P. Raman. Hybrid sparse-dense retrieval for scientific question answering. arXiv:2403.01234, 2024.",
        "[2] C. Wei and L. Martins. Low-rank adapters for efficient domain adaptation of language models. arXiv preprint, 2023.",
        "[3] V. Karpukhin, B. Oguz, and S. Min. Dense passage retrieval for open-domain question answering. In Proceedings of EMNLP, 2020. arXiv:2004.04906.",
    ],
)

SAMPLE_PAPERS = [RETRIEVAL_PAPER, LORA_PAPER, RAG_ADAPTER_PAPER]


def _math_font() -> pymupdf.Font:
    return pymupdf.Font("cjk")


class _Layout:
    """Tiny text-flow engine: wraps lines into two columns across pages."""

    PAGE_W, PAGE_H = 612.0, 792.0
    MARGIN_X, TOP, BOTTOM = 54.0, 72.0, 740.0
    GUTTER = 18.0

    def __init__(self, doc: pymupdf.Document, header: str) -> None:
        self.doc = doc
        self.header = header
        self.col_w = (self.PAGE_W - 2 * self.MARGIN_X - self.GUTTER) / 2
        self.page: pymupdf.Page | None = None
        self.column = 0
        self.y = self.TOP

    def new_page(self) -> None:
        self.page = self.doc.new_page(width=self.PAGE_W, height=self.PAGE_H)
        number = self.doc.page_count
        self.page.insert_text((self.MARGIN_X, 40), self.header, fontname="tiit", fontsize=8)
        self.page.insert_text((self.PAGE_W / 2 - 4, 770), str(number), fontname="tiro", fontsize=9)
        self.column, self.y = 0, self.TOP
        self.column_top = self.TOP

    @property
    def x(self) -> float:
        return self.MARGIN_X + self.column * (self.col_w + self.GUTTER)

    def _advance(self, height: float) -> None:
        if self.page is None:
            self.new_page()
        if self.y + height > self.BOTTOM:
            if self.column == 0:
                self.column, self.y = 1, self.column_top
            else:
                self.new_page()

    def paragraph(self, text: str, font: str = "tiro", size: float = 9.5, gap: float = 7.0) -> None:
        words, line = text.split(), ""
        lines: list[str] = []
        for word in words:
            trial = f"{line} {word}".strip()
            if pymupdf.get_text_length(trial, fontname=font, fontsize=size) > self.col_w:
                lines.append(line)
                line = word
            else:
                line = trial
        lines.append(line)
        for text_line in lines:
            self._advance(size * 1.25)
            assert self.page is not None
            self.page.insert_text((self.x, self.y + size), text_line, fontname=font, fontsize=size)
            self.y += size * 1.25
        self.y += gap

    def space(self, height: float) -> None:
        self._advance(height)
        self.y += height

    def table(self, rows: list[list[str]]) -> None:
        row_h = 14.0
        self._advance(row_h * len(rows) + 6)
        assert self.page is not None
        col_w = self.col_w / len(rows[0])
        top = self.y
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                font = "tibo" if r == 0 else "tiro"
                self.page.insert_text(
                    (self.x + c * col_w + 3, top + r * row_h + 10), cell, fontname=font, fontsize=8
                )
        for r in range(len(rows) + 1):
            y = top + r * row_h
            self.page.draw_line((self.x, y), (self.x + self.col_w, y), width=0.5)
        for c in range(len(rows[0]) + 1):
            x = self.x + c * col_w
            self.page.draw_line((x, top), (x, top + len(rows) * row_h), width=0.5)
        self.y = top + len(rows) * row_h + 6

    def figure(self, height: float = 110.0) -> None:
        self._advance(height + 6)
        assert self.page is not None
        base = self.y + height
        for i, bar in enumerate([0.35, 0.55, 0.8, 0.65, 0.95]):
            x0 = self.x + 20 + i * (self.col_w - 40) / 5
            rect = pymupdf.Rect(x0, base - bar * (height - 10), x0 + 18, base)
            self.page.draw_rect(rect, color=(0.2, 0.3, 0.7), fill=(0.55, 0.65, 0.95))
        self.page.draw_line((self.x + 10, base), (self.x + self.col_w - 10, base), width=0.8)
        self.page.draw_line((self.x + 10, self.y + 5), (self.x + 10, base), width=0.8)
        self.y = base + 6

    def equation(self, text: str) -> None:
        self._advance(22)
        assert self.page is not None
        # A Unicode font so symbols extract correctly (like real LaTeX PDFs).
        self.page.insert_font(fontname="eqfont", fontbuffer=_math_font().buffer)
        self.page.insert_text((self.x + 12, self.y + 12), text, fontname="eqfont", fontsize=10)
        self.y += 24


def write_sample_pdf(paper: SamplePaper, path: Path, demo: bool = False) -> Path:
    """`demo`: the copy given to users (demo mode) — labelled synthetic in every page header,
    no arXiv stamp (the ids are made up and could match a real, unrelated paper), and
    example.org e-mail addresses."""
    doc = pymupdf.open()
    layout = _Layout(
        doc,
        "Synthetic sample paper for demonstration - not a real publication."
        if demo
        else "Preprint. Under review.",
    )
    layout.new_page()
    page = layout.page
    assert page is not None

    # Full-width front matter.
    title_rect = pymupdf.Rect(72, 70, 540, 120)
    page.insert_textbox(title_rect, paper.title, fontname="tibo", fontsize=16, align=1)
    page.insert_textbox(
        pymupdf.Rect(72, 122, 540, 146),
        ",  ".join(paper.authors),
        fontname="tiro",
        fontsize=11,
        align=1,
    )
    page.insert_textbox(
        pymupdf.Rect(72, 144, 540, 164), paper.affiliation, fontname="tiit", fontsize=9.5, align=1
    )
    domain = "example.org" if demo else "northbridge.edu"
    emails = ",  ".join(f"{a.split()[0].lower()}@{domain}" for a in paper.authors)
    page.insert_textbox(
        pymupdf.Rect(72, 163, 540, 180), emails, fontname="cour", fontsize=8, align=1
    )
    if not demo:
        stamp = f"arXiv:{paper.arxiv_id}v1  [{paper.category}]  {paper.date}"
        page.insert_text(
            (30, 560), stamp, fontname="tiro", fontsize=14, rotate=90, color=(0.5, 0.5, 0.5)
        )
    layout.y = layout.column_top = 190

    layout.paragraph("Abstract", font="tibo", size=11, gap=3)
    layout.paragraph(paper.abstract)
    layout.paragraph("Keywords: " + ", ".join(paper.keywords), size=9, gap=10)

    for heading, paragraphs in paper.sections:
        level2 = heading.split()[0].count(".") > 0
        layout.space(4)
        layout.paragraph(heading, font="tibo", size=10 if level2 else 11, gap=4)
        if heading.endswith("Training Objective"):
            layout.equation(paper.equation)
        for text in paragraphs:
            layout.paragraph(text)
        if heading.startswith("4 "):
            layout.paragraph(paper.table_caption, size=9, gap=3)
            layout.table(paper.table_rows)
            layout.figure()
            layout.paragraph(paper.figure_caption, size=9)
        if heading.startswith("3 ") and not any(
            h.endswith("Training Objective") for h, _ in paper.sections
        ):
            layout.equation(paper.equation)

    layout.space(4)
    layout.paragraph("References", font="tibo", size=11, gap=4)
    for reference in paper.references:
        layout.paragraph(reference, size=8.5, gap=3)

    doc.set_metadata({"title": "", "author": "", "creationDate": "D:20240312120000"})
    doc.subset_fonts()
    doc.save(path, garbage=3, deflate=True)
    doc.close()
    return path


def write_sample_markdown(paper: SamplePaper, path: Path) -> Path:
    lines = [
        f"# {paper.title}",
        "",
        ", ".join(paper.authors),
        "",
        "## Abstract",
        "",
        paper.abstract,
        "",
    ]
    for heading, paragraphs in paper.sections:
        number = heading.partition(" ")[0]
        hashes = "###" if "." in number else "##"
        lines += [f"{hashes} {heading}", ""]
        for text in paragraphs:
            lines += [text, ""]
    header, *rows = paper.table_rows
    lines += [paper.table_caption, "", "| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    lines += ["", "$$", paper.equation.split("  ")[0], "$$", "", "## References", ""]
    lines += [ref for r in paper.references for ref in (r, "")]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_sample_html(paper: SamplePaper, path: Path) -> Path:
    body = [
        f"<h1>{paper.title}</h1>",
        f"<p>{', '.join(paper.authors)}</p>",
        "<h2>Abstract</h2>",
        f"<p>{paper.abstract}</p>",
    ]
    for heading, paragraphs in paper.sections:
        tag = "h3" if "." in heading.split()[0] else "h2"
        body.append(f"<{tag}>{heading}</{tag}>")
        body.extend(f"<p>{p}</p>" for p in paragraphs)
    rows = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in paper.table_rows)
    body.append(f"<table><caption>{paper.table_caption}</caption>{rows}</table>")
    html = (
        "<!doctype html><html><head>"
        f"<title>{paper.title}</title>"
        f'<meta name="citation_title" content="{paper.title}">'
        + "".join(f'<meta name="citation_author" content="{a}">' for a in paper.authors)
        + f'<meta name="citation_publication_date" content="{paper.date}">'
        "</head><body><nav>Skip me</nav><article>" + "".join(body) + "</article></body></html>"
    )
    path.write_text(html, encoding="utf-8")
    return path


def write_sample_docx(paper: SamplePaper, path: Path) -> Path:
    from docx import Document

    document = Document()
    document.core_properties.title = paper.title
    document.core_properties.author = "; ".join(paper.authors)
    document.add_heading(paper.title, level=0)
    document.add_paragraph(", ".join(paper.authors))
    document.add_heading("Abstract", level=1)
    document.add_paragraph(paper.abstract)
    for heading, paragraphs in paper.sections:
        document.add_heading(heading, level=2 if "." in heading.split()[0] else 1)
        for text in paragraphs:
            document.add_paragraph(text)
    document.add_paragraph(paper.table_caption)
    table = document.add_table(rows=len(paper.table_rows), cols=len(paper.table_rows[0]))
    for r, row in enumerate(paper.table_rows):
        for c, cell in enumerate(row):
            table.cell(r, c).text = cell
    document.save(str(path))
    return path


def write_scanned_pdf(path: Path) -> Path:
    """An image-only PDF (no text layer), like a scanned document."""
    source = pymupdf.open()
    page = source.new_page()
    page.insert_text((72, 100), "Scanned page content", fontsize=20)
    pix = page.get_pixmap(dpi=72)
    doc = pymupdf.open()
    out = doc.new_page()
    out.insert_image(out.rect, pixmap=pix)
    doc.save(path)
    return path
