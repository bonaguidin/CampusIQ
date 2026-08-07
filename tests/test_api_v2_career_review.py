"""Tests for GET/PATCH /api/v2/student/me/career/review.

The Supabase double here is deliberately NOT shared with
tests/test_api_v2_resume.py. It has to model three behaviors that file's fake
does not: the confirmed_at is-null filter on UPDATE, the empty-result
ambiguity PostgREST returns for "absent" vs "not yours" vs "already
confirmed", and a 23505 unique violation raised by an UPDATE that renames a
row onto another row's natural key. Those are the mechanics under test, so
they are modelled explicitly rather than borrowed.

All three behaviors were verified live against the database under a real
non-admin session token before this fake was written.
"""

import pytest
from fastapi.testclient import TestClient

from CampusIQ_career import api


TEST_PROXY_SECRET = "test-proxy-secret"
PROXY_HEADERS = {api.PROXY_SECRET_HEADER: TEST_PROXY_SECRET}
AUTH = {"Authorization": "Bearer real-session-jwt"}
HEADERS = {**PROXY_HEADERS, **AUTH}

STUDENT_A = "8f14e45f-ceea-467a-9f0e-1c2d3e4f5a6b"
STUDENT_B = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"

REVIEW = "/api/v2/student/me/career/review"

NATURAL_KEYS = {
    "certifications": ("student_id", "name"),
    "work_experience": ("student_id", "employer", "role"),
    "projects": ("student_id", "name"),
}


class FakeAPIError(Exception):
    """Mirrors postgrest's APIError: carries a .code attribute."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


class FakeDB:
    def __init__(self):
        self.tables = {
            "students": [],
            "career_profiles": [],
            "certifications": [],
            "work_experience": [],
            "projects": [],
        }

    def add_student(self, student_id):
        self.tables["students"].append({"id": student_id, "name": "Student"})

    def rows_for(self, table, student_id):
        return [r for r in self.tables[table] if r.get("student_id") == student_id]

    def by_id(self, table, row_id):
        return next((r for r in self.tables[table] if r["id"] == row_id), None)


class FakeQuery:
    def __init__(self, db, table, student_id):
        self.db = db
        self.table_name = table
        self.student_id = student_id
        self.op = None
        self.payload = None
        self.filters = []

    def select(self, *a, **k):
        self.op = "select"
        return self

    def update(self, json, **k):
        self.op = "update"
        self.payload = json
        return self

    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def is_(self, column, value):
        self.filters.append(("is", column, value))
        return self

    def _matches(self, row):
        for kind, column, value in self.filters:
            if kind == "eq" and row.get(column) != value:
                return False
            if kind == "is":
                wanted = None if value in (None, "null") else value
                if row.get(column) is not wanted:
                    return False
        return True

    def _visible(self):
        """RLS: this session sees only its own student's rows."""
        rows = self.db.tables[self.table_name]
        if self.table_name == "students":
            return [r for r in rows if r["id"] == self.student_id]
        return [r for r in rows if r.get("student_id") == self.student_id]

    def execute(self):
        if self.op == "select":
            return _Result([dict(r) for r in self._visible() if self._matches(r)])

        if self.op == "update":
            targets = [r for r in self._visible() if self._matches(r)]
            columns = NATURAL_KEYS.get(self.table_name)
            for row in targets:
                if columns:
                    # Would this edit collide with a sibling's natural key?
                    candidate = {**row, **self.payload}
                    key = tuple(candidate.get(c) for c in columns)
                    for other in self.db.tables[self.table_name]:
                        if other["id"] == row["id"]:
                            continue
                        if tuple(other.get(c) for c in columns) == key:
                            raise FakeAPIError(
                                "23505",
                                f'duplicate key value violates unique constraint '
                                f'"{self.table_name}_key"',
                            )
                row.update(self.payload)
            return _Result([dict(r) for r in targets])

        raise AssertionError(f"unsupported op {self.op}")


