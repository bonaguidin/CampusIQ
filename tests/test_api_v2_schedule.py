"""Tests for GET /api/v2/student/me/schedule (GradusIQ_career/api.py).

Mirrors test_api_v2_requirement_satisfaction.py's FakeClient/monkeypatch
convention exactly, reusing its ethan_brooks_tables() as the base and
extending it with the tables this route additionally needs: institutions
(for LocalCatalogRepository institution resolution), students.expected_
graduation, academic_term_dates (for the starting-term horizon), and
course_catalog rows widened with real credit_min/credit_max pulled from
data/catalog/smu/*.json (see the build task's investigation -- all 63
coursedog_group_ids in the shared fixture resolve cleanly against the real
catalog with matching codes).
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from GradusIQ_career import api
from test_api_v2_requirement_satisfaction import (
    CATALOG_YEAR,
    PROXY_HEADERS,
    SMU_INSTITUTION_ID,
    TEST_PROXY_SECRET,
    FakeClient,
    ethan_brooks_tables,
    make_test_config,
    student_with_no_program_tables,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ethan_brooks_requirement_tree.json"
SCHEDULE_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ethan_brooks_scheduler_input.json"
URL = "/api/v2/student/me/schedule"

# Real credit_min/credit_max per coursedog_group_id, cross-referenced against
# every entry in the shared fixture's catalog_by_gid (63 gids, all resolve
# cleanly, all codes match) directly from data/catalog/smu/*.json.
_REAL_CREDIT_ROWS = json.loads((Path(__file__).parent / "fixtures" / "smu_catalog_credit_rows.json").read_text())

# Six long terms, Fall 2026 (the real upcoming term as of the fixture's
# 2026-08-19 pull date) through Spring 2029 -- matches spec §10.1's "5 terms,
# comfortably inside the 6-term horizon to Spring 2029" worked example.
_SMU_TERM_DATES = [
    {"institution_id": SMU_INSTITUTION_ID, "year": 2026, "season": "Fall", "label": "Fall 2026", "start_date": "2026-08-24", "end_date": "2026-12-12"},
    {"institution_id": SMU_INSTITUTION_ID, "year": 2027, "season": "Spring", "label": "Spring 2027", "start_date": "2027-01-19", "end_date": "2027-05-08"},
    {"institution_id": SMU_INSTITUTION_ID, "year": 2027, "season": "Fall", "label": "Fall 2027", "start_date": "2027-08-23", "end_date": "2027-12-11"},
    {"institution_id": SMU_INSTITUTION_ID, "year": 2028, "season": "Spring", "label": "Spring 2028", "start_date": "2028-01-18", "end_date": "2028-05-06"},
    {"institution_id": SMU_INSTITUTION_ID, "year": 2028, "season": "Fall", "label": "Fall 2028", "start_date": "2028-08-21", "end_date": "2028-12-09"},
    {"institution_id": SMU_INSTITUTION_ID, "year": 2029, "season": "Spring", "label": "Spring 2029", "start_date": "2029-01-16", "end_date": "2029-05-05"},
]


def _schedule_tables(expected_graduation="Spring 2029"):
    tables, student_id, program_id = ethan_brooks_tables()
    tables["institutions"] = [{"id": SMU_INSTITUTION_ID, "name": "Southern Methodist University"}]
    tables["students"][0]["expected_graduation"] = expected_graduation
    tables["academic_terms"] = []
    tables["academic_term_dates"] = _SMU_TERM_DATES
    tables["course_catalog"] = [
        {"institution_id": SMU_INSTITUTION_ID, "code": row["code"], "coursedog_group_id": row["coursedog_group_id"], "credit_min": row["credit_min"], "credit_max": row["credit_max"]}
        for row in _REAL_CREDIT_ROWS
    ]
    return tables, student_id, program_id


@pytest.fixture
def client():
    return TestClient(api.create_app(make_test_config()), headers=PROXY_HEADERS)


def _patch_client(monkeypatch, tables):
    fake = FakeClient(tables)
    monkeypatch.setattr(api, "build_client_for_token", lambda token: fake)
    return fake


# 1. Ethan Brooks -- 200, full ScheduleResult, matches the known-correct
#    13-course / 5-term plan.
def test_ethan_brooks_returns_full_schedule_result(client, monkeypatch):
    tables, student_id, program_id = _schedule_tables()
    _patch_client(monkeypatch, tables)

    response = client.get(URL, headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200
    body = response.json()

    assert body["student_id"] == student_id
    assert body["program_id"] == program_id
    assert body["status"] == "SCHEDULED"
    assert body["failure"] is None

    schedule_fixture = json.loads(SCHEDULE_FIXTURE_PATH.read_text())
    expected_unscheduled_names = {row["name"] for row in schedule_fixture["unscheduled"]}
    assert {u["name"] for u in body["unscheduled"]} == expected_unscheduled_names
    assert len(body["unscheduled"]) == 7

    scheduled_codes = {course["course_code"] for term in body["terms"] for course in term["courses"]}
    expected_codes = {row["course_code"] for row in schedule_fixture["courses"]}
    assert scheduled_codes == expected_codes
    assert len(scheduled_codes) == 13

    assert len(body["terms"]) == 5
    assert body["terms"][0]["term_key"] == "2026-Fall"
    for term in body["terms"]:
        assert term["total_credit_hours"] <= 15.0


# 2. No program data (every real student except Ethan Brooks) -> 200, skipped.
def test_no_program_data_returns_200_skipped(client, monkeypatch):
    _patch_client(monkeypatch, student_with_no_program_tables())

    response = client.get(URL, headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200
    body = response.json()
    assert body["feature"] == "SCHEDULE"
    assert body["status"] == "skipped"


# 3. Program data present but no expected_graduation on record -> 200, skipped.
def test_no_expected_graduation_returns_200_skipped(client, monkeypatch):
    tables, _student_id, _program_id = _schedule_tables(expected_graduation=None)
    _patch_client(monkeypatch, tables)

    response = client.get(URL, headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200
    body = response.json()
    assert body["feature"] == "SCHEDULE"
    assert body["status"] == "skipped"
    assert body["missing_fields"][0]["path"] == "students.expected_graduation"


# 4. Over-constrained: an expected_graduation in the immediate past relative
#    to the starting term forces max_terms down to 0 against a non-empty
#    course list -- schedule_courses()'s own over-constrained detection
#    fires, and the route returns 200 with the ERROR payload intact, not a
#    4xx/5xx.
def test_over_constrained_returns_200_with_error_payload(client, monkeypatch):
    tables, _student_id, _program_id = _schedule_tables(expected_graduation="Fall 2025")
    _patch_client(monkeypatch, tables)

    response = client.get(URL, headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "ERROR"
    assert body["terms"] == []
    assert body["unscheduled"] == []
    assert body["failure"] is not None
    assert body["failure"]["error_class"]
