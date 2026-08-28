import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from GradusIQ_career.syllabus.extraction import (
    MAX_ATTEMPTS,
    SyllabusExtractionEmptyContentError,
    SyllabusExtractionFailedError,
    extract_grade_model,
)
from GradusIQ_career.syllabus.models import GradeCategory, GradingMethod, GradingRuleType
from GradusIQ_career.syllabus.relevance import RelevantPage, RelevantSyllabusContent

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "phys_207_grade_model.json"


class _FixedResponseClient:
    """Always returns the same response text. Records every call's kwargs."""

    def __init__(self, text: str, *, model: str = "fake-model"):
        self.text = text
        self.model = model
        self.calls: list[dict] = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(text=self.text, model=self.model)


class _QueueClient:
    """Returns queued response texts in order. Records every call's kwargs."""

    def __init__(self, responses: list[str], *, model: str = "fake-model"):
        self.responses = list(responses)
        self.model = model
        self.calls: list[dict] = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        text = self.responses.pop(0)
        return SimpleNamespace(text=text, model=self.model)


class _NeverCalledClient:
    def complete(self, **kwargs):
        raise AssertionError("client.complete() must not be called")


def page(page_number: int, markdown: str) -> RelevantPage:
    return RelevantPage(page_number=page_number, markdown=markdown, relevance_score=5.0)


def relevant_content(pages: list[RelevantPage]) -> RelevantSyllabusContent:
    combined = "\n\n".join(f"<!-- page: {p.page_number} -->\n\n{p.markdown}" for p in pages)
    return RelevantSyllabusContent(
        selected_pages=pages,
        selected_sections=[],
        markdown=combined,
        source_page_count=len(pages),
        selected_page_count=len(pages),
    )


# --- PHYS 207 fixture data ---------------------------------------------------

PHYS_207_PAGES = [
    page(1, "PHYS 207\nSection 529\nFall 2026"),
    page(
        2,
        "Grading Policy\n\nMid-term Exam: 35%\nFinal Exam: 50%\n"
        "Lecture Quizzes: 5%\nRecitation Quizzes: 10%",
    ),
    page(3, "Grade Scale\n\nA: 90-100\nB: 80-89\nC: 60-79\nD: 45-59\nF: below 45"),
    page(
        4,
        "If the Final Exam grade is higher than the Mid-term Exam grade, the "
        "Final Exam replaces the Mid-term Exam grade.\n\n"
        "Grades may be curved upward.",
    ),
]

PHYS_207_CONTENT = relevant_content(PHYS_207_PAGES)

PHYS_207_MODEL_RESPONSE = {
    "course": {"course_code": "PHYS 207", "course_title": None, "section": "529", "term": "Fall 2026", "instructor": None},
    "grading_method": "weighted",
    "categories": [
        {
            "name": "Mid-term Exam",
            "weight": 35,
            "count": None,
            "evidence": {"page": 2, "text": "Mid-term Exam: 35%", "confidence": 1.0},
        },
        {
            "name": "Final Exam",
            "weight": 50,
            "count": None,
            "evidence": {"page": 2, "text": "Final Exam: 50%", "confidence": 1.0},
        },
        {
            "name": "Lecture Quizzes",
            "weight": 5,
            "count": None,
            "evidence": {"page": 2, "text": "Lecture Quizzes: 5%", "confidence": 1.0},
        },
        {
            "name": "Recitation Quizzes",
            "weight": 10,
            "count": None,
            "evidence": {"page": 2, "text": "Recitation Quizzes: 10%", "confidence": 1.0},
        },
    ],
    "assessments": [],
    "grade_thresholds": [
        {"letter": "A", "minimum": 90, "maximum": 100, "evidence": {"page": 3, "text": "A: 90-100", "confidence": 1.0}},
        {"letter": "B", "minimum": 80, "maximum": 89, "evidence": {"page": 3, "text": "B: 80-89", "confidence": 1.0}},
        {"letter": "C", "minimum": 60, "maximum": 79, "evidence": {"page": 3, "text": "C: 60-79", "confidence": 1.0}},
        {"letter": "D", "minimum": 45, "maximum": 59, "evidence": {"page": 3, "text": "D: 45-59", "confidence": 1.0}},
        {
            "letter": "F",
            "minimum": None,
            "maximum": 44,
            "evidence": {"page": 3, "text": "F: below 45", "confidence": 0.8},
        },
    ],
    "rules": [
        {
            "rule_type": "replacement",
            "description": (
                "If the Final Exam grade is higher than the Mid-term Exam grade, "
                "the Final Exam replaces the Mid-term Exam grade."
            ),
            "source": "Final Exam",
            "target": "Mid-term Exam",
            "condition": "final_score > midterm_score",
            "evidence": {
                "page": 4,
                "text": (
                    "If the Final Exam grade is higher than the Mid-term Exam "
                    "grade, the Final Exam replaces the Mid-term Exam grade."
                ),
                "confidence": 1.0,
            },
        },
        {
            "rule_type": "curve",
            "description": "Grades may be curved upward.",
            "source": None,
            "target": None,
            "condition": None,
            "evidence": {"page": 4, "text": "Grades may be curved upward.", "confidence": 0.7},
        },
    ],
    "warnings": [
        {
            "type": "unknown_assessment_count",
            "description": "The exact number of Lecture Quizzes is unknown.",
            "related_field": "Lecture Quizzes",
        },
        {
            "type": "unknown_assessment_count",
            "description": "The exact number of Recitation Quizzes is unknown.",
            "related_field": "Recitation Quizzes",
        },
        {
            "type": "possible_curve",
            "description": "The syllabus states grades may be curved upward, but no deterministic curve formula is given.",
            "related_field": None,
        },
    ],
}


