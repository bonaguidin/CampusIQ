"""Career market-intelligence provider for GAP (and, later, FIT/SHIFT).

The GAP prompt expects an O*NET-scored "market requirements" block per target
role so it can distinguish must-have vs. nice-to-have gaps. Per the June spec,
target roles map to SOC codes via a hardcoded map, and the SOC codes key into
importance-scored O*NET requirements.

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


# repo root = .../CampusIQ_career/features/market_data.py -> parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_PATH = _REPO_ROOT / "data" / "reference" / "onet_soc_requirements.json"

# Env override lets the demo/cache runner point at a different data file.
_DATA_PATH = Path(os.getenv("CAMPUSIQ_ONET_DATA", str(_DEFAULT_DATA_PATH)))

# Fallback if the data file omits its own threshold.
_DEFAULT_MUST_HAVE_THRESHOLD = 70

# Hardcoded target-role -> SOC map (2019 taxonomy). Free-text target roles are
# matched by keyword (longest keyword wins) so "Aerospace Engineering Intern",
# "Flight Systems Intern", etc. all resolve. Extend this from the handoff doc's
# full 10-code map.
_KEYWORD_TO_SOC: tuple[tuple[str, str], ...] = (
    ("aerospace", "17-2011.00"),
    ("flight systems", "17-2011.00"),
    ("flight", "17-2011.00"),
    ("mechanical", "17-2141.00"),
    ("industrial", "17-2112.00"),
    ("systems engineer", "17-2011.00"),
    ("data scien", "15-2051.00"),
    ("data analy", "15-2051.00"),
    ("machine learning", "15-2051.00"),
    ("software", "15-1252.00"),
    ("developer", "15-1252.00"),
    ("swe", "15-1252.00"),
    ("systems analyst", "15-1211.00"),
    ("business analyst", "15-1211.00"),
)


def _load_onet() -> Mapping[str, Any]:
    """Load the static O*NET requirements file; return {} on any problem."""
    try:
        with _DATA_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, Mapping) else {}


def resolve_soc(target_role: str) -> str | None:
    """Map one free-text target role to a SOC code via keyword match."""
    if not isinstance(target_role, str):
        return None
    text = target_role.strip().lower()
    if not text:
        return None
    best: tuple[int, str] | None = None
    for keyword, soc in _KEYWORD_TO_SOC:
        if keyword in text:
            if best is None or len(keyword) > best[0]:
                best = (len(keyword), soc)
    return best[1] if best else None


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
            notes.append(f"Role '{role}' did not map to any SOC code; add a keyword to the SOC map.")
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
