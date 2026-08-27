import io

import pytest
from pydantic import ValidationError
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas as rl_canvas

from GradusIQ_career.syllabus.models import ParsedPage, ParsedSection, ParsedSyllabusDocument
from GradusIQ_career.syllabus.parsing import parse_syllabus_pdf
from GradusIQ_career.syllabus.relevance import (
    RelevanceSignal,
    RelevantPage,
    RelevantSection,
    RelevantSyllabusContent,
    select_relevant_syllabus_content,
)


def page(page_number: int, markdown: str) -> ParsedPage:
    return ParsedPage(page_number=page_number, markdown=markdown)


def section(heading: str, page_numbers: list[int], markdown: str = "") -> ParsedSection:
    return ParsedSection(heading=heading, page_numbers=page_numbers, markdown=markdown)


def document(*, pages: list[ParsedPage] = (), sections: list[ParsedSection] = ()) -> ParsedSyllabusDocument:
    """Build a ParsedSyllabusDocument. Any page a section references but that
    wasn't explicitly supplied gets a matching blank ParsedPage, mirroring
    Phase 2's real invariant that every ParsedSection.page_numbers entry has
    a corresponding ParsedPage.
    """
    pages = list(pages)
    sections = list(sections)
    have_pages = {p.page_number for p in pages}
    for sec in sections:
        for page_number in sec.page_numbers:
            if page_number not in have_pages:
                pages.append(ParsedPage(page_number=page_number, markdown=sec.markdown))
                have_pages.add(page_number)
    pages.sort(key=lambda p: p.page_number)
    return ParsedSyllabusDocument(
        pages=pages,
        sections=sections,
        markdown="\n\n".join(f"<!-- page: {p.page_number} -->\n\n{p.markdown}" for p in pages),
    )


def page_numbers(result: RelevantSyllabusContent) -> list[int]:
    return [p.page_number for p in result.selected_pages]


# --- contract ----------------------------------------------------------------


def test_relevant_syllabus_content_can_be_constructed():
    result = RelevantSyllabusContent(source_page_count=0, selected_page_count=0)
    assert result.schema_version == "1"
    assert result.selected_pages == []
    assert result.selected_sections == []
    assert result.markdown == ""


def test_relevant_syllabus_content_rejects_extra_fields():
    with pytest.raises(ValidationError):
        RelevantSyllabusContent(source_page_count=0, selected_page_count=0, unexpected="oops")


def test_relevant_page_rejects_extra_fields():
    with pytest.raises(ValidationError):
        RelevantPage(page_number=1, markdown="x", relevance_score=1, unexpected="oops")


def test_relevant_section_requires_at_least_one_page_number():
    with pytest.raises(ValidationError):
        RelevantSection(heading="Grading", page_numbers=[], markdown="x", relevance_score=5)


# --- heading relevance ---------------------------------------------------------


def test_grading_heading_alone_selects_section():
    doc = document(sections=[section("Grading Policy", [1], "See below for details.")])
    result = select_relevant_syllabus_content(doc)
    assert len(result.selected_sections) == 1
    assert RelevanceSignal.GRADING_HEADING in result.selected_sections[0].matched_signals


def test_grade_scale_heading_alone_selects_section():
    doc = document(sections=[section("Grade Scale", [1], "See the table below.")])
    result = select_relevant_syllabus_content(doc)
    assert len(result.selected_sections) == 1
    assert RelevanceSignal.GRADE_SCALE_HEADING in result.selected_sections[0].matched_signals


def test_schedule_heading_combined_with_content_selects_section():
    doc = document(
        sections=[section("Course Schedule", [1], "Mid-term Exam - October 15\nFinal Exam - December 10")]
    )
    result = select_relevant_syllabus_content(doc)
    assert len(result.selected_sections) == 1
    assert RelevanceSignal.SCHEDULE_HEADING in result.selected_sections[0].matched_signals


def test_irrelevant_heading_does_not_select_section():
    doc = document(
        sections=[section("Office Hours", [1], "Please visit during office hours on Tuesdays and Thursdays.")]
    )
    result = select_relevant_syllabus_content(doc)
    assert result.selected_sections == []


# --- content relevance -----------------------------------------------------------


def test_weighted_category_content_is_selected_from_raw_page():
    doc = document(
        pages=[
            page(
                1,
                "Mid-term Exam: 35%\nFinal Exam: 50%\nLecture Quizzes: 5%\nRecitation Quizzes: 10%",
            )
        ]
    )
    result = select_relevant_syllabus_content(doc)
    assert page_numbers(result) == [1]
    signals = result.selected_pages[0].matched_signals
    assert RelevanceSignal.ASSESSMENT_TERM in signals
    assert RelevanceSignal.WEIGHT_TERM in signals
    assert RelevanceSignal.MULTI_SIGNAL in signals


