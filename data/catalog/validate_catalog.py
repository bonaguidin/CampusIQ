#!/usr/bin/env python3
"""Validate TAMU catalog JSON files after normalization."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any


CATALOG_ROOT = Path(__file__).resolve().parent
EXCLUDED_DIRS = {"reference", "students"}
BASE_REQUIRED_FIELDS = [
    "code",
    "title",
    "credit_hours",
    "description",
    "prerequisites",
    "department",
]
NORMALIZED_REQUIRED_FIELDS = [
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
]
SOURCE_REQUIRED_FIELDS = [
    "source_url",
    "catalog_year",
    "source_last_checked",
]
ARRAY_FIELDS = [
    "ucc_attributes",
    "tccns",
    "cross_listings",
    "campuses",
    "prerequisite_courses",
    "restrictions",
]
CODE_RE = re.compile(r"^\s*([A-Z]{2,5})\s+([0-9]{3}[A-Z]?)\s*$")
SOURCE_URL_PREFIX = "https://catalog.tamu.edu/undergraduate/course-descriptions/"
CATALOG_YEAR_PENDING = "PENDING_CONFIRMATION"


def iter_catalog_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*.json"):
        if EXCLUDED_DIRS.intersection(path.relative_to(root).parts):
            continue
        files.append(path)
    return sorted(files)


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def load_courses(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError(f"{path} is not a top-level JSON array")
    return data


def validate_course(course: Any, label: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(course, dict):
        return [f"{label}: course is not an object"]

    for field in BASE_REQUIRED_FIELDS + NORMALIZED_REQUIRED_FIELDS + SOURCE_REQUIRED_FIELDS:
        if field not in course:
            errors.append(f"{label}: missing {field}")

    code = course.get("code")
    code_match = CODE_RE.match(code) if isinstance(code, str) else None
    if not code_match:
        errors.append(f"{label}: code is not parseable: {code!r}")
    else:
        if course.get("prefix") != code_match.group(1):
            errors.append(f"{label}: prefix does not match code")
        if course.get("number") != code_match.group(2):
            errors.append(f"{label}: number does not match code")

    title = course.get("title")
    if not isinstance(title, str) or not title.strip():
        errors.append(f"{label}: title is empty")

    description = course.get("description")
    if not isinstance(description, str) or not description.strip():
        errors.append(f"{label}: description is empty")

    credit_min = course.get("credit_min")
    credit_max = course.get("credit_max")
    if not is_number(credit_min):
        errors.append(f"{label}: credit_min is not a valid number")
    if not is_number(credit_max):
        errors.append(f"{label}: credit_max is not a valid number")
    if is_number(credit_min) and is_number(credit_max) and credit_min > credit_max:
        errors.append(f"{label}: credit_min is greater than credit_max")

    if "is_variable_credit" in course and not isinstance(course.get("is_variable_credit"), bool):
        errors.append(f"{label}: is_variable_credit is not boolean")

    for field in ARRAY_FIELDS:
        if field in course and not isinstance(course.get(field), list):
            errors.append(f"{label}: {field} is not an array")

    if "repeatability" in course and course.get("repeatability") is not None and not isinstance(course.get("repeatability"), str):
        errors.append(f"{label}: repeatability is not a string or null")

    source_url = course.get("source_url")
    if "source_url" in course:
        if not isinstance(source_url, str) or not source_url.startswith(SOURCE_URL_PREFIX):
            errors.append(f"{label}: source_url is not an official TAMU course-description URL")

    catalog_year = course.get("catalog_year")
    if "catalog_year" in course:
        if catalog_year == CATALOG_YEAR_PENDING:
            pass
        elif not isinstance(catalog_year, str) or not catalog_year.strip():
            errors.append(f"{label}: catalog_year is empty")

    source_last_checked = course.get("source_last_checked")
    if "source_last_checked" in course:
        if not isinstance(source_last_checked, str):
            errors.append(f"{label}: source_last_checked is not a YYYY-MM-DD string")
        else:
            try:
                date.fromisoformat(source_last_checked)
            except ValueError:
                errors.append(f"{label}: source_last_checked is not valid YYYY-MM-DD")

    return errors


def main() -> int:
    files = iter_catalog_files(CATALOG_ROOT)
    errors: list[str] = []
    total_courses = 0

    for path in files:
        try:
            courses = load_courses(path)
        except ValueError as exc:
            errors.append(str(exc))
            continue

        if not isinstance(courses, list):
            errors.append(f"{path.relative_to(CATALOG_ROOT)}: top-level value is not an array")
            continue

        total_courses += len(courses)
        counts = Counter(course.get("code") for course in courses if isinstance(course, dict) and course.get("code"))
        for code, count in sorted(counts.items()):
            if count > 1:
                errors.append(f"{path.relative_to(CATALOG_ROOT)}: duplicate course code {code}")

        for index, course in enumerate(courses):
            code = course.get("code") if isinstance(course, dict) else None
            label = f"{path.relative_to(CATALOG_ROOT)}[{index}]"
            if code:
                label = f"{path.relative_to(CATALOG_ROOT)} {code}"
            errors.extend(validate_course(course, label))

    print(f"Total files scanned: {len(files)}")
    print(f"Total courses scanned: {total_courses}")
    print(f"Validation errors: {len(errors)}")
    for error in errors[:100]:
        print(f"  {error}")
    if len(errors) > 100:
        print(f"  ... {len(errors) - 100} more")

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