def phys_207_response_text() -> str:
    return json.dumps(PHYS_207_MODEL_RESPONSE)


# --- valid extraction ----------------------------------------------------------


def test_valid_structured_response_produces_grade_model():
    client = _FixedResponseClient(phys_207_response_text())
    result = extract_grade_model(PHYS_207_CONTENT, client)
    assert result.grading_method == GradingMethod.WEIGHTED
    assert len(client.calls) == 1


def test_child_models_parse_correctly():
    client = _FixedResponseClient(phys_207_response_text())
    result = extract_grade_model(PHYS_207_CONTENT, client)
    assert isinstance(result.categories[0], GradeCategory)
    assert result.rules[0].rule_type == GradingRuleType.REPLACEMENT


def test_extra_field_still_rejected_by_strict_model():
    payload = dict(PHYS_207_MODEL_RESPONSE)
    payload["unexpected_top_level_field"] = "oops"
    client = _QueueClient([json.dumps(payload), json.dumps(payload)])
    with pytest.raises(SyllabusExtractionFailedError):
        extract_grade_model(PHYS_207_CONTENT, client)
    assert len(client.calls) == MAX_ATTEMPTS


# --- PHYS 207 semantic comparison against the golden fixture --------------------


def test_phys_207_matches_golden_fixture_semantics():
    client = _FixedResponseClient(phys_207_response_text())
    result = extract_grade_model(PHYS_207_CONTENT, client)
    golden = json.loads(FIXTURE_PATH.read_text())

    assert result.grading_method.value == golden["grading_method"]

    result_categories = {c.name: c.weight for c in result.categories}
    golden_categories = {c["name"]: c["weight"] for c in golden["categories"]}
    assert result_categories == golden_categories
    assert len(result.categories) == 4

    lecture = next(c for c in result.categories if c.name == "Lecture Quizzes")
    recitation = next(c for c in result.categories if c.name == "Recitation Quizzes")
    assert lecture.count is None
    assert recitation.count is None

    result_thresholds = {t.letter: (t.minimum, t.maximum) for t in result.grade_thresholds}
    golden_thresholds = {t["letter"]: (t["minimum"], t["maximum"]) for t in golden["grade_thresholds"]}
    assert result_thresholds == golden_thresholds

    replacement_rules = [r for r in result.rules if r.rule_type == GradingRuleType.REPLACEMENT]
    assert len(replacement_rules) == 1
    assert replacement_rules[0].source == "Final Exam"
    assert replacement_rules[0].target == "Mid-term Exam"

    curve_rules = [r for r in result.rules if r.rule_type == GradingRuleType.CURVE]
    assert len(curve_rules) == 1

    curve_warnings = [w for w in result.warnings if w.type.value == "possible_curve"]
    assert len(curve_warnings) == 1


