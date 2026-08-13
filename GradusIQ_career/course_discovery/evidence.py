"""Hard boundary between model-authored GAP prose and C1 authority."""

from enum import Enum
from typing import Any, Mapping

from .models import CareerSkillNeed


class GapFieldClassification(str, Enum):
    SAFE_STRUCTURED_CAREER_NEED = "SAFE_STRUCTURED_CAREER_NEED"
    UNVERIFIED_NARRATIVE = "UNVERIFIED_NARRATIVE"
    COURSE_CERT_RECOMMENDATION = "COURSE_CERT_RECOMMENDATION"
    OTHER = "OTHER"


GAP_FIELD_CLASSIFICATION = {
    "must_have_gaps": GapFieldClassification.UNVERIFIED_NARRATIVE,
    "nice_to_have_gaps": GapFieldClassification.UNVERIFIED_NARRATIVE,
    "strengths": GapFieldClassification.UNVERIFIED_NARRATIVE,
    "recommended_next_steps": GapFieldClassification.COURSE_CERT_RECOMMENDATION,
    "readiness_score": GapFieldClassification.OTHER,
}


def classify_gap_output_fields() -> dict[str, GapFieldClassification]:
    return dict(GAP_FIELD_CLASSIFICATION)


def career_needs_from_gap_output(
    _gap_output: Mapping[str, Any],
) -> tuple[CareerSkillNeed, ...]:
    """No current GapOutput field crosses the deterministic evidence boundary.

    GapOutput contains useful reviewer-facing narrative, but no item carries a
    deterministic source identifier or evidence state. C2 must derive needs
    from local role grounding plus the canonical profile instead.
    """
    return ()
