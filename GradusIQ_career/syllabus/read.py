"""Reconstruct typed domain models from persisted syllabus grade rows.

Never returns raw dicts to callers outside the syllabus package -- every
read validates through the existing Pydantic contracts (GradeModel,
GradeModelReconciliationResult, StudentGradeState), failing loudly on
schema-invalid persisted JSON (a future contract-version bump, a hand-edited
row) rather than silently coercing it.
"""

from typing import Any

from GradusIQ_career.syllabus.calculator import StudentGradeState
from GradusIQ_career.syllabus.models import GradeModel
from GradusIQ_career.syllabus.reconciliation import (
    EvidenceCoverage,
    GradeModelReconciliationResult,
    ReconciliationFinding,
    ReconciliationStatus,
)
from GradusIQ_career.syllabus.relevance import RelevantSyllabusContent


class PersistedRecordInvalidError(ValueError):
    """Persisted JSON no longer validates against the current Pydantic
    contract. Raised rather than silently coerced -- see module docstring.
    """


def _validate(model_cls: type, data: Any, *, context: str):
    try:
        return model_cls.model_validate(data)
    except Exception as exc:
        raise PersistedRecordInvalidError(f"{context}: {exc}") from exc


def extracted_grade_model_from_row(revision_row: dict) -> GradeModel:
    return _validate(GradeModel, revision_row["extracted_grade_model"], context="extracted_grade_model")


def confirmed_grade_model_from_row(revision_row: dict) -> GradeModel | None:
    data = revision_row.get("confirmed_grade_model")
    if data is None:
        return None
    return _validate(GradeModel, data, context="confirmed_grade_model")


def relevant_content_from_row(revision_row: dict) -> RelevantSyllabusContent:
    return _validate(RelevantSyllabusContent, revision_row.get("relevant_content") or {}, context="relevant_content")


def reconciliation_result_from_row(
    revision_row: dict, *, confirmed: bool = False
) -> GradeModelReconciliationResult:
    """Reconstruct the reconciliation result stored for a revision.

    `confirmed=True` reconstructs the CANDIDATE reconciliation (the
    corrected model's own re-reconciliation), using confirmed_grade_model +
    confirmed_reconciliation_status. `confirmed=False` (default)
    reconstructs the ORIGINAL extraction's reconciliation.
    """
    if confirmed:
        grade_model = confirmed_grade_model_from_row(revision_row)
        status = revision_row.get("confirmed_reconciliation_status")
        if grade_model is None or status is None:
            raise PersistedRecordInvalidError("revision has no confirmed grade model/status to reconstruct")
    else:
        grade_model = extracted_grade_model_from_row(revision_row)
        status = revision_row["reconciliation_status"]

    findings = [
        _validate(ReconciliationFinding, f, context="reconciliation_finding")
        for f in revision_row.get("reconciliation_findings", [])
    ]
    coverage = _validate(EvidenceCoverage, revision_row.get("evidence_coverage") or {}, context="evidence_coverage")

    return GradeModelReconciliationResult(
        status=ReconciliationStatus(status),
        grade_model=grade_model,
        findings=findings,
        evidence_coverage=coverage,
    )


def grade_state_from_row(state_row: dict) -> StudentGradeState:
    return _validate(
        StudentGradeState,
        {
            "category_scores": state_row.get("category_scores", []),
            "assessment_scores": state_row.get("assessment_scores", []),
        },
        context="student_grade_state",
    )


def calculator_ready(profile_row: dict, revision_row: dict | None) -> bool:
    """The single deterministic definition of calculator-ready.

    Requires BOTH: the student has confirmed (`review_state == 'confirmed'`)
    AND the confirmed model's own reconciliation is ACCEPTED. Neither
    condition alone is sufficient -- confirm_grade_model() (service.py) is
    the only writer of these columns and enforces the same rule before it
    ever sets confirmed_reconciliation_status = 'accepted', so this
    function is a read-side restatement of that same trust gate, never an
    independent or looser one.
    """
    if revision_row is None:
        return False
    return (
        profile_row.get("review_state") == "confirmed"
        and revision_row.get("confirmed_grade_model") is not None
        and revision_row.get("confirmed_reconciliation_status") == "accepted"
    )
