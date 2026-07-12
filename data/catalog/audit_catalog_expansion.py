#!/usr/bin/env python3
"""Audit TAMU catalog subject coverage against the official subject index.

This script reads existing local catalog JSON files and fetches only the
official undergraduate course-description index page. It does not fetch subject
detail pages, create catalog files, or modify existing catalog JSON data.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin


try:
    import requests
except ImportError:  # pragma: no cover - fallback for minimal environments
    requests = None

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - fallback for minimal environments
    BeautifulSoup = None


CATALOG_ROOT = Path(__file__).resolve().parent
REPO_ROOT = CATALOG_ROOT.parents[1]
REPORT_PATH = REPO_ROOT / "data" / "reference" / "catalog_expansion_audit.md"
INDEX_URL = "https://catalog.tamu.edu/undergraduate/course-descriptions/"
SOURCE_URL_PREFIX = "https://catalog.tamu.edu/undergraduate/course-descriptions/"
SUBJECT_HREF_RE = re.compile(r"^/undergraduate/course-descriptions/([a-z0-9]+)/?$")
SUBJECT_TEXT_RE = re.compile(r"^\s*([A-Z0-9]{2,6})\s+-\s+(.+?)(?:\s+\(([A-Z0-9]{2,6})\))?\s*$")
COURSE_CODE_RE = re.compile(r"\b([A-Z]{2,6})\s+([0-9]{3}[A-Z]?)\b")

KNOWN_HIGH_PRIORITY = {
    "CSCE",
    "ECEN",
    "MEEN",
    "ISEN",
    "BMEN",
    "ECON",
    "COMM",
    "JOUR",
    "PHIL",
    "SOCI",
}
HIGH_KEYWORDS = {
    "accounting",
    "analytics",
    "artificial intelligence",
    "biomedical engineering",
    "business",
    "computer",
    "data",
    "economics",
    "engineering",
    "finance",
    "freshman",
    "information",
    "management information",
    "mathematics",
    "mechanical engineering",
    "statistics",
}
MEDIUM_KEYWORDS = {
    "administration",
    "communication",
    "ethics",
    "interdisciplinary",
    "journalism",
    "law",
    "legal",
    "philosophy",
    "policy",
    "political",
    "psychology",
    "public",
    "sociology",
}
NEXT_BATCH_ORDER = ["CSCE", "ECON", "MEEN", "ISEN", "BMEN", "COMM", "JOUR", "PHIL", "SOCI"]


@dataclass(frozen=True)
class Subject:
    prefix: str
    name: str
    source_url: str


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attrs_dict = dict(attrs)
        href = attrs_dict.get("href")
        if href:
            self._href = href
            self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            self.links.append((self._href, " ".join(self._text_parts)))
            self._href = None
            self._text_parts = []


def fetch_index_html() -> str:
    if requests is not None:
        response = requests.get(INDEX_URL, timeout=30)
        response.raise_for_status()
        return response.text

    from urllib.request import urlopen

    with urlopen(INDEX_URL, timeout=30) as response:  # noqa: S310 - official fixed URL
        return response.read().decode("utf-8")


def extract_links(html: str) -> list[tuple[str, str]]:
    if BeautifulSoup is not None:
        soup = BeautifulSoup(html, "html.parser")
        return [(str(anchor.get("href")), anchor.get_text(" ", strip=True)) for anchor in soup.find_all("a", href=True)]

    parser = LinkParser()
    parser.feed(html)
    return [(href, " ".join(text.split())) for href, text in parser.links]


def parse_subjects(html: str) -> list[Subject]:
    subjects: dict[str, Subject] = {}
    for href, text in extract_links(html):
        match = SUBJECT_HREF_RE.match(href)
        if not match:
            continue

        source_url = urljoin(INDEX_URL, href)
        text = " ".join(unescape(text).replace("\u200b", "").split())
        subject_match = SUBJECT_TEXT_RE.match(text)
        if subject_match:
            prefix = subject_match.group(1)
            name = subject_match.group(2).strip()
        else:
            prefix = match.group(1).upper()
            name = text or prefix

        if prefix.lower() != match.group(1).lower():
            continue
        subjects[prefix] = Subject(prefix=prefix, name=name, source_url=source_url)

    return sorted(subjects.values(), key=lambda subject: subject.prefix)


def iter_catalog_files() -> list[Path]:
    return sorted(CATALOG_ROOT.rglob("*.json"))


def load_courses(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError(f"{path} is not a top-level JSON array")
    return data


def collect_local_coverage() -> tuple[dict[str, Counter[str]], Counter[str], set[str], set[str]]:
    coverage: dict[str, Counter[str]] = defaultdict(Counter)
    departments: set[str] = set()
    cross_listing_prefixes: set[str] = set()
    all_prefixes: set[str] = set()

    for path in iter_catalog_files():
        relative_path = str(path.relative_to(CATALOG_ROOT))
        for course in load_courses(path):
            if not isinstance(course, dict):
                continue
            prefix = course.get("prefix")
            if not isinstance(prefix, str) or not prefix.strip():
                code = course.get("code")
                if isinstance(code, str) and code.strip():
                    prefix = code.strip().split()[0]
            if isinstance(prefix, str) and prefix.strip():
                normalized_prefix = prefix.strip().upper()
                all_prefixes.add(normalized_prefix)
                coverage[normalized_prefix][relative_path] += 1

            department = course.get("department")
            if isinstance(department, str) and department.strip():
                departments.add(department.strip())

            cross_listings = course.get("cross_listings")
            if isinstance(cross_listings, list):
                for listing in cross_listings:
                    if isinstance(listing, str):
                        match = COURSE_CODE_RE.search(listing)
                        if match:
                            cross_listing_prefixes.add(match.group(1))

    return coverage, Counter({prefix: sum(files.values()) for prefix, files in coverage.items()}), departments, cross_listing_prefixes


def priority_for(subject: Subject, covered_prefixes: set[str], cross_listing_prefixes: set[str]) -> tuple[str, str]:
    name_lower = subject.name.lower()
    if subject.prefix in covered_prefixes:
        return "covered", "Already represented in the current catalog data."
    if subject.prefix in KNOWN_HIGH_PRIORITY:
        return "high", "Known high-priority subject for AI, CS, engineering, analytics, economics, or career-relevant pathways."
    if any(keyword in name_lower for keyword in HIGH_KEYWORDS):
        return "high", "Subject name indicates support for AI, engineering, business analytics, data, economics, or common freshman pathways."
    if subject.prefix in cross_listing_prefixes:
        return "medium", "Referenced as a cross-listing in existing catalog data."
    if any(keyword in name_lower for keyword in MEDIUM_KEYWORDS):
        return "medium", "Supports communication, policy, ethics, pre-law, psychology, or interdisciplinary career paths."
    return "low", "No immediate data-foundation priority signal found."


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(escape_cell(value) for value in row) + " |")
    return "\n".join(lines)


def escape_cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def build_report(
    subjects: list[Subject],
    coverage_by_prefix: dict[str, Counter[str]],
    course_counts: Counter[str],
    departments: set[str],
    cross_listing_prefixes: set[str],
) -> tuple[str, list[tuple[Subject, str, str]], list[Subject]]:
    covered_prefixes = set(course_counts)
    subject_prefixes = {subject.prefix for subject in subjects}
    covered_subjects = sorted(covered_prefixes.intersection(subject_prefixes))
    missing_subjects: list[tuple[Subject, str, str]] = []
    for subject in subjects:
        priority, reason = priority_for(subject, covered_prefixes, cross_listing_prefixes)
        if priority != "covered":
            missing_subjects.append((subject, priority, reason))

    priority_rank = {"high": 0, "medium": 1, "low": 2}
    missing_subjects.sort(key=lambda item: (priority_rank[item[1]], NEXT_BATCH_ORDER.index(item[0].prefix) if item[0].prefix in NEXT_BATCH_ORDER else 99, item[0].prefix))
    next_batch = [item[0] for item in missing_subjects if item[1] == "high"][:5]

    coverage_rows: list[list[str]] = []
    for prefix in sorted(course_counts):
        files = ", ".join(f"{file_name} ({count})" for file_name, count in sorted(coverage_by_prefix[prefix].items()))
        coverage_rows.append([prefix, files, str(course_counts[prefix])])

    missing_rows = [
        [priority, subject.prefix, subject.name, subject.source_url, reason]
        for subject, priority, reason in missing_subjects
    ]

    cross_listing_only = sorted(cross_listing_prefixes - covered_prefixes)
    cross_listing_rows: list[list[str]] = []
    subject_by_prefix = {subject.prefix: subject for subject in subjects}
    for prefix in cross_listing_only:
        subject = subject_by_prefix.get(prefix)
        cross_listing_rows.append(
            [
                prefix,
                subject.name if subject else "Unknown official subject name",
                subject.source_url if subject else "Not found on official index",
            ]
        )

    next_batch_rows = []
    recommendation_lookup = {subject.prefix: (priority, reason) for subject, priority, reason in missing_subjects}
    for subject in next_batch:
        _, reason = recommendation_lookup[subject.prefix]
        next_batch_rows.append([subject.prefix, subject.name, subject.source_url, reason])

    report = f"""# TAMU Catalog Expansion Audit

