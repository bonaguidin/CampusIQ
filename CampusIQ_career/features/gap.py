"""GAP career feature runner."""

from typing import Any, Mapping

from .base import CareerFeatureRunner
from .market_data import get_market_requirements


class GapRunner(CareerFeatureRunner):
    feature = "GAP"
    prompt_filename = "campus_iq_prompt_GAP.md"
    required_paths = (
        "student.expected_graduation",
        "career.target_roles",
        "career.skills_self_reported",
        "career.work_experience",
    )
    output_contract: Mapping[str, Any] = {
        "readiness_score": 0,
        "strengths": [],
        "must_have_gaps": [],
        "nice_to_have_gaps": [],
        "recommended_next_steps": [],
    }

    def build_student_context(self, student_profile):
        student = student_profile.get("student", {})
        career = student_profile.get("career", {})
        target_roles = career.get("target_roles", [])
        return {
            "major_current": student.get("major_current") or student.get("major"),
            "major_intended": student.get("major_intended") or student.get("major"),
            "classification": student.get("classification"),
            "expected_graduation": student.get("expected_graduation"),
            "target_roles": target_roles,
            "skills_self_reported": career.get("skills_self_reported", {}),
            "certifications": career.get("certifications", []),
            "work_experience": career.get("work_experience", []),
            "projects": career.get("projects", []),
            "courses": student_profile.get("courses", []),
            # Market grounding: O*NET importance-scored requirements per target
            # role (static for the demo, live O*NET/DFW in Phase 2). This fills
            # the GAP prompt's "MARKET REQUIREMENTS" injection point. Requirements
            # with importance >= must_have_threshold are must-haves; below it are
            # nice-to-haves.
            "market_requirements": get_market_requirements(target_roles),
        }

    def default_summary(self, data):
        score = data.get("readiness_score")
        if score is not None:
            return f"GAP analysis completed with readiness score {score}."
        return "GAP analysis completed."
