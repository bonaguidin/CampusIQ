"""Tests for requirement_satisfaction_fetch.py's _split_course_code() --
the one pure helper in an otherwise untested-by-design fetch module (see
that module's docstring). fetch_requirement_tree() itself stays untested
here, same as before this change.
"""

from __future__ import annotations

from GradusIQ_career.requirement_satisfaction_fetch import _split_course_code


def test_split_course_code_plain_code_passes_through():
    assert _split_course_code("CHEM 107") == ["CHEM 107"]


def test_split_course_code_splits_cross_listing():
    assert _split_course_code("ENGR 216/PHYS 216") == ["ENGR 216", "PHYS 216"]


def test_split_course_code_strips_whitespace_around_slash():
    assert _split_course_code("CSCE 222 / ECEN 222") == ["CSCE 222", "ECEN 222"]
