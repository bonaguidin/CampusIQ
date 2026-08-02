"""Tests for the session-scoped /api/v2/student/me/* routes.

These serve real, Postgres-backed students. Identity comes from the bearer
token via RLS -- there is no slug in the path -- so they cover the half of the
space the slug-addressed routes structurally cannot reach.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from CampusIQ_career import api
from CampusIQ_career.ai.types import AIResponse
from CampusIQ_career.supabase_client import SupabaseConfigError


TEST_PROXY_SECRET = "test-proxy-secret"
PROXY_HEADERS = {api.PROXY_SECRET_HEADER: TEST_PROXY_SECRET}
AUTH = {"Authorization": "Bearer real-session-jwt"}
STUDENT_UUID = "8f14e45f-ceea-467a-9f0e-1c2d3e4f5a6b"

ME_ROUTES = [
    ("post", "/api/v2/student/me/analyze/gap", None),
    ("post", "/api/v2/student/me/chat", {"message": "hi", "history": []}),
    ("get", "/api/v2/student/me/profile", None),
]
ME_IDS = ["analyze", "chat", "profile"]


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


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "CACHED_ANALYSIS_DIR", tmp_path)
    return tmp_path


FEATURE_JSON = json.dumps(
    {
        "summary": "LIVE-RESULT",
        "data": {
            "readiness_score": 6,
            "strengths": [],
            "must_have_gaps": [],
            "nice_to_have_gaps": [],
            "recommended_next_steps": [],
            "role_matches": [],
            "overall_fit_summary": "ok",
            "role_evolution_summary": "ok",
            "task_shifts": [],
            "durable_skills": [],
            "adjacent_paths": [],
            "ai_fluency_guidance": [],
            "themes": [],
            "overall_summary": "ok",
        },
    }
)


class FakeAI:
    def __init__(self, text=FEATURE_JSON):
        self.text = text
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return AIResponse(text=self.text, raw={"choices": []}, model="fake-model")


def _full_profile():
    return {
        "student": {
            "id": STUDENT_UUID,
            "name": "Real Student",
            "classification": "Junior",
            "major_current": "Computer Science",
            "major_intended": "Computer Science",
            "expected_graduation": "2028-05",
            "onboarding_stage": 3,
            "institution": "Texas A&M University",
            "gpa_current": None,
        },
        "career": {
            "target_roles": ["SWE Intern"],
            "interests": ["backend"],
            "career_goals": "Ship things.",
            "geographic_preference": "DFW",
            "ai_anxiety_level": "low",
            "skills_self_reported": {
                "technical": ["Python"],
                "soft": ["communication"],
                "ai_exposure": "some",
            },
            "certifications": [],
            "work_experience": [{"employer": "Acme", "role": "Intern"}],
            "projects": [],
        },
    }


def _patch_session(monkeypatch, profile=None, student_rows=None):
    """Stub the session client + builder, leaving route logic real."""
    rows = [{"id": STUDENT_UUID}] if student_rows is None else student_rows

    class _Client:
        def table(self, name):
            return self

        def select(self, *a, **k):
            return self

        def eq(self, *a, **k):
            return self

        def execute(self):
            class _R:
                data = rows

            return _R()

    monkeypatch.setattr(api, "build_client_for_token", lambda token: _Client())
    if profile is not None:
        monkeypatch.setattr(
            api,
            "build_profile_from_supabase",
            lambda client, sid: type("R", (), {"profile": profile})(),
        )
    return rows


def _call(client, method, path, body):
    kwargs = {"headers": {**PROXY_HEADERS, **AUTH}}
    if body is not None:
        kwargs["json"] = body
    return getattr(client, method)(path, **kwargs)


# 1. No Authorization header -> 401.
@pytest.mark.parametrize(("method", "path", "body"), ME_ROUTES, ids=ME_IDS)
def test_no_authorization_is_401(method, path, body, client, monkeypatch):
    monkeypatch.setattr(
        api, "build_client_for_token", lambda t: pytest.fail("must not build a client")
    )
    kwargs = {"json": body} if body is not None else {}
    response = getattr(client, method)(path, **kwargs)

    assert response.status_code == 401


# 2. Malformed Authorization -> 401.
@pytest.mark.parametrize("header_value", ["", "Token abc", "Bearer", "Bearer   ", "abc"])
@pytest.mark.parametrize(("method", "path", "body"), ME_ROUTES, ids=ME_IDS)
def test_malformed_authorization_is_401(method, path, body, header_value, client, monkeypatch):
    monkeypatch.setattr(
        api, "build_client_for_token", lambda t: pytest.fail("must not build a client")
    )
    kwargs = {"headers": {**PROXY_HEADERS, "Authorization": header_value}}
    if body is not None:
        kwargs["json"] = body
    response = getattr(client, method)(path, **kwargs)

    assert response.status_code == 401


# 3. Valid token but no visible students row -> 404.
@pytest.mark.parametrize(("method", "path", "body"), ME_ROUTES, ids=ME_IDS)
def test_no_visible_student_row_is_404(method, path, body, client, monkeypatch):
    _patch_session(monkeypatch, student_rows=[])

    response = _call(client, method, path, body)

    assert response.status_code == 404
    assert "No student profile visible" in response.json()["detail"]


# 4. Valid token, full profile -> 200 with the right shape.
def test_me_profile_returns_the_profile(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())

    response = _call(client, "get", "/api/v2/student/me/profile", None)

    assert response.status_code == 200
    body = response.json()
    assert body["student"]["id"] == STUDENT_UUID
    assert body["student"]["institution"] == "Texas A&M University"
    assert body["career"]["target_roles"] == ["SWE Intern"]


@pytest.mark.parametrize("feature", ["gap", "fit", "shift", "professor-comments"])
def test_me_analyze_returns_a_feature_result(feature, client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    monkeypatch.setattr(api, "build_client", lambda: FakeAI())

    response = _call(client, "post", f"/api/v2/student/me/analyze/{feature}", None)

    assert response.status_code == 200
    body = response.json()
    expected = {
        "gap": "GAP",
        "fit": "FIT",
        "shift": "SHIFT",
        "professor-comments": "PROFESSOR_COMMENTS",
    }[feature]
    assert body["feature"] == expected
    assert set(body) == {"feature", "status", "summary", "data", "errors"}


def test_me_chat_returns_a_reply(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    fake = FakeAI("Here is your advice.")
    monkeypatch.setattr(api, "build_client", lambda: fake)

    response = _call(
        client, "post", "/api/v2/student/me/chat", {"message": "How ready am I?", "history": []}
    )

    assert response.status_code == 200
    assert response.json()["reply"] == "Here is your advice."
    assert fake.calls[0]["role"] == "chat"
    assert "Real Student" in fake.calls[0]["messages"][0]["content"]


def test_me_chat_requires_a_message(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    monkeypatch.setattr(api, "build_client", lambda: pytest.fail("must not reach the AI client"))

    response = _call(client, "post", "/api/v2/student/me/chat", {"message": "  ", "history": []})

    assert response.status_code == 400


# 5. Unrecognized feature -> 404, not 500.
#
# Values are deliberately single-segment and URL-safe. A value containing "/"
# (e.g. "gap/../fit") cannot reach {feature} as one path segment anyway, and
# sending one makes TestClient follow a redirect chain that never terminates --
# a client artifact, not a route behavior. Traversal is therefore not
# expressible here; the mapping is a dict lookup with four exact keys.
#
# "GAP" and "professor_comments" are the near-misses that matter: the first is
# the internal name leaking into a URL, the second is what
# normalize_feature_name would have accepted. Both must 404.
@pytest.mark.parametrize("bad", ["nope", "GAP", "professor_comments", "Gap", "chat", "profile"])
def test_unknown_feature_is_404_not_500(bad, client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())

    response = _call(client, "post", f"/api/v2/student/me/analyze/{bad}", None)

    assert response.status_code == 404
    assert response.status_code != 500


# 6. A demo cache file for a DIFFERENT numeric-id student must not leak.
def test_uuid_profile_does_not_read_another_students_cache(client, monkeypatch, isolated_cache):
    (isolated_cache / "analysis_jordanReyes.json").write_text(
        json.dumps(
            {
                "student_id": 601,
                "results": {
                    "GAP": {
                        "feature": "GAP",
                        "status": "success",
                        "summary": "CACHED-601-MUST-NOT-APPEAR",
                        "errors": [],
                        "data": {
                            "readiness_score": 9,
                            "strengths": [],
                            "must_have_gaps": [],
                            "nice_to_have_gaps": [],
                            "recommended_next_steps": [],
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    _patch_session(monkeypatch, profile=_full_profile())
    fake = FakeAI()
    monkeypatch.setattr(api, "build_client", lambda: fake)

    response = _call(client, "post", "/api/v2/student/me/analyze/gap", None)

    assert response.status_code == 200
    assert "CACHED-601" not in response.text
    assert response.json()["summary"] == "LIVE-RESULT"
    assert len(fake.calls) == 1  # live call was made


# 7. /me/chat must never consult the demo analysis bundles.
def test_me_chat_never_calls_load_analysis_bundle(client, monkeypatch):
    _patch_session(monkeypatch, profile=_full_profile())
    monkeypatch.setattr(
        api,
        "load_analysis_bundle",
        lambda slug: pytest.fail("me/chat must not read demo analysis bundles"),
    )
    monkeypatch.setattr(api, "build_client", lambda: FakeAI("ok"))

    response = _call(client, "post", "/api/v2/student/me/chat", {"message": "hi", "history": []})

    assert response.status_code == 200
    # The prompt carries an empty prior-analysis section, not another
    # student's bundle.
    assert response.json()["reply"] == "ok"


# 8. SupabaseConfigError -> 503 on all three.
@pytest.mark.parametrize(("method", "path", "body"), ME_ROUTES, ids=ME_IDS)
def test_supabase_config_error_is_503(method, path, body, client, monkeypatch):
    monkeypatch.setattr(
        api,
        "build_client_for_token",
        lambda t: (_ for _ in ()).throw(SupabaseConfigError("SUPABASE_URL is not set.")),
    )

    response = _call(client, method, path, body)

    assert response.status_code == 503
    assert response.status_code != 500
    assert "SUPABASE_URL" in response.json()["detail"]


# Proxy secret still required (these routes carry authorize_proxy_request).
@pytest.mark.parametrize(("method", "path", "body"), ME_ROUTES, ids=ME_IDS)
def test_me_routes_still_require_the_proxy_secret(method, path, body, monkeypatch):
    unauth = TestClient(api.create_app(make_test_config()))
    kwargs = {"headers": AUTH}
    if body is not None:
        kwargs["json"] = body

    response = getattr(unauth, method)(path, **kwargs)

    assert response.status_code == 401


# 10. Plant a cache file at the EXACT path a UUID slug would produce, then
#     assert it is never opened -- pinning the isalnum() rejection mechanism
#     itself, not merely its outcome.
def test_uuid_named_cache_file_is_never_read(client, monkeypatch, isolated_cache):
    planted = isolated_cache / f"analysis_{STUDENT_UUID}.json"
    planted.write_text(
        json.dumps(
            {
                "student_id": STUDENT_UUID,
                "results": {
                    "GAP": {
                        "feature": "GAP",
                        "status": "success",
                        "summary": "PLANTED-UUID-CACHE-MUST-NOT-APPEAR",
                        "errors": [],
                        "data": {
                            "readiness_score": 1,
                            "strengths": [],
                            "must_have_gaps": [],
                            "nice_to_have_gaps": [],
                            "recommended_next_steps": [],
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    assert planted.exists(), "the file must really be on disk for this test to mean anything"

    # Spy on the read itself, not just the returned value.
    reads: list[str] = []
    original_read_text = Path.read_text

    def spying_read_text(self, *args, **kwargs):
        reads.append(str(self))
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", spying_read_text)

    _patch_session(monkeypatch, profile=_full_profile())
    fake = FakeAI()
    monkeypatch.setattr(api, "build_client", lambda: fake)

    response = _call(client, "post", "/api/v2/student/me/analyze/gap", None)

    assert response.status_code == 200
    # The planted file was never opened -- isalnum() rejected the UUID slug
    # before any path was built.
    assert str(planted) not in reads, f"planted cache file WAS read: {reads}"
    # And its content never surfaced.
    assert "PLANTED-UUID-CACHE" not in response.text
    # A live call happened instead.
    assert len(fake.calls) == 1
    assert response.json()["summary"] == "LIVE-RESULT"


def test_uuid_slug_is_rejected_by_isalnum_directly():
    """The mechanism this route relies on, asserted in isolation."""
    assert not STUDENT_UUID.isalnum()  # hyphens
    assert len(STUDENT_UUID) <= 64  # length alone would have passed
    assert api.load_cached_feature_result(STUDENT_UUID, "GAP", STUDENT_UUID) is None
    assert api.load_analysis_bundle(STUDENT_UUID) == {}
