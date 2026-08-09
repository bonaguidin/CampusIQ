"""SHIFT career feature runner."""

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Mapping

from . import role_research_agent
from .base import CareerFeatureRunner
from .market_data import get_shift_signals

logger = logging.getLogger(__name__)

# Ceiling on concurrent research threads per request. A student's target_roles
# list is user-controlled, so this is capped rather than left as len(roles).
_MAX_TREND_WORKERS = 4


def _safe_role_trends(role: str) -> dict[str, Any] | None:
    """Never let one role's failure abort the others.

    get_role_trends is contractually non-raising, but pool.map re-raises on
    collection -- so a regression there would take down the whole SHIFT run
    instead of costing one role its trend data. Cheap insurance for a property
    that matters more now that these run in parallel.
    """
    try:
        return role_research_agent.get_role_trends(role)
    except Exception:  # noqa: BLE001 -- degrade to "unresearched", never fail SHIFT
        logger.warning("role_trends raised for role=%s; treating as unresearched", role, exc_info=True)
        return None


class ShiftRunner(CareerFeatureRunner):
    feature = "SHIFT"
    prompt_filename = "campus_iq_prompt_SHIFT.md"
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
        target_roles = career.get("target_roles", [])
        return {
            "major_current": student.get("major_current") or student.get("major"),
            "major_intended": student.get("major_intended") or student.get("major"),
            "classification": student.get("classification"),
            "target_roles": target_roles,
            "interests": career.get("interests", []),
            "skills_self_reported": career.get("skills_self_reported", {}),
            "ai_anxiety_level": career.get("ai_anxiety_level", ""),
            "career_goals": career.get("career_goals", ""),
            # Local O*NET grounding: adjacent occupations, hot technologies and
            # core tasks. Free and instant -- it is already on disk.
            "shift_signals": get_shift_signals(target_roles),
            # Live trend research: the only source for what is changing right
            # now. Absent roles simply have no entry, and the prompt requires
            # SHIFT to stay generic rather than invent a trend for them.
            "role_trends": self.role_trends_for(target_roles),
        }

    def role_trends_for(self, target_roles: Any) -> dict[str, Any]:
        """Research current trends for each target role, concurrently.

        A role missing from the returned map means research did not come back.
        That is reported rather than hidden, because the alternative -- letting
        the model fill the silence from memory -- is exactly the behaviour this
        feature is being built to stop.

        Run in parallel because the lookups are independent and I/O-bound
        (model call -> web search -> model call). Serially they made SHIFT's
        wall time the SUM of every role's research: measured at ~24s per role,
        so a three-role student spent ~2m43s researching and finished in
        ~3m42s -- uncomfortably close to the 300s ceiling the frontend proxy
        enforces on any request. Concurrently that research collapses to
        roughly the slowest single role.
        """
        roles = [r for r in (target_roles or []) if isinstance(r, str) and r.strip()]
        # Deduplicated before dispatch: two identical role strings would
        # otherwise research twice in parallel, and neither would see the
        # other's cache entry because both start before either writes.
        unique = list(dict.fromkeys(roles))
        if not unique:
            return {}

        with ThreadPoolExecutor(max_workers=min(len(unique), _MAX_TREND_WORKERS)) as pool:
            researched = dict(zip(unique, pool.map(_safe_role_trends, unique)))

        trends: dict[str, Any] = {}
        unresearched: list[str] = []
        for role in unique:
            result = researched.get(role)
            if result:
                trends[role] = result
            else:
                unresearched.append(role)
        if unresearched:
            trends["_unresearched_roles"] = unresearched
        return trends

    def default_summary(self, data):
        return data.get("role_evolution_summary", "SHIFT analysis completed.")
