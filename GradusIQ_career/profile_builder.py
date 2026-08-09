"""Reconstruct a student profile dict from Postgres, shaped like the JSON one.

Placed alongside supabase_client.py rather than under features/ because it is a
data-access concern, not a feature concern: every caller already holds a
session-scoped client from build_client_for_token, and the feature runners stay
completely unaware of where their profile dict came from.

The output is structurally interchangeable with what
GradusIQ_career.api.load_student_profile returns from data/students/*.json, so
the runners in features/ need no change to consume it.

UNCONFIRMED ROWS
----------------
Rows whose confirmed_at is null are parser output pending student review. They
are excluded from the profile rather than silently dropped: every exclusion is
recorded as (row, reason) in the returned result, mirroring how
academics/gpa.py already treats "unconfirmed" as a first-class, reportable
reason rather than an invisible filter. Callers may ignore the list today, but
the record exists from the start so a review UI can explain omissions later.
"""

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

# Matches academics/gpa.py's reason string exactly -- one vocabulary for
# "this row exists but was not counted", across GPA and career data alike.
UNCONFIRMED_REASON = "unconfirmed"

# Columns that exist on every career-side row but never appear in the JSON
# shape the runners read. Projected out so the reconstructed dict is
# field-for-field identical to the file-backed one.
_DB_ONLY_FIELDS = frozenset(
    {
        "id",
        "career_profile_id",
        "student_id",
        "created_at",
        "updated_at",
        "source",
        "confirmed_at",
    }
)

_CHILD_TABLES = ("certifications", "work_experience", "projects")


@dataclass(frozen=True)
class ProfileBuildResult:
    """A reconstructed profile plus the rows deliberately left out of it.

    NOTE: the brief specified `-> dict`; returning this dataclass instead is
    the only way to surface `exclusions` alongside the profile, which the same
    brief also required. `.profile` is the plain dict callers pass to runners.
    """

    profile: dict[str, Any]
    exclusions: list[tuple[Mapping[str, Any], str]] = field(default_factory=list)


def _strip_db_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    """Project a DB row down to the keys the JSON shape carries."""
    return {k: v for k, v in row.items() if k not in _DB_ONLY_FIELDS}


def _partition_confirmed(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[tuple[Mapping[str, Any], str]]]:
    """Split rows into (included, excluded-with-reason) on confirmed_at.

    `.get()` rather than subscript: the confirmed_at column arrives with
    select("*") only once the provenance migration is applied, and a row
    predating it must be treated as unconfirmed rather than raising.
    """
    included: list[dict[str, Any]] = []
    excluded: list[tuple[Mapping[str, Any], str]] = []
    for row in rows:
        if row.get("confirmed_at") is None:
            excluded.append((row, UNCONFIRMED_REASON))
            continue
        included.append(_strip_db_fields(row))
    return included, excluded


