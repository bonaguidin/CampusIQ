#!/usr/bin/env python3
"""Add source traceability fields to existing TAMU catalog JSON files.

Dry-run is the default. Use --write to update files, and --force to overwrite
existing source_url, catalog_year, or source_last_checked values.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any


CATALOG_ROOT = Path(__file__).resolve().parent
EXCLUDED_DIRS = {"reference", "students"}
CATALOG_YEAR = "2026-2027"
SOURCE_LAST_CHECKED = "2026-06-20"
SOURCE_URL_BASE = "https://catalog.tamu.edu/undergraduate/course-descriptions/"
SOURCE_FIELDS = ["source_url", "catalog_year", "source_last_checked"]
KNOWN_PREFIXES = {
    "ACCT",
    "AERO",
    "BIOL",
    "BUSN",
    "CHEM",
    "ECEN",
    "ENGL",
    "ENGR",
    "FINC",
    "HIST",
    "ISTM",
    "KINE",
    "MATH",
    "MGMT",
    "MKTG",
    "PBSI",
    "PHYS",
    "POLS",
    "SCMT",
    "STAT",
}
FIELD_ORDER = [
    "code",
    "title",
    "credit_hours",
    "description",
    "prerequisites",
    "department",
    "satisfies_ucc",
    "prefix",
    "number",
    "course_level",
    "credit_min",
    "credit_max",
    "is_variable_credit",
    "ucc_attributes",
    "tccns",
    "cross_listings",
    "repeatability",
    "campuses",
    "prerequisite_courses",
    "restrictions",
    "source_url",
    "catalog_year",
    "source_last_checked",
]


def iter_catalog_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*.json"):
        if EXCLUDED_DIRS.intersection(path.relative_to(root).parts):
            continue
        files.append(path)
    return sorted(files)


def load_courses(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError(f"{path} is not a top-level JSON array")
    for index, course in enumerate(data):
        if not isinstance(course, dict):
            raise ValueError(f"{path}[{index}] is not a JSON object")
    return data


def infer_prefix(course: dict[str, Any]) -> str | None:
    prefix = course.get("prefix")
    if isinstance(prefix, str) and prefix.strip():
        return prefix.strip().upper()

    code = course.get("code")
    if isinstance(code, str) and code.strip():
        return code.strip().split()[0].upper()

    return None


def source_url_for_prefix(prefix: str | None) -> str | None:
    if not prefix or prefix not in KNOWN_PREFIXES:
        return None
    return f"{SOURCE_URL_BASE}{prefix.lower()}/"


def ordered_course(course: dict[str, Any]) -> dict[str, Any]:
    ordered: dict[str, Any] = {}
    for key in FIELD_ORDER:
        if key in course:
            ordered[key] = course[key]
    for key in sorted(course):
        if key not in ordered:
            ordered[key] = course[key]
    return ordered


def enrich_course(course: dict[str, Any], force: bool) -> tuple[dict[str, Any], list[str], list[str]]:
    enriched = deepcopy(course)
    prefix = infer_prefix(course)
    source_url = source_url_for_prefix(prefix)
    changed_fields: list[str] = []
    warnings: list[str] = []

    if source_url is None:
        warnings.append(f"missing source_url mapping for prefix {prefix!r} on {course.get('code')!r}")
    elif force or "source_url" not in enriched:
        if enriched.get("source_url") != source_url:
            enriched["source_url"] = source_url
            changed_fields.append("source_url")
    elif enriched.get("source_url") != source_url:
        warnings.append(
            f"existing source_url differs for {course.get('code')!r}; use --force to overwrite"
        )

    if force or "catalog_year" not in enriched:
        if enriched.get("catalog_year") != CATALOG_YEAR:
            enriched["catalog_year"] = CATALOG_YEAR
            changed_fields.append("catalog_year")
    elif enriched.get("catalog_year") != CATALOG_YEAR:
        warnings.append(
            f"existing catalog_year differs for {course.get('code')!r}; use --force to overwrite"
        )

    if force or "source_last_checked" not in enriched:
        if enriched.get("source_last_checked") != SOURCE_LAST_CHECKED:
            enriched["source_last_checked"] = SOURCE_LAST_CHECKED
            changed_fields.append("source_last_checked")

    return ordered_course(enriched), changed_fields, warnings


def missing_counts(courses: list[dict[str, Any]]) -> dict[str, int]:
    return {
        field: sum(1 for course in courses if field not in course or course.get(field) in (None, ""))
        for field in SOURCE_FIELDS
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write source fields back to catalog JSON files")
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing source_url, catalog_year, and source_last_checked values",
    )
    args = parser.parse_args()

    files = iter_catalog_files(CATALOG_ROOT)
    total_courses = 0
    files_with_changes = 0
    field_counts: Counter[str] = Counter()
    prefix_counts: Counter[str] = Counter()
    mapping_counts: Counter[str] = Counter()
    warnings: list[str] = []
    missing_after: Counter[str] = Counter()
    prefixes_by_file: dict[str, set[str]] = defaultdict(set)

    for path in files:
        courses = load_courses(path)
        total_courses += len(courses)
        normalized_courses: list[dict[str, Any]] = []
        file_changed = False

        for course in courses:
            prefix = infer_prefix(course)
            if prefix:
                prefix_counts[prefix] += 1
                prefixes_by_file[str(path.relative_to(CATALOG_ROOT))].add(prefix)
                source_url = source_url_for_prefix(prefix)
                if source_url:
                    mapping_counts[source_url] += 1

            enriched, changed_fields, course_warnings = enrich_course(course, args.force)
            normalized_courses.append(enriched)
            if changed_fields:
                file_changed = True
                field_counts.update(changed_fields)
            warnings.extend(f"{path.relative_to(CATALOG_ROOT)}: {warning}" for warning in course_warnings)

        missing_after.update(missing_counts(normalized_courses))

        if file_changed:
            files_with_changes += 1
            if args.write:
                with path.open("w", encoding="utf-8") as handle:
                    json.dump(normalized_courses, handle, indent=2, ensure_ascii=False)
                    handle.write("\n")

    mode = "write" if args.write else "dry-run"
    print(f"Mode: {mode}")
    print(f"Force: {args.force}")
    print(f"Total files scanned: {len(files)}")
    print(f"Total courses scanned: {total_courses}")
    print(f"Files with changes: {files_with_changes}")
    print(f"Catalog year: {CATALOG_YEAR}")
    print(f"Source last checked: {SOURCE_LAST_CHECKED}")
    print(f"Unique prefixes found: {', '.join(sorted(prefix_counts))}")
    print("Prefixes by file:")
    for file_name in sorted(prefixes_by_file):
        print(f"  {file_name}: {', '.join(sorted(prefixes_by_file[file_name]))}")
    print("Fields added or updated:")
    for field in SOURCE_FIELDS:
        print(f"  {field}: {field_counts.get(field, 0)}")
    print("Source URL mappings applied:")
    for source_url, count in sorted(mapping_counts.items()):
        print(f"  {source_url}: {count}")
    print(f"Courses missing source_url after enrichment: {missing_after['source_url']}")
    print(f"Courses missing catalog_year after enrichment: {missing_after['catalog_year']}")
    print(f"Courses missing source_last_checked after enrichment: {missing_after['source_last_checked']}")
    print(f"Warnings requiring manual confirmation: {len(warnings)}")
    for warning in warnings[:50]:
        print(f"  {warning}")
    if len(warnings) > 50:
        print(f"  ... {len(warnings) - 50} more")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
