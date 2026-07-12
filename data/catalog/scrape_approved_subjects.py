#!/usr/bin/env python3
"""Scrape only the approved TAMU subject catalog pages.

Dry-run is the default. Use --write to create the five approved JSON files.
Use --force only if an approved target file already exists and should be
overwritten.
"""

from __future__ import annotations

import argparse
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

from normalize_catalog import derive_fields


CATALOG_ROOT = Path(__file__).resolve().parent
REPO_ROOT = CATALOG_ROOT.parents[1]
REPORT_PATH = REPO_ROOT / "data" / "reference" / "catalog_expansion_audit.md"
CATALOG_YEAR = "2026-2027"
SOURCE_LAST_CHECKED = "2026-06-20"
APPROVED_SUBJECTS = {
    "CSCE": {
        "department": "Computer Science and Engineering",
        "source_url": "https://catalog.tamu.edu/undergraduate/course-descriptions/csce/",
        "target_path": CATALOG_ROOT / "engineering" / "computer_science_engineering.json",
    },
    "ECON": {
        "department": "Economics",
        "source_url": "https://catalog.tamu.edu/undergraduate/course-descriptions/econ/",
        "target_path": CATALOG_ROOT / "business" / "economics.json",
    },
    "MEEN": {
        "department": "Mechanical Engineering",
        "source_url": "https://catalog.tamu.edu/undergraduate/course-descriptions/meen/",
        "target_path": CATALOG_ROOT / "engineering" / "mechanical_engineering.json",
    },
    "ISEN": {
        "department": "Industrial and Systems Engineering",
        "source_url": "https://catalog.tamu.edu/undergraduate/course-descriptions/isen/",
        "target_path": CATALOG_ROOT / "engineering" / "industrial_systems_engineering.json",
    },
    "BMEN": {
        "department": "Biomedical Engineering",
        "source_url": "https://catalog.tamu.edu/undergraduate/course-descriptions/bmen/",
        "target_path": CATALOG_ROOT / "engineering" / "biomedical_engineering.json",
    },
}
FIELD_ORDER = [
    "code",
    "title",
    "credit_hours",
    "description",
    "prerequisites",
    "department",
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
HEADING_RE = re.compile(
    r"^((?:[A-Z]{2,6}\s+[0-9]{3}[A-Z]?)(?:/[A-Z]{2,6}\s+[0-9]{3}[A-Z]?)*)\s+(.+)$"
)
COURSE_CODE_RE = re.compile(r"([A-Z]{2,6})\s+([0-9]{3}[A-Z]?)")
CREDITS_RE = re.compile(r"^Credits?\s+([0-9.]+)(?:\s+to\s+([0-9.]+))?\.\s*", re.IGNORECASE)
HOURS_RE = re.compile(
    r"^(?:[0-9.]+(?:\s+to\s+[0-9.]+)?\s+(?:Lecture|Lab|Other|Seminar|Studio)\s+Hours?\.\s*)+",
    re.IGNORECASE,
)
DETAIL_MARKER_RE = re.compile(r"\b(Prerequisites?|Corequisites?|Cross Listing):", re.IGNORECASE)


@dataclass
class ScrapeResult:
    prefix: str
    courses: list[dict[str, Any]]
    warnings: list[str]


def clean_text(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def parse_credit_hours(text: str) -> tuple[int | float | str | None, str]:
    match = CREDITS_RE.match(text)
    if not match:
        return None, text
    first = parse_number(match.group(1))
    second = parse_number(match.group(2)) if match.group(2) else None
    credit_hours: int | float | str
    if second is None:
        credit_hours = first
    else:
        credit_hours = f"{first}-{second}"
    return credit_hours, text[match.end() :].strip()


def parse_number(value: str | None) -> int | float:
    if value is None:
        raise ValueError("missing numeric value")
    parsed = float(value)
    return int(parsed) if parsed.is_integer() else parsed


def strip_hours(text: str) -> str:
    previous = None
    current = text
    while previous != current:
        previous = current
        current = HOURS_RE.sub("", current).strip()
    return current


def split_description_and_prerequisites(text: str) -> tuple[str, str | None]:
    match = DETAIL_MARKER_RE.search(text)
    if not match:
        return text.strip(), None
    description = text[: match.start()].strip()
    prerequisites = text[match.start() :].strip()
    return description, prerequisites or None


def parse_heading(text: str, expected_prefix: str) -> tuple[str | None, str | None, str | None]:
    match = HEADING_RE.match(clean_text(text))
    if not match:
        return None, None, None
    code_matches = COURSE_CODE_RE.findall(match.group(1))
    if not code_matches:
        return None, None, None
    prefix, number = code_matches[0]
    if prefix != expected_prefix:
        return None, None, None
    return f"{prefix} {number}", match.group(2).strip(), match.group(1)


def ordered_course(course: dict[str, Any]) -> dict[str, Any]:
    ordered: dict[str, Any] = {}
    for key in FIELD_ORDER:
        if key in course:
            ordered[key] = course[key]
    for key in sorted(course):
        if key not in ordered:
            ordered[key] = course[key]
    return ordered


def normalize_scraped_course(course: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    normalized = deepcopy(course)
    warnings: list[str] = []
    derived = derive_fields(course)
    for key, value in derived.items():
        normalized[key] = value
    if normalized["prefix"] is None or normalized["number"] is None:
        warnings.append(f"unparseable code: {course.get('code')!r}")
    if normalized["credit_min"] is None or normalized["credit_max"] is None:
        warnings.append(f"unparseable credit_hours for {course.get('code')!r}: {course.get('credit_hours')!r}")
    normalized["source_url"] = course["source_url"]
    normalized["catalog_year"] = CATALOG_YEAR
    normalized["source_last_checked"] = SOURCE_LAST_CHECKED
    return ordered_course(normalized), warnings


def scrape_subject(prefix: str, config: dict[str, Any]) -> ScrapeResult:
    response = requests.get(config["source_url"], timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    content = soup.find("main") or soup
    courses: list[dict[str, Any]] = []
    warnings: list[str] = []

    for heading in content.find_all("h2"):
        heading_text = clean_text(heading.get_text(" ", strip=True))
        code, title, _display_codes = parse_heading(heading_text, prefix)
        if not code or not title:
            continue
        paragraph = heading.find_next_sibling("p")
        if paragraph is None:
            warnings.append(f"{prefix}: missing details paragraph for {heading_text!r}")
            continue

        detail_text = clean_text(paragraph.get_text(" ", strip=True))
        credit_hours, remaining = parse_credit_hours(detail_text)
        if credit_hours is None:
            warnings.append(f"{code}: missing parseable credit hours")
            continue
        remaining = strip_hours(remaining)
        description, prerequisites = split_description_and_prerequisites(remaining)
        if not description:
            warnings.append(f"{code}: missing description after parsing")

        course = {
            "code": code,
            "title": title,
            "credit_hours": credit_hours,
            "description": description,
            "prerequisites": prerequisites,
            "department": config["department"],
            "source_url": config["source_url"],
        }
        normalized_course, course_warnings = normalize_scraped_course(course)
        courses.append(normalized_course)
        warnings.extend(course_warnings)

    return ScrapeResult(prefix=prefix, courses=courses, warnings=warnings)


def duplicate_codes(courses: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for course in courses:
        code = course.get("code")
        if not isinstance(code, str):
            continue
        if code in seen:
            duplicates.add(code)
        seen.add(code)
    return sorted(duplicates)


def write_json(path: Path, courses: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(courses, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def update_audit_report(results: dict[str, ScrapeResult], validation_status: str) -> None:
    if REPORT_PATH.exists():
        existing = REPORT_PATH.read_text(encoding="utf-8")
        existing = existing.split("\n## Approved Expansion Batch 1\n", 1)[0].rstrip()
    else:
        existing = "# TAMU Catalog Expansion Audit\n"

    rows = [
        "| Prefix | Subject | Date scraped | Course count | Source URL | Validation status |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for prefix in APPROVED_SUBJECTS:
        config = APPROVED_SUBJECTS[prefix]
        result = results[prefix]
        rows.append(
            f"| {prefix} | {config['department']} | {SOURCE_LAST_CHECKED} | {len(result.courses)} | {config['source_url']} | {validation_status} |"
        )

    section = "\n\n## Approved Expansion Batch 1\n\n" + "\n".join(rows) + "\n"
    REPORT_PATH.write_text(existing + section, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the five approved subject JSON files")
    parser.add_argument("--force", action="store_true", help="overwrite an existing approved target file")
    parser.add_argument(
        "--update-report",
        action="store_true",
        help="update data/reference/catalog_expansion_audit.md with batch results",
    )
    parser.add_argument(
        "--validation-status",
        default=None,
        help="validation status text to use when updating the audit report",
    )
    args = parser.parse_args()

    results: dict[str, ScrapeResult] = {}
    all_warnings: list[str] = []
    blocked_targets: list[Path] = []

    for prefix, config in APPROVED_SUBJECTS.items():
        result = scrape_subject(prefix, config)
        results[prefix] = result
        all_warnings.extend(result.warnings)
        duplicates = duplicate_codes(result.courses)
        all_warnings.extend(f"{prefix}: duplicate parsed code {code}" for code in duplicates)

        target_path = config["target_path"]
        if target_path.exists() and not args.force:
            blocked_targets.append(target_path)

    if args.write and blocked_targets:
        all_warnings.extend(
            f"target exists and would not be overwritten without --force: {path.relative_to(REPO_ROOT)}"
            for path in blocked_targets
        )
    elif args.write:
        for prefix, config in APPROVED_SUBJECTS.items():
            write_json(config["target_path"], results[prefix].courses)

    if args.update_report:
        validation_status = args.validation_status or ("pending validator run" if not args.write else "pending external validator run")
        update_audit_report(results, validation_status)

    print(f"Mode: {'write' if args.write else 'dry-run'}")
    print(f"Force: {args.force}")
    print(f"Subjects scraped: {', '.join(APPROVED_SUBJECTS)}")
    total_courses = sum(len(result.courses) for result in results.values())
    print("Courses scraped per subject:")
    for prefix in APPROVED_SUBJECTS:
        print(f"  {prefix}: {len(results[prefix].courses)}")
    print(f"Total new courses parsed: {total_courses}")
    print("Target files:")
    for prefix, config in APPROVED_SUBJECTS.items():
        action = "created/updated" if args.write and not blocked_targets else "would create"
        if config["target_path"].exists() and not args.force and not args.write:
            action = "would require --force to overwrite"
        print(f"  {prefix}: {config['target_path'].relative_to(REPO_ROOT)} ({action})")
    print(f"Warnings: {len(all_warnings)}")
    for warning in all_warnings[:50]:
        print(f"  {warning}")
    if len(all_warnings) > 50:
        print(f"  ... {len(all_warnings) - 50} more")

    return 1 if args.write and blocked_targets else 0


if __name__ == "__main__":
    raise SystemExit(main())