def test_replacement_rule_content_is_selected():
    doc = document(
        pages=[
            page(
                1,
                "If the Final Exam grade is higher than the Mid-term Exam grade, "
                "the Final Exam will replace the Mid-term Exam grade.",
            )
        ]
    )
    result = select_relevant_syllabus_content(doc)
    assert page_numbers(result) == [1]
    assert RelevanceSignal.RULE_TERM in result.selected_pages[0].matched_signals


def test_curve_rule_content_is_selected():
    doc = document(pages=[page(1, "Exam grades may be curved upward at the instructor's discretion.")])
    result = select_relevant_syllabus_content(doc)
    assert page_numbers(result) == [1]
    assert RelevanceSignal.RULE_TERM in result.selected_pages[0].matched_signals


def test_grade_thresholds_content_is_selected():
    doc = document(
        sections=[section("Grade Scale", [1], "A: 90-100\nB: 80-89\nC: 60-79\nD: 45-59\nF: below 45")]
    )
    result = select_relevant_syllabus_content(doc)
    assert len(result.selected_sections) == 1
    assert RelevanceSignal.GRADE_SCALE_TERM in result.selected_sections[0].matched_signals


# --- false positives --------------------------------------------------------------


def test_isolated_grade_mention_does_not_select_page():
    doc = document(pages=[page(1, "Academic integrity violations may result in a failing grade.")])
    result = select_relevant_syllabus_content(doc)
    assert result.selected_pages == []


def test_academic_integrity_boilerplate_does_not_select_page():
    doc = document(
        pages=[
            page(
                1,
                "Academic Integrity\n\nAcademic integrity violations may result in a failing grade "
                "and referral to the Honor Council.",
            )
        ]
    )
    result = select_relevant_syllabus_content(doc)
    assert result.selected_pages == []


def test_disability_policy_boilerplate_does_not_select_page():
    doc = document(
        pages=[
            page(
                1,
                "Disability Policy\n\nStudents with disabilities may request accommodations through "
                "Disability Resources.",
            )
        ]
    )
    result = select_relevant_syllabus_content(doc)
    assert result.selected_pages == []


def test_generic_policy_text_does_not_select_page():
    doc = document(
        pages=[
            page(
                1,
                "This course follows the university's general grading regulations and student services "
                "information policy.",
            )
        ]
    )
    result = select_relevant_syllabus_content(doc)
    assert result.selected_pages == []


# --- page fallback (case B: heading undetected by Phase 2) -----------------------


def test_page_content_selects_when_section_heading_detection_missed_it():
    doc = document(
        pages=[
            page(
                4,
                "Grading Policy\nMid-term Exam: 35%\nFinal Exam: 50%\n"
                "Lecture Quizzes: 5%\nRecitation Quizzes: 10%",
            )
        ],
        sections=[],  # simulates Phase 2 failing to detect "Grading Policy" as a heading
    )
    result = select_relevant_syllabus_content(doc)
    assert page_numbers(result) == [4]


# --- ordering ----------------------------------------------------------------------


def test_selected_pages_remain_in_original_page_order():
    doc = document(
        pages=[
            page(5, "Final Exam: 50%\nMid-term Exam: 35%"),
            page(1, "Course Info\nPHYS 207"),
            page(2, "Mid-term Exam: 35%\nFinal Exam: 50%"),
        ]
    )
    result = select_relevant_syllabus_content(doc)
    assert page_numbers(result) == sorted(page_numbers(result))
    assert page_numbers(result) == [2, 5]


# --- deduplication -------------------------------------------------------------------


def test_page_selected_by_both_section_and_raw_scan_appears_once():
    grading_markdown = "Mid-term Exam: 35%\nFinal Exam: 50%"
    doc = document(
        pages=[page(1, grading_markdown)],
        sections=[section("Grading Policy", [1], grading_markdown)],
    )
    result = select_relevant_syllabus_content(doc)
    assert page_numbers(result) == [1]
    assert result.markdown.count("<!-- page: 1 -->") == 1


# --- provenance ------------------------------------------------------------------------


def test_original_page_marker_and_number_are_retained():
    doc = document(pages=[page(4, "Mid-term Exam: 35%\nFinal Exam: 50%")])
    result = select_relevant_syllabus_content(doc)
    assert result.selected_pages[0].page_number == 4
    assert "<!-- page: 4 -->" in result.markdown
    assert result.selected_pages[0].markdown == "Mid-term Exam: 35%\nFinal Exam: 50%"