# --- evidence verification ------------------------------------------------------


def _single_category_payload(evidence: dict | None) -> dict:
    return {
        "course": {},
        "grading_method": "weighted",
        "categories": [{"name": "Mid-term Exam", "weight": 35, "count": None, "evidence": evidence}],
        "assessments": [],
        "grade_thresholds": [],
        "rules": [],
        "warnings": [],
    }


EVIDENCE_CONTENT = relevant_content([page(2, "Mid-term Exam:   35%\nFinal Exam: 50%")])


def test_valid_page_and_text_citation_is_accepted():
    payload = _single_category_payload({"page": 2, "text": "Mid-term Exam: 35%", "confidence": 1.0})
    client = _FixedResponseClient(json.dumps(payload))
    result = extract_grade_model(EVIDENCE_CONTENT, client)
    assert result.categories[0].evidence.page == 2
    assert len(client.calls) == 1


def test_nonexistent_page_is_rejected():
    payload = _single_category_payload({"page": 99, "text": "Mid-term Exam: 35%", "confidence": 1.0})
    client = _QueueClient([json.dumps(payload), json.dumps(payload)])
    with pytest.raises(SyllabusExtractionFailedError, match="not part of the selected"):
        extract_grade_model(EVIDENCE_CONTENT, client)
    assert len(client.calls) == MAX_ATTEMPTS


def test_evidence_text_missing_from_cited_page_is_rejected():
    payload = _single_category_payload({"page": 2, "text": "Midterm is worth 35 percent", "confidence": 1.0})
    client = _QueueClient([json.dumps(payload), json.dumps(payload)])
    with pytest.raises(SyllabusExtractionFailedError, match="was not found verbatim"):
        extract_grade_model(EVIDENCE_CONTENT, client)
    assert len(client.calls) == MAX_ATTEMPTS


def test_harmless_whitespace_normalization_is_accepted():
    # Source has "Mid-term Exam:   35%" (extra internal spaces); evidence is
    # single-spaced. Whitespace differences must not fail verification.
    payload = _single_category_payload({"page": 2, "text": "Mid-term Exam: 35%", "confidence": 1.0})
    client = _FixedResponseClient(json.dumps(payload))
    extract_grade_model(EVIDENCE_CONTENT, client)
    assert len(client.calls) == 1


def test_semantically_similar_but_nonverbatim_evidence_is_rejected():
    payload = _single_category_payload(
        {"page": 2, "text": "The midterm counts for thirty-five percent.", "confidence": 0.9}
    )
    client = _QueueClient([json.dumps(payload), json.dumps(payload)])
    with pytest.raises(SyllabusExtractionFailedError, match="was not found verbatim"):
        extract_grade_model(EVIDENCE_CONTENT, client)
    assert len(client.calls) == MAX_ATTEMPTS


def test_evidence_with_only_page_or_only_text_is_not_checked():
    # Partial provenance is explicitly allowed by the Phase 1 schema.
    payload = _single_category_payload({"page": None, "text": "not on any page, but page is null", "confidence": None})
    client = _FixedResponseClient(json.dumps(payload))
    result = extract_grade_model(EVIDENCE_CONTENT, client)
    assert result.categories[0].evidence.page is None
    assert len(client.calls) == 1


# --- hallucination defense --------------------------------------------------------


def test_invented_grading_fact_with_invented_evidence_is_rejected():
    payload = _single_category_payload(
        {"page": 2, "text": "Attendance is worth an additional 20% bonus.", "confidence": 0.6}
    )
    client = _QueueClient([json.dumps(payload), json.dumps(payload)])
    with pytest.raises(SyllabusExtractionFailedError):
        extract_grade_model(EVIDENCE_CONTENT, client)
    assert len(client.calls) == MAX_ATTEMPTS


# --- empty input -------------------------------------------------------------------


def test_empty_relevant_content_never_calls_the_model():
    empty = RelevantSyllabusContent(
        selected_pages=[], selected_sections=[], markdown="", source_page_count=3, selected_page_count=0
    )
    client = _NeverCalledClient()
    with pytest.raises(SyllabusExtractionEmptyContentError):
        extract_grade_model(empty, client)


