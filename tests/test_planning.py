"""Term view, planned courses, and catalog search.

The database-facing functions are exercised against a fake client with the
same surface transcript/store.py's tests use: .table().select().eq().execute()
returning a .data list. Nothing here talks to Supabase.
"""

from datetime import date

import pytest

from GradusIQ_career.planning import planned as planned_module
from GradusIQ_career.planning.planned import (
    PlannedCourseError,
    add_planned,
    clean_credit_hours,
    ensure_term_row,
    list_planned,
    remove_planned,
)
from GradusIQ_career.planning.search import normalize_search_prefix, search_catalog
from GradusIQ_career.planning.term_view import build_terms_view, term_key
from GradusIQ_career.transcript import terms


# ── fake client ─────────────────────────────────────────────────────────────


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, table):
        self.table = table
        self.filters = {}

    def select(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def insert(self, payload):
        self.table.inserted.append(payload)
        row = {"id": f"new-{len(self.table.inserted)}", **payload}
        self.table.rows.append(row)
        self._result = [row]
        return self

    def delete(self):
        self._deleting = True
        return self

    def execute(self):
        if getattr(self, "_result", None) is not None:
            return FakeResponse(self._result)
        matched = [
            row
            for row in self.table.rows
            if all(str(row.get(key)) == str(value) for key, value in self.filters.items())
        ]
        if getattr(self, "_deleting", False):
            for row in matched:
                self.table.rows.remove(row)
            self.table.deleted.extend(matched)
        return FakeResponse(matched)


class FakeTable:
    def __init__(self, rows):
        self.rows = list(rows)
        self.inserted = []
        self.deleted = []


class FakeClient:
    def __init__(self, **tables):
        self.tables = {name: FakeTable(rows) for name, rows in tables.items()}
        self.rpc_calls = []
        self.rpc_result = []

    def table(self, name):
        self.tables.setdefault(name, FakeTable([]))
        return FakeQuery(self.tables[name])

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        # supabase-py's rpc() returns a builder that must be .execute()d, the
        # same as .table(). Modelled exactly, so the test cannot pass against a
        # caller that forgets the execute.
        return _FakeRpc(self.rpc_result)


class _FakeRpc:
    def __init__(self, data):
        self._data = data

    def execute(self):
        return FakeResponse(self._data)


# ── season vocabulary ───────────────────────────────────────────────────────


def test_may_and_august_are_first_class_seasons():
    assert terms.parse_term_label("May 2026").season == "May"
    assert terms.parse_term_label("August 2026").season == "August"


def test_maymester_still_resolves_to_summer():
    # Deliberate: SMU's calendar says "May 2026", never "Maymester", so the
    # alias is left pointing where whatever transcripts printed it expect.
    assert terms.parse_term_label("Maymester 2024").season == "Summer"


def test_smu_intersessions_sort_between_the_terms_they_fall_between():
    labels = ["Fall 2026", "May 2026", "Spring 2026", "August 2026", "Summer 2026", "Winter 2026"]
    ordered = sorted(
        (terms.parse_term_label(label) for label in labels),
        key=lambda term: term.chronological_key,
    )
    assert [term.season for term in ordered] == [
        "Winter", "Spring", "May", "Summer", "August", "Fall",
    ]


def test_season_order_positions_match_smu_calendar_dates():
    """The ordinals are not a preference -- SMU's own dates fix them."""
    calendar = [
        ("Spring", date(2026, 1, 20)),
        ("May", date(2026, 5, 16)),
        ("Summer", date(2026, 6, 3)),
        ("August", date(2026, 8, 6)),
        ("Fall", date(2026, 8, 24)),
    ]
    by_ordinal = sorted(calendar, key=lambda item: terms.SEASON_ORDER[item[0]])
    by_start_date = sorted(calendar, key=lambda item: item[1])
    assert by_ordinal == by_start_date


# ── term view ───────────────────────────────────────────────────────────────


TERM_DATES = [
    {"year": 2026, "season": "Summer", "label": "Summer 2026",
     "start_date": "2026-05-26", "end_date": "2026-08-06"},
    {"year": 2026, "season": "Fall", "label": "Fall 2026",
     "start_date": "2026-08-24", "end_date": "2026-12-10"},
    {"year": 2027, "season": "Spring", "label": "Spring 2027",
     "start_date": "2027-01-19", "end_date": "2027-05-11"},
]


def test_upcoming_term_is_the_next_one_not_yet_started():
    view = build_terms_view([], TERM_DATES, date(2026, 8, 11))
    assert view.upcoming_term_key == term_key(2026, "Fall")


def test_the_term_in_progress_is_not_the_default():
    # Mid-fall, a student planning courses is planning spring.
    view = build_terms_view([], TERM_DATES, date(2026, 10, 1))
    assert view.upcoming_term_key == term_key(2027, "Spring")


def test_a_term_starting_today_counts_as_started():
    view = build_terms_view([], TERM_DATES, date(2026, 8, 24))
    assert view.upcoming_term_key == term_key(2027, "Spring")


def test_student_label_wins_over_the_calendar_label():
    student_terms = [
        {"id": "t1", "label": "Fall 2026 - College Station", "year": 2026,
         "season": "Fall", "sequence": 2},
    ]
    view = build_terms_view(student_terms, TERM_DATES, date(2026, 8, 11))
    fall = next(term for term in view.terms if term["key"] == term_key(2026, "Fall"))
    assert fall["label"] == "Fall 2026 - College Station"
    assert fall["start_date"] == "2026-08-24"
    assert fall["enrolled"] is True


def test_calendar_terms_the_student_has_no_row_for_are_plannable():
    view = build_terms_view([], TERM_DATES, date(2026, 8, 11))
    assert all(term["enrolled"] is False for term in view.terms)
    assert all(term["id"] is None for term in view.terms)


def test_a_term_with_no_calendar_row_still_appears_but_cannot_be_upcoming():
    """The five seeded season='current' rows land here."""
    seeded = [{"id": "t9", "label": "Current Term", "year": 2026,
               "season": "current", "sequence": 1}]
    view = build_terms_view(seeded, TERM_DATES, date(2026, 8, 11))

    current = next(term for term in view.terms if term["label"] == "Current Term")
    assert current["start_date"] is None
    assert current["is_upcoming"] is False
    # An unknown season sorts after every known one WITHIN ITS OWN YEAR -- the
    # fallback ordinal is a season position, not a year. So the 2026 'current'
    # row lands after Fall 2026 and still before Spring 2027.
    labels = [term["label"] for term in view.terms]
    assert labels == ["Summer 2026", "Fall 2026", "Current Term", "Spring 2027"]
    assert view.upcoming_term_key == term_key(2026, "Fall")


def test_no_future_term_means_no_upcoming_term():
    view = build_terms_view([], TERM_DATES, date(2030, 1, 1))
    assert view.upcoming_term_key is None
    assert all(term["is_upcoming"] is False for term in view.terms)


def test_terms_are_ordered_chronologically_across_years():
    view = build_terms_view([], TERM_DATES, date(2026, 8, 11))
    assert [term["key"] for term in view.terms] == [
        term_key(2026, "Summer"), term_key(2026, "Fall"), term_key(2027, "Spring"),
    ]


# ── search normalization ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "typed, expected",
    [
        ("math251", "MATH 251"),      # TAMU, no separator
        ("MATH-251", "MATH 251"),     # punctuation separator
        ("  math  251 ", "MATH 251"),
        ("acct2301", "ACCT 2301"),    # SMU, four digits
        ("csce", "CSCE"),             # subject only
        ("csce 1", "CSCE 1"),         # partial number -- normalize_code rejects this
        ("", ""),
        ("   ", ""),
    ],
)
def test_normalize_search_prefix(typed, expected):
    assert normalize_search_prefix(typed) == expected