Generated: {date.today().isoformat()}

Audit source: {INDEX_URL}

This is an audit-only report. It compares current local catalog coverage against the official TAMU undergraduate course-description subject index. It does not scrape course descriptions or create new catalog data files.

## Summary

- Current catalog files: {len(iter_catalog_files())}
- Current courses: {sum(course_counts.values())}
- Current prefixes: {", ".join(sorted(course_counts))}
- Current departments: {len(departments)}
- Total TAMU subject pages discovered: {len(subjects)}
- Subjects already covered: {len(covered_subjects)}
- Subjects not yet covered: {len(subjects) - len(covered_subjects)}

## Current Coverage

{markdown_table(["Prefix", "Department/source file", "Course count"], coverage_rows)}

## Missing Subject Candidates

{markdown_table(["Priority", "Prefix", "Subject name", "Source URL", "Reason"], missing_rows)}

## Cross-Listing Opportunities

{markdown_table(["Prefix", "Subject name", "Source URL"], cross_listing_rows) if cross_listing_rows else "No cross-listing-only prefixes were found in existing catalog data."}

## Recommended Next Expansion Batch

No more than five subjects are recommended for the next controlled batch:

{markdown_table(["Prefix", "Subject name", "Source URL", "Why next"], next_batch_rows)}

These should be added only after explicit approval. The recommendation favors high-signal foundations for computer science, economics, engineering, industrial systems, and biomedical engineering pathways.

