import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from GradusIQ_career.syllabus.models import (
    Assessment,
    CourseMetadata,
    ExtractionWarning,
    ExtractionWarningType,
    GradeCategory,
    GradeModel,
    GradeThreshold,
    GradingMethod,
    GradingRule,
    GradingRuleType,
    ParsedDocumentMetadata,
    ParsedPage,
    ParsedSection,
    ParsedSyllabusDocument,
    SourceEvidence,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "phys_207_grade_model.json"


def phys_207() -> GradeModel:
    return GradeModel.model_validate(json.loads(FIXTURE_PATH.read_text()))


# --- ParsedSyllabusDocument ---------------------------------------------------


def test_valid_parsed_document_can_be_constructed():
    doc = ParsedSyllabusDocument(
        pages=[ParsedPage(page_number=1, markdown="# PHYS 207")],
        sections=[],
        markdown="# PHYS 207",
    )
    assert doc.schema_version == "1"
    assert doc.pages[0].page_number == 1
    assert doc.metadata == ParsedDocumentMetadata()


def test_parsed_document_page_numbers_are_preserved():
    doc = ParsedSyllabusDocument(
        pages=[
            ParsedPage(page_number=1, markdown="page one"),
            ParsedPage(page_number=2, markdown="page two"),
        ],
        markdown="page one\npage two",
    )
    assert [page.page_number for page in doc.pages] == [1, 2]


def test_parsed_section_can_span_multiple_pages():
    section = ParsedSection(heading="Grading Policy", page_numbers=[3, 4], markdown="Grading details span two pages.")
    assert section.page_numbers == [3, 4]


def test_parsed_section_rejects_empty_page_numbers():
    with pytest.raises(ValidationError):
        ParsedSection(heading="Grading Policy", page_numbers=[], markdown="text")


def test_parsed_section_rejects_non_positive_page_number():
    with pytest.raises(ValidationError):
        ParsedSection(heading="Grading Policy", page_numbers=[0], markdown="text")


# --- PHYS 207 fixture ----------------------------------------------------------


def test_phys_207_fixture_loads_successfully():
    model = phys_207()
    assert model.course.course_code == "PHYS 207"
    assert model.course.section == "529"
    assert model.course.term == "Fall 2026"


def test_phys_207_grading_method_is_weighted():
    assert phys_207().grading_method == GradingMethod.WEIGHTED


def test_phys_207_has_expected_four_categories():
    model = phys_207()
    names = {category.name for category in model.categories}
    assert names == {"Mid-term Exam", "Final Exam", "Lecture Quizzes", "Recitation Quizzes"}


def test_phys_207_quiz_counts_remain_unknown():
    model = phys_207()
    quiz_categories = [c for c in model.categories if "Quizzes" in c.name]
    assert len(quiz_categories) == 2
    assert all(category.count is None for category in quiz_categories)


def test_phys_207_category_weights_total_100():
    model = phys_207()
    assert sum(category.weight for category in model.categories) == 100


def test_phys_207_final_midterm_replacement_rule_is_represented():
    model = phys_207()
    replacement_rules = [r for r in model.rules if r.rule_type == GradingRuleType.REPLACEMENT]
    assert len(replacement_rules) == 1
    rule = replacement_rules[0]
    assert rule.source == "Final Exam"
    assert rule.target == "Mid-term Exam"
    assert rule.condition == "final_score > midterm_score"


def test_phys_207_curve_uncertainty_is_represented():
    model = phys_207()
    curve_rules = [r for r in model.rules if r.rule_type == GradingRuleType.CURVE]
    assert len(curve_rules) == 1

    curve_warnings = [w for w in model.warnings if w.type == ExtractionWarningType.POSSIBLE_CURVE]
    assert len(curve_warnings) == 1


def test_phys_207_grade_thresholds_are_represented():
    model = phys_207()
    thresholds = {t.letter: t for t in model.grade_thresholds}
    assert thresholds["A"].minimum == 90 and thresholds["A"].maximum == 100
    assert thresholds["F"].minimum is None and thresholds["F"].maximum == 44


# --- GradeModel field-level constraints -----------------------------------------


def test_grade_category_rejects_negative_weight():
    with pytest.raises(ValidationError):
        GradeCategory(name="Homework", weight=-1)


def test_grade_category_rejects_negative_count():
    with pytest.raises(ValidationError):
        GradeCategory(name="Homework", count=-1)


def test_assessment_rejects_negative_points():
    with pytest.raises(ValidationError):
        Assessment(name="Quiz 1", points=-5)


def test_source_evidence_rejects_confidence_below_zero():
    with pytest.raises(ValidationError):
        SourceEvidence(confidence=-0.1)


def test_source_evidence_rejects_confidence_above_one():
    with pytest.raises(ValidationError):
        SourceEvidence(confidence=1.1)


def test_source_evidence_confidence_is_optional():
    evidence = SourceEvidence(page=4, text="Midterm - 35%")
    assert evidence.confidence is None


def test_grading_rule_rejects_unknown_rule_type():
    with pytest.raises(ValidationError):
        GradingRule(rule_type="not_a_real_type", description="bogus")


def test_grading_method_rejects_unknown_enum_value():
    with pytest.raises(ValidationError):
        GradeModel(grading_method="curved_on_a_whim")


def test_grade_threshold_requires_at_least_one_bound():
    with pytest.raises(ValidationError):
        GradeThreshold(letter="A")


def test_grade_threshold_rejects_minimum_above_maximum():
    with pytest.raises(ValidationError):
        GradeThreshold(letter="A", minimum=95, maximum=90)


def test_grade_threshold_allows_minimum_only():
    threshold = GradeThreshold(letter="A", minimum=90)
    assert threshold.maximum is None


def test_grade_threshold_allows_maximum_only():
    threshold = GradeThreshold(letter="F", maximum=44)
    assert threshold.minimum is None


# --- Partial / unknown-heavy models remain representable ------------------------


def test_grade_model_with_all_unknown_course_metadata_is_valid():
    model = GradeModel(course=CourseMetadata())
    assert model.course.course_code is None
    assert model.grading_method == GradingMethod.UNKNOWN


def test_grade_model_rejects_extra_fields():
    with pytest.raises(ValidationError):
        GradeModel(course=CourseMetadata(), unexpected_field="oops")


def test_extraction_warning_round_trips():
    warning = ExtractionWarning(type=ExtractionWarningType.UNKNOWN_WEIGHT, description="No weight given for Homework.")
    restored = ExtractionWarning.model_validate(warning.model_dump(mode="json"))
    assert restored == warning
