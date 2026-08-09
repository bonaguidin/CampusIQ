"""Tests for the transcript parser's pure logic: contract, coercion, terms,
catalog normalization, counts flags, and the arithmetic cross-check.

No network and no database: everything here is either a pure function or takes
a tiny fake client. The route-level tests live in tests/test_api_v2_transcript.py.
"""

from decimal import Decimal

import pytest

from CampusIQ_career.transcript import catalog, crosscheck, parser, store, terms


TAMU_LETTERS = ("A", "B", "C", "D", "F", "W", "I")
SMU_LETTERS = ("A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "D-", "F", "P", "W", "I")


def course(**overrides):
    base = {
        "course_code": "MATH 251",
        "title": "Engineering Mathematics III",
        "credit_hours": 3,
        "letter_grade": "A",
        "term_label": "Fall 2023",
        "status": "completed",
    }
    base.update(overrides)
    return base


def payload(courses=None, **extra):
    body = {"status": "ok", "courses": courses if courses is not None else [course()]}
    body.update(extra)
    return body


# ── 1. credit_hours coercion: reject, never default ─────────────────────────


@pytest.mark.parametrize(
    "raw, expected",
    [
        (3, Decimal("3.00")),
        (3.0, Decimal("3.00")),
        ("3", Decimal("3.00")),
        ("3.0", Decimal("3.00")),
        (" 4.00 ", Decimal("4.00")),
        (Decimal("1.5"), Decimal("1.50")),
        (0, Decimal("0.00")),
        (99.99, Decimal("99.99")),
    ],
)
def test_credit_hours_coerces_valid_values(raw, expected):
    assert parser.coerce_credit_hours(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "three",
        "3 hours",
        -1,
        -0.5,
        100,
        1e9,
        float("nan"),
        float("inf"),
        True,          # isinstance(True, int) -- must not become 1 credit
        False,
        [3],
        {"value": 3},
    ],
)
def test_credit_hours_rejects_rather_than_defaulting(raw):
    assert parser.coerce_credit_hours(raw) is None, (
        f"{raw!r} must reject; a defaulted credit_hours silently changes the GPA"
    )


# ── 2. reject-not-repair on course rows ─────────────────────────────────────


def test_clean_courses_accepts_a_good_row():
    warnings = []
    accepted, rejected = parser.clean_courses(
        [course()], grade_letters=TAMU_LETTERS, warnings=warnings
    )

    assert rejected == []
    assert len(accepted) == 1
    assert accepted[0]["course_code"] == "MATH 251"
    assert accepted[0]["credit_hours"] == Decimal("3.00")
    assert accepted[0]["status"] == "completed"


@pytest.mark.parametrize(
    "bad, reason",
    [
        ({"credit_hours": "three"}, "uncoercible_credit_hours"),
        ({"credit_hours": None}, "uncoercible_credit_hours"),
        ({"credit_hours": -3}, "uncoercible_credit_hours"),
        ({"letter_grade": "B+"}, "unmapped_letter_grade"),   # TAMU has no B+
        ({"letter_grade": "Z"}, "unmapped_letter_grade"),
        ({"letter_grade": None}, "missing_letter_grade"),    # completed, no grade
        ({"course_code": None}, "missing_course_code"),
        ({"course_code": "   "}, "missing_course_code"),
        ({"status": "finished"}, "invalid_status"),
        ({"status": None}, "invalid_status"),
    ],
)
def test_bad_rows_are_rejected_not_repaired(bad, reason):
    warnings = []
    accepted, rejected = parser.clean_courses(
        [course(**bad)], grade_letters=TAMU_LETTERS, warnings=warnings
    )

    assert accepted == [], f"{bad} must not produce a writable row"
    assert len(rejected) == 1
    assert rejected[0].reason == reason
    # The raw entry survives so a review screen can show what was on the page.
    assert rejected[0].raw != {}