def test_title_queries_are_left_alone():
    assert normalize_search_prefix("Data Structures") == "Data Structures"


def test_search_is_institution_scoped_and_normalized():
    client = FakeClient()
    client.rpc_result = [
        {"id": "c1", "code": "MATH 251", "title": "Engineering Mathematics III",
         "department": "Mathematics", "course_level": 200, "credit_min": 3, "credit_max": 3},
    ]
    results = search_catalog(client, "inst-1", "math251")

    name, params = client.rpc_calls[0]
    assert name == "search_course_catalog"
    assert params["p_institution_id"] == "inst-1"
    assert params["p_query"] == "MATH 251"
    assert results[0].code == "MATH 251"


def test_empty_query_never_reaches_the_database():
    client = FakeClient()
    assert search_catalog(client, "inst-1", "   ") == []
    assert client.rpc_calls == []


def test_search_limit_is_bounded():
    client = FakeClient()
    search_catalog(client, "inst-1", "csce", limit=5000)
    assert client.rpc_calls[0][1]["p_limit"] == 50


# ── planned courses ─────────────────────────────────────────────────────────


def test_ensure_term_row_reuses_an_existing_term_by_year_and_season():
    client = FakeClient(academic_terms=[
        {"id": "t1", "student_id": "s1", "label": "Fall 2026 - College Station",
         "year": 2026, "season": "Fall", "sequence": 0},
    ])
    term_id = ensure_term_row(client, "s1", "inst-1", 2026, "Fall", label="Fall 2026")

    assert term_id == "t1"
    assert client.tables["academic_terms"].inserted == []


