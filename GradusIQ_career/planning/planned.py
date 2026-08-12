"""Read and write planned_courses.

Everything here runs under the caller's own session client, so RLS
(planned_courses_owner_all) is the real access control and the explicit
student_id filters below are belt-and-braces alongside it -- the same posture
transcript/store.py takes on course_records.

NOTHING HERE TOUCHES course_records. A planned course that later turns into
real coursework is Phase 2; this module has no notion of fulfilment, no write
path into course_records, and no read of one.

TERM ROWS ARE CREATED ON DEMAND
-------------------------------
planned_courses.term_id points at academic_terms, whose rows are per student --
so planning a course for a term the student has never enrolled in requires
creating that term row first. ensure_term_row does it, reusing an existing row
by (year, season) exactly as transcript/terms.py does, and assigning `sequence`
the same append-after-max way for the same reason (renumbering would rewrite
ordinals that already-stored rows depend on).

That is a deliberate small duplication of terms.resolve_terms rather than a
call into it: resolve_terms takes printed transcript labels, returns a
TermResolution keyed on those labels, and reports parse errors as a batch. Here
the (year, season) is already known and validated -- it came from the term
dropdown, not from a PDF -- so the transcript-shaped entry point would mean
manufacturing a label string only for it to be parsed straight back.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from ..transcript.store_helpers import rows_of
from ..transcript.terms import SEASON_ORDER

MAX_COURSE_CODE_LENGTH = 32
MAX_TITLE_LENGTH = 200
# course_records.credit_hours is numeric(4,2); planned_courses matches it, so
# the same ceiling applies. A variable-credit course tops out at 23 credits in
# the live catalog.
MAX_CREDIT_HOURS = Decimal("99.99")


class PlannedCourseError(ValueError):
    """Invalid input from the caller. Maps to 422."""


@dataclass(frozen=True)
class PlannedCourse:
    id: str
    term_id: str | None
    course_code: str
    title: str | None
    credit_hours: float | None
    catalog_course_id: str | None
    created_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "term_id": self.term_id,
            "course_code": self.course_code,
            "title": self.title,
            "credit_hours": self.credit_hours,
            "catalog_course_id": self.catalog_course_id,
            "created_at": self.created_at,
            # Constant, not a column. The frontend renders planned courses in
            # the same term view as course_records rows, and this is what tells
            # the two apart in a payload where both are "a course in a term".
            "kind": "planned",
        }


def _row_to_planned(row: Mapping[str, Any]) -> PlannedCourse:
    credit_hours = row.get("credit_hours")
    return PlannedCourse(
        id=str(row["id"]),
        term_id=str(row["term_id"]) if row.get("term_id") else None,
        course_code=str(row.get("course_code") or ""),
        title=row.get("title"),
        credit_hours=float(credit_hours) if credit_hours is not None else None,
        catalog_course_id=(
            str(row["catalog_course_id"]) if row.get("catalog_course_id") else None
        ),
        created_at=row.get("created_at"),
    )


def clean_course_code(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlannedCourseError("course_code is required.")
    code = " ".join(value.split())
    if len(code) > MAX_COURSE_CODE_LENGTH:
        raise PlannedCourseError(
            f"course_code must be {MAX_COURSE_CODE_LENGTH} characters or fewer."
        )
    return code


def clean_title(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise PlannedCourseError("title must be a string.")
    title = " ".join(value.split())
    if not title:
        return None
    return title[:MAX_TITLE_LENGTH]


def clean_credit_hours(value: Any) -> str | None:
    """Nullable here, unlike on course_records -- see the migration's comment.

    Returned as a string: PostgREST serializes the payload as JSON, which has
    no Decimal, and float() would reintroduce binary rounding on a
    numeric(4,2) column. Same reasoning as transcript/store.py's payload.
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise PlannedCourseError("credit_hours must be a number.")
    try:
        hours = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise PlannedCourseError(f"credit_hours must be a number; got {value!r}.") from exc
    if hours < 0:
        raise PlannedCourseError("credit_hours cannot be negative.")
    if hours > MAX_CREDIT_HOURS:
        raise PlannedCourseError(f"credit_hours cannot exceed {MAX_CREDIT_HOURS}.")
    return str(hours.quantize(Decimal("0.01")))


