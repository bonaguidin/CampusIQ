"""Phase 6 calculator contracts: trust gate, student input, and results.

    ACCEPTED GradeModelReconciliationResult + StudentGradeState
        -> deterministic calculator (engine.py/rules.py/solver.py)
        -> GradeCalculationResult / TargetScoreResult

No LLM, no PDF/relevance knowledge, no network, no persistence. The
calculator only ever reads GradusIQ_career.syllabus.models/.reconciliation
types -- it has no idea a GradeModel originated from a PDF, and must work
identically for a future manually authored one.

TRUST GATE
----------
Every public entry point takes a GradeModelReconciliationResult, never a
bare GradeModel, and immediately checks `.status == ACCEPTED` before doing
anything else (see require_accepted). A NEEDS_STUDENT_REVIEW result raises
GradeModelNotReadyError. There is no calculator function that accepts a
raw GradeModel -- see engine.py/solver.py's public signatures.
"""

from enum import Enum

from pydantic import Field, model_validator

from GradusIQ_career.syllabus.models import GradingMethod, GradingRuleType, StrictModel
from GradusIQ_career.syllabus.reconciliation import GradeModelReconciliationResult, ReconciliationStatus

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class GradeCalculationError(ValueError):
    """Base class for all Phase 6 calculator failures."""


class GradeModelNotReadyError(GradeCalculationError):
    """The supplied reconciliation result is not ACCEPTED.

    The trust gate: no calculator function proceeds past this check.
    """


class GradeInputValidationError(GradeCalculationError):
    """The caller's StudentGradeState references an unknown category/
    assessment, or duplicates an input -- a caller mistake, not a syllabus
    data problem.
    """


class UnsupportedGradingMethodError(GradeCalculationError):
    """grading_method is UNKNOWN, or some other value this engine cannot
    safely calculate from (never guessed between weighted/points).
    """


class UnsupportedGradingStructureError(GradeCalculationError):
    """grading_method is HYBRID but the GradeModel's structure does not
    resolve to one safe, unambiguous interpretation.
    """


class UnsupportedDeterministicRuleError(GradeCalculationError):
    """A rule cannot be safely executed with the current GradeModel schema
    (e.g. a DROP rule with no way to know the full set of scores it drops
    from -- see rules.py's module docstring).
    """


class UnsupportedRuleConditionError(GradeCalculationError):
    """A GradingRule.condition string does not match a conservatively
    recognized pattern. Never eval()'d or exec()'d -- see rules.py.
    """


class GradeModelStructureError(GradeCalculationError):
    """The ACCEPTED GradeModel itself has no usable weighted/points
    components to calculate from (e.g. every category weight is null).
    Distinct from GradeInputValidationError (a caller mistake) and from
    ordinary incompleteness (represented as None + warnings, not raised).
    """


# ---------------------------------------------------------------------------
# Student input
# ---------------------------------------------------------------------------


class ScoreStatus(str, Enum):
    COMPLETED = "completed"
    PROJECTED = "projected"


class CategoryScoreInput(StrictModel):
    """A student-entered score for one GradeModel category, as a percentage
    (0-100). This is the primary way to score a category whose individual
    assessment count/composition is unknown -- see calculator/engine.py's
    module docstring for why individual assessments under a category are
    never auto-aggregated.

    Exactly one of actual_score/projected_score must be set. `None` for
    both is not "zero" and not "not entered" -- it is simply invalid; omit
    this input entirely to represent "not yet entered."
    """

    category_name: str = Field(min_length=1)
    actual_score: float | None = Field(default=None, ge=0, le=100)
    projected_score: float | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def exactly_one_score(self):
        provided = [v for v in (self.actual_score, self.projected_score) if v is not None]
        if len(provided) != 1:
            raise ValueError("category score input must set exactly one of actual_score or projected_score")
        return self

    @property
    def status(self) -> ScoreStatus:
        return ScoreStatus.COMPLETED if self.actual_score is not None else ScoreStatus.PROJECTED

    @property
    def score(self) -> float:
        return self.actual_score if self.actual_score is not None else self.projected_score