def test_ensure_term_row_creates_a_term_the_student_has_never_enrolled_in():
    client = FakeClient(academic_terms=[
        {"id": "t1", "student_id": "s1", "label": "Fall 2025", "year": 2025,
         "season": "Fall", "sequence": 3},
    ])
    term_id = ensure_term_row(client, "s1", "inst-1", 2027, "Spring", label="Spring 2027")

    assert term_id == "new-1"
    created = client.tables["academic_terms"].inserted[0]
    # Appended after the existing maximum, never renumbered -- terms.py's rule.
    assert created["sequence"] == 4
    assert (created["year"], created["season"]) == (2027, "Spring")


def test_ensure_term_row_rejects_an_unknown_season():
    client = FakeClient(academic_terms=[])
    with pytest.raises(PlannedCourseError):
        ensure_term_row(client, "s1", "inst-1", 2026, "Autumn")


def test_add_planned_writes_the_expected_payload():
    client = FakeClient(planned_courses=[])
    result = add_planned(
        client, "s1", "inst-1",
        course_code="CSCE 121", term_id="t1", title="Intro to Program Design",
        credit_hours=4, catalog_course_id="cat-1",
    )

    payload = client.tables["planned_courses"].inserted[0]
    assert payload["student_id"] == "s1"
    assert payload["term_id"] == "t1"
    assert payload["course_code"] == "CSCE 121"
    assert payload["credit_hours"] == "4.00"
    assert result.to_dict()["kind"] == "planned"


def test_add_planned_allows_a_duplicate():
    """No unique key, by decision -- planning is a scratchpad."""
    client = FakeClient(planned_courses=[])
    add_planned(client, "s1", "inst-1", course_code="CSCE 121", term_id="t1")
    add_planned(client, "s1", "inst-1", course_code="CSCE 121", term_id="t1")
    assert len(client.tables["planned_courses"].inserted) == 2


def test_add_planned_accepts_a_null_credit_hours():
    client = FakeClient(planned_courses=[])
    add_planned(client, "s1", "inst-1", course_code="ENGR 485", term_id="t1")
    assert client.tables["planned_courses"].inserted[0]["credit_hours"] is None


