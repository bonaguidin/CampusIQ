"""Local, non-Postgres substitute for
requirement_satisfaction_fetch.fetch_requirement_tree, for demo students
whose institution+major match a program with a local requirement-skeleton
JSON checked into data/catalog/. See api.py's
_reconstruct_academic_schedule_for_demo, the demo-only sibling of
_reconstruct_academic_schedule.

Demo students (data/students/student_<slug>.json) have no rows anywhere in
Postgres -- requirement_groups/requirement_group_options/
requirement_group_option_courses/programs/course_catalog included. Only one
program is wired here today: SMU Computer Science, sourced from
data/catalog/smu/requirements_cs-bs.json -- the same file
data/catalog/import_requirement_groups.py loads into Postgres for real
students. This module replicates that script's group/option/course
transform (to_requirement_group_row/build_option_rows) at request time
instead of at import time, using each group's coursedog_rule_id directly as
its id/parent_group_id -- no two-pass UUID resolution needed, since nothing
downstream of RawTreeInputs (evaluate_requirement_tree, scope_schedule_input,
etc. -- all pure, see their own module docstrings) requires a real UUID, only
a stable, unique string per group.

catalog_by_gid is built by reading coursedog_group_id directly off the raw
catalog JSON rows under data/catalog/<subtree>/**/*.json -- the same files
course_discovery.catalog.LocalCatalogRepository already parses, except that
repository doesn't surface coursedog_group_id as a field. Confirmed present
on every row this session (data/catalog/smu/lyle.json etc.), so no new data
source is needed here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..requirement_satisfaction_fetch import RawTreeInputs

CATALOG_ROOT = Path(__file__).resolve().parents[2] / "data" / "catalog"


@dataclass(frozen=True)
class LocalProgram:
    program_id: str
    institution_name: str
    catalog_year: str
    requirements_path: Path
    catalog_subtree: str


# v1 is SMU CS-BS only -- the one program with both a checked-in requirement
# skeleton and a demo student (ethanBrooks) whose institution+major match it.
# Extend this dict the same way to wire up a second program.
_LOCAL_PROGRAMS: dict[tuple[str, str], LocalProgram] = {
    ("Southern Methodist University", "Computer Science"): LocalProgram(
        program_id="local:smu-cs-bs",
        institution_name="Southern Methodist University",
        catalog_year="2026-2027",
        requirements_path=CATALOG_ROOT / "smu" / "requirements_cs-bs.json",
        catalog_subtree="smu",
    ),
}


def resolve_local_program(institution: str | None, major: str | None) -> LocalProgram | None:
    if institution is None or major is None:
        return None
    return _LOCAL_PROGRAMS.get((institution, major))


def local_term_dates(today: date) -> list[dict[str, Any]]:
    """Synthetic Fall/Spring institution-calendar rows, in the shape
    planning.term_view.build_terms_view expects for its date_rows argument --
    enough of a span around `today` for _resolve_starting_term/
    _count_long_terms to find an upcoming term and count terms through any
    plausible expected_graduation. No academic_terms rows exist for a demo
    student in this local path, so every one of these becomes a plannable,
    unenrolled term (build_terms_view's own behavior for a calendar term the
    student has no row for).
    """
    rows: list[dict[str, Any]] = []
    for year in range(today.year - 1, today.year + 8):
        rows.append({
            "year": year, "season": "Spring", "label": f"Spring {year}",
            "start_date": date(year, 1, 12).isoformat(),
            "end_date": date(year, 5, 8).isoformat(),
        })
        rows.append({
            "year": year, "season": "Fall", "label": f"Fall {year}",
            "start_date": date(year, 8, 25).isoformat(),
            "end_date": date(year, 12, 12).isoformat(),
        })
    return rows


@lru_cache(maxsize=8)
def _catalog_gid_index(catalog_subtree: str) -> tuple[dict[str, str], dict[str, float]]:
    """coursedog_group_id -> course_catalog.code, and code -> credit_min,
    scanned from every raw catalog JSON row under data/catalog/<subtree>/.
    """
    by_gid: dict[str, str] = {}
    credit_by_code: dict[str, float] = {}
    for path in sorted((CATALOG_ROOT / catalog_subtree).rglob("*.json")):
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(rows, list):
            continue  # requirements_*.json is a dict, not a course-row list -- skip it
        for row in rows:
            code = row.get("code")
            if not code:
                continue
            gid = row.get("coursedog_group_id")
            if gid:
                by_gid[gid] = code
            credit_min = row.get("credit_min")
            if credit_min is not None:
                credit_by_code[code] = float(credit_min)
    return by_gid, credit_by_code


@lru_cache(maxsize=8)
def _load_requirements_json(requirements_path: str) -> dict[str, Any]:
    return json.loads(Path(requirements_path).read_text(encoding="utf-8"))


def fetch_local_requirement_tree(program: LocalProgram, course_records: list[dict[str, Any]]) -> RawTreeInputs:
    """Local substitute for fetch_requirement_tree. `course_records` is
    supplied by the caller (see local_course_records below) rather than
    fetched here, since the caller already has the demo profile in hand.
    """
    payload = _load_requirements_json(str(program.requirements_path))
    raw_groups = payload.get("groups") or []

    groups: list[dict[str, Any]] = []
    options: list[dict[str, Any]] = []
    option_courses: list[dict[str, Any]] = []

    for group in raw_groups:
        rule_id = group["coursedog_rule_id"]
        groups.append({
            "id": rule_id,
            "program_id": program.program_id,
            "catalog_year": program.catalog_year,
            "parent_group_id": group.get("parent_coursedog_rule_id"),
            "coursedog_rule_id": rule_id,
            "name": group.get("name"),
            "group_type": group.get("group_type"),
            "n_required": group.get("n_required"),
            "credit_hours_required": group.get("credit_hours_required"),
            "notes_html": group.get("notes_html"),
            "requires_manual_definition": bool(group.get("requires_manual_definition", False)),
        })
        for option in group.get("options", []):
            option_id = f"{rule_id}:{option.get('option_index')}"
            options.append({
                "id": option_id,
                "requirement_group_id": rule_id,
                "option_index": option.get("option_index"),
                "logic": option.get("logic"),
            })
            for index, coursedog_group_id in enumerate(option.get("coursedog_group_ids", [])):
                option_courses.append({
                    "id": f"{option_id}:{index}",
                    "requirement_group_option_id": option_id,
                    "coursedog_group_id": coursedog_group_id,
                    "course_code": None,
                })

    catalog_by_gid, catalog_credit_by_code = _catalog_gid_index(program.catalog_subtree)

    return RawTreeInputs(
        groups=groups,
        options=options,
        option_courses=option_courses,
        course_records=course_records,
        catalog_by_gid=catalog_by_gid,
        catalog_by_code={},  # SMU's option_courses are 100% coursedog_group_id-keyed
        catalog_credit_by_code=catalog_credit_by_code,
    )