def test_source_text_is_preserved_verbatim_not_summarized():
    text = (
        "If the Final Exam grade is higher than the Mid-term Exam grade,\n"
        "the Final Exam will replace the Mid-term Exam grade."
    )
    doc = document(pages=[page(1, text)])
    result = select_relevant_syllabus_content(doc)
    assert result.selected_pages[0].markdown == text


# --- empty result ------------------------------------------------------------------------


def test_no_relevant_content_returns_valid_empty_result():
    doc = document(
        pages=[
            page(1, "Course Information\nPHYS 207, Fall 2026"),
            page(2, "Learning Objectives\nStudents will understand mechanics and thermodynamics."),
            page(3, "Disability Policy\nContact Disability Resources for accommodations."),
        ]
    )
    result = select_relevant_syllabus_content(doc)
    assert result.selected_pages == []
    assert result.selected_sections == []
    assert result.markdown == ""
    assert result.source_page_count == 3
    assert result.selected_page_count == 0


# --- determinism -----------------------------------------------------------------------


def test_selection_is_deterministic():
    doc = document(
        pages=[
            page(1, "Mid-term Exam: 35%\nFinal Exam: 50%"),
            page(2, "Disability Policy\nContact Disability Resources."),
        ]
    )
    first = select_relevant_syllabus_content(doc)
    second = select_relevant_syllabus_content(doc)
    assert first == second


# --- context expansion --------------------------------------------------------------------


def test_context_expansion_pulls_in_unheaded_continuation_page():
    doc = document(
        pages=[
            page(1, "## Grading Policy\n\nMid-term Exam: 35%\nFinal Exam: 50%"),
            page(2, "10%"),  # continuation table row: weak on its own, no new heading
            page(3, "## Academic Integrity\n\nStudents must not cheat."),
        ]
    )
    result = select_relevant_syllabus_content(doc)
    assert page_numbers(result) == [1, 2]
    page_2 = next(p for p in result.selected_pages if p.page_number == 2)
    assert RelevanceSignal.CONTEXT_EXPANSION in page_2.matched_signals


def test_context_expansion_does_not_trigger_from_a_weak_page():
    doc = document(
        pages=[
            page(1, "Mid-term Exam: 35%"),  # only one content category, below STRONG_SCORE_THRESHOLD
            page(2, "10%"),
        ]
    )
    result = select_relevant_syllabus_content(doc)
    assert 2 not in page_numbers(result)


# --- CASE I: mixed multi-page syllabus, page-fallback throughout -------------------------


def test_mixed_multi_page_syllabus_selects_only_grading_and_schedule_pages():
    doc = document(
        pages=[
            page(1, "PHYS 207\nFall 2026\nInstructor: Dr. Smith"),
            page(2, "Learning Objectives\nStudents will understand mechanics and thermodynamics."),
            page(3, "Grading\nMid-term Exam: 35%\nFinal Exam: 50%"),
            page(4, "Grading (continued)\nLecture Quizzes: 5%\nRecitation Quizzes: 10%"),
            page(5, "Course Schedule\nMid-term Exam - October 15\nFinal Exam - December 10"),
            page(6, "Disability Policy\nStudents with disabilities may request accommodations."),
            page(7, "Academic Integrity\nViolations may result in a failing grade."),
        ],
        sections=[],  # exercises the raw-page fallback path throughout
    )
    result = select_relevant_syllabus_content(doc)
    assert page_numbers(result) == [3, 4, 5]


# --- end-to-end integration through Phase 2's parser --------------------------------------


def _build_syllabus_pdf() -> bytes:
    buf = io.BytesIO()
    canvas = rl_canvas.Canvas(buf, pagesize=letter)
    pdf_pages = [
        [("PHYS 207", 10, False), ("Fall 2026", 10, False)],
        [
            ("Grading Policy", 14, True),
            ("Mid-term Exam: 35%", 10, False),
            ("Final Exam: 50%", 10, False),
        ],
        [("Disability Policy", 14, True), ("Contact Disability Resources for accommodations.", 10, False)],
    ]
    for pdf_page in pdf_pages:
        y = 750
        for text, size, bold in pdf_page:
            canvas.setFont("Helvetica-Bold" if bold else "Helvetica", size)
            canvas.drawString(72, y, text)
            y -= size + 10
        canvas.showPage()
    canvas.save()
    return buf.getvalue()


def test_end_to_end_through_phase_2_parser(tmp_path):
    path = tmp_path / "syllabus.pdf"
    path.write_bytes(_build_syllabus_pdf())
    parsed = parse_syllabus_pdf(path)

    result = select_relevant_syllabus_content(parsed)

    assert page_numbers(result) == [2]
    assert any(s.heading == "Grading Policy" for s in result.selected_sections)
    assert "<!-- page: 2 -->" in result.markdown
    assert "Disability Policy" not in result.markdown
