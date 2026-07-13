"""GAP career feature runner."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from . import role_research_agent
from .base import CareerFeatureRunner
from .market_data import get_market_requirements

# Static, hand-curated role-requirements lookup used in place of a live O*NET /
# job-market API for the demo (SOC code + must-have / nice-to-have skills & certs
# per target role). Keyed by the exact target_role strings in the student JSON.
ROLE_REQUIREMENTS_PATH = Path(__file__).resolve().parents[2] / "data" / "role_requirements.json"


@lru_cache(maxsize=1)
def _load_role_requirements() -> Mapping[str, Any]:
    try:
        with open(ROLE_REQUIREMENTS_PATH, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return {key: value for key, value in data.items() if not key.startswith("_")}


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
        "must_have_gaps": [
            {
                "gap": "string",
                "why_it_matters": "string",
                "how_to_close": "string",
            }
        ],
        "nice_to_have_gaps": [
            {
                "gap": "string",
                "why_it_helps": "string",
                "how_to_close": "string",
            }
        ],
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
            "role_requirements": self.role_requirements_for(target_roles),
        }

    def role_requirements_for(self, target_roles: Any) -> dict[str, Any]:
        """Match each target role against the live research agent, falling
        back to the static lookup, and return the SOC-code + must-have /
        nice-to-have skills & certs for the roles found. Unmatched roles are
        reported so the AI does not silently assume coverage.

        The agent is tried first per role (it returns None on any failure,
        per its own fallback contract); a None result falls through to the
        exact same static-file lookup this used before the agent existed.

        Every matched role carries a soc_source field recording which path
        served it -- the agent already tags its own results ("agent" /
        "agent_onet_corroborated"); a static-fallback result is tagged
        "static" here so provenance is inspectable on the returned dict
        instead of only inferable from the (gitignored) agent cache."""
        lookup = _load_role_requirements()
        matched: dict[str, Any] = {}
        unmatched: list[str] = []
        for role in target_roles or []:
            requirements = role_research_agent.get_role_requirements(role)
            if requirements is None:
                static_entry = lookup.get(role)
                requirements = dict(static_entry, soc_source="static") if static_entry else None
            if requirements:
                matched[role] = requirements
            else:
                unmatched.append(role)
        if unmatched:
            matched["_unmatched_roles"] = unmatched
        return matched

    def default_summary(self, data):
        score = data.get("readiness_score")
        if score is not None:
            return f"GAP analysis completed with readiness score {score}."
        return "GAP analysis completed."
