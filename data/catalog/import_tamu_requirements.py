#!/usr/bin/env python3
"""Import a normalized TAMU requirement-skeleton JSON (from
fetch_tamu_requirements.py) into Supabase: programs, requirement_groups,
requirement_group_options, requirement_group_option_courses.

Mirrors data/catalog/import_requirement_groups.py's structure (dry-run
default, pure mapping/validation functions before any Supabase call,
idempotent upsert-then-delete-then-rebuild-options write phase) as closely
as TAMU's real differences from SMU allow. Those differences, and how each
is handled, are documented below rather than silently absorbed.

REQUIRES supabase/migrations/20260823140000_requirement_group_option_
courses_course_code.sql applied first (course_code column + relaxed CHECK
constraint) -- this script will fail on insert against a database that
doesn't have it yet, not silently misbehave.

DIFFERENCE 1 -- no Coursedog IDs anywhere for TAMU (programs.
coursedog_program_id/program_group_id, requirement_groups.
coursedog_rule_id are all NOT NULL columns with no TAMU-specific
alternative -- adding one would be a schema change out of scope for this
pass). DECISION: reuse programs.code (e.g. "ECEN-CPEN-BS") as the value
for both coursedog_program_id and program_group_id, and reuse
fetch_tamu_requirements.py's synthesized rule_id (e.g. "tamu-rule-003") as
the value for requirement_groups.coursedog_rule_id. Both columns keep
their existing NOT NULL/uniqueness guarantees and this script's own
upsert-on-conflict / idempotent-rerun behavior working unchanged -- the
values just aren't sourced from Coursedog. Flagged here, not silently
assumed as "close enough".

DIFFERENCE 2 -- course identity is course_code, not coursedog_group_id.
Every course reference in the source JSON resolves through the new
course_code column (20260823140000) instead of coursedog_group_id. Uses
the exact same "flag and continue" posture SMU's importer established for
unresolved_course_ref: a course_code that doesn't resolve against
course_catalog (checking both halves for a "/"-joined cross-listing, e.g.
"ENGR 216/PHYS 216") is flagged via unresolved_course_ref instead of
failing the whole import.

DIFFERENCE 3 -- cross-listed courses. DECISION (per this build's Step 5):
the DB row stores the combined "ENGR 216/PHYS 216" string verbatim in
course_code, relying on requirement_satisfaction_fetch.py's fetch-time
split (catalog_by_code) to resolve either half at read time -- NOT split
into two option_courses rows at import time. Rationale: a cross-listed
pair is one course under two department codes (either counts), which is a
different relationship from a genuine two-course "or" alternative like
Fourth Year Fall's "CSCE 399 or ECEN 399" (two DIFFERENT courses, either
satisfies -- see DIFFERENCE 4). Keeping them structurally distinct at the
DB level -- one course_code row with an internal split vs. two separate
course_code rows under an "or" option -- preserves that semantic
difference for anyone reading the raw rows later, rather than collapsing
both into the same shape.

DIFFERENCE 4 -- the source JSON's "modeling_confidence": "inferred" flag
(Fourth Year Fall's "High Impact Experience" group, where
fetch_tamu_requirements.py inferred that the adjacent "CSCE 399 or
ECEN 399" row resolves the placeholder above it -- a best-effort
structural read, not confirmed by an advisor). No requirement_groups
column exists for this. DECISION: prepended as a plain-text note into
notes_html (an existing column, already documented as carrying qualifying
prose beyond just freeform groups) rather than adding a new column for a
single flagged row, PLUS a loud print() at import time so it can't be
missed in a normal run's output. This is intentionally visible in two
places, not buried in one.

DIFFERENCE 5 -- footnotes are NOT imported into the database in this
pass. The source JSON's footnotes{}/footnote_refs[] structure (added
specifically to keep footnote text out of any satisfaction-blocking path
-- footnotes_enforced: false) has no home in requirement_groups
(per-group) or requirement_group_option_courses (per-course-reference,
but no column exists). Building that storage is a real schema decision
this script does not make unilaterally. The source JSON file itself
remains the authoritative carrier of footnote text until that decision is
made -- this is flagged loudly (see FOOTNOTES NOT IMPORTED print block in
main()), not silently dropped.

DIFFERENCE 6 -- a choice group's alternative can itself be a freeform
"manual" option (no course_codes at all, e.g. First Year Spring's
"University Core Curriculum" alternative to CHEM 120 -- see
fetch_tamu_requirements.py's freeform_label field). No column represents
"this option has no fixed course by design" the way requirement_groups.
requires_manual_definition does at the group level. DECISION (v1
simplification, flagged in output, not silently absorbed): the
requirement_group_options row is still created (so n_required/logic
context is preserved), but zero requirement_group_option_courses rows are
written under it -- it can never resolve to SATISFIED, same practical
effect as a freeform group, just without MANUAL_REVIEW's distinct status.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from supabase import Client, create_client

CATALOG_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = CATALOG_ROOT.parents[1]

VALID_GROUP_TYPES = (
    "enumerated_all",
    "enumerated_at_least_n",
    "compound_all",
    "compound_any",
    "freeform",
    "enumerated_credit_threshold",
)
ENUMERATED_GROUP_TYPES = ("enumerated_all", "enumerated_at_least_n", "enumerated_credit_threshold")

INSTITUTION_NAME = "Texas A&M University"

HIGH_IMPACT_EXPERIENCE_NOTE = (
    "MODELING NOTE (inferred, needs human review): the option(s) under this "
    "group were nested here by fetch_tamu_requirements.py's parser based on "
    "row adjacency in the source catalog page (a 0-credit placeholder row "
    "immediately followed by a course row), not an explicit structural link "
    "in the CourseLeaf markup. This is a best-effort interpretation, not an "
    "advisor-confirmed relationship -- verify before treating this group's "
    "satisfaction as authoritative."
)


def stop(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


# ── Pure mapping/validation functions (no network, no Supabase client) ─────


def to_program_row(program: dict[str, Any], institution_id: str, catalog_year: str) -> dict[str, Any]:
    code = program.get("code")
    return {
        "institution_id": institution_id,
        # DIFFERENCE 1 -- see module docstring: TAMU has no Coursedog
        # identity, `code` stands in for both columns.
        "coursedog_program_id": code,
        "program_group_id": code,
        "code": code,
        "name": program.get("name"),
        "degree_designation": program.get("degree_designation"),
        "catalog_year": catalog_year,
    }


PROGRAM_NOT_NULL_COLUMNS = ("coursedog_program_id", "program_group_id", "code", "name", "catalog_year")


def validate_program_row(row: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for column in PROGRAM_NOT_NULL_COLUMNS:
        value = row.get(column)
        if value is None or (isinstance(value, str) and not value.strip()):
            problems.append(f"program: {column} is null/empty (NOT NULL)")
    return problems


def _credit_hours_as_int(value: Any, label: str, problems: list[str]) -> int | None:
    """requirement_groups.credit_hours_required is `int null`. The source
    JSON stores floats (e.g. 3.0) from the HTML credit-hours cell. Every
    real value observed in TAMU's data is a whole number -- this casts
    only when safe and flags (does not silently truncate) anything that
    isn't, since a fractional credit value would mean the scraper's
    assumption broke somewhere upstream.
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        problems.append(f"{label}: credit_hours_required {value!r} is not a number")
        return None
    if float(value) != int(value):
        problems.append(f"{label}: credit_hours_required {value!r} is not a whole number -- refusing to truncate")
        return None
    return int(value)