class _Result:
    def __init__(self, data):
        self.data = data


class _Postgrest:
    def __init__(self):
        self.tokens = []

    def auth(self, token):
        self.tokens.append(token)


class FakeSupabase:
    def __init__(self, db, student_id):
        self.db = db
        self.student_id = student_id
        self.postgrest = _Postgrest()

    def table(self, name):
        return FakeQuery(self.db, name, self.student_id)


def make_test_config(**overrides):
    values = {
        "proxy_secret": TEST_PROXY_SECRET,
        "allowed_origins": ("https://frontend.example",),
        "rate_limit_requests": 100,
        "rate_limit_window_seconds": 60.0,
        "max_concurrent_ai_requests": 2,
    }
    values.update(overrides)
    return api.APIConfig(**values)


@pytest.fixture
def client():
    return TestClient(api.create_app(make_test_config()), headers=PROXY_HEADERS)


@pytest.fixture
def db():
    store = FakeDB()
    store.add_student(STUDENT_A)
    store.add_student(STUDENT_B)
    return store


def patch_session(monkeypatch, db, student_id=STUDENT_A):
    monkeypatch.setattr(api, "build_client_for_token", lambda token: FakeSupabase(db, student_id))


def seed(db, student_id, prefix, *, confirmed=False, with_profile=True):
    """One unconfirmed (or confirmed) row in each table."""
    stamp = "2026-01-01T00:00:00+00:00" if confirmed else None
    cp_id = f"cp-{prefix}"
    if with_profile:
        db.tables["career_profiles"].append({
            "id": cp_id, "student_id": student_id, "source": "resume_parse",
            "confirmed_at": stamp, "updated_at": "2026-01-01T00:00:00+00:00",
            "target_roles": ["SWE"], "interests": ["backend"], "career_goals": None,
            "geographic_preference": None, "ai_anxiety_level": None,
            "skills_technical": ["Python"], "skills_soft": [], "ai_exposure": None,
        })
    db.tables["certifications"].append({
        "id": f"cert-{prefix}", "student_id": student_id, "career_profile_id": cp_id,
        "source": "resume_parse", "confirmed_at": stamp,
        "updated_at": "2026-01-01T00:00:00+00:00", "created_at": "2026-01-01T00:00:00+00:00",
        "name": f"Cert {prefix}", "issuer": "Amazon", "status": "completed", "date": "2024",
    })
    db.tables["work_experience"].append({
        "id": f"work-{prefix}", "student_id": student_id, "career_profile_id": cp_id,
        "source": "resume_parse", "confirmed_at": stamp,
        "updated_at": "2026-01-01T00:00:00+00:00",
        "employer": f"Emp {prefix}", "role": None, "duration": None, "location": None,
        "description": None, "skills_gained": [],
    })
    db.tables["projects"].append({
        "id": f"proj-{prefix}", "student_id": student_id, "career_profile_id": cp_id,
        "source": "resume_parse", "confirmed_at": stamp,
        "updated_at": "2026-01-01T00:00:00+00:00",
        "name": f"Proj {prefix}", "timeframe": None, "description": None, "tools": [],
    })


# ── 1. GET returns the caller's unconfirmed rows, scoped to them alone ──────


def test_get_returns_unconfirmed_rows_for_the_caller_only(client, db, monkeypatch):
    seed(db, STUDENT_A, "a")
    seed(db, STUDENT_B, "b")
    patch_session(monkeypatch, db, STUDENT_A)

    response = client.get(REVIEW, headers=HEADERS)

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"career_profile", "certifications", "work_experience", "projects"}

    assert body["career_profile"]["id"] == "cp-a"
    assert [r["id"] for r in body["certifications"]] == ["cert-a"]
    assert [r["id"] for r in body["work_experience"]] == ["work-a"]
    assert [r["id"] for r in body["projects"]] == ["proj-a"]

    # Nothing belonging to student B appears anywhere in the payload.
    assert "-b" not in response.text
    assert STUDENT_B not in response.text


