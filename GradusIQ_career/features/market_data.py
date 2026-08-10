"""Career market-intelligence provider for GAP (and, later, FIT/SHIFT).

The GAP prompt expects an O*NET-scored "market requirements" block per target
role so it can distinguish must-have vs. nice-to-have gaps. Target roles map
to SOC codes via the curated lookup in ``data/role_requirements.json`` (exact
role-string match, no guessing), and the SOC codes key into importance-scored
O*NET requirements.

For the demo this reads a STATIC data file housed in the repo
(``data/reference/onet_soc_requirements.json``). Live O*NET API + DFW job
postings (Adzuna/JSearch) are a deliberate Phase-2 follow-up; this module is
the single seam where that live fetch will later slot in behind
``get_market_requirements`` without touching the runners.

This module is dependency-free (stdlib only) and never raises into the runner:
if the data file is missing or a role can't be mapped, it returns a structured
block with a note so GAP still runs (just less grounded).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence


# repo root = .../GradusIQ_career/features/market_data.py -> parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_PATH = _REPO_ROOT / "data" / "reference" / "onet_soc_requirements.json"

# Env override lets the demo/cache runner point at a different data file.
_DATA_PATH = Path(os.getenv("GRADUSIQ_ONET_DATA", str(_DEFAULT_DATA_PATH)))

# Fallback if the data file omits its own threshold.
_DEFAULT_MUST_HAVE_THRESHOLD = 70

# Curated role -> SOC lookup, shared with role_requirements_for() in gap.py.
# Each of the 14 demo target roles has a hand-assigned, correct SOC code here.
# Loaded independently (not imported from gap.py) to keep this module
# dependency-free of the runners.
_ROLE_REQUIREMENTS_PATH = _REPO_ROOT / "data" / "role_requirements.json"

_role_soc_cache: Mapping[str, str] | None = None


def _load_role_soc_map() -> Mapping[str, str]:
    """Load {target_role: soc_code} from the curated role_requirements.json.

    Cached at module scope (not functools.lru_cache — a plain dict swap is
    enough here and keeps this testable via monkeypatching _DATA_PATH-style
    globals without cache-clearing gymnastics).
    """
    global _role_soc_cache
    if _role_soc_cache is not None:
        return _role_soc_cache
    try:
        with _ROLE_REQUIREMENTS_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        _role_soc_cache = {}
        return _role_soc_cache
    if not isinstance(data, Mapping):
        _role_soc_cache = {}
        return _role_soc_cache
    _role_soc_cache = {
        role: entry["soc_code"]
        for role, entry in data.items()
        if not role.startswith("_")
        and isinstance(entry, Mapping)
        and isinstance(entry.get("soc_code"), str)
        and entry["soc_code"]
    }
    return _role_soc_cache


def _load_onet() -> Mapping[str, Any]:
    """Load the static O*NET requirements file; return {} on any problem."""
    try:
        with _DATA_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, Mapping) else {}


def resolve_soc(target_role: str) -> str | None:
    """Look up one target role's curated SOC code from role_requirements.json.

    This used to keyword-match target-role text against a hardcoded SOC map,
    which could produce confidently wrong matches (e.g. "Business Analyst
    Intern" resolving to 15-1211.00 Computer Systems Analysts instead of the
    correct 13-1111.00 Management Analysts) and covered fewer roles than the
    hand-curated lookup already maintained in role_requirements.json. Exact
    match only, by design — an unrecognized role returns None rather than a
    guessed code.
    """
    if not isinstance(target_role, str):
        return None
    return _load_role_soc_map().get(target_role)


def get_market_requirements(target_roles: Sequence[str] | None) -> dict[str, Any]:
    """Build the market-requirements block injected into the GAP context.

    Shape (stable — export/cache can rely on it):
        {
          "source": "onet_static" | "none",
          "must_have_threshold": int,        # importance >= this => must-have
          "by_role": {                       # one entry per target role
             "<role text>": {
                 "soc_code": "17-2011.00" | None,
                 "soc_title": str | None,
                 "job_zone": int | None,
                 "requirements": {"skills": [...], "knowledge": [...], "abilities": [...]},
                 "matched": bool,
             }, ...
          },
          "dfw_postings": None,              # Phase 2: live Adzuna/JSearch
          "notes": [str, ...],
        }
    """
    roles = [r for r in (target_roles or []) if isinstance(r, str) and r.strip()]
    onet = _load_onet()
    catalog = onet.get("roles", {}) if isinstance(onet, Mapping) else {}
    threshold = int(onet.get("must_have_threshold", _DEFAULT_MUST_HAVE_THRESHOLD)) \
        if isinstance(onet, Mapping) else _DEFAULT_MUST_HAVE_THRESHOLD

    notes: list[str] = []
    if not catalog:
        notes.append(
            "O*NET requirements file unavailable or empty; GAP is running "
            "without market grounding. Populate data/reference/onet_soc_requirements.json."
        )
    if onet.get("_placeholder"):
        notes.append(
            "O*NET values are PLACEHOLDER. Replace with real importance scores "
            "from the June handoff doc before treating gap severity as authoritative."
        )

    by_role: dict[str, Any] = {}
    for role in roles:
        soc = resolve_soc(role)
        entry = catalog.get(soc, {}) if soc else {}
        matched = bool(soc and entry)
        if soc and not entry:
            notes.append(f"Role '{role}' mapped to SOC {soc} but no O*NET entry exists for it.")
        elif not soc:
            notes.append(
                f"Role '{role}' has no curated SOC code in role_requirements.json; "
                "add one there to enable O*NET grounding for it."
            )
        by_role[role] = {
            "soc_code": soc,
            "soc_title": entry.get("title") if isinstance(entry, Mapping) else None,
            "job_zone": entry.get("job_zone") if isinstance(entry, Mapping) else None,
            "requirements": {
                "skills": entry.get("skills", []) if isinstance(entry, Mapping) else [],
                "knowledge": entry.get("knowledge", []) if isinstance(entry, Mapping) else [],
                "abilities": entry.get("abilities", []) if isinstance(entry, Mapping) else [],
            },
            "matched": matched,
        }

    return {
        "source": "onet_static" if catalog else "none",
        "must_have_threshold": threshold,
        "by_role": by_role,
        "dfw_postings": None,
        "notes": notes,
    }