@pytest.mark.parametrize("value", ["not a number", -1, True, 1000])
def test_bad_credit_hours_are_rejected(value):
    with pytest.raises(PlannedCourseError):
        clean_credit_hours(value)


def test_missing_course_code_is_rejected():
    client = FakeClient(planned_courses=[])
    with pytest.raises(PlannedCourseError):
        add_planned(client, "s1", "inst-1", course_code="  ")


def test_list_planned_filters_by_term():
    client = FakeClient(planned_courses=[
        {"id": "p1", "student_id": "s1", "term_id": "t1", "course_code": "CSCE 121",
         "title": None, "credit_hours": 3, "catalog_course_id": None, "created_at": "x"},
        {"id": "p2", "student_id": "s1", "term_id": "t2", "course_code": "MATH 251",
         "title": None, "credit_hours": 3, "catalog_course_id": None, "created_at": "y"},
    ])
    rows = list_planned(client, "s1", term_id="t1")
    assert [row.id for row in rows] == ["p1"]


def test_remove_planned_is_scoped_to_the_owner():
    client = FakeClient(planned_courses=[
        {"id": "p1", "student_id": "s1", "term_id": "t1", "course_code": "CSCE 121",
         "title": None, "credit_hours": 3, "catalog_course_id": None, "created_at": "x"},
    ])
    assert remove_planned(client, "s2", "p1") is False
    assert remove_planned(client, "s1", "p1") is True
    assert client.tables["planned_courses"].rows == []