def test_get_omits_system_managed_columns(client, db, monkeypatch):
    seed(db, STUDENT_A, "a")
    patch_session(monkeypatch, db)

    body = client.get(REVIEW, headers=HEADERS).json()

    cert = body["certifications"][0]
    assert set(cert) == {"id", "name", "issuer", "status", "date", "source"}
    profile = body["career_profile"]
    assert set(profile) == {
        "id", "target_roles", "interests", "career_goals", "geographic_preference",
        "ai_anxiety_level", "skills_technical", "skills_soft", "ai_exposure", "source",
    }
    for key in ("student_id", "career_profile_id", "created_at", "updated_at", "confirmed_at"):
        assert key not in cert
        assert key not in profile
    assert set(body["work_experience"][0]) == {
        "id", "employer", "role", "duration", "location", "description",
        "skills_gained", "source",
    }
    assert set(body["projects"][0]) == {
        "id", "name", "timeframe", "description", "tools", "source",
    }


def test_get_excludes_already_confirmed_rows(client, db, monkeypatch):
    seed(db, STUDENT_A, "conf", confirmed=True)
    patch_session(monkeypatch, db)

    body = client.get(REVIEW, headers=HEADERS).json()

    assert body == {
        "career_profile": None, "certifications": [], "work_experience": [], "projects": []
    }


# ── 2. career_profile null but children still returned ──────────────────────


def test_career_profile_null_while_children_remain(client, db, monkeypatch):
    """The returning-student case: profile confirmed, a later upload added rows."""
    seed(db, STUDENT_A, "old", confirmed=True)
    # A second upload's children, unconfirmed, attached to the confirmed profile.
    db.tables["certifications"].append({
        "id": "cert-new", "student_id": STUDENT_A, "career_profile_id": "cp-old",
        "source": "resume_parse", "confirmed_at": None, "updated_at": "x",
        "name": "New Cert", "issuer": None, "status": None, "date": None,
    })
    patch_session(monkeypatch, db)

    body = client.get(REVIEW, headers=HEADERS).json()

    assert body["career_profile"] is None
    assert [r["id"] for r in body["certifications"]] == ["cert-new"]
    assert body["work_experience"] == []
    assert body["projects"] == []


def test_get_returns_empty_shape_when_nothing_pending(client, db, monkeypatch):
    patch_session(monkeypatch, db)

    body = client.get(REVIEW, headers=HEADERS).json()

    assert body == {
        "career_profile": None, "certifications": [], "work_experience": [], "projects": []
    }


# ── 3. PATCH succeeds on an unconfirmed row ─────────────────────────────────


@pytest.mark.parametrize(
    ("segment", "row_id", "field", "value"),
    [
        ("certifications", "cert-a", "issuer", "Amazon Web Services"),
        ("work_experience", "work-a", "role", "Software Intern"),
        ("projects", "proj-a", "description", "A scheduling app"),
        ("career_profile", "cp-a", "career_goals", "Ship reliable systems"),
    ],
)
def test_patch_updates_an_unconfirmed_row(segment, row_id, field, value, client, db, monkeypatch):
    seed(db, STUDENT_A, "a")
    patch_session(monkeypatch, db)
    table = api.TABLE_BY_SEGMENT[segment]
    before = dict(db.by_id(table, row_id))

    response = client.patch(f"{REVIEW}/{segment}/{row_id}", headers=HEADERS, json={field: value})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == row_id
    assert body[field] == value
    # Response carries the projected shape, not raw columns.
    assert "student_id" not in body and "confirmed_at" not in body

    stored = db.by_id(table, row_id)
    assert stored[field] == value
    assert stored["updated_at"] != before["updated_at"], "updated_at must be maintained"
    assert stored["confirmed_at"] is None


