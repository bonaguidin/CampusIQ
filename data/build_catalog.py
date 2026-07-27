#!/usr/bin/env python3
"""
Step 4: Reorganize catalog into college subfolders.

- Merges new department scrapes with existing department files
- Deduplicates: if a course code appears in both a full dept scrape AND ucc.json,
  the full dept record wins and gains a satisfies_ucc field
- Writes files into college subfolders
- Does NOT touch student JSON files
"""

import json
import os
import re
import pickle
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG_DIR = PROJECT_ROOT / "data" / "catalog"
BASE = CATALOG_DIR

# ── Load UCC dedup mapping: code -> list of area names ──────────────────────
with open(f"{BASE}/ucc.json") as f:
    ucc_raw = json.load(f)

ucc_map = {}  # course_code -> UCC area name(s)
for area_name, courses in ucc_raw["by_area"].items():
    for c in courses:
        code = c["code"].strip()
        # Some codes have slashes like "AFST 327/MUSC 327"
        # Index each individual code
        for part in re.split(r'[/,]', code):
            part = part.strip()
            if re.match(r'^[A-Z]+\s+\d+', part):
                ucc_map.setdefault(part, []).append(area_name)

print(f"UCC map: {len(ucc_map)} unique course codes indexed")

# ── Load new scrapes ─────────────────────────────────────────────────────────
with open("/tmp/new_dept_scrapes.pkl", "rb") as f:
    new_scrapes = pickle.load(f)   # dict: prefix -> list of course dicts

# ── Helper: apply satisfies_ucc and dedupe a course list ────────────────────
def enrich_and_dedupe(courses):
    """Dedupe by course code (keep first seen), add satisfies_ucc where applicable."""
    seen = {}
    for c in courses:
        code = c["code"]
        if code in seen:
            continue
        if code in ucc_map:
            c = dict(c)
            areas = ucc_map[code]
            c["satisfies_ucc"] = areas[0] if len(areas) == 1 else areas
        seen[code] = c
    return list(seen.values())

# ── Define output layout ─────────────────────────────────────────────────────
# Each entry: (output_path, list_of_course_lists_to_merge)
# course lists are loaded from existing files or new scrapes

def load_existing(fname):
    path = f"{BASE}/{fname}"
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)

LAYOUT = [
    # Arts and Sciences
    (f"{BASE}/arts_and_sciences/mathematics.json",
     [new_scrapes["MATH"]]),
    (f"{BASE}/arts_and_sciences/chemistry.json",
     [new_scrapes["CHEM"]]),
    (f"{BASE}/arts_and_sciences/physics.json",
     [new_scrapes["PHYS"]]),
    (f"{BASE}/arts_and_sciences/english.json",
     [new_scrapes["ENGL"]]),
    (f"{BASE}/arts_and_sciences/history.json",
     [new_scrapes["HIST"]]),
    (f"{BASE}/arts_and_sciences/statistics.json",
     [new_scrapes["STAT"]]),
    (f"{BASE}/arts_and_sciences/biology.json",
     [load_existing("biology.json")]),
    (f"{BASE}/arts_and_sciences/psychology.json",
     [load_existing("psychology.json")]),

    # Engineering
    (f"{BASE}/engineering/general_engineering.json",
     [new_scrapes["ENGR"]]),
    (f"{BASE}/engineering/aerospace_engineering.json",
     [load_existing("aerospace_engineering.json")]),
    (f"{BASE}/engineering/computer_engineering.json",
     [load_existing("computer_engineering.json")]),

    # Business
    (f"{BASE}/business/business.json",
     [load_existing("business.json")]),

    # Government & Public Service
    (f"{BASE}/government_public_service/political_science.json",
     [new_scrapes["POLS"]]),

    # Education & Human Development
    (f"{BASE}/education_human_development/kinesiology.json",
     [new_scrapes["KINE"]]),
]

total_written = 0
for out_path, source_lists in LAYOUT:
    merged = []
    for lst in source_lists:
        merged.extend(lst)
    final = enrich_and_dedupe(merged)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(final, f, indent=2, ensure_ascii=False)
    fname = os.path.relpath(out_path, BASE)
    ucc_enriched = sum(1 for c in final if "satisfies_ucc" in c)
    print(f"  {fname:<55} {len(final):>4} courses  ({ucc_enriched} satisfies_ucc)")
    total_written += len(final)

print(f"\nTotal courses written: {total_written}")

# ── Remove old flat files (now superseded by college subfolders) ─────────────
OLD_FILES = [
    "business.json",
    "aerospace_engineering.json",
    "computer_engineering.json",
    "psychology.json",
    "biology.json",
    "ucc.json",
]
print("\nRemoving superseded root-level files:")
for fname in OLD_FILES:
    path = f"{BASE}/{fname}"
    if os.path.exists(path):
        os.remove(path)
        print(f"  deleted {fname}")

print("\nDone.")