def to_requirement_group_row(
    group: dict[str, Any], program_id: str, catalog_year: str, problems: list[str]
) -> dict[str, Any]:
    label = f"group {group.get('rule_id')} ({group.get('name')})"
    notes_html = group.get("notes_html")
    if group.get("modeling_confidence") == "inferred":
        notes_html = f"{HIGH_IMPACT_EXPERIENCE_NOTE}\n\n{notes_html}" if notes_html else HIGH_IMPACT_EXPERIENCE_NOTE
    return {
        "program_id": program_id,
        "catalog_year": catalog_year,
        # DIFFERENCE 1 -- see module docstring: the synthesized rule_id
        # (e.g. "tamu-rule-003") stands in for a real coursedog_rule_id.
        "coursedog_rule_id": group.get("rule_id"),
        "name": group.get("name"),
        "group_type": group.get("group_type"),
        "n_required": group.get("n_required"),
        "credit_hours_required": _credit_hours_as_int(group.get("credit_hours_required"), label, problems),
        "notes_html": notes_html,
        "requires_manual_definition": bool(group.get("requires_manual_definition", False)),
    }


def validate_requirement_group_row(row: dict[str, Any], label: str) -> list[str]:
    """Mirrors requirement_groups' NOT NULL and CHECK constraints -- same
    checks import_requirement_groups.py runs for SMU, since the schema is
    shared.
    """
    problems: list[str] = []

    for column in ("coursedog_rule_id", "name", "group_type", "catalog_year"):
        value = row.get(column)
        if value is None or (isinstance(value, str) and not value.strip()):
            problems.append(f"{label}: {column} is null/empty (NOT NULL)")

    group_type = row.get("group_type")
    if group_type is not None and group_type not in VALID_GROUP_TYPES:
        problems.append(f"{label}: group_type {group_type!r} not one of {VALID_GROUP_TYPES}")

    n_required = row.get("n_required")
    if group_type == "enumerated_at_least_n":
        if not isinstance(n_required, int) or isinstance(n_required, bool) or n_required < 1:
            problems.append(
                f"{label}: group_type is enumerated_at_least_n but n_required is {n_required!r} "
                f"(must be a positive int)"
            )
    elif n_required is not None:
        problems.append(f"{label}: group_type is {group_type!r} but n_required is {n_required!r} (must be null)")

    credit_hours = row.get("credit_hours_required")
    if credit_hours is not None and (
        isinstance(credit_hours, bool) or not isinstance(credit_hours, int) or credit_hours < 0
    ):
        problems.append(f"{label}: credit_hours_required must be a non-negative int or null, got {credit_hours!r}")

    return problems


