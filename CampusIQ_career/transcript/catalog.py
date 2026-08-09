"""Match a printed course code against course_catalog. Tier 1 only.

TIER 1 IS THE WHOLE SCOPE FOR v1: normalize, then exact-match on
(institution_id, code). No fuzzy matching, no edit distance, no title
similarity, no prefix aliasing.

That is a deliberate limit, not an unfinished feature. A fuzzy match that binds
a student's "MATH 251" to the catalog's "MATH 151" attaches a wrong course --
wrong title, wrong credit range, wrong prerequisites -- to a permanent academic
record, and it does so with the same confidence as a correct match. A MISS is
harmless by comparison: catalog_course_id stays null, course_code and title
remain authoritative free text (see the column comment on
course_records.catalog_course_id), and the row is flagged for review.

Every miss is logged with its raw string. That log is the input to deciding
whether Tier 2 is worth building and what it should actually handle -- real
misses from real transcripts, rather than invented ones. No table is needed for
this; the log line is enough.

NORMALIZATION
-------------
course_catalog.code is stored as "MATH 251" (prefix, one space, number) -- see
the column comment. Transcripts print the same course as "MATH251", "MATH-251",
"math 251", or "MATH  251". Normalization reduces both sides to that canonical
form:

    uppercase -> strip non-alphanumerics -> re-split into letter run + digit
    run -> rejoin with one space

Splitting on the letter/digit boundary rather than on whitespace is what makes
"MATH251" (no separator at all) match: after stripping punctuation there is no
whitespace left to split on, so the boundary is the only signal available.
"""

import logging
import re
from dataclasses import dataclass
from typing import Any, Iterable

from .store_helpers import rows_of


logger = logging.getLogger(__name__)

# Letter run then digit run, with an optional trailing letter for codes like
# "MATH 251H" (honors) or "ENGR 102L" (lab section).
_CODE_PATTERN = re.compile(r"^([A-Z]+)(\d+)([A-Z]*)$")
_NON_ALNUM = re.compile(r"[^A-Z0-9]+")

# PostgREST caps a URL's length; chunk the .in_() lookup so a transcript with
# hundreds of distinct codes does not build one enormous query string.
LOOKUP_CHUNK_SIZE = 100


@dataclass(frozen=True)
class MatchReport:
    matched: int = 0
    unmatched: int = 0
    # Normalized codes with no catalog row, de-duplicated, for the response.
    misses: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "matched": self.matched,
            "unmatched": self.unmatched,
            "misses": list(self.misses),
        }


def normalize_code(raw: str) -> str | None:
    """Reduce a printed course code to catalog form, or None if unusable.

    "math-251" -> "MATH 251"; "MATH251" -> "MATH 251"; "MATH  251" ->
    "MATH 251"; "MATH 251H" -> "MATH 251H".

    Returns None for anything without both a letter run and a digit run --
    "SEMINAR", "101", "" -- which cannot address a catalog row and so is
    reported as a miss rather than matched against something.
    """
    if not isinstance(raw, str):
        return None

    condensed = _NON_ALNUM.sub("", raw.upper())
    if not condensed:
        return None

    match = _CODE_PATTERN.match(condensed)
    if match is None:
        return None

    prefix, number, suffix = match.groups()
    return f"{prefix} {number}{suffix}"


def _chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def lookup_catalog_ids(
    client: Any, institution_id: str, codes: Iterable[str]
) -> dict[str, str]:
    """Normalized code -> course_catalog.id, for codes this institution has.

    Codes with no catalog row are simply absent from the result. course_catalog
    is public-read (course_catalog_read_public), so the session-scoped client
    can query it directly.
    """
    wanted = sorted({code for code in codes if code})
    if not wanted:
        return {}

    found: dict[str, str] = {}
    for chunk in _chunks(wanted, LOOKUP_CHUNK_SIZE):
        rows = rows_of(
            client.table("course_catalog")
            .select("id,code")
            .eq("institution_id", institution_id)
            .in_("code", chunk)
            .execute()
        )
        for row in rows:
            code, row_id = row.get("code"), row.get("id")
            if code and row_id:
                found[code] = row_id

    return found


def match_courses(
    client: Any,
    institution_id: str,
    courses: list[dict[str, Any]],
) -> MatchReport:
    """Set catalog_course_id on each course dict, in place.

    A match sets the id; a miss sets it to None explicitly (rather than leaving
    the key absent) so the stored row is unambiguous either way. Mutates the
    dicts because they are the same objects store.py is about to write --
    copying them would make it possible for the two to drift.
    """
    normalized_by_index: dict[int, str | None] = {
        index: normalize_code(course.get("course_code") or "")
        for index, course in enumerate(courses)
    }

    catalog_ids = lookup_catalog_ids(
        client, institution_id, [code for code in normalized_by_index.values() if code]
    )

    matched = 0
    misses: list[str] = []
    seen_misses: set[str] = set()

    for index, course in enumerate(courses):
        normalized = normalized_by_index[index]
        catalog_id = catalog_ids.get(normalized) if normalized else None

        course["catalog_course_id"] = catalog_id

        if catalog_id is not None:
            matched += 1
            continue

        raw = course.get("course_code")
        # Logged individually and with the RAW string, not the normalized one:
        # the point is to learn what transcripts actually print, which the
        # normalized form has already thrown away.
        logger.info(
            "transcript catalog miss: institution_id=%s raw=%r normalized=%r title=%r",
            institution_id,
            raw,
            normalized,
            course.get("title"),
        )
        key = normalized or str(raw)
        if key not in seen_misses:
            seen_misses.add(key)
            misses.append(key)

    return MatchReport(
        matched=matched,
        unmatched=len(courses) - matched,
        misses=tuple(misses),
    )