def _career_block(
    career_row: Mapping[str, Any],
    children: Mapping[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Re-nest the flat career_profiles columns into the JSON career shape.

    The one non-flat mapping: skills_technical / skills_soft / ai_exposure are
    three separate columns that become a single nested skills_self_reported
    object. Note ai_exposure belongs INSIDE that object, not beside
    ai_anxiety_level -- an easy transposition to get wrong.

    Lists default to [] rather than None so the shape matches the JSON files,
    where every list key is always present.
    """
    return {
        "target_roles": career_row.get("target_roles") or [],
        "interests": career_row.get("interests") or [],
        "career_goals": career_row.get("career_goals") or "",
        "geographic_preference": career_row.get("geographic_preference") or "",
        "ai_anxiety_level": career_row.get("ai_anxiety_level") or "",
        "skills_self_reported": {
            "technical": career_row.get("skills_technical") or [],
            "soft": career_row.get("skills_soft") or [],
            "ai_exposure": career_row.get("ai_exposure") or "",
        },
        "certifications": children["certifications"],
        "work_experience": children["work_experience"],
        "projects": children["projects"],
    }


def _student_block(
    student_row: Mapping[str, Any], institution_name: str | None
) -> dict[str, Any]:
    """Shape the students row like the JSON student block.

    gpa_current has no column to source it from -- it is deliberately absent
    from the schema (GPA is always derived; see the students table comment in
    the first migration). Emitted as None so the key exists and consumers can
    guard on it.

    `institution` is resolved by the caller via _resolve_institution_name and
    passed in, since it needs its own two-hop query.

    auth_user_id / created_at / updated_at are projected out: they are not in
    the JSON shape and auth_user_id in particular has no business in a payload
    that ends up inside an LLM prompt.
    """
    return {
        "id": str(student_row["id"]),
        "name": student_row.get("name"),
        "classification": student_row.get("classification"),
        "major_current": student_row.get("major_current"),
        "major_intended": student_row.get("major_intended"),
        "expected_graduation": student_row.get("expected_graduation"),
        "onboarding_stage": student_row.get("onboarding_stage"),
        "institution": institution_name,
        "gpa_current": None,
    }


def _resolve_institution_name(client: Any, student_id: str) -> str | None:
    """The student's home institution name, or None if it can't be resolved.

    Same two-hop join GET /api/v2/student/me/gpa performs: student_institutions
    filtered to relationship='home', then institutions by id.

    Deliberately does NOT raise where the GPA route raises 409. That route is
    computing a GPA, which is meaningless without a grading scale, so incomplete
    reference data has to stop it. This constructor's job is to produce the best
    available profile -- a student with no home institution still has a name, a
    major, and a career block worth analyzing, and FIT/GAP/SHIFT read
    `institution` only as prompt context. Duplicating the 409s here would make a
    recoverable gap fatal at a layer that has no need to enforce it.
    """
    home_rows = (
        client.table("student_institutions")
        .select("institution_id")
        .eq("student_id", student_id)
        .eq("relationship", "home")
        .execute()
        .data
    )
    if not home_rows:
        return None

    institution_rows = (
        client.table("institutions")
        .select("*")
        .eq("id", home_rows[0]["institution_id"])
        .execute()
        .data
    )
    if not institution_rows:
        # Unreachable given the FK on student_institutions.institution_id, but
        # a dangling reference must degrade to null rather than IndexError.
        return None

    return institution_rows[0].get("name")


def build_profile_from_supabase(client: Any, student_id: str) -> ProfileBuildResult:
    """Assemble a runner-compatible profile dict for one student.

    `client` must already be session-scoped (build_client_for_token). RLS is the
    real boundary here: the students select carries no filter at all, exactly as
    GET /api/v2/student/me/gpa does, and the child selects filter on student_id
    only because they need to join, not because they are trusted to isolate.

    Returns career=None when the student has no career_profiles row -- the state
    right after signup, before any parser or manual entry has run. That mirrors
    the file-backed path, whose StudentProfile type declares
    `career: CareerBlock | null` and whose frontend adapter already handles null
    via emptyCareerBlock(). No demo JSON currently exercises it, but it is an
    anticipated shape, not an invented one.
    """
    student_rows = client.table("students").select("*").eq("id", student_id).execute().data
    if not student_rows:
        raise LookupError(f"No students row visible for id {student_id!r}.")
    student_row = student_rows[0]

    # Resolved before any early return so the student block is identical
    # whether or not a career_profiles row exists.
    institution_name = _resolve_institution_name(client, student_id)

    career_rows = (
        client.table("career_profiles").select("*").eq("student_id", student_id).execute().data
    )

    exclusions: list[tuple[Mapping[str, Any], str]] = []

    # No career_profiles row at all -- distinct from an unconfirmed one.
    if not career_rows:
        return ProfileBuildResult(
            profile={
                "student": _student_block(student_row, institution_name),
                "career": None,
            },
            exclusions=exclusions,
        )

    career_row = career_rows[0]

    # An unconfirmed career_profiles row takes the whole career block with it.
    # This is binary by construction: career_profiles is a single row, so there
    # is no schema-level notion of a half-confirmed profile. Returning the
    # scalars while dropping the child lists would be worse -- the runners would
    # see target_roles present and work_experience empty, and read that as "this
    # student has no work history" rather than "nothing here is reviewed yet".
    if career_row.get("confirmed_at") is None:
        exclusions.append((career_row, UNCONFIRMED_REASON))
        return ProfileBuildResult(
            profile={
                "student": _student_block(student_row, institution_name),
                "career": None,
            },
            exclusions=exclusions,
        )

    children: dict[str, list[dict[str, Any]]] = {}
    for table in _CHILD_TABLES:
        rows = client.table(table).select("*").eq("student_id", student_id).execute().data
        included, excluded = _partition_confirmed(rows)
        children[table] = included
        exclusions.extend(excluded)

    return ProfileBuildResult(
        profile={
            "student": _student_block(student_row, institution_name),
            "career": _career_block(career_row, children),
        },
        exclusions=exclusions,
    )
