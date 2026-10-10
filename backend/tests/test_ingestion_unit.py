"""Parsing, structure, metadata, validation and dedupe — no database involved."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.core.errors import ValidationError
from app.demo import sample_papers as sp
from app.models.document import DocumentMetadata, DuplicateKind
from app.services.documents import find_duplicate
from app.services.ingestion.cleaning import clean_text, normalize_title
from app.services.ingestion.ocr import DisabledOCRProvider
from app.services.ingestion.parsers import ParseError, default_registry
from app.services.ingestion.pipeline import run_pipeline
from app.services.ingestion.structure import classify_section
from app.services.ingestion.types import DocumentFormat, SectionKind
from app.services.ingestion.validation import sanitize_filename, validate_upload

REGISTRY = default_registry(DisabledOCRProvider())
MB = 1024 * 1024


@pytest.fixture(scope="module")
def pdf_result(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    path = sp.write_sample_pdf(sp.RETRIEVAL_PAPER, tmp_path_factory.mktemp("pdf") / "paper.pdf")
    return run_pipeline(path, DocumentFormat.PDF, "paper.pdf", REGISTRY)


# --- cleaning & validation ---------------------------------------------------------------


def test_clean_text_fixes_ligatures_hyphenation_and_whitespace() -> None:
    assert clean_text("e\ufb03cient trans-\nformer   models\n") == "efficient transformer models"
    assert clean_text("state-of-the-art") == "state-of-the-art"  # real hyphens kept


def test_normalize_title() -> None:
    assert normalize_title("  LoRA: Low-Rank Adaptation!  ") == "lora low rank adaptation"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd.pdf", "passwd.pdf"),
        ("C:\\Users\\x\\paper.pdf", "paper.pdf"),
        ('bad<>:"|?*name.pdf', "bad_______name.pdf"),
        ("\x00\x1f", "document"),
    ],
)
def test_sanitize_filename(raw: str, expected: str) -> None:
    assert sanitize_filename(raw) == expected


def test_validation_rejects_mismatched_and_unsupported(tmp_path: Path) -> None:
    fake_pdf = tmp_path / "paper.pdf"
    fake_pdf.write_bytes(b"PK\x03\x04 this is a zip, not a pdf")
    with pytest.raises(ValidationError, match="doesn't look like a valid PDF"):
        validate_upload(fake_pdf, "paper.pdf", 10 * MB)

    exe = tmp_path / "virus.exe"
    exe.write_bytes(b"MZ....")
    with pytest.raises(ValidationError, match="isn't a supported file type"):
        validate_upload(exe, "virus.exe", 10 * MB)

    empty = tmp_path / "empty.txt"
    empty.write_bytes(b"")
    with pytest.raises(ValidationError, match="is empty"):
        validate_upload(empty, "empty.txt", 10 * MB)


def test_validation_enforces_size_limit(tmp_path: Path) -> None:
    big = tmp_path / "big.txt"
    big.write_bytes(b"a" * 2048)
    with pytest.raises(ValidationError, match="larger than"):
        validate_upload(big, "big.txt", 1024)


def test_validation_rejects_docx_zip_bombs(tmp_path: Path) -> None:
    import zipfile

    bomb = tmp_path / "bomb.docx"
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<w:document>" + " " * (4 * MB) + "</w:document>")
    assert bomb.stat().st_size < 50_000  # 4 MB of spaces deflate to a few KB (ratio ~1000:1)
    with pytest.raises(ValidationError, match="unpacks to far more data"):
        validate_upload(bomb, "bomb.docx", 10 * MB)
    real = sp.write_sample_docx(sp.LORA_PAPER, tmp_path / "real.docx")
    with pytest.raises(ValidationError, match="unpacks"):  # also capped by total unpacked size
        validate_upload(real, "real.docx", 10 * MB, max_docx_unpacked=1024)


def test_validation_accepts_real_files(tmp_path: Path) -> None:
    pdf = sp.write_sample_pdf(sp.LORA_PAPER, tmp_path / "a.pdf")
    docx = sp.write_sample_docx(sp.LORA_PAPER, tmp_path / "a.docx")
    html = sp.write_sample_html(sp.LORA_PAPER, tmp_path / "a.html")
    assert validate_upload(pdf, "a.pdf", 10 * MB).format == DocumentFormat.PDF
    assert validate_upload(docx, "a.docx", 10 * MB).format == DocumentFormat.DOCX
    assert validate_upload(html, "a.html", 10 * MB).format == DocumentFormat.HTML


# --- PDF structure -------------------------------------------------------------------------


def test_pdf_sections_in_reading_order(pdf_result) -> None:  # type: ignore[no-untyped-def]
    sections = [(s.number, s.title, s.kind) for s in pdf_result.structure.all_sections()]
    titles = [title for _, title, _ in sections]
    assert titles == [
        "", "Abstract", "Introduction", "Related Work", "Method", "Training Objective",
        "Experiments", "Results", "Limitations", "Conclusion", "References",
    ]  # fmt: skip
    kinds = {title: kind for _, title, kind in sections}
    assert kinds["Introduction"] == SectionKind.INTRODUCTION
    assert kinds["Related Work"] == SectionKind.RELATED_WORK
    assert kinds["Training Objective"] == SectionKind.METHOD  # inherited from "3 Method"
    assert kinds["References"] == SectionKind.REFERENCES
    subsection = next(s for s in pdf_result.structure.all_sections() if s.number == "3.1")
    assert subsection.level == 2


def test_pdf_removes_running_headers_and_page_numbers(pdf_result) -> None:  # type: ignore[no-untyped-def]
    text = pdf_result.structure.full_text
    assert "Preprint. Under review." not in text
    assert "arXiv:2403.01234" not in text  # margin stamp goes to metadata, not body text


def test_pdf_paragraph_anchors_point_into_full_text(pdf_result) -> None:  # type: ignore[no-untyped-def]
    structure = pdf_result.structure
    for section in structure.all_sections():
        for paragraph in section.paragraphs:
            assert structure.full_text[paragraph.char_start : paragraph.char_end] == paragraph.text
            assert paragraph.page_start in structure.page_spans
            assert paragraph.boxes, "PDF paragraphs carry bounding boxes for highlighting"
    last_page = max(structure.page_spans)
    assert structure.page_spans[last_page][1] == len(structure.full_text)


def test_pdf_tables_figures_equations(pdf_result) -> None:  # type: ignore[no-untyped-def]
    elements = {e.label: e for e in pdf_result.structure.elements}
    table = elements["Table 1"]
    assert table.content["rows"][0] == ["Method", "Recall@10", "MRR", "nDCG@10"]
    assert table.content["rows"][-1][1] == "78.5"
    assert "Table 1 summarises" in (table.context or "")
    figure = elements["Figure 1"]
    assert figure.bbox is not None
    equation = elements["Equation 1"]
    assert "exp" in equation.content["text"]
    assert "where s is the relevance score" in (equation.context or "")


def test_pdf_references(pdf_result) -> None:  # type: ignore[no-untyped-def]
    refs = pdf_result.structure.references
    assert len(refs) == 4
    assert refs[1].arxiv_id == "2004.04906"
    assert refs[2].doi == "10.1145/1571941.1572114"
    assert refs[0].title == "The probabilistic relevance framework: BM25 and beyond"


def test_pdf_metadata(pdf_result) -> None:  # type: ignore[no-untyped-def]
    meta = pdf_result.metadata
    assert meta.title == sp.RETRIEVAL_PAPER.title
    assert [a["name"] for a in meta.authors] == sp.RETRIEVAL_PAPER.authors
    assert meta.authors[0]["email"] == "maya@northbridge.edu"
    assert meta.affiliations == [sp.RETRIEVAL_PAPER.affiliation]
    assert meta.arxiv_id == "2403.01234"
    assert meta.year == 2024 and meta.publication_date == "2024-03-12"
    assert meta.research_area == "Information Retrieval"
    assert meta.keywords == sp.RETRIEVAL_PAPER.keywords
    assert meta.abstract == sp.RETRIEVAL_PAPER.abstract
    assert meta.venue == "arXiv"  # not "Science" from "Computer Science"
    assert meta.provenance["title"]["source"] == "layout"


def test_scanned_pdf_without_ocr_explains_why(tmp_path: Path) -> None:
    path = sp.write_scanned_pdf(tmp_path / "scan.pdf")
    with pytest.raises(ParseError, match="scanned") as info:
        run_pipeline(path, DocumentFormat.PDF, "scan.pdf", REGISTRY)
    assert "OCR" in info.value.user_message


def test_corrupt_pdf(tmp_path: Path) -> None:
    path = tmp_path / "bad.pdf"
    path.write_bytes(b"%PDF-1.4 not really")
    with pytest.raises(ParseError, match="corrupted"):
        run_pipeline(path, DocumentFormat.PDF, "bad.pdf", REGISTRY)


# --- other formats -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("writer", "fmt", "name"),
    [
        (sp.write_sample_markdown, DocumentFormat.MARKDOWN, "p.md"),
        (sp.write_sample_html, DocumentFormat.HTML, "p.html"),
        (sp.write_sample_docx, DocumentFormat.DOCX, "p.docx"),
    ],
)
def test_structured_formats(writer, fmt: DocumentFormat, name: str, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    path = writer(sp.RETRIEVAL_PAPER, tmp_path / name)
    result = run_pipeline(path, fmt, name, REGISTRY)
    sections = {s.title: s for s in result.structure.all_sections()}
    assert result.metadata.title == sp.RETRIEVAL_PAPER.title
    assert [a["name"] for a in result.metadata.authors] == sp.RETRIEVAL_PAPER.authors
    assert result.metadata.abstract == sp.RETRIEVAL_PAPER.abstract
    assert sections["Training Objective"].level == 2
    assert sections["Method"].kind == SectionKind.METHOD
    assert any(e.label == "Table 1" and e.content.get("rows") for e in result.structure.elements)
    assert not result.raw.paginated


def test_plain_text_numbered_headings(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text(
        "1 Introduction\n\nTransformers use attention.\n\n2 Method\n\nWe fine-tune.\n",
        encoding="utf-8",
    )
    result = run_pipeline(path, DocumentFormat.TEXT, "notes.txt", REGISTRY)
    assert [s.title for s in result.structure.all_sections()] == ["Introduction", "Method"]
    assert result.metadata.title == "notes"  # falls back to filename, marked low confidence
    assert result.metadata.provenance["title"]["confidence"] == "low"


@pytest.mark.parametrize(
    ("title", "kind"),
    [
        ("1 Introduction", SectionKind.INTRODUCTION),
        ("IV. EXPERIMENTAL SETUP", SectionKind.EXPERIMENTS),
        ("2.3 Related Work", SectionKind.RELATED_WORK),
        ("Limitations and Broader Impact", SectionKind.LIMITATIONS),
        ("Acknowledgements", SectionKind.ACKNOWLEDGMENTS),
        ("A Proofs", SectionKind.OTHER),
        ("Appendix A: Proofs", SectionKind.APPENDIX),
    ],
)
def test_classify_section(title: str, kind: SectionKind) -> None:
    assert classify_section(title) == kind


# --- dedupe ---------------------------------------------------------------------------------------


def _meta(**kwargs: object) -> DocumentMetadata:
    record = DocumentMetadata(**kwargs)
    record.normalized_title = normalize_title(str(kwargs.get("title", "")))
    return record


def test_find_duplicate_levels() -> None:
    other = uuid.uuid4()
    candidates = [(other, _meta(title="Hybrid Sparse Dense Retrieval for QA", doi="10.1/ABC"))]
    exact = find_duplicate(file_match=other, metadata=None, candidates=[])
    assert exact is not None and exact.kind == DuplicateKind.EXACT

    same_doi = find_duplicate(
        file_match=None, metadata=_meta(title="x", doi="10.1/abc"), candidates=candidates
    )
    assert same_doi is not None and same_doi.kind == DuplicateKind.PROBABLE

    similar = find_duplicate(
        file_match=None,
        metadata=_meta(title="Hybrid Sparse-Dense Retrieval for Q.A."),
        candidates=candidates,
    )
    assert similar is not None and similar.kind in (DuplicateKind.PROBABLE, DuplicateKind.POSSIBLE)

    near = find_duplicate(
        file_match=None,
        metadata=_meta(title="Hybrid Sparse Dense Retrieval for QAs"),
        candidates=candidates,
    )
    assert near is not None and near.kind == DuplicateKind.POSSIBLE

    unrelated = find_duplicate(
        file_match=None,
        metadata=_meta(title="Low-Rank Adapters for Language Models"),
        candidates=candidates,
    )
    assert unrelated is None
