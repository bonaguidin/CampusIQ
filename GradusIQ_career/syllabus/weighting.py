"""The single definition of "effective course-level weighted component,"
shared by trust validation (validation.py/reconciliation.py) and the
calculator (calculator/engine.py) so the two layers can never disagree
about what counts toward a weighted course's 100%.

THE RULE
--------
A course-level weighted component is:

    A. every GradeCategory with a known weight, and
    B. every standalone Assessment (Assessment.category is None) with a
       known weight of its own.

An Assessment whose `.category` names a category is EXCLUDED from the
course-level total, regardless of whether that name resolves to a real
GradeCategory in this model. Its own `.weight` is never added on top of
its category's weight, and its category's weight is never reduced to make
room for it. This is a genuine schema ambiguity, not a solved case: the
Phase 1 schema has no field establishing whether such an assessment's
weight is a fraction of its category's weight, an independent course
percentage that happens to share a label, or something else entirely (see
Phase 6's calculator/engine.py module docstring, "WHY CATEGORIES AND
STANDALONE ASSESSMENTS, NEVER AGGREGATED"). Counting it either way would be
a guess; excluding it and surfacing that exclusion (both layers do, via
`categories_without_weight`/`category_scoped_weighted_assessments` here and
their corresponding warnings in validate_category_weights/engine.py) is the
conservative, deterministic choice both layers already made independently
before this module existed to keep them in sync.
"""

from dataclasses import dataclass

from GradusIQ_career.syllabus.models import Assessment, GradeCategory, GradeModel


@dataclass(frozen=True)
class EffectiveCourseWeights:
    weighted_categories: tuple[GradeCategory, ...]
    standalone_weighted_assessments: tuple[Assessment, ...]
    categories_without_weight: tuple[GradeCategory, ...]
    category_scoped_weighted_assessments: tuple[Assessment, ...]

    @property
    def total_weight(self) -> float:
        return sum(c.weight for c in self.weighted_categories) + sum(
            a.weight for a in self.standalone_weighted_assessments
        )

    @property
    def has_any_component(self) -> bool:
        return bool(self.weighted_categories or self.standalone_weighted_assessments)


def get_effective_course_weights(grade_model: GradeModel) -> EffectiveCourseWeights:
    """Classify every GradeCategory/Assessment into the effective
    course-level weighting picture. Deterministic, pure, no I/O.
    """
    weighted_categories = tuple(c for c in grade_model.categories if c.weight is not None)
    categories_without_weight = tuple(c for c in grade_model.categories if c.weight is None)

    standalone_weighted_assessments = tuple(
        a for a in grade_model.assessments if a.weight is not None and a.category is None
    )
    category_scoped_weighted_assessments = tuple(
        a for a in grade_model.assessments if a.weight is not None and a.category is not None
    )

    return EffectiveCourseWeights(
        weighted_categories=weighted_categories,
        standalone_weighted_assessments=standalone_weighted_assessments,
        categories_without_weight=categories_without_weight,
        category_scoped_weighted_assessments=category_scoped_weighted_assessments,
    )