def test_patch_only_changes_the_supplied_field(client, db, monkeypatch):
    seed(db, STUDENT_A, "a")
    patch_session(monkeypatch, db)

    client.patch(f"{REVIEW}/certifications/cert-a", headers=HEADERS, json={"issuer": "New"})

    stored = db.by_id("certifications", "cert-a")
    assert stored["issuer"] == "New"
    assert stored["name"] == "Cert a"
    assert stored["status"] == "completed"
    assert stored["date"] == "2024"


# ── 4. PATCH on an already-confirmed row -> 409, unchanged ──────────────────


def test_patch_on_a_confirmed_row_is_409_and_changes_nothing(client, db, monkeypatch):
    seed(db, STUDENT_A, "c", confirmed=True)
    patch_session(monkeypatch, db)

    response = client.patch(
        f"{REVIEW}/certifications/cert-c", headers=HEADERS, json={"issuer": "Should Not Apply"}
    )

    assert response.status_code == 409
    assert "confirmed" in response.json()["detail"].lower()

    stored = db.by_id("certifications", "cert-c")
    assert stored["issuer"] == "Amazon"
    assert stored["updated_at"] == "2026-01-01T00:00:00+00:00"
    assert stored["confirmed_at"] == "2026-01-01T00:00:00+00:00"


# ── 5 & 6. not found, and another student's row ─────────────────────────────


def test_patch_on_a_nonexistent_id_is_404(client, db, monkeypatch):
    seed(db, STUDENT_A, "a")
    patch_session(monkeypatch, db)

    response = client.patch(
        f"{REVIEW}/certifications/does-not-exist", headers=HEADERS, json={"issuer": "X"}
    )

    assert response.status_code == 404


def test_patch_on_another_students_row_is_404_and_leaks_nothing(client, db, monkeypatch):
    """Two real sessions over one database. B's row must be untouched."""
    seed(db, STUDENT_A, "a")
    seed(db, STUDENT_B, "b")
    patch_session(monkeypatch, db, STUDENT_A)

    response = client.patch(
        f"{REVIEW}/certifications/cert-b", headers=HEADERS, json={"issuer": "CROSS_STUDENT"}
    )

    assert response.status_code == 404, "must not be 403 -- that would confirm the row exists"
    assert response.status_code != 403
    detail = response.json()["detail"]
    # The message must not disclose existence, ownership, or confirmation state.
    for leak in ("confirmed", "another", "student", "permission", "forbidden", STUDENT_B):
        assert leak.lower() not in detail.lower(), f"detail leaks {leak!r}: {detail!r}"

    assert db.by_id("certifications", "cert-b")["issuer"] == "Amazon"

    # And the identical request from B's own session succeeds -- proving the
    # 404 above was authorization, not a broken id.
    patch_session(monkeypatch, db, STUDENT_B)
    ok = client.patch(
        f"{REVIEW}/certifications/cert-b", headers=HEADERS, json={"issuer": "Owner Edit"}
    )
    assert ok.status_code == 200
    assert db.by_id("certifications", "cert-b")["issuer"] == "Owner Edit"


# ── 7. system-managed fields are stripped ───────────────────────────────────


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("confirmed_at", "2026-06-01T00:00:00+00:00"),
        ("source", "manual"),
        ("student_id", STUDENT_B),
        ("career_profile_id", "cp-b"),
        ("id", "hijacked"),
        ("created_at", "2020-01-01T00:00:00+00:00"),
    ],
)
def test_patch_silently_strips_system_managed_fields(field, value, client, db, monkeypatch):
    seed(db, STUDENT_A, "a")
    patch_session(monkeypatch, db)
    before = dict(db.by_id("certifications", "cert-a"))

    response = client.patch(
        f"{REVIEW}/certifications/cert-a",
        headers=HEADERS,
        json={"issuer": "Legitimate Edit", field: value},
    )

    assert response.status_code == 200, response.text
    stored = db.by_id("certifications", "cert-a")
    # The legitimate field applied...
    assert stored["issuer"] == "Legitimate Edit"
    # ...and the system-managed one did not.
    assert stored[field] == before[field], f"{field} was writable through PATCH"
    assert stored["confirmed_at"] is None