def normalize_option_logic(source_logic: str | None) -> str | None:
    """See DIFFERENCE 6: the source JSON's "manual" (freeform/no-course
    alternative) has no DB-valid equivalent -- requirement_group_options.
    logic's CHECK only allows 'and'/'or'. Normalized to 'and', which is
    arbitrary-but-safe for an option with zero linked course rows (always
    unsatisfied either way). Anything else passes through unchanged.
    """
    return "and" if source_logic == "manual" else source_logic


def _resolves(code: str, resolved_codes: set[str]) -> bool:
    """A plain code resolves if it's directly in course_catalog. A
    "/"-joined cross-listing (DIFFERENCE 3) resolves if EITHER half is --
    TAMU stores each cross-listed department code as its own independent
    row, confirmed live 2026-08-23 (see fetch_tamu_requirements.py and
    requirement_satisfaction_fetch.py's matching docstrings).
    """
    if "/" in code:
        return any(part.strip() in resolved_codes for part in code.split("/"))
    return code in resolved_codes


def build_option_rows(
    group: dict[str, Any], resolved_codes: set[str], warnings: list[str]
) -> tuple[list[dict[str, Any]], list[list[dict[str, Any]]]]:
    """For one enumerated group, return (option rows without
    requirement_group_id yet, parallel list of that option's course rows
    without requirement_group_option_id yet).

    A course_codes entry that doesn't resolve becomes an
    unresolved_course_ref row instead of failing the import (same posture
    as SMU's importer). An option with course_codes == [] at all
    (DIFFERENCE 6 -- a freeform "manual" alternative within a choice
    group) gets zero course rows, flagged via `warnings`, not silently
    skipped.
    """
    option_rows: list[dict[str, Any]] = []
    course_rows_by_option: list[list[dict[str, Any]]] = []

    for option in group.get("options", []):
        option_rows.append(
            {"option_index": option.get("option_index"), "logic": normalize_option_logic(option.get("logic"))}
        )
        codes = option.get("course_codes") or []
        if not codes:
            warnings.append(
                f"group {group.get('rule_id')} ({group.get('name')}) option "
                f"{option.get('option_index')}: no course_codes (freeform/manual alternative, "
                f"e.g. \"or University Core Curriculum\" -- see DIFFERENCE 6) -- option row created "
                f"with zero linked courses, can never resolve SATISFIED"
            )
        course_rows: list[dict[str, Any]] = []
        for code in codes:
            if _resolves(code, resolved_codes):
                course_rows.append({"coursedog_group_id": None, "unresolved_course_ref": None, "course_code": code})
            else:
                course_rows.append({"coursedog_group_id": None, "unresolved_course_ref": code, "course_code": None})
        course_rows_by_option.append(course_rows)

    return option_rows, course_rows_by_option


def validate_option_row(row: dict[str, Any], label: str) -> list[str]:
    problems: list[str] = []
    option_index = row.get("option_index")
    if not isinstance(option_index, int) or isinstance(option_index, bool) or option_index < 0:
        problems.append(f"{label}: option_index must be a non-negative int, got {option_index!r}")
    if row.get("logic") not in ("and", "or"):
        problems.append(f"{label}: logic must be 'and' or 'or', got {row.get('logic')!r}")
    return problems


