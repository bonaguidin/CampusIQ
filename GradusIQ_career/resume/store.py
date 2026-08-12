"""Persist parsed resume data through a session-scoped (RLS) Supabase client.

Every function here takes a client built by
GradusIQ_career.supabase_client.build_client_for_token, so Postgres RLS
narrows all reads and writes to the caller's own rows. This module must never
construct its own client and must never read SUPABASE_SECRET_KEY -- doing so
would bypass the only thing keeping one student out of another's record.

DUPLICATE HANDLING. The three child tables carry natural-key unique
constraints, all verified live:

    certifications   certifications_student_name_key           (student_id, name)
    work_experience  work_experience_student_employer_role_key (student_id, employer, role)
                                                               NULLS NOT DISTINCT
    projects         projects_student_name_key                 (student_id, name)

Writes go through .upsert(..., ignore_duplicates=True, on_conflict=<columns>),
which resolves to ON CONFLICT DO NOTHING. Two properties were confirmed
against the live database rather than assumed:

  * PostgREST does infer the work_experience index despite it being a bare
    CREATE UNIQUE INDEX ... NULLS NOT DISTINCT rather than a named constraint,
    so a duplicate whose `role` is NULL is correctly skipped.
  * A conflict target that does not match an index raises 42P10 loudly rather
    than silently choosing another index -- so a wrong ON_CONFLICT here fails
    fast instead of overwriting the wrong row.

With the default returning=representation, an inserted row comes back in
.data and a skipped duplicate comes back as [] -- that difference is how
inserted and skipped are counted apart, with no follow-up read.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from .parser import ParsedResume


RESUME_SOURCE = "resume_parse"

CHILD_TABLES = ("certifications", "work_experience", "projects")
CONFIRMABLE_TABLES = ("career_profiles", *CHILD_TABLES)

ON_CONFLICT = {
    "certifications": "student_id,name",
    "work_experience": "student_id,employer,role",
    "projects": "student_id,name",
}

# career_profiles columns the bootstrap may populate from a parsed resume.
# Deliberately excludes career_goals, geographic_preference, ai_anxiety_level
# and ai_exposure: a resume does not state them, and inventing them here would
# put fabricated data behind an unconfirmed row the student is asked to accept.
PROFILE_COLUMNS = ("target_roles", "interests", "skills_technical", "skills_soft")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TableWriteReport:
    inserted: int = 0
    skipped_duplicate: int = 0

    def to_dict(self) -> dict[str, int]:
        return {"inserted": self.inserted, "skipped_duplicate": self.skipped_duplicate}


@dataclass
class StoreReport:
    career_profile_outcome: str = "unchanged"
    career_profile_id: str | None = None
    tables: dict[str, TableWriteReport] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "career_profile": {
                "outcome": self.career_profile_outcome,
                "id": self.career_profile_id,
            },
            "written": {name: report.to_dict() for name, report in self.tables.items()},
        }


def _rows(response: Any) -> list[dict[str, Any]]:
    data = getattr(response, "data", None)
    return list(data) if data else []


def ensure_career_profile(client: Any, student_id: str, profile: Mapping[str, Any]) -> tuple[str, str]:
    """Return (career_profile_id, outcome).

    outcome is "created" or "already_existed_untouched".

    An existing row is NEVER modified, even when this resume's parsed profile
    differs from what is stored. The existing row may be student-confirmed, and
    a later upload silently rewriting confirmed target_roles would be a
    correctness bug, not a merge. Reconciling a second resume against a
    confirmed profile is a review-screen decision, not a parser decision.
    """
    existing = _rows(
        client.table("career_profiles").select("id").eq("student_id", student_id).execute()
    )
    if existing:
        return existing[0]["id"], "already_existed_untouched"

    payload: dict[str, Any] = {
        "student_id": student_id,
        "source": RESUME_SOURCE,
        "confirmed_at": None,
    }
    for column in PROFILE_COLUMNS:
        payload[column] = list(profile.get(column) or [])

    created = _rows(client.table("career_profiles").insert(payload).execute())
    if not created:
        # Losing a race against a concurrent upload is not an error: the row
        # now exists, which is all the caller needs. student_id is UNIQUE, so
        # the re-read cannot return someone else's row.
        existing = _rows(
            client.table("career_profiles").select("id").eq("student_id", student_id).execute()
        )
        if not existing:
            raise RuntimeError("career_profiles insert returned no row and none is visible.")
        return existing[0]["id"], "already_existed_untouched"

    return created[0]["id"], "created"


def _write_child_rows(
    client: Any,
    table: str,
    items: Iterable[Mapping[str, Any]],
    *,
    student_id: str,
    career_profile_id: str,
) -> TableWriteReport:
    report = TableWriteReport()
    for item in items:
        row = dict(item)
        row.update(
            {
                "student_id": student_id,
                "career_profile_id": career_profile_id,
                "source": RESUME_SOURCE,
                "confirmed_at": None,
            }
        )
        response = (
            client.table(table)
            .upsert(row, ignore_duplicates=True, on_conflict=ON_CONFLICT[table])
            .execute()
        )
        if _rows(response):
            report.inserted += 1
        else:
            report.skipped_duplicate += 1
    return report


def store_parsed_resume(client: Any, student_id: str, parsed: ParsedResume) -> StoreReport:
    """Write a parsed resume's rows. Caller must have checked parsed.status."""
    career_profile_id, outcome = ensure_career_profile(client, student_id, parsed.profile)
    report = StoreReport(career_profile_outcome=outcome, career_profile_id=career_profile_id)

    for table, items in (
        ("certifications", parsed.certifications),
        ("work_experience", parsed.work_experience),
        ("projects", parsed.projects),
    ):
        report.tables[table] = _write_child_rows(
            client,
            table,
            items,
            student_id=student_id,
            career_profile_id=career_profile_id,
        )

    return report