def test_patch_with_only_system_managed_fields_is_422(client, db, monkeypatch):
    seed(db, STUDENT_A, "a")
    patch_session(monkeypatch, db)

    response = client.patch(
        f"{REVIEW}/certifications/cert-a", headers=HEADERS, json={"confirmed_at": "2026-06-01"}
    )

    assert response.status_code == 422
    assert "editable" in response.json()["detail"].lower()
    assert db.by_id("certifications", "cert-a")["confirmed_at"] is None


def test_patch_ignores_fields_belonging_to_a_different_table(client, db, monkeypatch):
    seed(db, STUDENT_A, "a")
    patch_session(monkeypatch, db)

    response = client.patch(
        f"{REVIEW}/certifications/cert-a",
        headers=HEADERS,
        json={"issuer": "Ok", "employer": "Wrong Table", "tools": ["nope"]},
    )

    assert response.status_code == 200
    stored = db.by_id("certifications", "cert-a")
    assert stored["issuer"] == "Ok"
    assert "employer" not in stored
    assert "tools" not in stored


# ── 8. natural-key collision -> 409, not 500 ────────────────────────────────


def test_renaming_onto_an_existing_natural_key_is_409(client, db, monkeypatch):
    seed(db, STUDENT_A, "a")
    db.tables["certifications"].append({
        "id": "cert-second", "student_id": STUDENT_A, "career_profile_id": "cp-a",
        "source": "resume_parse", "confirmed_at": None, "updated_at": "x",
        "name": "Other Cert", "issuer": None, "status": None, "date": None,
    })
    patch_session(monkeypatch, db)

    response = client.patch(
        f"{REVIEW}/certifications/cert-second", headers=HEADERS, json={"name": "Cert a"}
    )

    assert response.status_code == 409
    assert response.status_code != 500
    assert "name" in response.json()["detail"]
    assert db.by_id("certifications", "cert-second")["name"] == "Other Cert"


