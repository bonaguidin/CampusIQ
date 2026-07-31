"""Tests for GET /api/v2/student/me/gpa (CampusIQ_career/api.py).

The Supabase client is fully mocked -- no network calls, no real
Supabase project involved.
"""

import os

import pytest
from fastapi.testclient import TestClient

from CampusIQ_career import api


# ---------------------------------------------------------------------------
# Fake Supabase client: mimics the .table(...).select(...).eq(...).execute()
# chain used by the route, filtering an in-memory table dict.
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, rows):
        self._rows = list(rows)

    def select(self, *args, **kwargs):
        return self

    def eq(self, key, value):
        self._rows = [r for r in self._rows if r.get(key) == value]
        return self

    def execute(self):
        return FakeResponse(self._rows)


class FakeClient:
    def __init__(self, tables: dict):
        self._tables = tables

    def table(self, name):
        return FakeQuery(self._tables.get(name, []))


TAMU_INSTITUTION_ROW = {
    "id": "inst-tamu",
    "name": "Texas A&M University",
    "uses_plus_minus": False,
    "transfer_grades_count_toward_gpa": False,
}

TAMU_GRADE_MAP_ROWS = [
    {"institution_id": "inst-tamu", "letter": "A", "points": 4.0, "counts_toward_gpa": True, "counts_toward_credit": True},
    {"institution_id": "inst-tamu", "letter": "B", "points": 3.0, "counts_toward_gpa": True, "counts_toward_credit": True},
    {"institution_id": "inst-tamu", "letter": "C", "points": 2.0, "counts_toward_gpa": True, "counts_toward_credit": True},
    {"institution_id": "inst-tamu", "letter": "D", "points": 1.0, "counts_toward_gpa": True, "counts_toward_credit": True},
    {"institution_id": "inst-tamu", "letter": "F", "points": 0.0, "counts_toward_gpa": True, "counts_toward_credit": True},
    {"institution_id": "inst-tamu", "letter": "W", "points": None, "counts_toward_gpa": False, "counts_toward_credit": False},
    {"institution_id": "inst-tamu", "letter": "I", "points": None, "counts_toward_gpa": False, "counts_toward_credit": False},
]


def make_tables(student_id="stu-1", course_rows=None, include_home=True, include_institution=True):
    tables = {
        "students": [{"id": student_id, "name": "Test Student"}],
        "student_institutions": (
            [{"student_id": student_id, "institution_id": "inst-tamu", "relationship": "home"}]
            if include_home
            else []
        ),
        "institutions": [TAMU_INSTITUTION_ROW] if include_institution else [],
        "grade_point_map": TAMU_GRADE_MAP_ROWS,
        "course_records": course_rows if course_rows is not None else [],
    }
    return tables


def _course_row(course_code, letter_grade, status, credit_hours=3.0, student_id="stu-1"):
    return {
        "student_id": student_id,
        "course_code": course_code,
        "credit_hours": credit_hours,
        "letter_grade": letter_grade,
        "credit_type": "resident",
        "status": status,
        "institution_id": "inst-tamu",
        "confirmed_at": "2026-01-01T00:00:00Z",
    }


@pytest.fixture
def client():
    return TestClient(api.app)


def _patch_client(monkeypatch, tables):
    fake = FakeClient(tables)
    monkeypatch.setattr(api, "build_client_for_token", lambda token: fake)
    return fake


# 1. Missing Authorization header -> 401.
def test_missing_authorization_header_returns_401(client):
    response = client.get("/api/v2/student/me/gpa")
    assert response.status_code == 401


# 2. Malformed Authorization header -> 401.
@pytest.mark.parametrize(
    "header_value",
    ["", "Token abc123", "Bearer", "Bearer   ", "abc123"],
)
def test_malformed_authorization_header_returns_401(client, header_value):
    response = client.get("/api/v2/student/me/gpa", headers={"Authorization": header_value})
    assert response.status_code == 401


