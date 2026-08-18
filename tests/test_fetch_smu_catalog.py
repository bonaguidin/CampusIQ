"""Tests for data/catalog/fetch_smu_catalog.py.

Covers split_description()'s REQUISITE_SENTENCE / PERMISSION_PHRASE
classification and build_course()'s field mapping. No network calls -- every
case here works from fixed input text, the same descriptions pulled live
during the prior SMU prerequisite-coverage audit.
"""

from __future__ import annotations

from data.catalog import fetch_smu_catalog as smu


# ── split_description(): permission/approval phrasing (the fix) ────────────


def test_permission_required_independent_study_sentence_becomes_prerequisite():
    # CS 4190/4194/4392 and ~15 other CS 41xx-49xx independent-study
    # sections all carry this exact second sentence.
    text = (
        "An opportunity for the advanced undergraduate student to undertake "
        "independent investigation, design, or development. Written "
        "permission of the supervising faculty member is required before "
        "registration."
    )
    description, prerequisites = smu.split_description(text)
    assert description == (
        "An opportunity for the advanced undergraduate student to undertake "
        "independent investigation, design, or development."
    )
    assert prerequisites == (
        "Written permission of the supervising faculty member is required "
        "before registration."
    )


def test_instructor_permission_required_sentence_becomes_prerequisite():
    # ARHS 4302.
    text = (
        "Independent study for undergraduate majors under the direction and "
        "supervision of a faculty member. A directed study is a close "
        "collaboration between the professor and an advanced student who "
        "conducts a rigorous project that goes beyond the experience "
        "available in course offerings. Instructor permission required."
    )
    description, prerequisites = smu.split_description(text)
    assert prerequisites == "Instructor permission required."
    assert "Instructor permission required." not in description
    assert description.startswith("Independent study for undergraduate majors")


def test_deans_office_approved_sentence_becomes_prerequisite():
    # ENGR 3390/4390-family. Source text uses a curly apostrophe (U+2019) in
    # "Dean’s", not a straight one -- the regex must match either.
    text = (
        "A proficient-level, multidisciplinary study of a specialized topic "
        "beyond regular course offerings, conducted with guidance from a "
        "Dean’s Office-approved faculty member."
    )
    description, prerequisites = smu.split_description(text)
    # The whole course description is a single sentence and it's entirely an
    # eligibility gate, so body is empty and split_description() falls back
    # to preserving the original text in description (documented behavior
    # for courses that are nothing but their prerequisite sentence).
    assert prerequisites == text
    assert description == text


# ── split_description(): regression against the pre-existing patterns ──────


def test_prerequisite_prefix_still_matches():
    text = (
        "Foundations of mathematics including logic and set theory. "
        "Prerequisite: Grade of C or better in MATH 1309 or equivalent."
    )
    description, prerequisites = smu.split_description(text)
    assert description == "Foundations of mathematics including logic and set theory."
    assert prerequisites == "Prerequisite: Grade of C or better in MATH 1309 or equivalent."


def test_corequisite_prefix_still_matches():
    text = "Lab component for the lecture course. Corequisite: CHEM 1113."
    description, prerequisites = smu.split_description(text)
    assert description == "Lab component for the lecture course."
    assert prerequisites == "Corequisite: CHEM 1113."


def test_restricted_to_prefix_still_matches():
    text = "An advanced seminar on leadership theory. Restricted to Lyle seniors."
    description, prerequisites = smu.split_description(text)
    assert description == "An advanced seminar on leadership theory."
    assert prerequisites == "Restricted to Lyle seniors."


def test_may_not_be_taken_prefix_still_matches():
    text = (
        "Survey of accounting principles for non-majors. May not be taken "
        "for credit by students who have completed ACCT 2301."
    )
    description, prerequisites = smu.split_description(text)
    assert description == "Survey of accounting principles for non-majors."
    assert prerequisites == (
        "May not be taken for credit by students who have completed ACCT 2301."
    )


def test_no_false_positive_on_unrelated_use_of_permission():
    # "permission" appears but not in a phrase PERMISSION_PHRASE matches, and
    # nothing here should be pulled into prerequisites.
    text = "Students submit permission slips for the required field trip."
    description, prerequisites = smu.split_description(text)
    assert description == text
    assert prerequisites is None