def test_rejecting_one_row_does_not_discard_the_good_ones():
    warnings = []
    accepted, rejected = parser.clean_courses(
        [
            course(course_code="MATH 251"),
            course(course_code="CHEM 107", credit_hours="not a number"),
            course(course_code="ENGL 104"),
        ],
        grade_letters=TAMU_LETTERS,
        warnings=warnings,
    )

    assert [c["course_code"] for c in accepted] == ["MATH 251", "ENGL 104"]
    assert len(rejected) == 1
    assert rejected[0].index == 1


def test_in_progress_course_may_have_no_grade():
    """The one case where a null letter_grade is legitimate."""
    warnings = []
    accepted, rejected = parser.clean_courses(
        [course(letter_grade=None, status="in_progress")],
        grade_letters=TAMU_LETTERS,
        warnings=warnings,
    )

    assert rejected == []
    assert accepted[0]["letter_grade"] is None
    assert accepted[0]["status"] == "in_progress"


def test_plus_minus_grade_is_accepted_where_the_map_has_it():
    """The same B+ that rejects for TAMU is valid for SMU."""
    warnings = []
    accepted, rejected = parser.clean_courses(
        [course(letter_grade="B+")], grade_letters=SMU_LETTERS, warnings=warnings
    )

    assert rejected == []
    assert accepted[0]["letter_grade"] == "B+"


def test_grades_are_checked_against_raw_map_keys_not_resolve_grade():
    """A TAMU B+ must REJECT, not normalize to B.

    gpa.resolve_grade would normalize it (uses_plus_minus=false strips the
    modifier). That is right for scoring stored data and wrong as a parse-time
    gate -- a B+ printed on a TAMU transcript is an anomaly a human should see.
    """
    warnings = []
    accepted, rejected = parser.clean_courses(
        [course(letter_grade="B+")], grade_letters=TAMU_LETTERS, warnings=warnings
    )

    assert accepted == []
    assert rejected[0].reason == "unmapped_letter_grade"


# ── 3. contract validation ──────────────────────────────────────────────────


def test_validate_requires_a_known_status():
    with pytest.raises(parser.TranscriptContractError):
        parser.validate_parsed_transcript({"courses": []}, grade_letters=TAMU_LETTERS)
    with pytest.raises(parser.TranscriptContractError):
        parser.validate_parsed_transcript(
            {"status": "maybe"}, grade_letters=TAMU_LETTERS
        )
    with pytest.raises(parser.TranscriptContractError):
        parser.validate_parsed_transcript(["not", "an", "object"], grade_letters=TAMU_LETTERS)


@pytest.mark.parametrize("status", ["not_a_transcript", "unparseable"])
def test_non_ok_status_carries_no_content_through(status):
    parsed = parser.validate_parsed_transcript(
        {"status": status, "courses": [course()]}, grade_letters=TAMU_LETTERS
    )

    assert parsed.status == status
    assert parsed.courses == []
    assert parsed.has_content is False


def test_term_summaries_are_parsed_when_present():
    parsed = parser.validate_parsed_transcript(
        payload(term_summaries=[{"term_label": "Fall 2023", "term_gpa": 3.5, "term_credit_hours": 15}]),
        grade_letters=TAMU_LETTERS,
    )

    assert len(parsed.term_summaries) == 1
    assert parsed.term_summaries[0].term_gpa == 3.5
    assert parsed.term_summaries[0].term_credit_hours == 15.0


# ── 4. MAX_PROMPT_CHARS is a hard error, not a truncation ───────────────────


def test_over_length_transcript_raises_instead_of_truncating():
    text = "x" * (parser.MAX_PROMPT_CHARS + 1)

    with pytest.raises(parser.TranscriptTooLongError) as exc:
        parser.build_messages(text, "PROMPT")

    assert "truncat" in str(exc.value).lower()


def test_at_the_limit_is_allowed_and_not_truncated():
    text = "x" * parser.MAX_PROMPT_CHARS
    messages = parser.build_messages(text, "PROMPT")

    assert text in messages[1]["content"]
    assert "truncated" not in messages[1]["content"].lower()


