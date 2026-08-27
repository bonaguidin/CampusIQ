import io

import pytest
from reportlab.lib import pdfencrypt
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas as rl_canvas

from GradusIQ_career.syllabus.parsing import (
    SyllabusEmptyDocumentError,
    SyllabusEncryptedPDFError,
    SyllabusFileNotFoundError,
    SyllabusInvalidPDFError,
    SyllabusNoExtractableTextError,
    parse_syllabus_pdf,
)

BODY_SIZE = 10
HEADING_SIZE = 14

# Page 1: PHYS 207 / Fall 2026 (plain body text, no headings)
# Page 2: "Grading Policy" heading + two grading lines
# Page 3: "Course Schedule" heading + one schedule line
PHYS_207_PAGES = [
    [("PHYS 207", BODY_SIZE, False), ("Fall 2026", BODY_SIZE, False)],
    [
        ("Grading Policy", HEADING_SIZE, True),
        ("Mid-term Exam: 35%", BODY_SIZE, False),
        ("Final Exam: 50%", BODY_SIZE, False),
    ],
    [("Course Schedule", HEADING_SIZE, True), ("Mid-term Exam - October 15", BODY_SIZE, False)],
]


def _build_pdf(pages, *, title=None, author=None, encrypt=None) -> bytes:
    buf = io.BytesIO()
    kwargs = {}
    if encrypt is not None:
        kwargs["encrypt"] = encrypt
    canvas = rl_canvas.Canvas(buf, pagesize=letter, **kwargs)
    if title:
        canvas.setTitle(title)
    if author:
        canvas.setAuthor(author)
    for page in pages:
        y = 750
        for text, size, bold in page:
            canvas.setFont("Helvetica-Bold" if bold else "Helvetica", size)
            canvas.drawString(72, y, text)
            y -= size + 10
        canvas.showPage()
    canvas.save()
    return buf.getvalue()


def _blank_page_pdf() -> bytes:
    buf = io.BytesIO()
    canvas = rl_canvas.Canvas(buf, pagesize=letter)
    canvas.showPage()
    canvas.save()
    return buf.getvalue()


def _zero_page_pdf() -> bytes:
    from pypdf import PdfWriter

    buf = io.BytesIO()
    PdfWriter().write(buf)
    return buf.getvalue()


def _encrypted_pdf() -> bytes:
    enc = pdfencrypt.StandardEncryption("userpw", ownerPassword="ownerpw")
    return _build_pdf([[("secret", BODY_SIZE, False)]], encrypt=enc)


def phys_207_pdf_path(tmp_path, **kwargs):
    path = tmp_path / "phys207.pdf"
    path.write_bytes(_build_pdf(PHYS_207_PAGES, **kwargs))
    return path


# --- basic extraction ------------------------------------------------------


def test_valid_pdf_returns_parsed_syllabus_document(tmp_path):
    doc = parse_syllabus_pdf(phys_207_pdf_path(tmp_path))
    assert doc.metadata.page_count == 3


def test_page_count_matches_pdf_page_count(tmp_path):
    doc = parse_syllabus_pdf(phys_207_pdf_path(tmp_path))
    assert len(doc.pages) == 3


def test_page_numbers_are_1_indexed(tmp_path):
    doc = parse_syllabus_pdf(phys_207_pdf_path(tmp_path))
    assert [page.page_number for page in doc.pages] == [1, 2, 3]


def test_expected_text_appears_on_expected_pages(tmp_path):
    doc = parse_syllabus_pdf(phys_207_pdf_path(tmp_path))
    assert "PHYS 207" in doc.pages[0].markdown
    assert "Fall 2026" in doc.pages[0].markdown
    assert "Mid-term Exam: 35%" in doc.pages[1].markdown
    assert "Final Exam: 50%" in doc.pages[1].markdown
    assert "Course Schedule" in doc.pages[2].markdown
    assert "Mid-term Exam: 35%" not in doc.pages[2].markdown


# --- markdown provenance ----------------------------------------------------


def test_combined_markdown_contains_page_markers(tmp_path):
    doc = parse_syllabus_pdf(phys_207_pdf_path(tmp_path))
    for n in (1, 2, 3):
        assert f"<!-- page: {n} -->" in doc.markdown


def test_page_markers_appear_in_order(tmp_path):
    doc = parse_syllabus_pdf(phys_207_pdf_path(tmp_path))
    positions = [doc.markdown.index(f"<!-- page: {n} -->") for n in (1, 2, 3)]
    assert positions == sorted(positions)


def test_content_stays_associated_with_correct_page(tmp_path):
    doc = parse_syllabus_pdf(phys_207_pdf_path(tmp_path))
    marker_2 = doc.markdown.index("<!-- page: 2 -->")
    marker_3 = doc.markdown.index("<!-- page: 3 -->")
    page_2_block = doc.markdown[marker_2:marker_3]
    assert "Mid-term Exam: 35%" in page_2_block
    assert "Course Schedule" not in page_2_block


