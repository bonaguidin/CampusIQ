"""Deterministic career-skill needs from local O*NET and confirmed evidence."""

import re

from GradusIQ_career.features.market_data import get_market_requirements

from .models import CareerSkillNeed, EvidenceState


_NORMALIZE = re.compile(r"[^a-z0-9]+")
MAX_NEEDS = 8


def _key(value: str) -> str:
    return _NORMALIZE.sub(" ", value.lower()).strip()


def derive_career_skill_needs(profile, target_role: str) -> list[CareerSkillNeed]:
    """Return only locally grounded needs absent from confirmed skill evidence.

    Job titles, project prose, intended major, and GAP output are deliberately
    not interpreted as proof that a skill is possessed.
    """
    grounding = get_market_requirements([target_role])
    role = (grounding.get("by_role") or {}).get(target_role) or {}
    if role.get("provenance") not in {"onet", "onet_neighbor"} or not role.get("matched"):
        return []
    confirmed = {
        _key(value)
        for value in [*profile.career.skills.technical, *profile.career.skills.soft]
        if isinstance(value, str) and value.strip()
    }
    threshold = int(grounding.get("must_have_threshold") or 70)
    candidates: list[tuple[int, str, str]] = []
    for category in ("skills", "knowledge", "abilities"):
        for item in (role.get("requirements") or {}).get(category) or []:
            name = item.get("name") if isinstance(item, dict) else None
            importance = item.get("importance") if isinstance(item, dict) else None
            if isinstance(name, str) and isinstance(importance, (int, float)):
                candidates.append((int(importance), category, name))
    for software in role.get("in_demand_software") or []:
        if isinstance(software, str) and software.strip():
            candidates.append((threshold, "technology", software))
    needs: list[CareerSkillNeed] = []
    seen: set[str] = set()
    for importance, category, skill in sorted(candidates, key=lambda item: (-item[0], item[2])):
        key = _key(skill)
        if key in seen or key in confirmed:
            continue
        seen.add(key)
        needs.append(CareerSkillNeed(
            skill=skill,
            category=category,
            target_role=target_role,
            importance="required" if importance >= threshold else "preferred",
            evidence_state=EvidenceState.VERIFIED_LOCAL,
            evidence_source=f"O*NET {role.get('soc_code')} {role.get('provenance')}",
            confidence=min(1.0, importance / 100),
        ))
        if len(needs) >= MAX_NEEDS:
            break
    return needs
