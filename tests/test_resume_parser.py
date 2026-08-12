import pytest

from GradusIQ_career.resume.parser import (
    normalize_expected_graduation,
    validate_parsed_resume,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("May 2029", "Spring 2029"),
        ("MAY 2029", "Spring 2029"),
        ("Spring 2029", "Spring 2029"),
        ("spring 2029", "Spring 2029"),
        ("December 2028", "Fall 2028"),
        ("Dec 2028", "Fall 2028"),
        ("Fall 2028", "Fall 2028"),
        ("fall 2028", "Fall 2028"),
        ("Summer 2028", None),
        ("2029", None),
        (None, None),
    ],
)
def test_expected_graduation_normalization(raw, expected):
    assert normalize_expected_graduation(raw) == expected


def test_explicit_academic_facts_survive_validation():
    parsed = validate_parsed_resume(
        {
            "status": "ok",
            "academics": {
                "major_current": "Computer Engineering",
                "expected_graduation": "May 2029",
            },
        }
    )

    assert parsed.academics == {
        "major_current": "Computer Engineering",
        "expected_graduation": "Spring 2029",
    }


def test_absent_academic_facts_remain_null():
    parsed = validate_parsed_resume({"status": "ok"})
    assert parsed.academics == {"major_current": None, "expected_graduation": None}


def test_ambiguous_graduation_is_not_fabricated():
    parsed = validate_parsed_resume(
        {
            "status": "ok",
            "academics": {
                "major_current": None,
                "expected_graduation": "Summer 2029",
            },
        }
    )
    assert parsed.academics["expected_graduation"] is None
    assert any("unrecognized value" in warning for warning in parsed.warnings)