# 3. Valid token, no visible students row -> 404, and SUPABASE_SECRET_KEY never read.
def test_no_visible_student_row_returns_404_and_never_reads_secret_key(client, monkeypatch):
    _patch_client(monkeypatch, make_tables(course_rows=None) | {"students": []})

    original_get = os.environ.get

    def spying_get(key, *args, **kwargs):
        if key == "SUPABASE_SECRET_KEY":
            raise AssertionError("SUPABASE_SECRET_KEY must never be read by this route")
        return original_get(key, *args, **kwargs)

    monkeypatch.setattr(os.environ, "get", spying_get)

    response = client.get("/api/v2/student/me/gpa", headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 404


# 4. Valid token, no home institution -> 409.
def test_no_home_institution_returns_409(client, monkeypatch):
    _patch_client(monkeypatch, make_tables(include_home=False))
    response = client.get("/api/v2/student/me/gpa", headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 409


# 5. Valid token, full record -> 200 with the exact shape.
def test_full_record_returns_expected_shape(client, monkeypatch):
    course_rows = [
        _course_row("ENGR 102", "A", "completed", credit_hours=2.0),
        _course_row("MATH 151", "B", "in_progress", credit_hours=4.0),
    ]
    _patch_client(monkeypatch, make_tables(course_rows=course_rows))

    response = client.get("/api/v2/student/me/gpa", headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200
    body = response.json()

    assert set(body.keys()) == {
        "institution",
        "official",
        "projected",
        "completed_hours",
        "in_progress_hours",
        "earned_hours",
        "excluded",
    }
    assert body["institution"] == {
        "id": "inst-tamu",
        "name": "Texas A&M University",
        "uses_plus_minus": False,
    }
    assert body["official"] == 4.0
    assert body["completed_hours"] == 2.0
    assert body["in_progress_hours"] == 4.0
    assert isinstance(body["excluded"], list)


# 6. All courses in_progress -> official null, projected a number, both keys present.
def test_all_in_progress_official_null_projected_numeric(client, monkeypatch):
    course_rows = [
        _course_row("ENGR 102", "A", "in_progress", credit_hours=3.0),
        _course_row("MATH 151", "B", "in_progress", credit_hours=3.0),
    ]
    _patch_client(monkeypatch, make_tables(course_rows=course_rows))

    response = client.get("/api/v2/student/me/gpa", headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200
    body = response.json()

    assert "official" in body and body["official"] is None
    assert "projected" in body and isinstance(body["projected"], float)
    assert body["projected"] == 3.5


# 7. Zero course records -> both null, no exception.
def test_zero_course_records_both_null(client, monkeypatch):
    _patch_client(monkeypatch, make_tables(course_rows=[]))

    response = client.get("/api/v2/student/me/gpa", headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200
    body = response.json()
    assert body["official"] is None
    assert body["projected"] is None
    assert body["completed_hours"] == 0.0
    assert body["in_progress_hours"] == 0.0
    assert body["excluded"] == []


# 8. TAMU-shaped map with a 'B+' input -> normalization, not an error.
def test_bplus_against_tamu_map_normalizes_instead_of_erroring(client, monkeypatch):
    course_rows = [_course_row("ENGR 102", "B+", "completed", credit_hours=3.0)]
    _patch_client(monkeypatch, make_tables(course_rows=course_rows))

    response = client.get("/api/v2/student/me/gpa", headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200
    body = response.json()
    # 'B+' normalizes to 'B' (3.0) on a plus/minus-less TAMU map, not unmapped/excluded.
    assert body["official"] == 3.0
    assert body["excluded"] == []


# 9. Repeat policy: a first attempt carrying excluded_from_gpa_by is dropped
#    from the GPA, and only the second attempt scores.
def test_repeat_excluded_attempt_is_dropped_from_gpa(client, monkeypatch):
    # HIST 101 taken twice: first a D, then a B. The first attempt points at
    # the second via excluded_from_gpa_by (SMU-style grade replacement), so
    # only the B may score. Both rows are 'completed' and confirmed.
    first_attempt = _course_row("HIST 101", "D", "completed", credit_hours=3.0)
    first_attempt["id"] = "course-first"
    second_attempt = _course_row("HIST 101", "B", "completed", credit_hours=3.0)
    second_attempt["id"] = "course-second"
    first_attempt["excluded_from_gpa_by"] = second_attempt["id"]
    second_attempt["excluded_from_gpa_by"] = None

    _patch_client(monkeypatch, make_tables(course_rows=[first_attempt, second_attempt]))

    response = client.get("/api/v2/student/me/gpa", headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200
    body = response.json()

    # Hand-computed: only the B counts. B = 3.0 points x 3.0 hours = 9.0
    # quality points over 3.0 gpa_hours -> 3.0. Had the excluded D been
    # counted too, this would be (9.0 + 3.0) / 6.0 = 2.0.
    assert body["official"] == 3.0
    assert body["projected"] == 3.0

    # The excluded attempt is reported with the repeat-specific reason.
    excluded = {(e["course_code"], e["reason"]) for e in body["excluded"]}
    assert ("HIST 101", "excluded_by_repeat") in excluded
    assert sum(1 for e in body["excluded"] if e["reason"] == "excluded_by_repeat") == 1

    # Both attempts were completed and earned credit, so earned_hours keeps
    # both -- only the grade points were dropped.
    assert body["earned_hours"] == 6.0
    assert body["completed_hours"] == 6.0
