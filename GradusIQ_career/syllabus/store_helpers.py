"""Tiny, deliberately-duplicated Supabase row helpers.

Mirrors GradusIQ_career/transcript/store_helpers.py's own docstring
rationale: each feature package keeps its own copy of `rows_of`/`now_iso`
rather than importing another package's private helpers, to avoid
cross-package coupling.
"""

from datetime import datetime, timezone
from typing import Any


def rows_of(response: Any) -> list[dict]:
    data = getattr(response, "data", None)
    return data if isinstance(data, list) else []


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
