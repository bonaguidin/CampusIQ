"""Apply an institution's repeat policy by setting course_records.excluded_from_gpa_by.

WHAT THIS COLUMN MEANS (20260729193925:28-33)
---------------------------------------------
The row that CARRIES the value is the EXCLUDED one; it points AT the row that
caused its exclusion. It is "victim -> cause", not "earlier -> later" --
direction-neutral by design, because different institutions exclude different
attempts.

academics/gpa.py:177 checks it FIRST, ahead of status and grade resolution:

    if record.excluded_from_gpa_by is not None:
        excluded.append((record, "excluded_by_repeat"))
        continue

so setting it removes the row from BOTH the official and projected GPA. It does
NOT remove earned credit: gpa.py tallies earned_hours at :166-171, above that
check, so an excluded repeat still counts toward hours earned. That asymmetry is
deliberate and is what the transcript actually reflects -- the course was taken
and passed, it just is not scored twice.

WHY THIS RUNS AT CONFIRM TIME AND NOT AFTER STORE
-------------------------------------------------
Post-store is the intuitive place and it is wrong. gpa.py already excludes
unconfirmed rows. Consider a first attempt that is confirmed and a second that
was just uploaded and is not:

    attempt 1 (confirmed)   -> marked excluded_by_repeat by attempt 2
    attempt 2 (unconfirmed) -> excluded as "unconfirmed"

Both attempts are now out, and the course vanishes from the GPA entirely until
the student happens to confirm the second row -- a silently wrong GPA introduced
by the feature meant to fix GPA correctness. Running inside the confirm flow,
over confirmed rows only, makes that unrepresentable: a row can only ever be
superseded by a row that is already counting.

WHY FULL RECOMPUTE AND NOT INCREMENTAL
--------------------------------------
Every run clears the student's excluded_from_gpa_by values before re-deriving.
An incremental pass would leave stale exclusions behind whenever the underlying
facts change -- a grade corrected in review, a row deleted, a threshold retuned
-- and a stale exclusion is invisible: the row simply reports "excluded_by_repeat"
forever, with no signal that it is answering a question nobody is asking any
more. Recomputing from scratch costs one extra write per affected row and makes
the column a pure function of current state.
"""

import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Sequence

from .catalog import normalize_code
from .store_helpers import now_iso, rows_of
from .terms import SEASON_ORDER


logger = logging.getLogger(__name__)


ALL_ATTEMPTS_COUNT = "all_attempts_count"
LATEST_REPLACES = "latest_replaces"

# Policies under which no row is ever excluded. NULL is included deliberately:
# an institution nobody has classified yet must not have grades silently
# deleted. "GPA includes too much" is a visible failure mode a student can
# question; "a grade quietly stopped counting" is not.
SET_NOTHING_POLICIES = frozenset({ALL_ATTEMPTS_COUNT, None})


@dataclass(frozen=True)
class RepeatExclusion:
    """One resolved exclusion: `excluded_id` is out because of `superseded_by`."""

    excluded_id: str
    superseded_by: str
    course_code: str
    reason: str = "repeat_replacement"

    def to_dict(self) -> dict[str, Any]:
        return {
            "excluded_id": self.excluded_id,
            "superseded_by": self.superseded_by,
            "course_code": self.course_code,
            "reason": self.reason,
        }


@dataclass
class ReconcileReport:
    exclusions: list[RepeatExclusion] = field(default_factory=list)
    cleared: int = 0
    # Groups seen with 2+ attempts that produced no exclusion -- e.g. the
    # earlier attempt was above the threshold. Surfaced so "we looked and
    # decided not to" is distinguishable from "we never looked".
    groups_considered: int = 0
    skipped_no_term: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "excluded": [e.to_dict() for e in self.exclusions],
            "cleared": self.cleared,
            "groups_considered": self.groups_considered,
            "skipped_no_term": self.skipped_no_term,
        }


