"""Mock student importer: writes the five data/students/student_*.json mock
students into Supabase (auth users + the schema from
supabase/migrations/20260728000103_institution_grading_schema.sql).

Safe to re-run: every write is planned as an application-level
check-then-write "upsert" keyed on a natural key (query by the natural
key first; update the existing row if found, otherwise insert). This is
deliberate rather than relying on Postgres `ON CONFLICT`: the applied
migration only has a genuine unique constraint backing one of the
natural keys used here (career_profiles.student_id); the rest
(students.auth_user_id, student_institutions(student_id,
institution_id), academic_terms(student_id, sequence),
course_records(student_id, term_id, course_code), and the natural keys
on certifications/work_experience/projects) have no unique index, so a
native `ON CONFLICT` upsert would fail with a missing-constraint error.
Re-running this script must not modify the migration to add those
constraints, so idempotency is enforced here in the script instead.

Modes:
  (no flags)  dry run — plans every write, prints what would be
              created/updated per table, writes nothing.
  --write     performs the writes, then runs the read-back and RLS
              verification described in the task.

Connects using SUPABASE_URL / SUPABASE_SECRET_KEY from .env. Never
prints a key value.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from supabase import Client, create_client

from GradusIQ_career.academics.gpa import (
    CourseRecord,
    GradeMapRow,
    Institution,
    compute_both,
    resolve_grade,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STUDENTS_DIR = PROJECT_ROOT / "data" / "students"


def stop(message: str) -> None:
    print(f"\nSTOP: {message}")
    sys.exit(1)


def email_for_name(name: str) -> str:
    parts = name.strip().split()
    first, last = parts[0], parts[-1]
    return f"{first.lower()}.{last.lower()}@gradusiq.test"


# ---------------------------------------------------------------------------
# Generic application-level upsert: find by natural key, update or insert.
# ---------------------------------------------------------------------------


def find_existing(client: Client, table: str, filters: dict):
    query = client.table(table).select("*")
    for key, value in filters.items():
        query = query.eq(key, value)
    rows = query.execute().data
    if len(rows) > 1:
        raise RuntimeError(
            f"ambiguous natural key on {table}: {filters!r} matched {len(rows)} rows"
        )
    return rows[0] if rows else None


def plan_upsert(client: Client, table: str, filters: dict, desired: dict, write_mode: bool):
    """Returns (action, row) where action is 'create' or 'update' and row is
    the resulting row (existing+desired merged in dry run, or the real
    written row in write mode)."""
    existing = find_existing(client, table, filters)
    if existing is not None:
        if write_mode:
            client.table(table).update(desired).eq("id", existing["id"]).execute()
        return "update", {**existing, **desired}

    payload = {**filters, **desired}
    if write_mode:
        written = client.table(table).insert(payload).execute().data[0]
        return "create", written
    return "create", payload


def skip_downstream(action: str) -> bool:
    """If a parent row's action is 'create' in dry-run mode (no real id
    exists), every dependent row must also be a create — nothing can
    already reference an id that doesn't exist yet."""
    return action == "create"


# ---------------------------------------------------------------------------
# Reference data loaded from the live database (never hardcoded here).
# ---------------------------------------------------------------------------


def load_institutions(client: Client) -> dict:
    rows = client.table("institutions").select("*").execute().data
    return {row["name"]: row for row in rows}


def load_grade_maps(client: Client) -> dict:
    rows = client.table("grade_point_map").select("*").execute().data
    grade_maps: dict[str, dict[str, GradeMapRow]] = {}
    for row in rows:
        grade_maps.setdefault(row["institution_id"], {})[row["letter"]] = GradeMapRow(
            letter=row["letter"],
            points=row["points"],
            counts_toward_gpa=row["counts_toward_gpa"],
            counts_toward_credit=row["counts_toward_credit"],
        )
    return grade_maps


def load_existing_auth_users(client: Client) -> dict:
    # Explicit per_page: the default list_users() page size could otherwise
    # silently miss existing users once the project has more than one page,
    # which would make this script attempt to recreate an existing account.
    users = client.auth.admin.list_users(page=1, per_page=1000)
    return {u.email.lower(): u for u in users if u.email}