def test_planning_never_reads_or_writes_course_records():
    """The isolation Phase 1 (planned_courses CRUD) rests on, asserted rather
    than assumed. planned.py, term_view.py and search.py must not touch
    course_records or the GPA path -- checked against source text so a future
    edit that adds a course_records write to one of THOSE modules fails here
    rather than in a GPA that quietly changes.

    lifecycle.py is EXEMPT and deliberately so. It is Phase 2: the module
    whose entire job is moving a row from planned_courses into course_records
    once a term activates (promote_due_planned_courses), and reading/writing
    course_records directly for the in-progress edit and finalize surfaces.
    That is not a violation of the isolation the other three modules keep --
    it is the one module allowed to cross it, on purpose, so it is checked by
    its own tests (test_lifecycle.py) instead of by this invariant.

    course_records may still be NAMED in a comment explaining why it is not
    used, so only executable references are examined.
    """
    import ast
    import pathlib

    package_dir = pathlib.Path(planned_module.__file__).parent
    offenders = []

    for path in sorted(package_dir.glob("*.py")):
        if path.name == "lifecycle.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            # .table("course_records") in any form.
            if isinstance(node, ast.Constant) and node.value == "course_records":
                offenders.append(f"{path.name}: string literal 'course_records'")
            # from ..academics import ... / import GradusIQ_career.academics...
            if isinstance(node, ast.ImportFrom) and "academics" in (node.module or ""):
                offenders.append(f"{path.name}: imports {node.module}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if "academics" in alias.name:
                        offenders.append(f"{path.name}: imports {alias.name}")

    assert offenders == []


# ── SMU term-date fetch script ──────────────────────────────────────────────
#
# The script is not an importable package module, so it is loaded by path.
# build_rows is pure -- it takes the Coursedog payload and returns rows -- so
# the real network response shape can be exercised without a request.


def _load_fetch_script():
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "fetch_smu_term_dates.py"
    spec = importlib.util.spec_from_file_location("fetch_smu_term_dates", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Shapes taken verbatim from the live endpoint on 2026-08-11.
COURSEDOG_TERMS = [
    {"id": "1257", "displayName": "Fall 2025", "startDate": "2025-08-25",
     "endDate": "2025-12-17", "year": "2026", "historical": False},
    {"id": "1261", "displayName": "January 2026", "startDate": "2025-12-18",
     "endDate": "2026-01-16", "year": "2026", "historical": False},
    {"id": "1263", "displayName": "May 2026", "startDate": "2026-05-16",
     "endDate": "2026-06-02", "year": "2026", "historical": False},
    {"id": "1266", "displayName": "August 2026", "startDate": "2026-08-06",
     "endDate": "2026-08-20", "year": "2026", "historical": False},
    {"id": "1267", "displayName": "Fall 2026", "startDate": "2026-08-24",
     "endDate": "2026-12-16", "year": "2027", "historical": False},
    # Placeholder: month boundaries, not a registrar's calendar.
    {"id": "1277", "displayName": "Fall 2027", "startDate": "2027-09-01",
     "endDate": "2027-12-31", "year": "2028", "historical": False},
    {"id": "1014", "displayName": "Summer 2001", "startDate": "2001-06-01",
     "endDate": "2001-08-02", "year": "2001", "historical": True},
    {"id": "9998", "displayName": "Unknown Exp Grad SIRS (1212)", "startDate": "9998-09-01",
     "endDate": "9998-12-31", "year": "9998", "historical": True},
]


def test_fetch_script_derives_the_calendar_year_not_coursedogs_academic_year():
    """Coursedog files Fall 2025 under year='2026'. Using it would be wrong."""
    module = _load_fetch_script()
    rows, _ = module.build_rows(COURSEDOG_TERMS, date(2026, 8, 11))
    fall_2025 = next(row for row in rows if row["label"] == "Fall 2025")
    assert fall_2025["year"] == 2025


def test_fetch_script_maps_smu_intersessions_to_their_own_seasons():
    module = _load_fetch_script()
    rows, _ = module.build_rows(COURSEDOG_TERMS, date(2026, 8, 11))
    by_label = {row["label"]: row["season"] for row in rows}
    assert by_label["May 2026"] == "May"
    assert by_label["August 2026"] == "August"
    assert by_label["January 2026"] == "Winter"


def test_fetch_script_excludes_placeholders_historical_and_the_sentinel():
    module = _load_fetch_script()
    rows, skipped = module.build_rows(COURSEDOG_TERMS, date(2026, 8, 11))
    labels = {row["label"] for row in rows}

    # Fall 2027's 09-01..12-31 is a placeholder; importing it would give
    # upcoming-term detection confidently wrong dates a year from now.
    assert "Fall 2027" not in labels
    assert "Summer 2001" not in labels
    assert "Unknown Exp Grad SIRS (1212)" not in labels

    reasons = dict(skipped)
    assert "outside the import window" in reasons["Fall 2027"]
    assert reasons["Summer 2001"] == "historical"


def test_fetch_script_reports_every_exclusion_rather_than_dropping_silently():
    module = _load_fetch_script()
    rows, skipped = module.build_rows(COURSEDOG_TERMS, date(2026, 8, 11))
    assert len(rows) + len(skipped) == len(COURSEDOG_TERMS)


def test_fetch_script_refuses_two_terms_claiming_one_season():
    """A collision would otherwise fail the unique key mid-import."""
    module = _load_fetch_script()
    duplicated = [
        {"id": "a", "displayName": "Fall 2026", "startDate": "2026-08-24",
         "endDate": "2026-12-16", "year": "2027", "historical": False},
        {"id": "b", "displayName": "Fall 2026 Extended", "startDate": "2026-08-25",
         "endDate": "2026-12-18", "year": "2027", "historical": False},
    ]
    rows, skipped = module.build_rows(duplicated, date(2026, 8, 11))
    assert len(rows) == 1
    assert "duplicate season" in dict(skipped)["Fall 2026 Extended"]


def test_fetch_script_rejects_a_reversed_date_range():
    module = _load_fetch_script()
    bad = [{"id": "x", "displayName": "Fall 2026", "startDate": "2026-12-16",
            "endDate": "2026-08-24", "year": "2027", "historical": False}]
    rows, skipped = module.build_rows(bad, date(2026, 8, 11))
    assert rows == []
    assert "precedes" in dict(skipped)["Fall 2026"]
