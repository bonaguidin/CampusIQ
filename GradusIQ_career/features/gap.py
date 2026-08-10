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

# Skill/certification fields merged from the agent when it succeeds. SOC
# code/title are deliberately excluded here -- they always come from the
# static file, never the agent (see role_requirements_for).
_SKILL_CERT_FIELDS = (
    "must_have_skills",
    "nice_to_have_skills",
    "must_have_certifications",
    "nice_to_have_certifications",
)


@lru_cache(maxsize=1)
def _load_role_requirements() -> Mapping[str, Any]:
    try:
        with open(ROLE_REQUIREMENTS_PATH, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return {key: value for key, value in data.items() if not key.startswith("_")}


def _merge_requirements(
    static_entry: Mapping[str, Any] | None, agent_result: Mapping[str, Any] | None
) -> dict[str, Any] | None:
    """soc_code/soc_title always come from static_entry (the agent's own SOC
    guess has proven unstable across runs and is never used as a lookup key
    anywhere downstream, so there is nothing to gain from it). Skills/certs
    come from the agent when it succeeded, falling back field-by-field to
    static_entry -- an agent empty list for one field does not clobber a
    populated static list for that same field (observed for Operations
    Intern's nice_to_have_certifications)."""
    if static_entry is None:
        # No static SOC record to anchor to -- can't build a result even if
        # the agent found something, since soc_code/soc_title must come from
        # here. Every current target_roles string has a static entry, so
        # this is a future-role safety net, not a live path today.
        return None

    merged: dict[str, Any] = {
        "soc_code": static_entry.get("soc_code"),
        "soc_title": static_entry.get("soc_title"),
    }
    if agent_result is not None:
        merged["requirements_source"] = "agent"
        for field in _SKILL_CERT_FIELDS:
            agent_value = agent_result.get(field)
            merged[field] = agent_value if agent_value else static_entry.get(field, [])
    else:
        merged["requirements_source"] = "static"
        for field in _SKILL_CERT_FIELDS:
            merged[field] = static_entry.get(field, [])
    return merged


class GapRunner(CareerFeatureRunner):
    feature = "GAP"
    prompt_filename = "gradus_iq_prompt_GAP.md"
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
        """Match each target role against the live research agent, and
        return the SOC-code + must-have / nice-to-have skills & certs for
        the roles found. Unmatched roles are reported so the AI does not
        silently assume coverage.

        soc_code/soc_title always come from the static
        data/role_requirements.json file; the agent's own SOC guess has
        proven unstable across runs and is never used as a lookup key
        anywhere downstream, so it is deliberately discarded. Skills/certs
        come from the agent when it succeeds (field-by-field, so an agent
        empty list doesn't clobber a populated static list), else from the
        static file. requirements_source records which path supplied the
        skills/certs ("agent" or "static")."""
        lookup = _load_role_requirements()
        matched: dict[str, Any] = {}
        unmatched: list[str] = []
        for role in target_roles or []:
            agent_result = role_research_agent.get_role_requirements(role)
            requirements = _merge_requirements(lookup.get(role), agent_result)
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
