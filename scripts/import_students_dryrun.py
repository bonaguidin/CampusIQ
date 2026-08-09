"""Dry-run: map existing student JSON onto the new schema shape and compute
GPA with GradusIQ_career.academics.gpa, comparing against the pre-baked
gpa_current field. Nothing is written anywhere — no database connection,
no file writes, migration is not applied.

Institution and grade-map data is parsed out of the migration SQL seed
inserts (supabase/migrations/20260728000103_institution_grading_schema.sql)
rather than hardcoded here, so this script tracks whatever that file
actually seeds.
"""

import json
import re
from pathlib import Path

from GradusIQ_career.academics.gpa import (
    CourseRecord,
    GradeMapRow,
    Institution,
    compute_both,
    resolve_grade,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MIGRATION_PATH = (
    PROJECT_ROOT / "supabase" / "migrations" / "20260728000103_institution_grading_schema.sql"
)
STUDENTS_DIR = PROJECT_ROOT / "data" / "students"


# ---------------------------------------------------------------------------
# Minimal SQL literal / tuple-list parsing, tailored to this migration file's
# `insert into ... values (...)` and `cross join (values (...)) as g(...)`
# shapes. Not a general SQL parser.
# ---------------------------------------------------------------------------


def _strip_type_cast(raw: str) -> str:
    return re.sub(r"::[a-zA-Z_]+(\([^)]*\))?", "", raw).strip()


def _parse_sql_literal(raw: str):
    raw = _strip_type_cast(raw.strip())
    lowered = raw.lower()
    if lowered == "null":
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1].replace("''", "'")
    try:
        return int(raw) if "." not in raw else float(raw)
    except ValueError:
        return raw


def _split_fields(text: str) -> list[str]:
    """Split a comma-separated field list, respecting quotes and nested parens."""
    fields = []
    depth = 0
    in_quote = False
    buf = ""
    for ch in text:
        if ch == "'":
            in_quote = not in_quote
            buf += ch
            continue
        if not in_quote:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                fields.append(buf.strip())
                buf = ""
                continue
        buf += ch
    if buf.strip():
        fields.append(buf.strip())
    return fields


def _split_top_level_tuples(text: str) -> list[str]:
    """Given '(a, b), (c, d)' return ['a, b', 'c, d'], preserving nested parens."""
    tuples = []
    depth = 0
    buf = ""
    for ch in text:
        if ch == "(":
            depth += 1
            if depth == 1:
                buf = ""
                continue
        if ch == ")":
            depth -= 1
            if depth == 0:
                tuples.append(buf)
                continue
        if depth >= 1:
            buf += ch
    return tuples


def parse_institutions(sql: str) -> dict[str, Institution]:
    match = re.search(
        r"insert into institutions\s*\(([^)]*)\)\s*values\s*(.*?);",
        sql,
        re.DOTALL,
    )
    if not match:
        raise ValueError("could not find institutions insert in migration SQL")

    columns = [c.strip() for c in match.group(1).split(",")]
    tuples = _split_top_level_tuples(match.group(2))

    institutions: dict[str, Institution] = {}
    for tup in tuples:
        values = [_parse_sql_literal(f) for f in _split_fields(tup)]
        row = dict(zip(columns, values))
        name = row["name"]
        institutions[name] = Institution(
            id=name,
            name=name,
            uses_plus_minus=row["uses_plus_minus"],
            transfer_grades_count_toward_gpa=row["transfer_grades_count_toward_gpa"],
        )
    return institutions


def parse_grade_point_maps(sql: str, institution_names: list[str]) -> dict[str, dict[str, GradeMapRow]]:
    grade_maps: dict[str, dict[str, GradeMapRow]] = {name: {} for name in institution_names}

    # Each `insert into grade_point_map ... ; ` statement in the file.
    statements = re.findall(
        r"insert into grade_point_map\s*\([^)]*\)\s*select\s+(.*?)\s*from institutions\s*"
        r"cross join \(values(.*?)\) as g\(([^)]*)\)\s*where institutions\.name\s*(=|in)\s*(.*?);",
        sql,
        re.DOTALL,
    )

    for select_list_raw, values_block, g_cols_raw, op, where_raw in statements:
        select_exprs = [s.strip() for s in select_list_raw.split(",")]
        # select_exprs[0] = id, select_exprs[1] = letter (name lookup),
        # select_exprs[2:5] = points, counts_toward_gpa, counts_toward_credit
        g_cols = [c.strip() for c in g_cols_raw.split(",")]
        tuples = _split_top_level_tuples(values_block)
        rows = []
        for tup in tuples:
            values = [_parse_sql_literal(f) for f in _split_fields(tup)]
            rows.append(dict(zip(g_cols, values)))

        def resolve_expr(expr: str, row: dict):
            if expr in row:
                return row[expr]
            return _parse_sql_literal(expr)

        if op == "=":
            target_names = [_parse_sql_literal(where_raw.strip())]
        else:  # 'in (...)'
            in_list = where_raw.strip()
            if in_list.startswith("(") and in_list.endswith(")"):
                in_list = in_list[1:-1]
            target_names = [_parse_sql_literal(f) for f in _split_fields(in_list)]

        for row in rows:
            letter = resolve_expr(select_exprs[1], row)
            points = resolve_expr(select_exprs[2], row)
            counts_toward_gpa = resolve_expr(select_exprs[3], row)
            counts_toward_credit = resolve_expr(select_exprs[4], row)
            grade_row = GradeMapRow(
                letter=letter,
                points=points,
                counts_toward_gpa=counts_toward_gpa,
                counts_toward_credit=counts_toward_credit,
            )
            for name in target_names:
                if name in grade_maps:
                    grade_maps[name][letter] = grade_row

    return grade_maps