# --- sections ----------------------------------------------------------------


def test_headings_create_sections(tmp_path):
    doc = parse_syllabus_pdf(phys_207_pdf_path(tmp_path))
    headings = {section.heading for section in doc.sections}
    assert headings == {"Grading Policy", "Course Schedule"}


def test_section_page_numbers_are_correct(tmp_path):
    doc = parse_syllabus_pdf(phys_207_pdf_path(tmp_path))
    by_heading = {section.heading: section for section in doc.sections}
    assert by_heading["Grading Policy"].page_numbers == [2]
    assert by_heading["Course Schedule"].page_numbers == [3]


def test_section_spanning_pages_preserves_multiple_page_numbers(tmp_path):
    pages = [
        [("Grading Policy", HEADING_SIZE, True), ("Mid-term Exam: 35%", BODY_SIZE, False)],
        [("Final Exam: 50%", BODY_SIZE, False)],
    ]
    path = tmp_path / "spanning.pdf"
    path.write_bytes(_build_pdf(pages))
    doc = parse_syllabus_pdf(path)
    assert len(doc.sections) == 1
    assert doc.sections[0].page_numbers == [1, 2]
    assert "Final Exam: 50%" in doc.sections[0].markdown


def test_no_sections_when_no_headings_detected(tmp_path):
    pages = [[("Just a plain paragraph.", BODY_SIZE, False)]]
    path = tmp_path / "no_headings.pdf"
    path.write_bytes(_build_pdf(pages))
    doc = parse_syllabus_pdf(path)
    assert doc.sections == []


# --- metadata ------------------------------------------------------------------


def test_filename_is_preserved(tmp_path):
    doc = parse_syllabus_pdf(phys_207_pdf_path(tmp_path))
    assert doc.metadata.source_filename == "phys207.pdf"


def test_page_count_metadata_is_correct(tmp_path):
    doc = parse_syllabus_pdf(phys_207_pdf_path(tmp_path))
    assert doc.metadata.page_count == 3


def test_embedded_metadata_is_preserved_when_available(tmp_path):
    doc = parse_syllabus_pdf(phys_207_pdf_path(tmp_path, title="PHYS 207 Syllabus", author="Dr. Smith"))
    assert doc.metadata.extra["pdf_title"] == "PHYS 207 Syllabus"
    assert doc.metadata.extra["pdf_author"] == "Dr. Smith"


def test_embedded_metadata_absent_leaves_extra_empty(tmp_path):
    # reportlab's Canvas always stamps a "untitled"/"anonymous" default when
    # setTitle/setAuthor are never called, so exercise real absence by
    # re-writing the pages through pypdf, which leaves /Title and /Author
    # unset entirely -- closer to what a title-less LaTeX/Word PDF looks like.
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(_build_pdf(PHYS_207_PAGES)))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    path = tmp_path / "no_metadata.pdf"
    with path.open("wb") as f:
        writer.write(f)

    doc = parse_syllabus_pdf(path)
    assert doc.metadata.extra == {}


# --- error behavior --------------------------------------------------------------


def test_nonexistent_pdf_raises_clearly(tmp_path):
    with pytest.raises(SyllabusFileNotFoundError):
        parse_syllabus_pdf(tmp_path / "does_not_exist.pdf")


def test_invalid_pdf_raises_clearly(tmp_path):
    path = tmp_path / "not_a_pdf.pdf"
    path.write_bytes(b"this is not a pdf file at all")
    with pytest.raises(SyllabusInvalidPDFError):
        parse_syllabus_pdf(path)


def test_empty_text_pdf_raises_clearly(tmp_path):
    path = tmp_path / "blank.pdf"
    path.write_bytes(_blank_page_pdf())
    with pytest.raises(SyllabusNoExtractableTextError):
        parse_syllabus_pdf(path)


def test_zero_page_pdf_raises_clearly(tmp_path):
    path = tmp_path / "zero_pages.pdf"
    path.write_bytes(_zero_page_pdf())
    with pytest.raises(SyllabusEmptyDocumentError):
        parse_syllabus_pdf(path)


def test_encrypted_pdf_raises_clearly(tmp_path):
    path = tmp_path / "encrypted.pdf"
    path.write_bytes(_encrypted_pdf())
    with pytest.raises(SyllabusEncryptedPDFError):
        parse_syllabus_pdf(path)


# --- stability -------------------------------------------------------------------


def test_parsing_is_deterministic(tmp_path):
    path = phys_207_pdf_path(tmp_path)
    first = parse_syllabus_pdf(path).markdown
    second = parse_syllabus_pdf(path).markdown
    assert first == second
