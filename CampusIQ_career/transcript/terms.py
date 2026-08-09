"""Resolve printed term labels ("Fall 2023") to academic_terms rows.

No resume analogue -- this is specific to transcripts.

SCHEMA THIS MUST SATISFY (20260728000103_institution_grading_schema.sql:68-77,
plus 20260728035418):

    academic_terms(id, student_id, institution_id, label, year, season,
                   sequence, created_at)
    unique (student_id, sequence)        -- academic_terms_student_sequence_key

There is NO unique constraint on (student_id, label) or on
(student_id, year, season). The only natural key the database enforces is
(student_id, sequence).

WHY THAT MATTERS FOR REUSE
--------------------------
The lookup key for "does this term already exist for this student" therefore
cannot be a database upsert -- there is no constraint to conflict on. Reuse is
done with an explicit read-then-match on (year, season), which is the real
identity of a term: "Fall 2023" and "FALL 2023" and "Fall Semester 2023" are
the same term and must resolve to the same row. Matching on the raw label
string would create a duplicate the second time a student uploads a transcript
that spells the heading differently -- and because course_records' natural key
includes term_id, a duplicate term silently duplicates every course under it.

(year, season) is used rather than label for exactly that reason. The label is
still stored, as printed, for display.

WHY SEQUENCE IS ASSIGNED THE WAY IT IS
--------------------------------------
sequence is a per-student monotonic ordinal. It is derived by sorting terms
CHRONOLOGICALLY (year, then season order), not by the order they appear on the
page: transcripts print terms out of order often enough -- reverse-chronological
listings, transfer credit blocks appended after resident coursework -- that
page order is not a usable proxy for time.

New terms are appended after the student's existing maximum sequence rather
than renumbering. Renumbering would rewrite sequence values on rows a previous
upload already created, and those values are what any "order my terms" query
depends on. So a second upload that introduces an EARLIER term gives it a
HIGHER sequence than a later term already stored. That is a real limitation and
it is the deliberate trade: a stable-but-imperfect ordinal beats one that
silently changes under rows the student already reviewed. Anything needing true
chronological order should sort on (year, season), which is always correct.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .store_helpers import rows_of


# Season vocabulary. academic_terms.season carries NO check constraint, so this
# set is the application's own contract, not a database one -- which is exactly
# why it is normalized here rather than trusted from the model.
SEASON_ORDER: Mapping[str, int] = {
    "Winter": 0,
    "Spring": 1,
    "Summer": 2,
    "Fall": 3,
}

# Spellings seen on real transcripts, mapped to the canonical season. Keys are
# compared casefolded.
SEASON_ALIASES: Mapping[str, str] = {
    "fall": "Fall",
    "autumn": "Fall",
    "fa": "Fall",
    "spring": "Spring",
    "spr": "Spring",
    "sp": "Spring",
    "summer": "Summer",
    "sum": "Summer",
    "su": "Summer",
    "winter": "Winter",
    "wint": "Winter",
    "wi": "Winter",
    "intersession": "Winter",
    "january": "Winter",
    "jan": "Winter",
    "maymester": "Summer",
    "may": "Summer",
}

_YEAR_PATTERN = re.compile(r"\b(19|20)\d{2}\b")
_WORD_PATTERN = re.compile(r"[A-Za-z]+")


@dataclass(frozen=True)
class TermResolution:
    """Outcome of resolving one transcript's term labels.

    `errors` holds labels that could not be parsed; their courses are stored
    with a null term_id rather than filed under a guessed semester.
    """

    term_id_by_label: dict[str, str] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    created: int = 0
    reused: int = 0


@dataclass(frozen=True)
class ResolvedTerm:
    """A parsed term label. `sequence` is assigned later, by resolve_terms."""

    label: str
    year: int
    season: str

    @property
    def chronological_key(self) -> tuple[int, int]:
        return (self.year, SEASON_ORDER.get(self.season, 99))


class TermParseError(ValueError):
    """A term label that cannot be resolved to a (year, season)."""


def parse_term_label(label: str) -> ResolvedTerm:
    """Derive (year, season) from a printed term heading.

    Handles the orderings that actually appear: "Fall 2023", "2023 Fall",
    "FALL 2023", "Fall Semester 2023", "Fall Term 2023-2024".

    A two-year span ("2023-2024") takes the FIRST year: an academic year
    labelled 2023-2024 begins in 2023, and the season disambiguates the rest.
    Raises TermParseError rather than guessing -- an unresolvable term means
    its courses go to review, which is better than filing them under a
    fabricated semester.
    """
    if not isinstance(label, str) or not label.strip():
        raise TermParseError("Term label is empty.")

    text = label.strip()

    year_match = _YEAR_PATTERN.search(text)
    if year_match is None:
        raise TermParseError(f"No four-digit year in term label {label!r}.")
    year = int(year_match.group(0))

    season: str | None = None
    for word in _WORD_PATTERN.findall(text):
        candidate = SEASON_ALIASES.get(word.casefold())
        if candidate is not None:
            season = candidate
            break

    if season is None:
        raise TermParseError(
            f"No recognizable season in term label {label!r}. "
            f"Expected one of: {', '.join(sorted(SEASON_ORDER))}."
        )

    return ResolvedTerm(label=text, year=year, season=season)


def _existing_terms(client: Any, student_id: str) -> list[dict[str, Any]]:
    return rows_of(
        client.table("academic_terms")
        .select("*")
        .eq("student_id", student_id)
        .execute()
    )


def resolve_terms(
    client: Any,
    student_id: str,
    institution_id: str,
    labels: Iterable[str],
) -> TermResolution:
    """Map each printed term label to an academic_terms.id.

    A label that cannot be parsed appears in `.errors` and NOT in
    `.term_id_by_label`; its courses are stored with a null term_id rather than
    being filed under a guess.

    Existing terms are reused by (year, season) -- see the module docstring.
    Distinct labels that resolve to the same (year, season) collapse onto one
    row, which is the point: "Fall 2023" and "FALL 2023" are one term. Such a
    collapse counts as a reuse, not a creation.
    """
    term_id_by_label: dict[str, str] = {}
    errors: dict[str, str] = {}
    created = 0
    reused = 0

    resolved: dict[str, ResolvedTerm] = {}
    for label in labels:
        if label is None or label in resolved or label in errors:
            continue
        try:
            resolved[label] = parse_term_label(label)
        except TermParseError as exc:
            errors[label] = str(exc)

    if not resolved:
        return TermResolution(term_id_by_label, errors, created, reused)

    existing = _existing_terms(client, student_id)
    by_year_season: dict[tuple[int, str], str] = {}
    for row in existing:
        year, season = row.get("year"), row.get("season")
        if year is None or season is None:
            continue
        by_year_season.setdefault((int(year), str(season)), row["id"])

    next_sequence = max((int(r.get("sequence") or 0) for r in existing), default=-1) + 1

    # Chronological, so a first upload numbers terms in real time order
    # regardless of how the transcript printed them.
    for label, term in sorted(resolved.items(), key=lambda item: item[1].chronological_key):
        key = (term.year, term.season)
        existing_id = by_year_season.get(key)
        if existing_id is not None:
            term_id_by_label[label] = existing_id
            reused += 1
            continue

        inserted = rows_of(
            client.table("academic_terms")
            .insert(
                {
                    "student_id": student_id,
                    "institution_id": institution_id,
                    "label": term.label,
                    "year": term.year,
                    "season": term.season,
                    "sequence": next_sequence,
                }
            )
            .execute()
        )
        if not inserted:
            raise RuntimeError(
                f"academic_terms insert returned no row for {label!r}."
            )

        new_id = inserted[0]["id"]
        by_year_season[key] = new_id
        term_id_by_label[label] = new_id
        created += 1
        next_sequence += 1

    return TermResolution(term_id_by_label, errors, created, reused)