def confirm_career_rows(
    client: Any,
    student_id: str,
    *,
    selection: Mapping[str, Any] | None = None,
) -> dict[str, int]:
    """Stamp confirmed_at on unconfirmed rows for this student.

    With `selection` omitted, confirms everything still unconfirmed. With a
    selection, confirms only the named ids per table (and career_profiles when
    its flag is set), which is what a future review screen needs for
    "confirm these, not those".

    Two filters are always applied and are not caller-controllable:
      * .eq("student_id", student_id) -- belt and braces alongside RLS, which
        already prevents touching another student's rows.
      * .is_("confirmed_at", "null") -- so re-running never rewrites an
        earlier confirmation timestamp, and a supplied id that is already
        confirmed is a no-op rather than a silent backdating.
    """
    stamp = _now_iso()
    confirmed: dict[str, int] = {}

    for table in CONFIRMABLE_TABLES:
        ids: list[str] | None = None
        if selection is not None:
            if table == "career_profiles":
                if not selection.get("career_profile"):
                    confirmed[table] = 0
                    continue
            else:
                raw = selection.get(table)
                ids = [str(value) for value in raw] if raw else []
                if not ids:
                    confirmed[table] = 0
                    continue

        query = (
            client.table(table)
            .update({"confirmed_at": stamp, "updated_at": stamp})
            .eq("student_id", student_id)
            .is_("confirmed_at", "null")
        )
        if ids is not None:
            query = query.in_("id", ids)

        confirmed[table] = len(_rows(query.execute()))

    return confirmed


def write_confirmed_academic_facts(
    client: Any,
    student_id: str,
    academics: Mapping[str, Any] | None,
) -> int:
    """Persist only reviewed, non-null resume facts for the authenticated student."""
    if not academics:
        return 0

    payload: dict[str, str] = {}
    major = academics.get("major_current")
    graduation = academics.get("expected_graduation")
    if isinstance(major, str) and major.strip():
        payload["major_current"] = major.strip()
    if isinstance(graduation, str) and graduation.strip():
        payload["expected_graduation"] = graduation.strip()
    if not payload:
        return 0

    payload["updated_at"] = _now_iso()
    rows = _rows(
        client.table("students").update(payload).eq("id", student_id).execute()
    )
    return len(rows)
