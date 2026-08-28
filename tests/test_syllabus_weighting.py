"""Phase 6.5: trust validation and the calculator must agree on what counts
as a course-level weighted component. See GradusIQ_career/syllabus/weighting.py.
"""

import json
from pathlib import Path

import pytest

from GradusIQ_career.syllabus.calculator import (
    AssessmentScoreInput,
    CategoryScoreInput,
    GradeModelNotReadyError,
    StudentGradeState,
    calculate_grade_projection,
)
from GradusIQ_career.syllabus.models import (
    Assessment,
    GradeCategory,
    GradeModel,
    GradingMethod,
    SourceEvidence,
)
from GradusIQ_career.syllabus.reconciliation import ReconciliationStatus, reconcile_grade_model
from GradusIQ_career.syllabus.relevance import RelevantPage, RelevantSyllabusContent
from GradusIQ_career.syllabus.validation import ValidationSeverity, validate_category_weights
from GradusIQ_career.syllabus.weighting import get_effective_course_weights

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "phys_207_grade_model.json"


def evidence(page_number: int, text: str) -> SourceEvidence:
    return SourceEvidence(page=page_number, text=text, confidence=1.0)


def content_for(*texts: str) -> RelevantSyllabusContent:
    pages = [RelevantPage(page_number=i + 1, markdown=text, relevance_score=5.0) for i, text in enumerate(texts)]
    combined = "\n\n".join(f"<!-- page: {p.page_number} -->\n\n{p.markdown}" for p in pages)
    return RelevantSyllabusContent(
        selected_pages=pages,
        selected_sections=[],
        markdown=combined,
        source_page_count=len(pages),
        selected_page_count=len(pages),
    )


def phys_207() -> GradeModel:
    return GradeModel.model_validate(json.loads(FIXTURE_PATH.read_text()))


# --- Case A: categories only (unchanged) ------------------------------------------


def test_categories_only_effective_total_is_100():
    effective = get_effective_course_weights(phys_207())
    assert effective.total_weight == 100.0
    assert len(effective.weighted_categories) == 4
    assert effective.standalone_weighted_assessments == ()


def test_phys_207_validation_unchanged():
    findings = validate_category_weights(phys_207())
    assert len(findings) == 1
    assert findings[0].severity == ValidationSeverity.VALID


# --- Case B: standalone assessments only -------------------------------------------


def standalone_only_model() -> GradeModel:
    return GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        assessments=[
            Assessment(name="Midterm", weight=30, evidence=evidence(1, "Midterm: 30%")),
            Assessment(name="Final", weight=40, evidence=evidence(1, "Final: 40%")),
            Assessment(name="Project", weight=30, evidence=evidence(1, "Project: 30%")),
        ],
    )


def test_standalone_assessments_only_effective_total_is_100():
    effective = get_effective_course_weights(standalone_only_model())
    assert effective.total_weight == 100.0
    assert len(effective.standalone_weighted_assessments) == 3
    assert effective.weighted_categories == ()


def test_standalone_assessments_only_validates_as_coherent():
    findings = validate_category_weights(standalone_only_model())
    assert findings[0].severity == ValidationSeverity.VALID


def test_standalone_assessments_only_reconciles_to_accepted():
    content = content_for("Midterm: 30% Final: 40% Project: 30%")
    result = reconcile_grade_model(standalone_only_model(), content)
    assert result.status == ReconciliationStatus.ACCEPTED


# --- Case C: mixed categories + standalone assessments (primary regression) --------


def mixed_model() -> GradeModel:
    return GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[
            GradeCategory(name="Homework", weight=30, evidence=evidence(1, "Homework: 30%")),
            GradeCategory(name="Quizzes", weight=20, evidence=evidence(1, "Quizzes: 20%")),
        ],
        assessments=[
            Assessment(name="Midterm", weight=20, evidence=evidence(1, "Midterm: 20%")),
            Assessment(name="Final", weight=30, evidence=evidence(1, "Final: 30%")),
        ],
    )


MIXED_CONTENT = content_for("Homework: 30% Quizzes: 20% Midterm: 20% Final: 30%")


def test_mixed_effective_total_is_100():
    effective = get_effective_course_weights(mixed_model())
    assert effective.total_weight == 100.0
    assert len(effective.weighted_categories) == 2
    assert len(effective.standalone_weighted_assessments) == 2


def test_mixed_model_reconciles_to_accepted():
    result = reconcile_grade_model(mixed_model(), MIXED_CONTENT)
    assert result.status == ReconciliationStatus.ACCEPTED


