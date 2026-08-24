"""Tests for GradusIQ_career/demo/local_requirement_tree.py: the local
(non-Postgres) substitute for requirement_satisfaction_fetch.fetch_requirement_tree,
run against the real checked-in data/catalog/smu/requirements_cs-bs.json and
SMU catalog files -- no mocking, since these are the actual files the demo
schedule/requirement-satisfaction routes read at request time.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from GradusIQ_career.course_discovery.requirement_satisfaction import evaluate_requirement_tree
from GradusIQ_career.demo.local_requirement_tree import (
    CATALOG_ROOT,
    _LOCAL_PROGRAMS,
    fetch_local_requirement_tree,
    local_term_dates,
    resolve_local_program,
)
from GradusIQ_career.planning.term_view import build_terms_view

_SMU_CS_PROGRAM = _LOCAL_PROGRAMS[("Southern Methodist University", "Computer Science")]
_REQUIREMENTS_PAYLOAD = json.loads(_SMU_CS_PROGRAM.requirements_path.read_text(encoding="utf-8"))


def test_resolve_local_program_matches_smu_computer_science():
    program = resolve_local_program("Southern Methodist University", "Computer Science")
    assert program is not None
    assert program.requirements_path == CATALOG_ROOT / "smu" / "requirements_cs-bs.json"


def test_resolve_local_program_returns_none_for_unwired_institution_or_major():
    assert resolve_local_program("Texas A&M University", "Computer Engineering") is None
    assert resolve_local_program("Southern Methodist University", "Mechanical Engineering") is None
    assert resolve_local_program(None, None) is None


def test_fetch_local_requirement_tree_reproduces_every_group_and_option():
    raw = fetch_local_requirement_tree(_SMU_CS_PROGRAM, course_records=[])
    source_groups = _REQUIREMENTS_PAYLOAD["groups"]
    assert len(raw.groups) == len(source_groups)

    ids = {group["id"] for group in raw.groups}
    assert len(ids) == len(raw.groups), "coursedog_rule_id must be unique per group, used directly as id"

    # Every child's parent_group_id resolves to a real id among these groups.
    for group in raw.groups:
        if group["parent_group_id"] is not None:
            assert group["parent_group_id"] in ids

    source_option_count = sum(len(g.get("options", [])) for g in source_groups)
    assert len(raw.options) == source_option_count
    source_course_count = sum(
        len(o.get("coursedog_group_ids", [])) for g in source_groups for o in g.get("options", [])
    )
    assert len(raw.option_courses) == source_course_count


def test_fetch_local_requirement_tree_resolves_nearly_every_referenced_coursedog_group_id():
    """Almost every coursedog_group_id the requirement JSON references should
    resolve to a real catalog course code. A handful of misses is expected
    real-world data incompleteness (some referenced courses aren't in the
    scraped catalog subset) -- import_requirement_groups.py's own Postgres
    path tolerates this identically, flagging as unresolved_course_ref
    rather than failing. What this guards against is a SYSTEMIC parsing
    failure (wrong field name, wrong subtree) that would leave
    catalog_by_gid empty and every option unresolved.
    """
    raw = fetch_local_requirement_tree(_SMU_CS_PROGRAM, course_records=[])
    referenced_gids = {row["coursedog_group_id"] for row in raw.option_courses}
    assert referenced_gids, "fixture sanity: the requirement JSON must reference at least one course"
    unresolved = referenced_gids - raw.catalog_by_gid.keys()
    resolved_fraction = 1 - (len(unresolved) / len(referenced_gids))
    assert resolved_fraction >= 0.9, (
        f"only {resolved_fraction:.0%} resolved -- unresolved: {sorted(unresolved)[:10]}"
    )


def test_fetch_local_requirement_tree_evaluates_without_error():
    """End-to-end smoke test of the pure evaluator against these local
    inputs -- catches shape mismatches evaluate_requirement_tree would
    reject (missing keys, wrong types) that the structural tests above
    wouldn't necessarily catch.
    """
    raw = fetch_local_requirement_tree(_SMU_CS_PROGRAM, course_records=[
        {"course_code": "CS 1341", "status": "completed", "credit_hours": 3.0, "counts_toward_credit": True},
    ])
    groups = evaluate_requirement_tree(
        raw.groups, raw.options, raw.option_courses, raw.course_records, raw.catalog_by_gid, raw.catalog_by_code,
    )
    assert len(groups) > 0
    all_matched = {code for g in groups for code in g.matched_course_codes}
    assert "CS 1341" in all_matched


def test_local_term_dates_covers_upcoming_fall_and_spring_around_today():
    today = date(2026, 8, 24)
    rows = local_term_dates(today)
    terms_view = build_terms_view([], rows, today)
    assert terms_view.upcoming_term_key is not None
    upcoming = next(t for t in terms_view.terms if t["key"] == terms_view.upcoming_term_key)
    assert upcoming["season"] in ("Fall", "Spring")
    assert date.fromisoformat(upcoming["start_date"]) > today


def test_local_term_dates_spans_far_enough_for_a_multi_year_expected_graduation():
    today = date(2026, 8, 24)
    rows = local_term_dates(today)
    years = {row["year"] for row in rows}
    assert max(years) >= 2029, "must reach a Spring-2029-style expected_graduation"