def test_build_messages_embeds_the_whole_transcript():
    text = "FIRST_MARKER\n" + ("filler\n" * 100) + "LAST_MARKER"
    messages = parser.build_messages(text, "PROMPT")

    assert "FIRST_MARKER" in messages[1]["content"]
    assert "LAST_MARKER" in messages[1]["content"]


# ── 5. temperature=0 on the parsing call ────────────────────────────────────


class _RecordingAI:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)

        class _R:
            def __init__(self, text):
                self.text = text
                self.model = "fake-model"

        return _R(self.text)


def test_parse_transcript_text_passes_temperature_zero(tmp_path):
    import json

    prompt = tmp_path / "prompt.md"
    prompt.write_text("PROMPT BODY", encoding="utf-8")
    ai = _RecordingAI(json.dumps(payload()))

    parsed, model = parser.parse_transcript_text(
        "some transcript text",
        ai,
        grade_letters=TAMU_LETTERS,
        prompt_path=prompt,
    )

    assert parsed.status == "ok"
    assert model == "fake-model"
    assert len(ai.calls) == 1
    assert ai.calls[0]["temperature"] == 0
    assert ai.calls[0]["role"] == "parsing"


# ── 6. term label parsing ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "label, year, season",
    [
        ("Fall 2023", 2023, "Fall"),
        ("FALL 2023", 2023, "Fall"),
        ("fall 2023", 2023, "Fall"),
        ("2023 Fall", 2023, "Fall"),
        ("Fall Semester 2023", 2023, "Fall"),
        ("Spring 2024", 2024, "Spring"),
        ("Summer 2024", 2024, "Summer"),
        ("Winter 2024", 2024, "Winter"),
        ("Autumn 2023", 2023, "Fall"),
        ("Maymester 2024", 2024, "Summer"),
        ("Fall Term 2023-2024", 2023, "Fall"),
    ],
)
def test_term_labels_resolve_to_year_and_season(label, year, season):
    resolved = terms.parse_term_label(label)

    assert (resolved.year, resolved.season) == (year, season)
    assert resolved.label == label


@pytest.mark.parametrize("label", ["", "   ", "Fall", "2023", "Term 5", "Semester One", None])
def test_unresolvable_term_labels_raise_rather_than_guess(label):
    with pytest.raises(terms.TermParseError):
        terms.parse_term_label(label)


def test_chronological_key_orders_seasons_within_a_year():
    ordered = sorted(
        [
            terms.parse_term_label("Fall 2023"),
            terms.parse_term_label("Spring 2023"),
            terms.parse_term_label("Summer 2023"),
            terms.parse_term_label("Winter 2023"),
        ],
        key=lambda t: t.chronological_key,
    )

    assert [t.season for t in ordered] == ["Winter", "Spring", "Summer", "Fall"]


# ── 7. catalog code normalization ───────────────────────────────────────────


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("MATH 251", "MATH 251"),
        ("math 251", "MATH 251"),
        ("MATH251", "MATH 251"),
        ("MATH-251", "MATH 251"),
        ("  MATH   251  ", "MATH 251"),
        ("math.251", "MATH 251"),
        ("MATH 251H", "MATH 251H"),
        ("engr102l", "ENGR 102L"),
    ],
)
def test_code_normalization_reaches_catalog_form(raw, expected):
    assert catalog.normalize_code(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "SEMINAR", "101", "---", None, 251])
def test_uncodeable_strings_normalize_to_none(raw):
    assert catalog.normalize_code(raw) is None


# ── 8. counts_toward_* flags ────────────────────────────────────────────────


GRADE_MAP = {
    "A": {"letter": "A", "points": 4.0, "counts_toward_gpa": True, "counts_toward_credit": True},
    "F": {"letter": "F", "points": 0.0, "counts_toward_gpa": True, "counts_toward_credit": True},
    "W": {"letter": "W", "points": None, "counts_toward_gpa": False, "counts_toward_credit": False},
    "P": {"letter": "P", "points": None, "counts_toward_gpa": False, "counts_toward_credit": True},
}


