"""SHIFT career feature runner."""

from typing import Any, Mapping

from . import role_research_agent
from .base import CareerFeatureRunner
from .market_data import get_shift_signals


class ShiftRunner(CareerFeatureRunner):
    feature = "SHIFT"
    prompt_filename = "gradus_iq_prompt_SHIFT.md"
    # ai_anxiety_level is deliberately NOT gated on. It calibrates SHIFT's tone
    # -- how much reassurance to offer about AI -- and everything the feature
    # actually reasons over (target roles, skills, O*NET signals, live trends)
    # is present without it. Blocking the whole analysis on an optional
    # self-report was withholding the answer to punish an incomplete profile.
    # See build_student_context: absent, it is omitted rather than sent empty.
    required_paths = (
        "career.target_roles",
        "career.skills_self_reported",
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
        target_roles = career.get("target_roles", [])
        context = {
            "major_current": student.get("major_current") or student.get("major"),
            "major_intended": student.get("major_intended") or student.get("major"),
            "classification": student.get("classification"),
            "target_roles": target_roles,
            "interests": career.get("interests", []),
            "skills_self_reported": career.get("skills_self_reported", {}),
            "career_goals": career.get("career_goals", ""),
            # Local O*NET grounding: adjacent occupations, hot technologies and
            # core tasks. Free and instant -- it is already on disk.
            "shift_signals": get_shift_signals(target_roles),
            # Live trend research: the only source for what is changing right
            # now. Absent roles simply have no entry, and the prompt requires
            # SHIFT to stay generic rather than invent a trend for them.
            "role_trends": self.role_trends_for(target_roles),
        }

        # Omitted entirely when unset, rather than sent as "". The prompt asks
        # the model to acknowledge the student's stated AI anxiety and
        # calibrate to it; an empty string is not a level, and handing one over
        # invites the model to characterize a feeling the student never
        # reported. Absent, the key simply is not in the JSON, and the prompt's
        # TONE GUIDANCE makes that branch explicit.
        ai_anxiety_level = career.get("ai_anxiety_level")
        if isinstance(ai_anxiety_level, str) and ai_anxiety_level.strip():
            context["ai_anxiety_level"] = ai_anxiety_level

        return context

    def role_trends_for(self, target_roles: Any) -> dict[str, Any]:
        """Research current trends for each target role, skipping failures.

        A role missing from the returned map means research did not come back.
        That is reported rather than hidden, because the alternative -- letting
        the model fill the silence from memory -- is exactly the behaviour this
        feature is being built to stop.
        """
        trends: dict[str, Any] = {}
        unresearched: list[str] = []
        for role in target_roles or []:
            result = role_research_agent.get_role_trends(role)
            if result:
                trends[role] = result
            else:
                unresearched.append(role)
        if unresearched:
            trends["_unresearched_roles"] = unresearched
        return trends

    def default_summary(self, data):
        return data.get("role_evolution_summary", "SHIFT analysis completed.")