# ── Supabase-touching functions ─────────────────────────────────────────────


def resolve_institution(client: Client) -> str:
    rows = client.table("institutions").select("id,name").eq("name", INSTITUTION_NAME).execute().data
    if not rows:
        stop(f"No institutions row named {INSTITUTION_NAME!r}.")
    if len(rows) > 1:
        stop(f"Ambiguous: {len(rows)} institutions rows named {INSTITUTION_NAME!r}.")
    return rows[0]["id"]


def fetch_resolved_course_codes(client: Client, institution_id: str) -> set[str]:
    """All course_catalog.code values for this institution -- paginated,
    same reasoning as import_requirement_groups.py's
    fetch_resolved_coursedog_group_ids (course_catalog is thousands of
    rows; PostgREST default-limits a single select).
    """
    resolved: set[str] = set()
    page_size = 1000
    offset = 0
    while True:
        rows = (
            client.table("course_catalog")
            .select("code")
            .eq("institution_id", institution_id)
            .range(offset, offset + page_size - 1)
            .execute()
            .data
        )
        if not rows:
            break
        resolved.update(row["code"] for row in rows if row.get("code"))
        if len(rows) < page_size:
            break
        offset += page_size
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="path to a normalized JSON file from fetch_tamu_requirements.py")
    parser.add_argument("--write", action="store_true", help="perform the writes; without this, report only")
    args = parser.parse_args()

    if not args.input.exists():
        stop(f"{args.input} does not exist.")

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    program = payload.get("program") or {}
    catalog_year = payload.get("catalog_year")
    groups = payload.get("groups") or []
    footnotes = payload.get("footnotes") or {}

    print(f"mode: {'WRITE' if args.write else 'DRY RUN (no writes)'}")
    print(f"input: {args.input}")
    print(f"source: {payload.get('source')!r}")
    print(f"program: {program.get('name')} ({program.get('code')})")
    print(f"catalog_year: {catalog_year}")
    print(f"groups in file: {len(groups)}")

    if footnotes:
        print(
            f"\nFOOTNOTES NOT IMPORTED -- {len(footnotes)} footnote(s) in the source JSON "
            f"(footnotes_enforced: {payload.get('footnotes_enforced')!r}) have no database column to "
            f"land in this pass -- see DIFFERENCE 5 in this script's module docstring. The source JSON "
            f"file remains the only place footnote text is captured. Not a bug; a scoped-out decision."
        )

    # ── Validate before touching the network ───────────────────────────────
    problems: list[str] = []
    warnings: list[str] = []

    program_row_template = to_program_row(program, institution_id="<pending>", catalog_year=catalog_year)
    problems.extend(validate_program_row(program_row_template))

    known_rule_ids = {g.get("rule_id") for g in groups}
    for group in groups:
        label = f"group {group.get('rule_id')} ({group.get('name')})"
        row = to_requirement_group_row(group, program_id="<pending>", catalog_year=catalog_year, problems=problems)
        problems.extend(validate_requirement_group_row(row, label))

        parent_id = group.get("parent_rule_id")
        if parent_id is not None and parent_id not in known_rule_ids:
            problems.append(f"{label}: parent_rule_id {parent_id!r} is not among this file's own groups")

        if group.get("group_type") in ENUMERATED_GROUP_TYPES:
            for option in group.get("options", []):
                option_label = f"{label} option {option.get('option_index')}"
                problems.extend(
                    validate_option_row(
                        {
                            "option_index": option.get("option_index"),
                            "logic": normalize_option_logic(option.get("logic")),
                        },
                        option_label,
                    )
                )
        elif group.get("options"):
            problems.append(
                f"{label}: group_type {group.get('group_type')!r} should carry no options, "
                f"but {len(group['options'])} present"
            )

    print("\n-- Validation --")
    if problems:
        print(f"  {len(problems)} problem(s):")
        for problem in problems[:50]:
            print(f"    {problem}")
        if len(problems) > 50:
            print(f"    ... and {len(problems) - 50} more")
        stop("Refusing to proceed: fix the problems above first. Nothing was written.")
    else:
        print("  0 problems.")

    if not args.write:
        print("\nDRY RUN — no writes were performed. Re-run with --write to apply.")
        return 0

    load_dotenv(PROJECT_ROOT / ".env")
    url = os.environ.get("SUPABASE_URL")
    secret_key = os.environ.get("SUPABASE_SECRET_KEY")
    if not url or not secret_key:
        stop("SUPABASE_URL and/or SUPABASE_SECRET_KEY are not set in .env.")

    client: Client = create_client(url, secret_key)
    try:
        _write(client, program, catalog_year, groups, warnings)
    except Exception:
        print(
            "\nERROR: write phase failed partway through -- see traceback below. Same idempotent-rerun "
            "guarantee as import_requirement_groups.py: re-running this exact script against this same "
            "input file, with no manual cleanup, converges to the correct end state.",
            file=sys.stderr,
        )
        raise
    return 0