# ---------------------------------------------------------------------------
# Student JSON -> CourseRecord mapping
# ---------------------------------------------------------------------------


def build_course_records(student_json: dict) -> tuple[list[CourseRecord], list[dict]]:
    courses_by_id = {c["id"]: c for c in student_json["courses"]}
    institution_name = student_json["student"]["institution"]

    records = []
    unmatched_enrollments = []

    for enrollment in student_json["enrollments"]:
        course_id = enrollment["course_id"]
        course = courses_by_id.get(course_id)
        if course is None:
            unmatched_enrollments.append(enrollment)
            continue

        grades = enrollment.get("grades", {})
        final_grade = grades.get("final_grade")
        current_grade = grades.get("current_grade")
        letter_grade = final_grade if final_grade is not None else current_grade
        status = "completed" if final_grade is not None else "in_progress"

        records.append(
            CourseRecord(
                course_code=course["course_code"],
                credit_hours=float(course["credit_hours"]),
                letter_grade=letter_grade,
                credit_type="resident",
                status=status,
                institution_id=institution_name,
                confirmed_at="mock-data-confirmed",
            )
        )

    return records, unmatched_enrollments


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def main():
    sql = MIGRATION_PATH.read_text()
    institutions = parse_institutions(sql)
    grade_maps = parse_grade_point_maps(sql, list(institutions.keys()))

    print("Parsed institutions from migration SQL:")
    for name, inst in institutions.items():
        print(f"  {name}: uses_plus_minus={inst.uses_plus_minus}, "
              f"transfer_grades_count_toward_gpa={inst.transfer_grades_count_toward_gpa}")
    print("Parsed grade_point_map sizes:")
    for name, gmap in grade_maps.items():
        print(f"  {name}: {sorted(gmap.keys())}")
    print()

    summary_rows = []

    for path in sorted(STUDENTS_DIR.glob("student_*.json")):
        student_json = json.loads(path.read_text())
        name = student_json["student"]["name"]
        institution_name = student_json["student"]["institution"]
        pre_baked_gpa = student_json["student"]["gpa_current"]

        institution = institutions.get(institution_name)
        grade_map = grade_maps.get(institution_name, {})

        print("=" * 78)
        print(f"{name}  ({path.name})")
        print("=" * 78)
        print(f"institution:      {institution_name}")
        print(f"pre-baked gpa_current: {pre_baked_gpa}")

        if institution is None:
            print(f"  !! no institution seed matched name {institution_name!r} — skipping")
            summary_rows.append((name, pre_baked_gpa, None, None))
            continue

        records, unmatched = build_course_records(student_json)

        if unmatched:
            print(f"  !! {len(unmatched)} enrollment(s) with no matching courses[] row:")
            for enr in unmatched:
                print(f"       enrollment id={enr.get('id')} course_id={enr.get('course_id')}")

        both = compute_both(records, institution, grade_map)

        print(f"official GPA:     {both.official.gpa}")
        print(f"projected GPA:    {both.projected.gpa}")
        print(f"completed_hours:  {both.completed_hours}")
        print(f"in_progress_hours:{both.in_progress_hours}")
        print(f"earned_hours (official): {both.official.earned_hours}")
        print(f"earned_hours (projected): {both.projected.earned_hours}")

        print("excluded (official):")
        if not both.official.excluded:
            print("  (none)")
        for record, reason in both.official.excluded:
            print(f"  {record.course_code}: grade={record.letter_grade!r} "
                  f"credit_type={record.credit_type} status={record.status} -> {reason}")

        print("excluded (projected):")
        if not both.projected.excluded:
            print("  (none)")
        for record, reason in both.projected.excluded:
            print(f"  {record.course_code}: grade={record.letter_grade!r} "
                  f"credit_type={record.credit_type} status={record.status} -> {reason}")

        print("grades with match_type in {'normalized', 'unmapped'}:")
        any_flagged = False
        for record in records:
            resolution = resolve_grade(record.letter_grade, institution, grade_map)
            if resolution.match_type in ("normalized", "unmapped"):
                any_flagged = True
                print(f"  {record.course_code}: letter_input={resolution.letter_input!r} "
                      f"-> match_type={resolution.match_type} letter_resolved={resolution.letter_resolved!r} "
                      f"points={resolution.points}")
        if not any_flagged:
            print("  (none)")

        print()
        summary_rows.append((name, pre_baked_gpa, both.official.gpa, both.projected.gpa))

    print("=" * 78)
    print("SUMMARY: pre-baked vs official vs projected")
    print("=" * 78)
    header = f"{'name':<20} {'pre-baked':>10} {'official':>10} {'projected':>10}"
    print(header)
    print("-" * len(header))
    for name, pre_baked, official, projected in summary_rows:
        print(f"{name:<20} {pre_baked!s:>10} {official!s:>10} {projected!s:>10}")


if __name__ == "__main__":
    main()
