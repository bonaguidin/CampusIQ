"""Tiny shared helpers for the transcript package's Supabase calls.

Deliberately NOT imported from resume.store. Stage 1 already imports
underscore-prefixed names out of resume.extraction, which is a documented and
narrowly-scoped wart; reaching into resume.store for `_rows` and `_now_iso`
would widen it from "one module borrows format primitives" into "the transcript
package depends on resume's internals throughout". These two functions are four
lines. Copying them is cheaper than the coupling.
"""

from datetime import datetime, timezone
from typing import Any


def rows_of(response: Any) -> list[dict[str, Any]]:
    """Rows from a PostgREST response, or [] when it returned nothing."""
    data = getattr(response, "data", None)
    return list(data) if data else []


def now_iso() -> str:
    """UTC timestamp. No trigger maintains updated_at anywhere in this schema
    (see migration 20260801190523) -- the writing application does."""
    return datetime.now(timezone.utc).isoformat()