# --- Case D: assessment inside a weighted category (no double counting) -----------


def nested_quiz_model() -> GradeModel:
    return GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[GradeCategory(name="Quizzes", weight=20, evidence=evidence(1, "Quizzes: 20%"))],
        assessments=[
            Assessment(name="Quiz 1", category="Quizzes", weight=25, evidence=evidence(1, "Quiz 1: 25%")),
            Assessment(name="Quiz 2", category="Quizzes", weight=25, evidence=evidence(1, "Quiz 2: 25%")),
        ],
    )


def test_category_linked_assessment_weight_is_not_double_counted():
    effective = get_effective_course_weights(nested_quiz_model())
    # NOT 20 + 25 + 25 = 70 -- only the category's own 20% counts.
    assert effective.total_weight == 20.0
    assert len(effective.weighted_categories) == 1
    assert effective.standalone_weighted_assessments == ()
    assert len(effective.category_scoped_weighted_assessments) == 2


def test_category_linked_assessment_excluded_from_calculator_too():
    content = content_for("Quizzes: 20% Quiz 1: 25% Quiz 2: 25%")
    result = reconcile_grade_model(nested_quiz_model(), content)
    # 20% alone is far from 100 -- correctly flagged for review, proving the
    # calculator-side exclusion (not a naive 70 that Phase 5 would also
    # have called incomplete, but for the wrong number).
    assert result.status == ReconciliationStatus.NEEDS_STUDENT_REVIEW
    weight_finding = next(f for f in result.findings if f.code == "category_weight_validation")
    assert "20.0" in weight_finding.message


# --- Case: mixed nested + standalone (section 8) ------------------------------------


def nested_plus_standalone_model() -> GradeModel:
    return GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[GradeCategory(name="Quizzes", weight=20, evidence=evidence(1, "Quizzes: 20%"))],
        assessments=[
            Assessment(name="Quiz 1", category="Quizzes", evidence=evidence(1, "Quiz 1")),
            Assessment(name="Quiz 2", category="Quizzes", evidence=evidence(1, "Quiz 2")),
            Assessment(name="Midterm", weight=30, evidence=evidence(1, "Midterm: 30%")),
            Assessment(name="Final", weight=50, evidence=evidence(1, "Final: 50%")),
        ],
    )


def test_nested_plus_standalone_effective_total_is_100():
    effective = get_effective_course_weights(nested_plus_standalone_model())
    assert effective.total_weight == 100.0
    names = {a.name for a in effective.standalone_weighted_assessments}
    assert names == {"Midterm", "Final"}


def test_nested_plus_standalone_reconciles_to_accepted():
    content = content_for("Quizzes: 20% Quiz 1 Quiz 2 Midterm: 30% Final: 50%")
    result = reconcile_grade_model(nested_plus_standalone_model(), content)
    assert result.status == ReconciliationStatus.ACCEPTED


# --- unknown weights remain unknown (section 9) -------------------------------------


def test_category_with_null_weight_is_excluded_not_inferred():
    model = GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[
            GradeCategory(name="Homework", weight=None),
            GradeCategory(name="Exams", weight=100, evidence=evidence(1, "Exams: 100%")),
        ],
    )
    effective = get_effective_course_weights(model)
    assert effective.total_weight == 100.0
    assert len(effective.categories_without_weight) == 1
    assert effective.categories_without_weight[0].name == "Homework"


def test_assessment_with_null_weight_is_not_counted():
    model = GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        assessments=[
            Assessment(name="Bonus", weight=None),
            Assessment(name="Exams", weight=100, evidence=evidence(1, "Exams: 100%")),
        ],
    )
    effective = get_effective_course_weights(model)
    assert effective.total_weight == 100.0


def test_incomplete_total_still_produces_warning_not_silently_accepted():
    model = GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[GradeCategory(name="Homework", weight=30, evidence=evidence(1, "Homework: 30%"))],
        assessments=[Assessment(name="Midterm", weight=20, evidence=evidence(1, "Midterm: 20%"))],
    )
    findings = validate_category_weights(model)
    assert findings[0].severity == ValidationSeverity.WARNING
    assert "50.0" in findings[0].message
    assert "not 100" in findings[0].message


# --- points model unaffected (section 10) -------------------------------------------


def test_points_model_effective_weights_are_empty():
    model = GradeModel(
        grading_method=GradingMethod.POINTS,
        assessments=[
            Assessment(name="Midterm", points=200, evidence=evidence(1, "Midterm: 200 points")),
            Assessment(name="Final", points=300, evidence=evidence(1, "Final: 300 points")),
        ],
    )
    effective = get_effective_course_weights(model)
    assert effective.total_weight == 0.0
    assert not effective.has_any_component


