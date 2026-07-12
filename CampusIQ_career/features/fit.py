"""FIT career feature runner."""

from typing import Any, Mapping

from .base import CareerFeatureRunner

# Sentinel value used in the data for "not switching majors" (Decision (b) —
# it stays in the data as-is; FIT resolves around it here in feature logic).
_NO_INTENDED_MAJOR = "N/A"


def _resolve_major(student: Mapping[str, Any]) -> tuple[str, str]:
    """Resolve the major FIT should reason about without mutating stored data.

    Returns (effective_major, major_status). Use major_intended when it is a
    real major; fall back to major_current when major_intended is "N/A", empty,
    or missing. major_status is "switching" when a distinct intended major is
    declared, else "staying"."""
    current = (student.get("major_current") or student.get("major") or "").strip()
    intended = (student.get("major_intended") or "").strip()

    if intended and intended.upper() != _NO_INTENDED_MAJOR and intended != current:
        return intended, "switching"
    return current, "staying"


class FitRunner(CareerFeatureRunner):
    feature = "FIT"
    prompt_filename = "campus_iq_prompt_FIT.md"
    required_paths = (
        "student.major_intended",
        "career.target_roles",
        "career.interests",
        "career.skills_self_reported",
    )
    output_contract: Mapping[str, Any] = {
        "role_matches": [
            {
                "role": "string",
                "fit_level": "high|medium|low",
                "rationale": "string",
                "supporting_signals": [],
                "missing_signals": [],
            }
        ],
        "overall_fit_summary": "string",
    }

    def build_student_context(self, student_profile):
        student = student_profile.get("student", {})
        career = student_profile.get("career", {})
        effective_major, major_status = _resolve_major(student)
        return {
            "effective_major": effective_major,
            "major_status": major_status,
            "major_current": student.get("major_current") or student.get("major"),
            "major_intended": student.get("major_intended") or student.get("major"),
            "classification": student.get("classification"),
            "target_roles": career.get("target_roles", []),
            "interests": career.get("interests", []),
            "career_goals": career.get("career_goals", ""),
            "geographic_preference": career.get("geographic_preference", ""),
            "skills_self_reported": career.get("skills_self_reported", {}),
            "work_experience": career.get("work_experience", []),
            "projects": career.get("projects", []),
        }

    def default_summary(self, data):
        return data.get("overall_fit_summary", "FIT analysis completed.")