def _write(
    client: Client, program: dict[str, Any], catalog_year: str, groups: list[dict[str, Any]], warnings: list[str]
) -> None:
    institution_id = resolve_institution(client)
    print(f"\nresolved institution: {INSTITUTION_NAME} ({institution_id})")

    program_row = to_program_row(program, institution_id=institution_id, catalog_year=catalog_year)
    program_result = (
        client.table("programs").upsert(program_row, on_conflict="institution_id,coursedog_program_id").execute()
    )
    if not program_result.data:
        stop(f"programs upsert for {program_row['code']!r} returned no rows.")
    program_id = program_result.data[0]["id"]
    print(f"program upserted: {program_id}")

    resolved_codes = fetch_resolved_course_codes(client, institution_id)
    print(f"course_catalog code values known for TAMU: {len(resolved_codes)}")

    problems_ignored: list[str] = []  # already validated in main(); rows are known-good here
    group_rows = [
        to_requirement_group_row(group, program_id=program_id, catalog_year=catalog_year, problems=problems_ignored)
        for group in groups
    ]
    result = client.table("requirement_groups").upsert(group_rows, on_conflict="program_id,coursedog_rule_id").execute()
    id_by_rule_id = {row["coursedog_rule_id"]: row["id"] for row in result.data}
    print(f"requirement_groups upserted: {len(id_by_rule_id)}")

    for group in groups:
        if group.get("modeling_confidence") == "inferred":
            print(
                f"  MODELING NOTE surfaced on {group['name']!r} ({id_by_rule_id[group['rule_id']]}) -- "
                f"see DIFFERENCE 4, notes_html on this row."
            )

    parent_updates = 0
    for group in groups:
        parent_rule_id = group.get("parent_rule_id")
        if parent_rule_id is None:
            continue
        child_id = id_by_rule_id[group["rule_id"]]
        parent_id = id_by_rule_id[parent_rule_id]
        client.table("requirement_groups").update({"parent_group_id": parent_id}).eq("id", child_id).execute()
        parent_updates += 1
    print(f"parent_group_id set on {parent_updates} row(s)")

    enumerated_group_ids = [
        id_by_rule_id[g["rule_id"]] for g in groups if g.get("group_type") in ENUMERATED_GROUP_TYPES
    ]
    if enumerated_group_ids:
        client.table("requirement_group_options").delete().in_("requirement_group_id", enumerated_group_ids).execute()

    options_written = 0
    courses_written = 0
    unresolved_refs = 0
    for group in groups:
        if group.get("group_type") not in ENUMERATED_GROUP_TYPES:
            continue
        group_id = id_by_rule_id[group["rule_id"]]
        option_rows, course_rows_by_option = build_option_rows(group, resolved_codes, warnings)
        for option_row in option_rows:
            option_row["requirement_group_id"] = group_id
        inserted_options = (
            client.table("requirement_group_options").insert(option_rows).execute().data if option_rows else []
        )
        options_written += len(inserted_options)

        all_course_rows: list[dict[str, Any]] = []
        for option_result, course_rows in zip(inserted_options, course_rows_by_option):
            for course_row in course_rows:
                course_row = dict(course_row)
                course_row["requirement_group_option_id"] = option_result["id"]
                if course_row["unresolved_course_ref"] is not None:
                    unresolved_refs += 1
                all_course_rows.append(course_row)
        if all_course_rows:
            client.table("requirement_group_option_courses").insert(all_course_rows).execute()
            courses_written += len(all_course_rows)

    print(f"requirement_group_options written: {options_written}")
    print(f"requirement_group_option_courses written: {courses_written} ({unresolved_refs} unresolved_course_ref)")

    if warnings:
        print(f"\n{len(warnings)} warning(s) (not failures):")
        for warning in warnings:
            print(f"  {warning}")


if __name__ == "__main__":
    raise SystemExit(main())
