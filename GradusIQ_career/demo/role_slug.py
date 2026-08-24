"""Filename-safe slug for a target role, shared by api.py and the demo cache builder.

A single shared function so the two never drift and produce mismatched cache
filenames.
"""

import re

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def role_slug(target_role: str) -> str:
    return _NON_ALNUM.sub("-", target_role.lower()).strip("-")