class AssessmentScoreInput(StrictModel):
    """A student-entered score for one GradeModel assessment.

    Exactly one input shape is allowed per assessment: a percentage
    (actual_score or projected_score), or points (earned_points, with an
    optional possible_points override when the GradeModel's own
    Assessment.points is missing or the student wants to supply it
    directly). `points_status` is required alongside earned_points since,
    unlike the percentage fields, there is only one points field to carry
    both a real and a hypothetical value.
    """

    assessment_name: str = Field(min_length=1)
    actual_score: float | None = Field(default=None, ge=0, le=100)
    projected_score: float | None = Field(default=None, ge=0, le=100)
    earned_points: float | None = Field(default=None, ge=0)
    possible_points: float | None = Field(default=None, gt=0)
    points_status: ScoreStatus | None = None

    @model_validator(mode="after")
    def exactly_one_input_shape(self):
        percentage_fields = [v for v in (self.actual_score, self.projected_score) if v is not None]
        if len(percentage_fields) > 1:
            raise ValueError("assessment score input cannot set both actual_score and projected_score")
        points_given = self.earned_points is not None
        if len(percentage_fields) + (1 if points_given else 0) != 1:
            raise ValueError(
                "assessment score input must set exactly one of actual_score, projected_score, or earned_points"
            )
        if points_given and self.points_status is None:
            raise ValueError("earned_points requires points_status (completed or projected)")
        if not points_given and self.points_status is not None:
            raise ValueError("points_status is only meaningful alongside earned_points")
        if not points_given and self.possible_points is not None:
            raise ValueError("possible_points is only meaningful alongside earned_points")
        return self

    @property
    def is_points_based(self) -> bool:
        return self.earned_points is not None


class StudentGradeState(StrictModel):
    category_scores: list[CategoryScoreInput] = Field(default_factory=list)
    assessment_scores: list[AssessmentScoreInput] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Explainable breakdown
# ---------------------------------------------------------------------------


class ComponentSourceType(str, Enum):
    CATEGORY = "category"
    ASSESSMENT = "assessment"


class CalculationComponent(StrictModel):
    """One weighted/points component's contribution, before and after any
    deterministic rule effect -- e.g. a replacement rule changing a
    midterm's effective_score without touching original_score.
    """

    name: str
    source_type: ComponentSourceType
    status: ScoreStatus | None = None  # None = not yet entered
    original_score: float | None = None  # as entered by the student, 0-100
    effective_score: float | None = None  # after rule application, 0-100
    weight_percent: float | None = None  # this component's share of the course, 0-100
    contribution: float | None = None  # effective_score * weight_percent / 100
    earned_points: float | None = None
    possible_points: float | None = None


class AppliedRule(StrictModel):
    rule_type: GradingRuleType
    source: str | None
    target: str | None
    changed_calculation: bool
    description: str


class GradeCalculationResult(StrictModel):
    grading_method: GradingMethod
    components: list[CalculationComponent] = Field(default_factory=list)
    completed_weight: float | None = None  # % of the course completed so far
    earned_course_percentage: float | None = None  # % of the WHOLE course earned so far
    current_grade: float | None = None  # normalized grade on completed work only
    projected_grade: float | None = None  # only set when every component has a score
    current_letter_grade: str | None = None
    projected_letter_grade: str | None = None
    applied_rules: list[AppliedRule] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TargetScoreResult(StrictModel):
    target_component: str
    target_grade: float
    target_label: str | None = None  # the letter grade solved from, if any
    required_score: float | None = None  # None only when unsolvable -- see `warnings`
    feasible: bool = False
    already_achieved: bool = False
    applied_rules: list[AppliedRule] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def require_accepted(reconciliation: GradeModelReconciliationResult) -> None:
    """The Phase 6 trust gate. Every public calculator entry point calls
    this before touching `reconciliation.grade_model`.
    """
    if reconciliation.status != ReconciliationStatus.ACCEPTED:
        raise GradeModelNotReadyError(
            f"reconciliation status is {reconciliation.status.value}, not accepted; "
            "the calculator refuses to run against a model that still needs student review"
        )
