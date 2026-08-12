"""Course search for planned-course entry.

Wraps the search_course_catalog() function added in
20260811120200_course_catalog_search.sql. The function exists because
PostgREST cannot express `lower(title) LIKE ...`; that migration carries the
full reasoning.

QUERY NORMALIZATION
-------------------
Two institutions print course codes differently and students type them a third
way:

    TAMU catalog:  "MATH 251"   (letters, one space, 3 digits)
    SMU catalog:   "ACCT 2301"  (letters, one space, 4 digits)
    typed:         "math251", "MATH-251", "acct 23", "csce"

normalize_search_prefix reduces all of them to the stored form, using the same
letter-run / digit-run split as transcript/catalog.py's normalize_code -- and
for the same reason: after stripping punctuation there may be no whitespace
left to split on, so the letter/digit boundary is the only signal.

It differs from normalize_code in one way that matters: normalize_code
validates a COMPLETE code and returns nothing for a partial one, because
attaching a wrong catalog course to a permanent academic record is worse than
attaching none. A search box is the opposite case -- "CSCE" and "MATH 2" are
the normal input, not a failure -- so this normalizes partials rather than
rejecting them. The two functions are deliberately not shared.

Because search is prefix-anchored and case-sensitive on code, normalization
must never invent characters: "csce1" becomes "CSCE 1", which matches
"CSCE 120" and "CSCE 181", and never "CSCE 1" alone.
"""

import re
from dataclasses import dataclass
from typing import Any

# Anything that is not a letter or digit is a separator, including the space
# the catalog itself stores.
_NON_ALNUM = re.compile(r"[^A-Z0-9]+")
_LETTERS_THEN_DIGITS = re.compile(r"^([A-Z]+)(\d*)$")

MAX_QUERY_LENGTH = 64
DEFAULT_LIMIT = 20
MAX_LIMIT = 50


class CatalogSearchError(RuntimeError):
    """The search could not be run. Distinct from 'ran and found nothing'."""


@dataclass(frozen=True)
class CatalogResult:
    id: str
    code: str
    title: str
    department: str | None
    course_level: int | None
    credit_min: int | None
    credit_max: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "code": self.code,
            "title": self.title,
            "department": self.department,
            "course_level": self.course_level,
            "credit_min": self.credit_min,
            "credit_max": self.credit_max,
        }


def normalize_search_prefix(query: str) -> str:
    """Reduce typed input to the catalog's stored code form, partials included.

    Title searches pass through this too, and are expected to come out
    unchanged in shape -- a multi-word title keeps its spaces, because the
    letters/digits split only applies when the whole query collapses to one
    letter run followed by one digit run. "machine l" stays "machine l" (the
    caller lowercases for the title branch); "csce1" becomes "CSCE 1".
    """
    if not isinstance(query, str):
        return ""

    trimmed = " ".join(query.split())[:MAX_QUERY_LENGTH].strip()
    if not trimmed:
        return ""

    # A course code is at most two tokens ("MATH 251", "MATH-251", "MATH251").
    # Anything longer is prose and must survive intact: collapsing separators
    # in "Data Structures" would produce "DATASTRUCTURES", which matches no
    # title and no code -- a search that silently returns nothing for the most
    # natural thing to type.
    if len(trimmed.split(" ")) > 2:
        return trimmed

    collapsed = _NON_ALNUM.sub("", trimmed.upper())
    match = _LETTERS_THEN_DIGITS.match(collapsed)
    if match is None:
        # Digits before letters, or empty after stripping punctuation.
        return trimmed

    prefix, digits = match.group(1), match.group(2)
    if not digits:
        # A single bare word. It could be a subject prefix ("csce") or a
        # one-word title ("Biology"), and there is no way to tell -- so it is
        # returned in the code's own casing and the SQL tries both branches.
        # Safe because the title branch lowercases both sides: 'BIOLOGY' still
        # matches the title "Biology Laboratory".
        if " " in trimmed:
            # Two tokens, no digits ("Organic Chemistry") -- prose, not a code.
            return trimmed
        return prefix

    return f"{prefix} {digits}"


def search_catalog(
    client: Any,
    institution_id: str,
    query: str,
    limit: int = DEFAULT_LIMIT,
) -> list[CatalogResult]:
    """Prefix-search one institution's catalog. Empty query -> no results.

    institution_id is required and never defaulted: course_catalog's unique key
    is (institution_id, code), so an unscoped search would return another
    school's MATH 251 alongside this student's.
    """
    normalized = normalize_search_prefix(query)
    if not normalized:
        return []

    bounded = min(max(int(limit or DEFAULT_LIMIT), 1), MAX_LIMIT)

    try:
        response = client.rpc(
            "search_course_catalog",
            {
                "p_institution_id": institution_id,
                "p_query": normalized,
                "p_limit": bounded,
            },
        ).execute()
    except Exception as exc:  # noqa: BLE001 -- transport or RLS denial
        raise CatalogSearchError("Course catalog search is unavailable.") from exc

    rows = response.data or []
    return [
        CatalogResult(
            id=str(row["id"]),
            code=str(row.get("code") or ""),
            title=str(row.get("title") or ""),
            department=row.get("department"),
            course_level=row.get("course_level"),
            credit_min=row.get("credit_min"),
            credit_max=row.get("credit_max"),
        )
        for row in rows
        if row.get("id")
    ]