def test_work_experience_collision_names_both_key_columns(client, db, monkeypatch):
    seed(db, STUDENT_A, "a")
    db.tables["work_experience"].append({
        "id": "work-second", "student_id": STUDENT_A, "career_profile_id": "cp-a",
        "source": "resume_parse", "confirmed_at": None, "updated_at": "x",
        "employer": "Other Emp", "role": None, "duration": None, "location": None,
        "description": None, "skills_gained": [],
    })
    patch_session(monkeypatch, db)

    response = client.patch(
        f"{REVIEW}/work_experience/work-second", headers=HEADERS, json={"employer": "Emp a"}
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "employer" in detail and "role" in detail


# ── 9. certifications.status validation -> 422 ──────────────────────────────


@pytest.mark.parametrize("bad", ["expired", "COMPLETE", "", "pending", 7, True, ["completed"]])
def test_invalid_certification_status_is_422(bad, client, db, monkeypatch):
    seed(db, STUDENT_A, "a")
    patch_session(monkeypatch, db)

    response = client.patch(
        f"{REVIEW}/certifications/cert-a", headers=HEADERS, json={"status": bad}
    )

    assert response.status_code == 422, f"{bad!r} should be rejected before Postgres sees it"
    assert response.status_code != 500
    assert db.by_id("certifications", "cert-a")["status"] == "completed"


@pytest.mark.parametrize("good", ["completed", "in_progress", "Completed", "IN_PROGRESS", None])
def test_valid_certification_status_is_accepted_and_normalized(good, client, db, monkeypatch):
    seed(db, STUDENT_A, "a")
    patch_session(monkeypatch, db)

    response = client.patch(
        f"{REVIEW}/certifications/cert-a", headers=HEADERS, json={"status": good}
    )

    assert response.status_code == 200, response.text
    stored = db.by_id("certifications", "cert-a")["status"]
    assert stored == (good.lower() if isinstance(good, str) else None)


def test_status_is_not_validated_on_other_tables(client, db, monkeypatch):
    """Only certifications carries the CHECK; projects has no status column."""
    seed(db, STUDENT_A, "a")
    patch_session(monkeypatch, db)

    response = client.patch(
        f"{REVIEW}/projects/proj-a", headers=HEADERS, json={"name": "Renamed", "status": "expired"}
    )

    assert response.status_code == 200
    assert db.by_id("projects", "proj-a")["name"] == "Renamed"
    assert "status" not in db.by_id("projects", "proj-a")


# ── 10. unknown table segment -> 404 ────────────────────────────────────────


@pytest.mark.parametrize(
    "segment",
    ["students", "career_profiles", "institutions", "course_records", "__proto__", "CERTIFICATIONS"],
)
def test_unknown_table_segment_is_404(segment, client, db, monkeypatch):
    seed(db, STUDENT_A, "a")
    patch_session(monkeypatch, db)

    response = client.patch(f"{REVIEW}/{segment}/cert-a", headers=HEADERS, json={"issuer": "X"})

    assert response.status_code == 404
    assert db.by_id("certifications", "cert-a")["issuer"] == "Amazon"


def test_table_segment_mapping_is_a_closed_allowlist():
    assert set(api.TABLE_BY_SEGMENT) == {
        "career_profile", "certifications", "work_experience", "projects"
    }
    # 'career_profiles' (the real table name) is NOT a valid segment; the
    # singular form is, and maps onto it.
    assert api.TABLE_BY_SEGMENT["career_profile"] == "career_profiles"
    assert "career_profiles" not in api.TABLE_BY_SEGMENT


# ── shared route wiring ─────────────────────────────────────────────────────


def test_both_routes_declare_the_proxy_dependency():
    paths = {REVIEW, f"{REVIEW}/{{table}}/{{row_id}}"}
    found = {r.path: r for r in api.router.routes if getattr(r, "path", None) in paths}
    assert set(found) == paths, f"missing route(s): {paths - set(found)}"
    for path, route in found.items():
        names = [getattr(d.dependency, "__name__", "") for d in route.dependencies]
        assert "authorize_proxy_request" in names, path
    assert "GET" in found[REVIEW].methods
    assert "PATCH" in found[f"{REVIEW}/{{table}}/{{row_id}}"].methods


@pytest.mark.parametrize("method", ["get", "patch"])
def test_rate_limit_applies_to_both_routes(method, db, monkeypatch):
    limited = TestClient(
        api.create_app(make_test_config(rate_limit_requests=1)), headers=PROXY_HEADERS
    )
    seed(db, STUDENT_A, "a")
    patch_session(monkeypatch, db)

    def call():
        if method == "get":
            return limited.get(REVIEW, headers=HEADERS)
        return limited.patch(
            f"{REVIEW}/certifications/cert-a", headers=HEADERS, json={"issuer": "X"}
        )

    assert call().status_code != 429
    second = call()
    assert second.status_code == 429
    assert second.json()["detail"] == "Request rate limit exceeded."


@pytest.mark.parametrize("method", ["get", "patch"])
def test_proxy_secret_is_required(method, db, monkeypatch):
    unauth = TestClient(api.create_app(make_test_config()))
    patch_session(monkeypatch, db)

    if method == "get":
        response = unauth.get(REVIEW, headers=AUTH)
    else:
        response = unauth.patch(
            f"{REVIEW}/certifications/cert-a", headers=AUTH, json={"issuer": "X"}
        )

    assert response.status_code == 401


@pytest.mark.parametrize("method", ["get", "patch"])
def test_no_authorization_header_is_401(method, client, monkeypatch):
    monkeypatch.setattr(
        api, "build_client_for_token", lambda t: pytest.fail("must not build a client")
    )
    if method == "get":
        response = client.get(REVIEW, headers=PROXY_HEADERS)
    else:
        response = client.patch(
            f"{REVIEW}/certifications/cert-a", headers=PROXY_HEADERS, json={"issuer": "X"}
        )
    assert response.status_code == 401


@pytest.mark.parametrize("method", ["get", "patch"])
def test_no_visible_student_row_is_404(method, client, monkeypatch):
    empty = FakeDB()
    monkeypatch.setattr(api, "build_client_for_token", lambda t: FakeSupabase(empty, STUDENT_A))

    if method == "get":
        response = client.get(REVIEW, headers=HEADERS)
    else:
        response = client.patch(
            f"{REVIEW}/certifications/cert-a", headers=HEADERS, json={"issuer": "X"}
        )
    assert response.status_code == 404


@pytest.mark.parametrize("method", ["get", "patch"])
def test_supabase_config_error_is_503(method, client, monkeypatch):
    from CampusIQ_career.supabase_client import SupabaseConfigError

    monkeypatch.setattr(
        api,
        "build_client_for_token",
        lambda t: (_ for _ in ()).throw(SupabaseConfigError("SUPABASE_URL is not set.")),
    )
    if method == "get":
        response = client.get(REVIEW, headers=HEADERS)
    else:
        response = client.patch(
            f"{REVIEW}/certifications/cert-a", headers=HEADERS, json={"issuer": "X"}
        )
    assert response.status_code == 503


# ── 12. SUPABASE_SECRET_KEY is never read ───────────────────────────────────


@pytest.mark.parametrize("method", ["get", "patch"])
def test_supabase_secret_key_is_never_read(method, db, monkeypatch):
    """Non-vacuous: build_client_for_token runs for real under the spy.

    Only the supabase SDK's create_client is replaced, so the builder's own
    _required_env calls execute and are visible to the spy -- the same shape as
    tests/test_api.py:809. Stubbing build_client_for_token itself, as the
    lighter tests above do, would make this assertion vacuous.
    """
    import os

    from CampusIQ_career import supabase_client as supabase_client_module

    seed(db, STUDENT_A, "a")

    reads: list[str] = []
    original_get = os.environ.get

    def spying_get(key, *args, **kwargs):
        reads.append(key)
        if key == "SUPABASE_SECRET_KEY":
            raise AssertionError("SUPABASE_SECRET_KEY must never be read by these routes")
        return original_get(key, *args, **kwargs)

    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-publishable-key")
    monkeypatch.setattr(
        supabase_client_module, "create_client", lambda url, key: FakeSupabase(db, STUDENT_A)
    )
    monkeypatch.setattr(os.environ, "get", spying_get)

    live = TestClient(api.create_app(make_test_config()), headers=PROXY_HEADERS)
    if method == "get":
        response = live.get(REVIEW, headers=HEADERS)
    else:
        response = live.patch(
            f"{REVIEW}/certifications/cert-a", headers=HEADERS, json={"issuer": "X"}
        )

    assert response.status_code == 200, response.text
    assert "SUPABASE_URL" in reads
    assert "SUPABASE_PUBLISHABLE_KEY" in reads
    assert "SUPABASE_SECRET_KEY" not in reads


@pytest.mark.parametrize("method", ["get", "patch"])
def test_caller_token_reaches_postgrest(method, db, monkeypatch):
    from CampusIQ_career import supabase_client as supabase_client_module

    seed(db, STUDENT_A, "a")
    built = []

    def fake_create_client(url, key):
        instance = FakeSupabase(db, STUDENT_A)
        built.append(instance)
        return instance

    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-publishable-key")
    monkeypatch.setattr(supabase_client_module, "create_client", fake_create_client)

    live = TestClient(api.create_app(make_test_config()), headers=PROXY_HEADERS)
    if method == "get":
        live.get(REVIEW, headers=HEADERS)
    else:
        live.patch(f"{REVIEW}/certifications/cert-a", headers=HEADERS, json={"issuer": "X"})

    assert built and built[0].postgrest.tokens == ["real-session-jwt"]
