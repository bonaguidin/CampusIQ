"""Compare parsed course rows against the term totals the transcript printed.

Cheap detection for the failure mode nothing else catches: a dropped or
duplicated course. Every other check in this package validates a row against
its own contents -- this is the only one that can notice that a row is MISSING,
because the transcript itself told us what the term should add up to.

NEVER BLOCKS. A mismatch is surfaced in the upload response and nowhere else.
The printed totals are themselves model output and can be misread; the rows may
be right and the summary wrong. More importantly a mismatch is often expected:
this compares against rows that were PARSED, and rejected rows are legitimately
absent from that set, so a transcript with one unreadable grade will mismatch
by design. Blocking on it would turn a useful signal into a wall.

The GPA comparison is deliberately approximate. It recomputes quality points
the standard way (sum of points x hours, over hours that count) but cannot
account for institution-specific rules gpa.py applies -- repeat replacement,
transfer inclusion, exam exclusion. It is a smoke alarm, not a second
implementation of the GPA. GPA_TOLERANCE is wide enough to absorb ordinary
rounding without swallowing a genuinely missing course.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable, Mapping, Sequence

from .parser import TermSummary


# A term GPA is printed to two decimals; a single dropped 3-credit course in a
# 15-credit term moves it far more than this.
GPA_TOLERANCE = 0.05

# Credit hours are printed exactly, so this only absorbs float noise.
CREDIT_TOLERANCE = 0.01


@dataclass(frozen=True)
class TermMismatch:
    term_label: str
    field: str
    printed: float
    computed: float

    @property
    def difference(self) -> float:
        return round(self.computed - self.printed, 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "term_label": self.term_label,
            "field": self.field,
            "printed": self.printed,
            "computed": self.computed,
            "difference": self.difference,
        }


@dataclass(frozen=True)
class CrossCheckReport:
    mismatches: tuple[TermMismatch, ...] = ()
    terms_checked: int = 0
    terms_skipped: int = 0

    @property
    def ok(self) -> bool:
        return not self.mismatches

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "terms_checked": self.terms_checked,
            "terms_skipped": self.terms_skipped,
            "mismatches": [m.to_dict() for m in self.mismatches],
        }


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except (ValueError, TypeError):
            return None
    return None


def cross_check_terms(
    courses: Sequence[Mapping[str, Any]],
    summaries: Iterable[TermSummary],
    grade_map: Mapping[str, Mapping[str, Any]],
) -> CrossCheckReport:
    """Recompute each term's totals from parsed rows and compare to printed.

    Only completed courses participate: in-progress coursework has no grade and
    is not part of a printed term GPA. A term whose summary prints neither a
    GPA nor a credit total is skipped, as is one with no completed rows.
    """
    by_label: dict[str, list[Mapping[str, Any]]] = {}
    for course in courses:
        label = course.get("term_label")
        if label:
            by_label.setdefault(label, []).append(course)

    mismatches: list[TermMismatch] = []
    checked = 0
    skipped = 0

    for summary in summaries:
        printed_gpa = summary.term_gpa
        printed_credits = summary.term_credit_hours
        if printed_gpa is None and printed_credits is None:
            skipped += 1
            continue

        rows = [
            course
            for course in by_label.get(summary.term_label, [])
            if course.get("status") == "completed"
        ]
        if not rows:
            skipped += 1
            continue

        credit_total = 0.0
        quality_points = 0.0
        gpa_hours = 0.0

        for course in rows:
            hours = _as_float(course.get("credit_hours"))
            if hours is None:
                continue
            letter = course.get("letter_grade")
            entry = grade_map.get(letter) if letter else None

            if entry is not None and entry.get("counts_toward_credit"):
                credit_total += hours

            if entry is not None and entry.get("counts_toward_gpa"):
                points = _as_float(entry.get("points"))
                if points is not None:
                    quality_points += points * hours
                    gpa_hours += hours

        checked += 1

        if printed_credits is not None:
            if abs(credit_total - printed_credits) > CREDIT_TOLERANCE:
                mismatches.append(
                    TermMismatch(
                        term_label=summary.term_label,
                        field="term_credit_hours",
                        printed=printed_credits,
                        computed=round(credit_total, 2),
                    )
                )

        if printed_gpa is not None and gpa_hours > 0:
            computed_gpa = quality_points / gpa_hours
            if abs(computed_gpa - printed_gpa) > GPA_TOLERANCE:
                mismatches.append(
                    TermMismatch(
                        term_label=summary.term_label,
                        field="term_gpa",
                        printed=printed_gpa,
                        computed=round(computed_gpa, 2),
                    )
                )

    return CrossCheckReport(
        mismatches=tuple(mismatches), terms_checked=checked, terms_skipped=skipped
    )
