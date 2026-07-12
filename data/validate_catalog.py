#!/usr/bin/env python3
"""
Validates the reorganized college-folder catalog structure.
Reports: JSON validity, course counts, level breakdowns, satisfies_ucc counts,
and coverage of every course code referenced by the 5 student data files.
"""

import json
import os
import re
import sys
from collections import defaultdict

BASE = "/Users/deepakmurali/Projects/CareerOS/data/catalog"
REQUIRED_KEYS = {"code", "title", "credit_hours", "description", "prerequisites", "department"}

# Course codes referenced in student mock data
STUDENT_COURSES = {
    "ACCT 229": "jordanReyes",
    "AERO 211": "priyaNair",
    "AERO 221": "priyaNair",
    "BIOL 213": "sofiaRamirez",
    "BUSN 101": "jordanReyes",
    "CHEM 119": "ethanBrooks",
    "CHEM 227": "sofiaRamirez",
    "ENGL 104": "jordanReyes",
    "ENGR 102": "ethanBrooks",
    "ENGR 111": "ethanBrooks",   # does not exist in catalog — mock invented it
    "HIST 105": "priyaNair/sofiaRamirez",
    "KINE 199": "ethanBrooks",
    "MATH 142": "jordanReyes",
    "MATH 151": "ethanBrooks",
    "MATH 251": "priyaNair",
    "PBSI 107": "background",
    "PBSI 209": "marcusWebb",    # does not exist — fabricated code
    "PBSI 211": "marcusWebb",    # does not exist — closest is PBSI 208
    "PHYS 201": "sofiaRamirez",
    "PHYS 206": "background",
    "POLS 206": "jordanReyes/marcusWebb",
    "STAT 201": "marcusWebb",
}

KNOWN_MOCK_ONLY = {"ENGR 111", "PBSI 209", "PBSI 211"}

def level_bucket(code):
    m = re.search(r'\d+', code)
    if not m: return "???"
    n = int(m.group())
    return f"{(n // 100) * 100}s"

errors = []
all_courses = {}
file_stats = []

for root, dirs, files in os.walk(BASE):
    dirs.sort()
    for fname in sorted(files):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(root, fname)
        rel = os.path.relpath(path, BASE)

        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            errors.append(f"INVALID JSON {rel}: {e}")
            continue

        if not isinstance(data, list):
            errors.append(f"NOT A LIST: {rel}")
            continue

        bad_keys = sum(1 for c in data if isinstance(c, dict) and REQUIRED_KEYS - set(c.keys()))
        if bad_keys:
            errors.append(f"{rel}: {bad_keys} records missing required keys")

        buckets = defaultdict(int)
        ucc_count = 0
        for c in data:
            code = c.get("code", "")
            if code:
                all_courses[code] = c
                buckets[level_bucket(code)] += 1
            if "satisfies_ucc" in c:
                ucc_count += 1

        bd = "  ".join(f"{k}:{v}" for k, v in sorted(buckets.items()))
        file_stats.append((rel, len(data), ucc_count, bd))

# ── File table ───────────────────────────────────────────────────────────────
print(f"\n{'File':<58} {'N':>5}  {'UCC↑':>5}  Level breakdown")
print("-" * 115)
total = 0
for rel, n, ucc, bd in file_stats:
    print(f"  {rel:<56} {n:>5}  {ucc:>5}  {bd}")
    total += n
print("-" * 115)
print(f"  {'TOTAL':<56} {total:>5}")

# ── Student course coverage ──────────────────────────────────────────────────
print("\n── Student data course coverage ──")
found_count = 0
for code in sorted(STUDENT_COURSES):
    student = STUDENT_COURSES[code]
    if code in all_courses:
        c = all_courses[code]
        ucc = f"  [→ UCC: {c['satisfies_ucc']!r}]" if "satisfies_ucc" in c else ""
        print(f"  ✓ {code:<14} {c['title'][:55]:<55}{ucc}")
        found_count += 1
    elif code in KNOWN_MOCK_ONLY:
        print(f"  ~ {code:<14} mock-only code — not in TAMU catalog  ({student})")
    else:
        print(f"  ✗ {code:<14} MISSING  ({student})")
        errors.append(f"Missing catalog entry: {code}")

# ── Mandatory 5 checks ───────────────────────────────────────────────────────
print("\n── Five mandatory exact-code checks ──")
for code in ["MATH 251", "CHEM 227", "PHYS 206", "ENGR 102", "ENGR 111"]:
    if code in all_courses:
        c = all_courses[code]
        print(f"  ✓ {code} — {c['title']} ({c['credit_hours']} cr)")
    elif code in KNOWN_MOCK_ONLY:
        print(f"  ~ {code} — mock-only code (not a real TAMU course number)")
    else:
        print(f"  ✗ {code} — NOT FOUND")
        errors.append(f"MISSING MANDATORY: {code}")

# ── Final ────────────────────────────────────────────────────────────────────
print()
real_errors = [e for e in errors if "mock-only" not in e.lower()]
if real_errors:
    print(f"RESULT: FAILED ({len(real_errors)} real error(s)):")
    for e in real_errors:
        print(f"  {e}")
    sys.exit(1)
else:
    print("RESULT: Catalog structure valid. 3 mock-only codes noted above are fabrications")
    print("        in student data files (not catalog errors) — see ~ lines above.")
