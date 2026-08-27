import json
from pathlib import Path

from GradusIQ_career.syllabus.models import GradeCategory, GradeModel, GradingMethod
from GradusIQ_career.syllabus.validation import (
    ValidationSeverity,
    validate_category_weights,
    validate_grade_model,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "phys_207_grade_model.json"


def phys_207() -> GradeModel:
    return GradeModel.model_validate(json.loads(FIXTURE_PATH.read_text()))


def test_phys_207_weights_validate_successfully():
    findings = validate_category_weights(phys_207())
    assert len(findings) == 1
    assert findings[0].severity == ValidationSeverity.VALID


def test_weights_totaling_over_100_produce_warning_not_error():
    model = GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[
            GradeCategory(name="Exams", weight=90),
            GradeCategory(name="Extra Credit", weight=15),
        ],
    )
    findings = validate_category_weights(model)
    assert findings[0].severity == ValidationSeverity.WARNING
    assert "exceeding 100" in findings[0].message


def test_weights_totaling_under_100_produce_warning():
    model = GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[GradeCategory(name="Exams", weight=50)],
    )
    findings = validate_category_weights(model)
    assert findings[0].severity == ValidationSeverity.WARNING
    assert "not 100" in findings[0].message


def test_partial_grade_model_with_no_weights_is_still_representable():
    model = GradeModel(
        grading_method=GradingMethod.POINTS,
        categories=[GradeCategory(name="Homework", weight=None, count=None)],
    )
    findings = validate_category_weights(model)
    assert findings[0].severity == ValidationSeverity.VALID
    assert model.categories[0].weight is None
    assert model.categories[0].count is None


def test_weighted_method_with_categories_but_no_known_weights_is_error():
    model = GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[GradeCategory(name="Exams", weight=None)],
    )
    findings = validate_category_weights(model)
    assert findings[0].severity == ValidationSeverity.ERROR


def test_empty_grade_model_has_no_categories_to_validate():
    findings = validate_category_weights(GradeModel())
    assert findings[0].severity == ValidationSeverity.VALID


def test_validate_grade_model_delegates_to_weight_check():
    assert validate_grade_model(phys_207()) == validate_category_weights(phys_207())