def ensure_term_row(
    client: Any,
    student_id: str,
    institution_id: str,
    year: int,
    season: str,
    label: str | None = None,
) -> str:
    """academic_terms.id for (year, season), creating the row if needed.

    Reuse is by (year, season) and never by label -- the same rule, and the
    same reason, as terms.resolve_terms: "Fall 2026" and "Fall 2026 - College
    Station" are one term, and a duplicate term row would split a student's
    coursework across two entries in the dropdown.
    """
    if season not in SEASON_ORDER:
        raise PlannedCourseError(
            f"Unrecognized season {season!r}. Expected one of: "
            f"{', '.join(sorted(SEASON_ORDER, key=lambda s: SEASON_ORDER[s]))}."
        )
    try:
        year_value = int(year)
    except (TypeError, ValueError) as exc:
        raise PlannedCourseError(f"year must be an integer; got {year!r}.") from exc

    existing = rows_of(
        client.table("academic_terms")
        .select("id,year,season,sequence")
        .eq("student_id", student_id)
        .execute()
    )
    for row in existing:
        if row.get("year") is None or row.get("season") is None:
            continue
        if int(row["year"]) == year_value and str(row["season"]) == season:
            return str(row["id"])

    next_sequence = max((int(r.get("sequence") or 0) for r in existing), default=-1) + 1
    inserted = rows_of(
        client.table("academic_terms")
        .insert(
            {
                "student_id": student_id,
                "institution_id": institution_id,
                "label": label or f"{season} {year_value}",
                "year": year_value,
                "season": season,
                "sequence": next_sequence,
            }
        )
        .execute()
    )
    if not inserted:
        raise PlannedCourseError("Could not create the term for this plan.")
    return str(inserted[0]["id"])


def list_planned(
    client: Any, student_id: str, *, term_id: str | None = None
) -> list[PlannedCourse]:
    query = (
        client.table("planned_courses")
        .select("id,term_id,course_code,title,credit_hours,catalog_course_id,created_at")
        .eq("student_id", student_id)
    )
    if term_id is not None:
        query = query.eq("term_id", term_id)
    rows = rows_of(query.order("created_at").execute())
    return [_row_to_planned(row) for row in rows]


def add_planned(
    client: Any,
    student_id: str,
    institution_id: str,
    *,
    course_code: Any,
    term_id: str | None = None,
    title: Any = None,
    credit_hours: Any = None,
    catalog_course_id: str | None = None,
) -> PlannedCourse:
    """Insert one planned course. No dedupe -- see the migration.

    A repeat add is a successful insert of a second row, not a 409. The UI
    disables the control for a course already planned in the selected term;
    that is an affordance, and nothing downstream depends on it holding.
    """
    payload = {
        "student_id": student_id,
        "institution_id": institution_id,
        "term_id": term_id,
        "course_code": clean_course_code(course_code),
        "title": clean_title(title),
        "credit_hours": clean_credit_hours(credit_hours),
        "catalog_course_id": catalog_course_id or None,
    }

    inserted = rows_of(client.table("planned_courses").insert(payload).execute())
    if not inserted:
        raise PlannedCourseError("The planned course could not be saved.")
    return _row_to_planned(inserted[0])


def remove_planned(client: Any, student_id: str, planned_id: str) -> bool:
    """Delete one planned course. Returns False if it did not exist.

    The student_id filter rides alongside RLS for the same reason
    confirm_course_rows applies one: it makes the ownership requirement visible
    in the query rather than resting entirely on a policy defined elsewhere.
    """
    deleted = rows_of(
        client.table("planned_courses")
        .delete()
        .eq("id", planned_id)
        .eq("student_id", student_id)
        .execute()
    )
    return bool(deleted)
