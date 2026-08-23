"""Pure evaluation of a program's requirement_groups tree against one
student's course_records, per planning-docs/degree-planner-spec.md §9
(semantics) and §9.1 (architecture).

Deliberately has no Client parameter and performs no I/O -- see
requirement_satisfaction_fetch.fetch_requirement_tree() for the thin,
untested-by-unit-test fetch boundary that supplies this module's inputs,
mirroring profile_builder.build_student_intelligence_profile()'s own
flat-fetch-then-Python-tree split. Kept out of course_discovery/'s own
fetch path (rather than adding fetch_requirement_tree here too) because
course_discovery/README.md states C1 "does not call ... Supabase" --
this module's evaluator honors that boundary; only the sibling fetch
module in GradusIQ_career/ touches a Client, same placement rationale
profile_builder.py already documents for itself.

LEAF-GROUP STATUS: applies the unified three-state model (SATISFIED /
IN_PROGRESS / NOT_STARTED) to every leaf group uniformly, including
multi-option ones -- e.g. Computer Science Core, which for Ethan Brooks
has 3 of 11 options matched, correctly shows IN_PROGRESS rather than
being forced into a binary SATISFIED/NOT_STARTED choice. §9's leaf-
groups parenthetical, read fully literally, restricts leaves to
SATISFIED/NOT_STARTED only -- inconsistent with §9's own NOT_STARTED
definition ("no matched course anywhere in the subtree") for a
partially-matched multi-option leaf. This implementation resolves that
by applying the general three-state rule uniformly; §9's text itself has
not been edited to match -- see the requirement-satisfaction build
task's report for the full reasoning, still pending a spec-text pass.

CREDIT-THRESHOLD DETECTION: keyed directly off
group_type == "enumerated_credit_threshold"
(supabase/migrations/20260819160000_requirement_groups_credit_threshold_
group_type.sql), Coursedog's completeVariableCoursesAndVariableCredits
condition mapped to this group_type by fetch_smu_requirements.py's
CONDITION_TO_GROUP_TYPE. No coursedog_rule_id allowlist or other
ID-based special-casing -- the schema itself now carries the
distinction §8.4 originally flagged as unresolved.

COURSE_CODE RESOLUTION (added for TAMU, any future non-Coursedog school --
supabase/migrations/20260823140000_requirement_group_option_courses_
course_code.sql): a requirement_group_option_courses row now resolves via
either coursedog_group_id (through catalog_by_gid, SMU's existing path,
untouched) or course_code (through catalog_by_code, new). Internally every
row resolves to a LIST of acceptable codes, not a single code-or-None --
normally 0 or 1 entries, but 2 for a TAMU-style slash-joined cross-listing
(e.g. "ENGR 216/PHYS 216": course_catalog stores each cross-listed
department code as its own independent row, so a student's transcript
shows only ONE of the two and either must count). This is a strict
generalization of the old str | None representation (wrap in a list),
proven behavior-identical for SMU's existing coursedog_group_id path by
tests/test_requirement_satisfaction.py's full existing suite passing
unmodified -- see _resolve_option_codes() and _evaluate_option().
"""

from __future__ import annotations

from collections import defaultdict
from enum import Enum
from typing import Any

from pydantic import Field

from .models import StrictModel


class RequirementGroupStatus(str, Enum):
    SATISFIED = "SATISFIED"
    IN_PROGRESS = "IN_PROGRESS"
    NOT_STARTED = "NOT_STARTED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class RequirementGroupResult(StrictModel):
    id: str
    coursedog_rule_id: str
    name: str
    group_type: str
    status: RequirementGroupStatus
    detail: str | None = None
    matched_course_codes: list[str] = Field(default_factory=list)
    children: list["RequirementGroupResult"] = Field(default_factory=list)


RequirementGroupResult.model_rebuild()


class RequirementSatisfactionResult(StrictModel):
    student_id: str
    program_id: str
    groups: list[RequirementGroupResult] = Field(default_factory=list)


