"""Deterministic domain-level validation for GradeModel.

Field-level rules (weights/counts/points non-negative, confidence in
[0, 1], enum membership) are already enforced by pydantic on construction --
see models.py. This module covers cross-field checks that are informative
rather than construction-blocking: an incomplete or unusual syllabus should
still produce a valid GradeModel, with findings surfaced separately for
ingestion code to act on.
"""

from GradusIQ_career.syllabus.models import GradeModel, GradingMethod, StrictModel
from GradusIQ_career.syllabus.weighting import get_effective_course_weights
from enum import Enum


class ValidationSeverity(str, Enum):
    VALID = "valid"
    WARNING = "warning"
    ERROR = "error"


class ValidationFinding(StrictModel):
    severity: ValidationSeverity
    message: str
    field: str | None = None


def validate_category_weights(model: GradeModel, *, tolerance: float = 0.01) -> list[ValidationFinding]:
    """Check whether effective course-level weighted components sum to ~100.

    "Effective course-level weighted components" (see
    GradusIQ_career.syllabus.weighting) is every GradeCategory.weight plus
    every standalone Assessment.weight (Assessment.category is None) --
    not GradeCategory.weight alone. A category-scoped assessment's own
    weight is never added on top of its category's weight; see
    weighting.py's module docstring for why that would be a guess.

    Not a universal requirement: incomplete extraction, extra credit above
    100, and point-based classes with no weighted components are all
    legitimate and must not fail construction. Callers decide what to do
    with a WARNING/ERROR finding; the model itself stays representable
    either way.
    """
    effective = get_effective_course_weights(model)
    if not effective.has_any_component:
        if model.grading_method == GradingMethod.WEIGHTED and (model.categories or model.assessments):
            return [
                ValidationFinding(
                    severity=ValidationSeverity.ERROR,
                    message="grading method is weighted but no category or standalone assessment has a known weight",
                    field="categories",
                )
            ]
        return [
            ValidationFinding(
                severity=ValidationSeverity.VALID,
                message="no weighted categories to validate",
                field="categories",
            )
        ]

    total = effective.total_weight
    if abs(total - 100) <= tolerance:
        return [
            ValidationFinding(
                severity=ValidationSeverity.VALID,
                message=f"category weights sum to {total}",
                field="categories",
            )
        ]
    if total > 100:
        return [
            ValidationFinding(
                severity=ValidationSeverity.WARNING,
                message=f"category weights sum to {total}, exceeding 100 (possible extra credit)",
                field="categories",
            )
        ]
    return [
        ValidationFinding(
            severity=ValidationSeverity.WARNING,
            message=f"category weights sum to {total}, not 100 (possibly incomplete extraction)",
            field="categories",
        )
    ]


def validate_grade_model(model: GradeModel) -> list[ValidationFinding]:
    """Run all Phase 1 cross-field checks and return their findings."""
    return validate_category_weights(model)