def _as_points(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _chronological_key(row: Mapping[str, Any]) -> tuple[int, int]:
    """(year, season ordinal) for a course row's term.

    NOT academic_terms.sequence. sequence is appended-after-max rather than
    renumbered (see terms.py), so a student who uploads an older transcript
    SECOND gets a higher sequence on an earlier term. Ordering repeats by
    sequence would then invert which attempt is "later" and exclude the wrong
    one -- a confidently wrong GPA. (year, season) is always correct.
    """
    year = row.get("_term_year")
    season = row.get("_term_season")
    return (int(year or 0), SEASON_ORDER.get(str(season), 99))


def group_key(row: Mapping[str, Any]) -> tuple[str, str] | None:
    """Identity for "these rows are attempts at the same course".

    Prefers catalog_course_id: it is the stronger identity and is immune to the
    code-format drift ("MATH251" vs "MATH 251") that free text carries. Falls
    back to the normalized code when the row never matched the catalog.

    Always scoped by institution_id. A transfer "MATH 251" and a resident
    "MATH 251" are different courses at different institutions, and SMU's grade
    replacement applies to SMU coursework -- gpa.py already handles transfer
    credit separately via transfer_grades_count_toward_gpa. Cross-institution
    repeats are out of scope for v1.
    """
    institution_id = row.get("institution_id")
    if not institution_id:
        return None

    catalog_id = row.get("catalog_course_id")
    if catalog_id:
        return (str(institution_id), f"catalog:{catalog_id}")

    normalized = normalize_code(row.get("course_code") or "")
    if normalized:
        return (str(institution_id), f"code:{normalized}")

    raw = (row.get("course_code") or "").strip().upper()
    return (str(institution_id), f"raw:{raw}") if raw else None


def plan_exclusions(
    rows: Sequence[Mapping[str, Any]],
    *,
    repeat_policy: str | None,
    max_points: Any,
    grade_map: Mapping[str, Mapping[str, Any]],
) -> ReconcileReport:
    """Decide which rows to exclude. Pure -- no database access.

    `rows` are one institution's CONFIRMED course records, each carrying
    _term_year / _term_season resolved from academic_terms.
    """
    report = ReconcileReport()

    if repeat_policy in SET_NOTHING_POLICIES:
        # TAMU and every unclassified institution land here. See the module
        # docstring and the migration's TAMU note: Rule 10.22 is a degree-audit
        # rule, and modeling it with this column would corrupt the cumulative
        # GPA that Rule 10.21 requires.
        return report

    if repeat_policy != LATEST_REPLACES:
        logger.warning(
            "repeat reconciliation: unrecognized repeat_policy %r; setting nothing",
            repeat_policy,
        )
        return report

    threshold = _as_points(max_points)

    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        # A row with no term has no position in time, so there is no basis for
        # calling it the earlier or the later attempt. Defaulting either way
        # would be a coin flip on which grade gets deleted from the GPA.
        if not row.get("term_id"):
            report.skipped_no_term += 1
            continue
        key = group_key(row)
        if key is None:
            continue
        groups.setdefault(key, []).append(row)

    for attempts in groups.values():
        if len(attempts) < 2:
            continue
        report.groups_considered += 1

        ordered = sorted(attempts, key=_chronological_key)
        latest = ordered[-1]
        latest_id = latest.get("id")
        if not latest_id:
            continue

        for earlier in ordered[:-1]:
            earlier_id = earlier.get("id")
            if not earlier_id or earlier_id == latest_id:
                continue

            if threshold is not None:
                # THE ELIGIBILITY GATE. SMU replaces only when the EARLIER
                # attempt was D+ or lower; a student who earned a B and retook
                # the course keeps both grades. Comparing points rather than
                # letters keeps this institution-agnostic -- see the migration.
                entry = grade_map.get(earlier.get("letter_grade"))
                earlier_points = _as_points(entry.get("points")) if entry else None
                if earlier_points is None or earlier_points > threshold:
                    continue

            report.exclusions.append(
                RepeatExclusion(
                    excluded_id=str(earlier_id),
                    superseded_by=str(latest_id),
                    course_code=str(earlier.get("course_code") or ""),
                )
            )

    return report


# -- database-facing --------------------------------------------------------


def _confirmed_rows_with_terms(client: Any, student_id: str) -> list[dict[str, Any]]:
    """Confirmed course records, annotated with their term's (year, season)."""
    # Confirmed-only is filtered in Python rather than with PostgREST's
    # `not.is.null`. The builder exposes that as a stateful `.not_` property
    # that negates whichever filter follows it, which is easy to misread and
    # easy to break with a later reorder. A student's full course history is a
    # few dozen rows, so the difference is not measurable.
    rows = [
        row
        for row in rows_of(
            client.table("course_records")
            .select("*")
            .eq("student_id", student_id)
            .execute()
        )
        if row.get("confirmed_at") is not None
    ]

    terms = rows_of(
        client.table("academic_terms").select("*").eq("student_id", student_id).execute()
    )
    by_id = {t["id"]: t for t in terms if t.get("id")}

    annotated: list[dict[str, Any]] = []
    for row in rows:
        term = by_id.get(row.get("term_id")) or {}
        enriched = dict(row)
        enriched["_term_year"] = term.get("year")
        enriched["_term_season"] = term.get("season")
        annotated.append(enriched)
    return annotated


def _institutions_by_id(
    client: Any, institution_ids: Iterable[str]
) -> dict[str, dict[str, Any]]:
    wanted = sorted({i for i in institution_ids if i})
    if not wanted:
        return {}
    rows = rows_of(
        client.table("institutions")
        .select("id,name,repeat_policy,repeat_replacement_max_points")
        .in_("id", wanted)
        .execute()
    )
    return {row["id"]: row for row in rows if row.get("id")}


def _grade_maps_by_institution(
    client: Any, institution_ids: Iterable[str]
) -> dict[str, dict[str, dict[str, Any]]]:
    wanted = sorted({i for i in institution_ids if i})
    if not wanted:
        return {}
    rows = rows_of(
        client.table("grade_point_map").select("*").in_("institution_id", wanted).execute()
    )
    maps: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        institution_id, letter = row.get("institution_id"), row.get("letter")
        if institution_id and letter:
            maps.setdefault(institution_id, {})[letter] = row
    return maps


def reconcile_repeats(client: Any, student_id: str) -> ReconcileReport:
    """Recompute excluded_from_gpa_by across this student's confirmed rows.

    Idempotent: clears every existing exclusion first, then re-derives. Called
    from confirm_course_rows AFTER confirmed_at is stamped -- see the module
    docstring for why not post-store.
    """
    rows = _confirmed_rows_with_terms(client, student_id)

    stamp = now_iso()

    # CLEAR FIRST. Scoped to rows that actually carry a value so the write is
    # proportional to what changed, but unconditional in effect: after this,
    # nothing is excluded, and everything below is derived from current state.
    already_excluded = [r for r in rows if r.get("excluded_from_gpa_by") is not None]
    cleared = 0
    if already_excluded:
        cleared = len(
            rows_of(
                client.table("course_records")
                .update({"excluded_from_gpa_by": None, "updated_at": stamp})
                .eq("student_id", student_id)
                .in_("id", [r["id"] for r in already_excluded])
                .execute()
            )
        )
        for row in rows:
            row["excluded_from_gpa_by"] = None

    institution_ids = {r.get("institution_id") for r in rows if r.get("institution_id")}
    institutions = _institutions_by_id(client, institution_ids)
    grade_maps = _grade_maps_by_institution(client, institution_ids)

    report = ReconcileReport(cleared=cleared)

    by_institution: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        institution_id = row.get("institution_id")
        if institution_id:
            by_institution.setdefault(institution_id, []).append(row)

    for institution_id, institution_rows in by_institution.items():
        institution = institutions.get(institution_id) or {}
        plan = plan_exclusions(
            institution_rows,
            repeat_policy=institution.get("repeat_policy"),
            max_points=institution.get("repeat_replacement_max_points"),
            grade_map=grade_maps.get(institution_id, {}),
        )
        report.exclusions.extend(plan.exclusions)
        report.groups_considered += plan.groups_considered
        report.skipped_no_term += plan.skipped_no_term

    for exclusion in report.exclusions:
        client.table("course_records").update(
            {"excluded_from_gpa_by": exclusion.superseded_by, "updated_at": stamp}
        ).eq("id", exclusion.excluded_id).eq("student_id", student_id).execute()
        logger.info(
            "repeat exclusion: student=%s course=%s excluded=%s superseded_by=%s",
            student_id,
            exclusion.course_code,
            exclusion.excluded_id,
            exclusion.superseded_by,
        )

    return report