## Safety Notes

- Do not scrape all departments automatically.
- Add only approved subjects.
- Do not add new departments without approval.
- Do not scrape course detail pages during expansion audits.
- Run normalization after each approved subject addition.
- Run `python3 data/catalog/validate_catalog.py` after each addition.
- Keep `credit_hours` unchanged; do not rename it to `credits`.

Dry-run command example:

```bash
python3 data/catalog/audit_catalog_expansion.py
```
"""

    return report, missing_subjects, next_batch


def main() -> int:
    coverage_by_prefix, course_counts, departments, cross_listing_prefixes = collect_local_coverage()
    html = fetch_index_html()
    subjects = parse_subjects(html)
    report, missing_subjects, next_batch = build_report(
        subjects,
        coverage_by_prefix,
        course_counts,
        departments,
        cross_listing_prefixes,
    )

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")

    covered_prefixes = set(course_counts)
    subject_prefixes = {subject.prefix for subject in subjects}
    covered_subjects = covered_prefixes.intersection(subject_prefixes)

    print(f"Total subjects discovered: {len(subjects)}")
    print(f"Already covered subjects: {len(covered_subjects)}")
    print(f"Missing subjects: {len(subjects) - len(covered_subjects)}")
    print("Recommended next 5 subjects:")
    for subject in next_batch:
        print(f"  {subject.prefix}: {subject.name} ({subject.source_url})")
    print(f"Audit report: {REPORT_PATH}")
    print(f"Cross-listing-only prefixes: {', '.join(sorted(cross_listing_prefixes - covered_prefixes)) or 'none'}")
    print("Catalog JSON files modified: 0")

    if not subjects:
        print("Warning: no subjects were discovered from the official index page.")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