# ---------------------------------------------------------------------------
# Per-student planning / import
# ---------------------------------------------------------------------------


class Counters:
    def __init__(self):
        self.created: dict[str, int] = {}
        self.updated: dict[str, int] = {}

    def record(self, table: str, action: str):
        bucket = self.created if action == "create" else self.updated
        bucket[table] = bucket.get(table, 0) + 1

    def report(self):
        tables = sorted(set(self.created) | set(self.updated))
        print(f"{'table':<22} {'would create':>14} {'would update':>14}")
        print("-" * 52)
        for t in tables:
            print(f"{t:<22} {self.created.get(t, 0):>14} {self.updated.get(t, 0):>14}")


def process_student(
    client: Client,
    path: Path,
    institutions_by_name: dict,
    grade_maps_by_institution_id: dict,
    existing_users: dict,
    test_password: str,
    write_mode: bool,
    counters: Counters,
):
    student_json = json.loads(path.read_text())
    student = student_json["student"]
    name = student["name"]
    email = email_for_name(name)

    print(f"\n--- {name} ({path.name}) -> {email} ---")

    # -- Auth account -------------------------------------------------
    existing_user = existing_users.get(email)
    if existing_user is not None:
        auth_action = "reuse"
        auth_user_id = existing_user.id
        print(f"  auth user: reuse existing ({auth_user_id})")
    else:
        auth_action = "create"
        auth_user_id = None
        print("  auth user: would create (email_confirm=true)")
        if write_mode:
            created = client.auth.admin.create_user(
                {
                    "email": email,
                    "password": test_password,
                    "email_confirm": True,
                }
            )
            auth_user_id = created.user.id
            print(f"    created auth user {auth_user_id}")

    # -- institutions ---------------------------------------------------
    institution_name = student["institution"]
    institution_row = institutions_by_name.get(institution_name)
    if institution_row is None:
        stop(
            f"{name}: student.institution {institution_name!r} has no exact match in "
            "institutions — refusing to create one. Fix the seed data or the student "
            "record, then re-run."
        )
    home_institution_id = institution_row["id"]
    institution = Institution(
        id=home_institution_id,
        name=institution_row["name"],
        uses_plus_minus=institution_row["uses_plus_minus"],
        transfer_grades_count_toward_gpa=institution_row["transfer_grades_count_toward_gpa"],
    )
    grade_map = grade_maps_by_institution_id.get(home_institution_id, {})

    # -- students ---------------------------------------------------
    if auth_action == "create" and not write_mode:
        # No real auth_user_id yet in dry-run; nothing downstream can exist.
        student_action = "create"
        student_row = {
            "auth_user_id": "<to be created>",
            "name": student["name"],
            "classification": student.get("classification"),
            "major_current": student.get("major_current"),
            "major_intended": student.get("major_intended"),
            "expected_graduation": student.get("expected_graduation"),
            "onboarding_stage": student.get("onboarding_stage"),
        }
        student_id = None
    else:
        student_desired = {
            "name": student["name"],
            "classification": student.get("classification"),
            "major_current": student.get("major_current"),
            "major_intended": student.get("major_intended"),
            "expected_graduation": student.get("expected_graduation"),
            "onboarding_stage": student.get("onboarding_stage"),
        }
        student_action, student_row = plan_upsert(
            client, "students", {"auth_user_id": auth_user_id}, student_desired, write_mode
        )
        student_id = student_row.get("id")

    counters.record("students", student_action)
    print(f"  students: {student_action}")

    # -- student_institutions ---------------------------------------
    if student_id is None:
        si_action = "create"
        print("  student_institutions: create (pending parent)")
    else:
        si_desired = {"relationship": "home"}
        si_action, _ = plan_upsert(
            client,
            "student_institutions",
            {"student_id": student_id, "institution_id": home_institution_id},
            si_desired,
            write_mode,
        )
        print(f"  student_institutions: {si_action}")
    counters.record("student_institutions", si_action)

    # -- academic_terms (exactly one: 'Current Term', sequence 1) ---
    if student_id is None:
        term_action = "create"
        term_id = None
        print("  academic_terms: create (pending parent)")
    else:
        term_desired = {
            "label": "Current Term",
            "year": datetime.now(timezone.utc).year,
            "season": "current",
            "institution_id": home_institution_id,
        }
        term_action, term_row = plan_upsert(
            client,
            "academic_terms",
            {"student_id": student_id, "sequence": 1},
            term_desired,
            write_mode,
        )
        term_id = term_row.get("id")
        print(f"  academic_terms: {term_action}")
    counters.record("academic_terms", term_action)

    # -- course_records: one per enrollment --------------------------
    courses_by_id = {c["id"]: c for c in student_json["courses"]}
    unmatched = []
    course_actions = []
    normalized_or_unmapped = []

    for enrollment in student_json["enrollments"]:
        course_id = enrollment["course_id"]
        course = courses_by_id.get(course_id)
        if course is None:
            unmatched.append(enrollment)
            continue

        grades = enrollment.get("grades", {})
        final_grade = grades.get("final_grade")
        current_grade = grades.get("current_grade")
        letter_grade = final_grade if final_grade is not None else current_grade
        status = "completed" if final_grade is not None else "in_progress"

        resolution = resolve_grade(letter_grade, institution, grade_map)
        if resolution.match_type in ("normalized", "unmapped"):
            normalized_or_unmapped.append((course["course_code"], resolution))

        course_desired = {
            "title": course["name"],
            "credit_hours": course["credit_hours"],
            "letter_grade": letter_grade,
            "status": status,
            "credit_type": "resident",
            "source": "manual",
            "confirmed_at": datetime.now(timezone.utc).isoformat(),
            "counts_toward_credit": resolution.counts_toward_credit,
            "counts_toward_gpa": resolution.counts_toward_gpa,
            "institution_id": home_institution_id,
        }

        if student_id is None or term_id is None:
            action = "create"
        else:
            action, _ = plan_upsert(
                client,
                "course_records",
                {
                    "student_id": student_id,
                    "term_id": term_id,
                    "course_code": course["course_code"],
                },
                course_desired,
                write_mode,
            )
        course_actions.append(action)
        counters.record("course_records", action)

    if unmatched:
        details = ", ".join(
            f"enrollment id={e.get('id')} course_id={e.get('course_id')}" for e in unmatched
        )
        stop(f"{name}: enrollment(s) with no matching courses[] row: {details}")

    print(
        f"  course_records: {course_actions.count('create')} create, "
        f"{course_actions.count('update')} update"
    )
    if normalized_or_unmapped:
        print("    grade resolution flags:")
        for code, res in normalized_or_unmapped:
            print(
                f"      {code}: letter={res.letter_input!r} match_type={res.match_type} "
                f"resolved={res.letter_resolved!r}"
            )

    # -- career_profiles ---------------------------------------------
    career = student_json["career"]
    skills = career.get("skills_self_reported", {})
    career_desired = {
        "target_roles": career.get("target_roles"),
        "interests": career.get("interests"),
        "career_goals": career.get("career_goals"),
        "geographic_preference": career.get("geographic_preference"),
        "ai_anxiety_level": career.get("ai_anxiety_level"),
        "skills_technical": skills.get("technical"),
        "skills_soft": skills.get("soft"),
        "ai_exposure": skills.get("ai_exposure"),
    }

    if student_id is None:
        career_action = "create"
        career_profile_id = None
        print("  career_profiles: create (pending parent)")
    else:
        career_action, career_row = plan_upsert(
            client, "career_profiles", {"student_id": student_id}, career_desired, write_mode
        )
        career_profile_id = career_row.get("id")
        print(f"  career_profiles: {career_action}")
    counters.record("career_profiles", career_action)

    # -- certifications / work_experience / projects -----------------
    def child_rows(child_table, entries, natural_key_fields, desired_fields_fn):
        if career_profile_id is None or student_id is None:
            for _ in entries:
                counters.record(child_table, "create")
            if entries:
                print(f"  {child_table}: {len(entries)} create (pending parent)")
            return

        create_n = update_n = 0
        for entry in entries:
            filters = {"student_id": student_id}
            filters.update({k: entry.get(k) for k in natural_key_fields})
            desired = desired_fields_fn(entry)
            desired["career_profile_id"] = career_profile_id
            action, _ = plan_upsert(client, child_table, filters, desired, write_mode)
            counters.record(child_table, action)
            if action == "create":
                create_n += 1
            else:
                update_n += 1
        if entries:
            print(f"  {child_table}: {create_n} create, {update_n} update")

    child_rows(
        "certifications",
        career.get("certifications", []),
        ["name"],
        lambda e: {"issuer": e.get("issuer"), "status": e.get("status"), "date": e.get("date")},
    )
    child_rows(
        "work_experience",
        career.get("work_experience", []),
        ["employer", "role"],
        lambda e: {
            "duration": e.get("duration"),
            "location": e.get("location"),
            "description": e.get("description"),
            "skills_gained": e.get("skills_gained"),
        },
    )
    child_rows(
        "projects",
        career.get("projects", []),
        ["name"],
        lambda e: {
            "timeframe": e.get("timeframe"),
            "description": e.get("description"),
            "tools": e.get("tools"),
        },
    )

    return {
        "name": name,
        "email": email,
        "pre_baked_gpa": student["gpa_current"],
    }