@pytest.mark.parametrize(
    "letter, status, expected",
    [
        ("A", "completed", (True, True)),
        ("F", "completed", (True, True)),      # an F counts toward BOTH
        ("W", "completed", (False, False)),
        ("P", "completed", (True, False)),     # pass earns credit, not GPA
        ("A", "in_progress", (False, False)),  # no final grade to score
        (None, "completed", (False, False)),
        ("Z", "completed", (False, False)),    # unmapped
    ],
)
def test_counts_flags_follow_the_grade_map(letter, status, expected):
    assert store.counts_flags(letter, status, GRADE_MAP) == expected


# ── 9. arithmetic cross-check ───────────────────────────────────────────────


def _completed(code, hours, letter, label="Fall 2023"):
    return {
        "course_code": code,
        "credit_hours": Decimal(str(hours)),
        "letter_grade": letter,
        "term_label": label,
        "status": "completed",
    }


def test_cross_check_passes_when_rows_match_printed_totals():
    courses = [
        _completed("MATH 251", 3, "A"),
        _completed("CHEM 107", 4, "A"),
        _completed("ENGL 104", 3, "F"),
    ]
    summaries = [parser.TermSummary("Fall 2023", term_gpa=2.80, term_credit_hours=10)]

    report = crosscheck.cross_check_terms(courses, summaries, GRADE_MAP)

    assert report.ok, report.to_dict()
    assert report.terms_checked == 1


def test_cross_check_flags_a_dropped_course():
    """The failure this exists to catch: a course silently missing."""
    courses = [_completed("MATH 251", 3, "A")]  # ENGL 104 dropped
    summaries = [parser.TermSummary("Fall 2023", term_gpa=4.0, term_credit_hours=6)]

    report = crosscheck.cross_check_terms(courses, summaries, GRADE_MAP)

    assert not report.ok
    fields = {m.field for m in report.mismatches}
    assert "term_credit_hours" in fields
    mismatch = next(m for m in report.mismatches if m.field == "term_credit_hours")
    assert mismatch.printed == 6
    assert mismatch.computed == 3.0
    assert mismatch.difference == -3.0


def test_cross_check_flags_a_duplicated_course():
    courses = [_completed("MATH 251", 3, "A"), _completed("MATH 251", 3, "A")]
    summaries = [parser.TermSummary("Fall 2023", term_gpa=4.0, term_credit_hours=3)]

    report = crosscheck.cross_check_terms(courses, summaries, GRADE_MAP)

    assert not report.ok
    assert any(m.field == "term_credit_hours" for m in report.mismatches)


def test_cross_check_skips_terms_with_nothing_printed():
    courses = [_completed("MATH 251", 3, "A")]
    summaries = [parser.TermSummary("Fall 2023", term_gpa=None, term_credit_hours=None)]

    report = crosscheck.cross_check_terms(courses, summaries, GRADE_MAP)

    assert report.ok
    assert report.terms_checked == 0
    assert report.terms_skipped == 1


def test_cross_check_ignores_in_progress_courses():
    courses = [
        _completed("MATH 251", 3, "A"),
        {
            "course_code": "CSCE 121",
            "credit_hours": Decimal("4"),
            "letter_grade": None,
            "term_label": "Fall 2023",
            "status": "in_progress",
        },
    ]
    summaries = [parser.TermSummary("Fall 2023", term_gpa=4.0, term_credit_hours=3)]

    report = crosscheck.cross_check_terms(courses, summaries, GRADE_MAP)

    assert report.ok, "in-progress hours are not part of a printed term total"


def test_cross_check_never_raises_on_odd_input():
    courses = [
        {"course_code": "X", "credit_hours": None, "letter_grade": "A", "term_label": "Fall 2023", "status": "completed"},
        {"course_code": "Y", "credit_hours": "abc", "letter_grade": "Z", "term_label": "Fall 2023", "status": "completed"},
    ]
    summaries = [parser.TermSummary("Fall 2023", term_gpa=3.0, term_credit_hours=6)]

    report = crosscheck.cross_check_terms(courses, summaries, GRADE_MAP)

    assert isinstance(report.to_dict(), dict)
