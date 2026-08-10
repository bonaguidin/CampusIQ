"""SHIFT career feature runner."""

from typing import Any, Mapping

from .base import CareerFeatureRunner


class ShiftRunner(CareerFeatureRunner):
    feature = "SHIFT"
    prompt_filename = "gradus_iq_prompt_SHIFT.md"
    required_paths = (
        "career.target_roles",
        "career.skills_self_reported",
        "career.ai_anxiety_level",
    )
    output_contract: Mapping[str, Any] = {
        "role_evolution_summary": "string",
        "task_shifts": [
            {
                "task": "string",
                "changing": "string",
                "meaning": "string",
            }
        ],
        "durable_skills": [
            {
                "task": "string",
                "reason": "string",
            }
        ],
        "adjacent_paths": [
            {
                "path": "string",
                "relevance": "string",
                "driver": "string",
            }
        ],
        "ai_fluency_guidance": [],
    }

    def build_student_context(self, student_profile):
        student = student_profile.get("student", {})
        career = student_profile.get("career", {})
        return {
            "major_current": student.get("major_current") or student.get("major"),
            "major_intended": student.get("major_intended") or student.get("major"),
            "classification": student.get("classification"),
            "target_roles": career.get("target_roles", []),
            "interests": career.get("interests", []),
            "skills_self_reported": career.get("skills_self_reported", {}),
            "ai_anxiety_level": career.get("ai_anxiety_level", ""),
            "career_goals": career.get("career_goals", ""),
        }

    def default_summary(self, data):
        return data.get("role_evolution_summary", "SHIFT analysis completed.")