def test_blank_markdown_with_pages_present_never_calls_the_model():
    blank = RelevantSyllabusContent(
        selected_pages=[page(1, "")],
        selected_sections=[],
        markdown="   \n\n  ",
        source_page_count=1,
        selected_page_count=1,
    )
    client = _NeverCalledClient()
    with pytest.raises(SyllabusExtractionEmptyContentError):
        extract_grade_model(blank, client)


# --- malformed output ---------------------------------------------------------------


def test_invalid_json_is_rejected():
    client = _QueueClient(["this is not json at all {{{", "this is not json at all {{{"])
    with pytest.raises(SyllabusExtractionFailedError):
        extract_grade_model(PHYS_207_CONTENT, client)
    assert len(client.calls) == MAX_ATTEMPTS


def test_empty_response_is_rejected():
    client = _QueueClient(["", ""])
    with pytest.raises(SyllabusExtractionFailedError):
        extract_grade_model(PHYS_207_CONTENT, client)
    assert len(client.calls) == MAX_ATTEMPTS


def test_invalid_enum_value_is_rejected():
    payload = dict(PHYS_207_MODEL_RESPONSE)
    payload["grading_method"] = "curved_on_a_whim"
    client = _QueueClient([json.dumps(payload), json.dumps(payload)])
    with pytest.raises(SyllabusExtractionFailedError):
        extract_grade_model(PHYS_207_CONTENT, client)
    assert len(client.calls) == MAX_ATTEMPTS


def test_wrong_field_type_is_rejected():
    payload = _single_category_payload({"page": 2, "text": "Mid-term Exam: 35%", "confidence": 1.0})
    payload["categories"][0]["weight"] = "thirty-five"
    client = _QueueClient([json.dumps(payload), json.dumps(payload)])
    with pytest.raises(SyllabusExtractionFailedError):
        extract_grade_model(EVIDENCE_CONTENT, client)
    assert len(client.calls) == MAX_ATTEMPTS


def test_incomplete_grade_threshold_is_rejected():
    payload = {
        "course": {},
        "grading_method": "unknown",
        "categories": [],
        "assessments": [],
        "grade_thresholds": [{"letter": "A", "minimum": None, "maximum": None, "evidence": None}],
        "rules": [],
        "warnings": [],
    }
    client = _QueueClient([json.dumps(payload), json.dumps(payload)])
    with pytest.raises(SyllabusExtractionFailedError):
        extract_grade_model(PHYS_207_CONTENT, client)
    assert len(client.calls) == MAX_ATTEMPTS


# --- retry behavior ------------------------------------------------------------------


def test_malformed_first_response_recovers_via_bounded_retry():
    client = _QueueClient(["not valid json {{{", phys_207_response_text()])
    result = extract_grade_model(PHYS_207_CONTENT, client)
    assert result.grading_method == GradingMethod.WEIGHTED
    assert len(client.calls) == 2
    second_call_messages = client.calls[1]["messages"]
    assert any("corrected JSON" in m["content"] for m in second_call_messages if m["role"] == "user")


def test_retry_count_never_exceeds_configured_limit():
    client = _QueueClient(["bad {{{"] * 5)
    with pytest.raises(SyllabusExtractionFailedError):
        extract_grade_model(PHYS_207_CONTENT, client)
    assert len(client.calls) == MAX_ATTEMPTS


# --- determinism -----------------------------------------------------------------------


def test_same_source_and_mocked_output_produce_identical_grade_model():
    first = extract_grade_model(PHYS_207_CONTENT, _FixedResponseClient(phys_207_response_text()))
    second = extract_grade_model(PHYS_207_CONTENT, _FixedResponseClient(phys_207_response_text()))
    assert first == second


# --- model role -----------------------------------------------------------------------


def test_extraction_calls_use_parsing_role_and_zero_temperature():
    client = _FixedResponseClient(phys_207_response_text())
    extract_grade_model(PHYS_207_CONTENT, client)
    assert client.calls[0]["role"] == "parsing"
    assert client.calls[0]["temperature"] == 0