def test_points_model_validation_and_reconciliation_unaffected():
    model = GradeModel(
        grading_method=GradingMethod.POINTS,
        assessments=[
            Assessment(name="Midterm", points=200, evidence=evidence(1, "Midterm: 200 points")),
            Assessment(name="Final", points=300, evidence=evidence(1, "Final: 300 points")),
        ],
    )
    findings = validate_category_weights(model)
    assert findings[0].severity == ValidationSeverity.VALID
    content = content_for("Midterm: 200 points Final: 300 points")
    result = reconcile_grade_model(model, content)
    assert result.status == ReconciliationStatus.ACCEPTED


def test_points_calculation_unchanged_by_weighting_module():
    from GradusIQ_career.syllabus.calculator import ScoreStatus

    model = GradeModel(
        grading_method=GradingMethod.POINTS,
        assessments=[Assessment(name="Midterm", points=200, evidence=evidence(1, "Midterm: 200 points"))],
    )
    content = content_for("Midterm: 200 points")
    recon = reconcile_grade_model(model, content)
    assert recon.status == ReconciliationStatus.ACCEPTED
    state = StudentGradeState(
        assessment_scores=[
            AssessmentScoreInput(assessment_name="Midterm", earned_points=180, points_status=ScoreStatus.COMPLETED)
        ]
    )
    result = calculate_grade_projection(recon, state)
    assert result.current_grade == 90.0


# --- trust gate unchanged ------------------------------------------------------------


def test_mixed_accepted_model_can_calculate():
    recon = reconcile_grade_model(mixed_model(), MIXED_CONTENT)
    assert recon.status == ReconciliationStatus.ACCEPTED
    state = StudentGradeState(
        category_scores=[
            CategoryScoreInput(category_name="Homework", actual_score=90),
            CategoryScoreInput(category_name="Quizzes", actual_score=80),
        ],
        assessment_scores=[
            AssessmentScoreInput(assessment_name="Midterm", actual_score=85),
            AssessmentScoreInput(assessment_name="Final", actual_score=95),
        ],
    )
    result = calculate_grade_projection(recon, state)
    expected = 90 * 0.30 + 80 * 0.20 + 85 * 0.20 + 95 * 0.30
    assert result.projected_grade == round(expected, 2) == 88.5


def test_needs_review_still_blocks_mixed_model_calculation():
    incomplete = GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[GradeCategory(name="Homework", weight=30, evidence=evidence(1, "Homework: 30%"))],
        assessments=[Assessment(name="Midterm", weight=20, evidence=evidence(1, "Midterm: 20%"))],
    )
    content = content_for("Homework: 30% Midterm: 20%")
    recon = reconcile_grade_model(incomplete, content)
    assert recon.status == ReconciliationStatus.NEEDS_STUDENT_REVIEW
    with pytest.raises(GradeModelNotReadyError):
        calculate_grade_projection(recon, StudentGradeState())


# --- calculator alignment: reconciliation and calculator agree (section 13) --------


def test_reconciliation_and_calculator_agree_on_mixed_structure():
    """The exact worked example from the Phase 6.5 task: Phase 5 sees the
    same 100% total the calculator computes 88.5% from.
    """
    recon = reconcile_grade_model(mixed_model(), MIXED_CONTENT)
    assert recon.status == ReconciliationStatus.ACCEPTED
    weight_finding = next(f for f in recon.findings if f.code == "category_weight_validation")
    assert weight_finding.severity == ValidationSeverity.VALID
    assert "100.0" in weight_finding.message

    state = StudentGradeState(
        category_scores=[
            CategoryScoreInput(category_name="Homework", actual_score=90),
            CategoryScoreInput(category_name="Quizzes", actual_score=80),
        ],
        assessment_scores=[
            AssessmentScoreInput(assessment_name="Midterm", actual_score=85),
            AssessmentScoreInput(assessment_name="Final", actual_score=95),
        ],
    )
    result = calculate_grade_projection(recon, state)
    assert result.projected_grade == 88.5
    assert result.current_grade == 88.5  # every component completed


# --- determinism --------------------------------------------------------------------


def test_effective_course_weights_is_deterministic():
    model = mixed_model()
    first = get_effective_course_weights(model)
    second = get_effective_course_weights(model)
    assert first == second
    assert first.total_weight == second.total_weight