def _build_matched_courses(course_records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """course_code -> the student's row for it, completed preferred over
    in_progress when both exist. Only rows with counts_toward_credit truthy
    (default True when absent) and status in (completed, in_progress) --
    per §9, counts_toward_gpa/excluded_from_gpa_by are GPA-only concerns and
    are deliberately never consulted here.
    """
    matched: dict[str, dict[str, Any]] = {}
    for record in course_records:
        if not record.get("counts_toward_credit", True):
            continue
        status = record.get("status")
        if status not in ("completed", "in_progress"):
            continue
        code = record["course_code"]
        existing = matched.get(code)
        if existing is None or (existing.get("status") != "completed" and status == "completed"):
            matched[code] = record
    return matched


def _resolve_option_codes(
    option_id: str,
    option_courses: list[dict[str, Any]],
    catalog_by_gid: dict[str, str],
    catalog_by_code: dict[str, list[str]] | None = None,
) -> list[list[str]]:
    """One entry per requirement_group_option_courses row under this option,
    each entry itself a list of acceptable course codes for that row.

    Normally 0 (unresolved) or 1 entry -- an empty list marks an
    unresolved_course_ref row, or a coursedog_group_id/course_code with no
    course_catalog match, per §9's Engineering Leadership known-limitation;
    it can never be matched against a transcript. Exactly 2 entries only
    for a course_code row that is a "/"-joined cross-listing already split
    by catalog_by_code (see requirement_satisfaction_fetch.py) -- either
    counts as a match for that one row.

    coursedog_group_id and course_code are mutually exclusive per-row (the
    schema's own CHECK constraint), so each row resolves through exactly
    one of catalog_by_gid or catalog_by_code, never both.
    """
    catalog_by_code = catalog_by_code or {}
    resolved: list[list[str]] = []
    for row in option_courses:
        gid = row.get("coursedog_group_id")
        if gid:
            code = catalog_by_gid.get(gid)
            resolved.append([code] if code else [])
            continue
        course_code = row.get("course_code")
        if course_code:
            resolved.append(list(catalog_by_code.get(course_code, [])))
            continue
        resolved.append([])
    return resolved


def _evaluate_option(
    logic: str, resolved_rows: list[list[str]], matched_by_code: dict[str, dict[str, Any]]
) -> tuple[bool, list[str]]:
    """Returns (option_satisfied, matched_course_codes_within_this_option).

    resolved_rows has one entry per requirement_group_option_courses row,
    each entry itself a list of acceptable codes for that row (see
    _resolve_option_codes -- more than one only for a cross-listed
    course_code). A row counts as "matched" if ANY of its codes is in
    matched_by_code -- this is a strict generalization of the old
    str | None shape (a single code is just a 1-element list), so SMU's
    coursedog_group_id rows (always 0 or 1 codes) behave identically to
    before.

    'and': every row must resolve to at least one code AND be matched --
    a wholly-unresolved row makes the option permanently unsatisfiable.
    'or': any single resolved+matched code, from any row, satisfies the
    option.
    """
    if not resolved_rows:
        return False, []
    if logic == "and":
        if any(not codes for codes in resolved_rows):
            return False, []
        rows_matched = 0
        matched: list[str] = []
        for codes in resolved_rows:
            hits = [c for c in codes if c in matched_by_code]
            if hits:
                rows_matched += 1
                matched.extend(hits)
        return (rows_matched == len(resolved_rows)), matched
    matched = [c for codes in resolved_rows for c in codes if c in matched_by_code]
    return (len(matched) > 0), matched


def _fmt_credits(value: float) -> str:
    return f"{value:g}"


def _subtree_has_match(result: RequirementGroupResult) -> bool:
    if result.status == RequirementGroupStatus.MANUAL_REVIEW:
        return False
    if result.matched_course_codes:
        return True
    return any(_subtree_has_match(child) for child in result.children)


def evaluate_requirement_tree(
    groups: list[dict[str, Any]],
    options: list[dict[str, Any]],
    option_courses: list[dict[str, Any]],
    course_records: list[dict[str, Any]],
    catalog_by_gid: dict[str, str],
    catalog_by_code: dict[str, list[str]] | None = None,
) -> list[RequirementGroupResult]:
    """Walk a program's requirement_groups tree and return each top-level
    group's (and its descendants') RequirementGroupResult per §9's
    three-state model. Pure function -- no Client, no I/O.

    catalog_by_code is optional and defaults to empty -- existing callers
    (SMU, all of which resolve purely via catalog_by_gid) pass 5 positional
    args exactly as before and are completely unaffected; see the module
    docstring's COURSE_CODE RESOLUTION note.
    """
    catalog_by_code = catalog_by_code or {}
    children_by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for group in groups:
        parent_id = group.get("parent_group_id")
        if parent_id:
            children_by_parent[parent_id].append(group)

    options_by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for option in options:
        options_by_group[option["requirement_group_id"]].append(option)
    for option_list in options_by_group.values():
        option_list.sort(key=lambda o: o["option_index"])

    option_courses_by_option: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in option_courses:
        option_courses_by_option[row["requirement_group_option_id"]].append(row)

    matched_by_code = _build_matched_courses(course_records)

    def evaluate_leaf(group: dict[str, Any]) -> RequirementGroupResult:
        group_id = group["id"]
        opts = options_by_group.get(group_id, [])

        if group["group_type"] == "enumerated_credit_threshold":
            all_codes: set[str] = set()
            for option in opts:
                for codes in _resolve_option_codes(
                    option["id"], option_courses_by_option.get(option["id"], []), catalog_by_gid, catalog_by_code
                ):
                    all_codes.update(codes)
            matched_codes = sorted(code for code in all_codes if code in matched_by_code)
            accumulated = sum(matched_by_code[code].get("credit_hours") or 0 for code in matched_codes)
            required = group.get("credit_hours_required") or 0
            if accumulated <= 0:
                status = RequirementGroupStatus.NOT_STARTED
            elif accumulated >= required:
                status = RequirementGroupStatus.SATISFIED
            else:
                status = RequirementGroupStatus.IN_PROGRESS
            detail = f"{_fmt_credits(accumulated)} of {_fmt_credits(required)} credits"
            return RequirementGroupResult(
                id=group_id,
                coursedog_rule_id=group["coursedog_rule_id"],
                name=group["name"],
                group_type=group["group_type"],
                status=status,
                detail=detail,
                matched_course_codes=matched_codes,
            )

        option_evals = [
            _evaluate_option(
                option["logic"],
                _resolve_option_codes(
                    option["id"], option_courses_by_option.get(option["id"], []), catalog_by_gid, catalog_by_code
                ),
                matched_by_code,
            )
            for option in opts
        ]
        satisfied_count = sum(1 for satisfied, _ in option_evals if satisfied)
        matched_codes = sorted({code for _, codes in option_evals for code in codes})

        if group["group_type"] == "enumerated_at_least_n":
            n_required = group["n_required"]
            if satisfied_count >= n_required:
                status = RequirementGroupStatus.SATISFIED
            elif matched_codes:
                status = RequirementGroupStatus.IN_PROGRESS
            else:
                status = RequirementGroupStatus.NOT_STARTED
            detail = f"{satisfied_count} of {n_required} required options satisfied ({len(opts)} available)"
        else:  # enumerated_all
            if opts and satisfied_count == len(opts):
                status = RequirementGroupStatus.SATISFIED
            elif matched_codes:
                status = RequirementGroupStatus.IN_PROGRESS
            else:
                status = RequirementGroupStatus.NOT_STARTED
            detail = f"{satisfied_count} of {len(opts)} required options satisfied"

        return RequirementGroupResult(
            id=group_id,
            coursedog_rule_id=group["coursedog_rule_id"],
            name=group["name"],
            group_type=group["group_type"],
            status=status,
            detail=detail,
            matched_course_codes=matched_codes,
        )

    def evaluate(group: dict[str, Any]) -> RequirementGroupResult:
        group_id = group["id"]

        if group.get("requires_manual_definition"):
            return RequirementGroupResult(
                id=group_id,
                coursedog_rule_id=group["coursedog_rule_id"],
                name=group["name"],
                group_type=group["group_type"],
                status=RequirementGroupStatus.MANUAL_REVIEW,
                detail="No structured course list exists for this requirement — ask your adviser.",
            )

        if group["group_type"] not in ("compound_all", "compound_any"):
            return evaluate_leaf(group)

        child_results = [evaluate(child) for child in children_by_parent.get(group_id, [])]
        satisfied_count = sum(1 for child in child_results if child.status == RequirementGroupStatus.SATISFIED)
        any_progress = any(_subtree_has_match(child) for child in child_results)
        total = len(child_results)

        if group["group_type"] == "compound_all":
            if total and satisfied_count == total:
                status = RequirementGroupStatus.SATISFIED
            elif any_progress:
                status = RequirementGroupStatus.IN_PROGRESS
            else:
                status = RequirementGroupStatus.NOT_STARTED
            detail = f"{satisfied_count} of {total} children satisfied"
        else:  # compound_any
            if satisfied_count > 0:
                status = RequirementGroupStatus.SATISFIED
                satisfied_names = [child.name for child in child_results if child.status == RequirementGroupStatus.SATISFIED]
                detail = f"satisfied via {satisfied_names[0]}"
                if len(satisfied_names) > 1:
                    detail += f" (also via {', '.join(satisfied_names[1:])})"
            elif any_progress:
                status = RequirementGroupStatus.IN_PROGRESS
                started = sum(1 for child in child_results if _subtree_has_match(child))
                detail = f"{started} of {total} paths started"
            else:
                status = RequirementGroupStatus.NOT_STARTED
                detail = f"0 of {total} paths started"

        return RequirementGroupResult(
            id=group_id,
            coursedog_rule_id=group["coursedog_rule_id"],
            name=group["name"],
            group_type=group["group_type"],
            status=status,
            detail=detail,
            children=child_results,
        )

    top_level = [group for group in groups if not group.get("parent_group_id")]
    return [evaluate(group) for group in top_level]


def to_satisfaction_result(
    student_id: str, program_id: str, groups: list[RequirementGroupResult]
) -> RequirementSatisfactionResult:
    return RequirementSatisfactionResult(student_id=student_id, program_id=program_id, groups=groups)