# ---------------------------------------------------------------------------
# Verification (write mode only)
# ---------------------------------------------------------------------------


def run_verification(client: Client, url: str, publishable_key: str, test_password: str, students_meta: list):
    print("\n" + "=" * 78)
    print("VERIFICATION (post-write read-back)")
    print("=" * 78)

    from GradusIQ_career.academics.gpa import CourseRecord as _CR  # local alias

    institutions_by_name = load_institutions(client)
    grade_maps_by_institution_id = load_grade_maps(client)
    existing_users = load_existing_auth_users(client)

    for meta in students_meta:
        email = meta["email"]
        user = existing_users.get(email)
        if user is None:
            print(f"{meta['name']}: !! auth user not found on read-back")
            continue

        student_row = (
            client.table("students").select("*").eq("auth_user_id", user.id).execute().data
        )
        if not student_row:
            print(f"{meta['name']}: !! no students row on read-back")
            continue
        student_row = student_row[0]
        student_id = student_row["id"]

        counts = {}
        for table in [
            "students",
            "student_institutions",
            "academic_terms",
            "course_records",
            "career_profiles",
            "certifications",
            "work_experience",
            "projects",
        ]:
            filter_col = "id" if table == "students" else "student_id"
            filter_val = student_id if table != "students" else student_id
            rows = client.table(table).select("*").eq(filter_col, filter_val).execute().data
            counts[table] = len(rows)

        si_rows = (
            client.table("student_institutions")
            .select("institution_id, relationship")
            .eq("student_id", student_id)
            .eq("relationship", "home")
            .execute()
            .data
        )
        home_institution_id = si_rows[0]["institution_id"] if si_rows else None
        institution_row = next(
            (row for row in institutions_by_name.values() if row["id"] == home_institution_id),
            None,
        )

        course_rows = (
            client.table("course_records").select("*").eq("student_id", student_id).execute().data
        )
        records = [
            _CR(
                course_code=r["course_code"],
                credit_hours=float(r["credit_hours"]),
                letter_grade=r["letter_grade"],
                credit_type=r["credit_type"],
                status=r["status"],
                institution_id=r["institution_id"],
                confirmed_at=r["confirmed_at"],
                # .get(): the column arrives with select("*") once the
                # repeat-policy migration is applied, and is absent before that.
                excluded_from_gpa_by=r.get("excluded_from_gpa_by"),
            )
            for r in course_rows
        ]

        institution = Institution(
            id=institution_row["id"],
            name=institution_row["name"],
            uses_plus_minus=institution_row["uses_plus_minus"],
            transfer_grades_count_toward_gpa=institution_row["transfer_grades_count_toward_gpa"],
        )
        grade_map = grade_maps_by_institution_id.get(institution_row["id"], {})
        both = compute_both(records, institution, grade_map)

        print(f"\n{meta['name']}:")
        print(f"  row counts: {counts}")
        print(f"  official GPA: {both.official.gpa}")
        print(f"  projected GPA: {both.projected.gpa}")
        matches = both.projected.gpa == meta["pre_baked_gpa"]
        print(f"  pre-baked gpa_current: {meta['pre_baked_gpa']} -> projected matches: {matches}")

    # -- RLS behavioral test as Jordan Reyes --------------------------
    print("\n" + "=" * 78)
    print("RLS BEHAVIORAL TEST — signed in as jordan.reyes@gradusiq.test")
    print("=" * 78)

    jordan_client: Client = create_client(url, publishable_key)
    jordan_client.auth.sign_in_with_password(
        {"email": "jordan.reyes@gradusiq.test", "password": test_password}
    )

    students_visible = jordan_client.table("students").select("*").execute().data
    course_records_visible = jordan_client.table("course_records").select("*").execute().data
    career_profiles_visible = jordan_client.table("career_profiles").select("*").execute().data

    print(f"a. students rows visible: {len(students_visible)} (expected 1)")
    print(f"   course_records rows visible: {len(course_records_visible)}")
    print(f"   career_profiles rows visible: {len(career_profiles_visible)} (expected 1)")
    a_pass = len(students_visible) == 1 and len(career_profiles_visible) == 1
    print(f"   a. PASS: {a_pass}" if a_pass else f"   a. FAIL: {a_pass}")

    priya_email = "priya.nair@gradusiq.test"
    priya_visible_students = [
        s for s in students_visible if s.get("name", "").lower().startswith("priya")
    ]
    b_pass = len(priya_visible_students) == 0
    print(f"b. Priya Nair rows visible to Jordan: {len(priya_visible_students)} (expected 0)")
    print(f"   b. PASS: {b_pass}" if b_pass else f"   b. FAIL: {b_pass}")

    institutions_visible = jordan_client.table("institutions").select("*").execute().data
    gpm_visible = jordan_client.table("grade_point_map").select("*").execute().data
    c_pass = len(institutions_visible) >= 2 and len(gpm_visible) > 0
    print(
        f"c. institutions visible: {len(institutions_visible)}, "
        f"grade_point_map visible: {len(gpm_visible)}"
    )
    print(f"   c. PASS: {c_pass}" if c_pass else f"   c. FAIL: {c_pass}")

    jordan_client.auth.sign_out()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    write_mode = args.write

    load_dotenv(PROJECT_ROOT / ".env")

    url = os.environ.get("SUPABASE_URL")
    secret_key = os.environ.get("SUPABASE_SECRET_KEY")
    publishable_key = os.environ.get("SUPABASE_PUBLISHABLE_KEY")
    test_password = os.environ.get("GRADUSIQ_TEST_PASSWORD")

    if not url or not secret_key:
        stop("SUPABASE_URL and/or SUPABASE_SECRET_KEY are not set in .env.")
    if not test_password:
        stop(
            "GRADUSIQ_TEST_PASSWORD is not set. Set it (in .env or the environment) "
            "before running this script. No password is hardcoded or invented here."
        )

    print(f"mode: {'WRITE' if write_mode else 'DRY RUN (no writes)'}")

    client: Client = create_client(url, secret_key)

    institutions_by_name = load_institutions(client)
    grade_maps_by_institution_id = load_grade_maps(client)
    existing_users = load_existing_auth_users(client)

    counters = Counters()
    students_meta = []

    for path in sorted(STUDENTS_DIR.glob("student_*.json")):
        meta = process_student(
            client,
            path,
            institutions_by_name,
            grade_maps_by_institution_id,
            existing_users,
            test_password,
            write_mode,
            counters,
        )
        students_meta.append(meta)

    print("\n" + "=" * 78)
    print("PLAN SUMMARY" if not write_mode else "WRITE SUMMARY")
    print("=" * 78)
    counters.report()

    if not write_mode:
        print("\nDRY RUN — no writes were performed. Re-run with --write to apply.")
        return

    if publishable_key is None:
        stop("SUPABASE_PUBLISHABLE_KEY not set — cannot run RLS verification.")

    run_verification(client, url, publishable_key, test_password, students_meta)


if __name__ == "__main__":
    main()
