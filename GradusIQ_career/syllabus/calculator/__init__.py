"""Phase 6: deterministic grade calculation over an ACCEPTED GradeModel.

Public surface only -- internal helpers stay in engine.py/rules.py/solver.py.
"""

from GradusIQ_career.syllabus.calculator.engine import calculate_grade_projection, classify_grade
from GradusIQ_career.syllabus.calculator.models import (
    AppliedRule,
    AssessmentScoreInput,
    CalculationComponent,
    CategoryScoreInput,
    ComponentSourceType,
    GradeCalculationError,
    GradeCalculationResult,
    GradeInputValidationError,
    GradeModelNotReadyError,
    GradeModelStructureError,
    ScoreStatus,
    StudentGradeState,
    TargetScoreResult,
    UnsupportedDeterministicRuleError,
    UnsupportedGradingMethodError,
    UnsupportedGradingStructureError,
    UnsupportedRuleConditionError,
)
from GradusIQ_career.syllabus.calculator.solver import solve_required_score

__all__ = [
    "calculate_grade_projection",
    "classify_grade",
    "solve_required_score",
    "AppliedRule",
    "AssessmentScoreInput",
    "CalculationComponent",
    "CategoryScoreInput",
    "ComponentSourceType",
    "GradeCalculationError",
    "GradeCalculationResult",
    "GradeInputValidationError",
    "GradeModelNotReadyError",
    "GradeModelStructureError",
    "ScoreStatus",
    "StudentGradeState",
    "TargetScoreResult",
    "UnsupportedDeterministicRuleError",
    "UnsupportedGradingMethodError",
    "UnsupportedGradingStructureError",
    "UnsupportedRuleConditionError",
]
