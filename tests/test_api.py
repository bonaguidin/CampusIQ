import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from GradusIQ_career import api
from GradusIQ_career.ai.errors import AIConfigError
from GradusIQ_career.ai.types import AIResponse


TEST_PROXY_SECRET = "test-proxy-secret"
PROXY_HEADERS = {api.PROXY_SECRET_HEADER: TEST_PROXY_SECRET}

# Captured at import, before the autouse isolated_analysis_cache fixture
# repoints api.CACHED_ANALYSIS_DIR at tmp_path for each test. Tests asserting
# on the *real* configured location must use this, not the patched attribute.
REAL_CACHED_ANALYSIS_DIR = api.CACHED_ANALYSIS_DIR


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


class FakeClient:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return AIResponse(text=self.text, raw={"choices": []}, model="fake-model")


@pytest.fixture
def client():
    return TestClient(api.create_app(make_test_config()), headers=PROXY_HEADERS)


@pytest.fixture(autouse=True)
def isolated_analysis_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "CACHED_ANALYSIS_DIR", tmp_path)


def write_gap_cache(
    cache_dir,
    *,
    slug="jordanReyes",
    student_id=601,
    result_feature="GAP",
    result_status="success",
    overall_status="success",
):
    result = {
        "feature": result_feature,
        "status": result_status,
        "summary": "Cached GAP result.",
        "data": {
            "readiness_score": 7,
            "strengths": [],
            "must_have_gaps": [],
            "nice_to_have_gaps": [],
            "recommended_next_steps": [],
        },
        "errors": [] if result_status == "success" else ["cached failure"],
    }
    path = cache_dir / f"analysis_{slug}.json"
    path.write_text(
        json.dumps(
            {
                "analysis_type": "career",
                "status": overall_status,
                "student_id": student_id,
                "features_requested": ["GAP"],
                "results": {"GAP": result},
                "summary": "Cached analysis.",
                "errors": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_public_health_route_requires_no_proxy_credential():
    test_client = TestClient(api.create_app(make_test_config()))
    response = test_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert test_client.get("/docs").status_code == 404
    assert test_client.get("/redoc").status_code == 404
    assert test_client.get("/openapi.json").status_code == 404


@pytest.mark.parametrize("headers", [{}, {api.PROXY_SECRET_HEADER: "wrong-secret"}])
def test_missing_or_incorrect_proxy_credential_is_rejected_before_client_build(headers, monkeypatch):
    built = False

    def unexpected_build():
        nonlocal built
        built = True
        raise AssertionError("paid client must not be constructed")

    monkeypatch.setattr(api, "build_client", unexpected_build)
    test_client = TestClient(api.create_app(make_test_config()))

    response = test_client.post("/api/students/jordanReyes/analyze/gap", headers=headers)

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized."}
    assert built is False


def test_unconfigured_backend_proxy_authentication_fails_closed(monkeypatch):
    monkeypatch.setattr(api, "build_client", lambda: pytest.fail("client must not be built"))
    config = make_test_config(proxy_secret="")

    response = TestClient(api.create_app(config)).post("/api/students/jordanReyes/analyze/gap")

    assert response.status_code == 503
    assert response.json() == {"detail": "Backend proxy authentication is not configured."}


def test_proxy_secret_is_not_logged_on_authentication_failure(caplog):
    secret = "do-not-log-this-secret"
    config = make_test_config(proxy_secret=secret)

    with caplog.at_level("DEBUG"):
        response = TestClient(api.create_app(config)).post(
            "/api/students/jordanReyes/analyze/gap",
            headers={api.PROXY_SECRET_HEADER: "wrong-secret"},
        )

    assert response.status_code == 401
    assert secret not in caplog.text
    assert "wrong-secret" not in caplog.text


def test_cors_allows_only_explicit_configured_origin():
    test_client = TestClient(api.create_app(make_test_config()))
    allowed = test_client.options(
        "/api/students/jordanReyes/analyze/gap",
        headers={
            "Origin": "https://frontend.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": api.PROXY_SECRET_HEADER,
        },
    )
    denied = test_client.options(
        "/api/students/jordanReyes/analyze/gap",
        headers={
            "Origin": "https://attacker.example",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert allowed.headers["access-control-allow-origin"] == "https://frontend.example"
    assert "access-control-allow-origin" not in denied.headers


def test_cors_allows_exactly_the_methods_the_app_exposes():
    """Pins allow_methods itself.

    test_cors_allows_only_explicit_configured_origin above varies the ORIGIN
    and always sends Access-Control-Request-Method: POST, so it passes
    identically whatever the method list contains. This varies the method
    instead, which is the thing that changed when PATCH was added.

    DELETE joined the allowed list when the planned-course removal route
    (DELETE /api/v2/student/me/planned-courses/{id}) was added. The assertion
    below is derived from the router rather than restated as a literal, so the
    next route carrying a new method updates it by existing -- which is what
    this test is actually for. PUT stays in the negative case: no route uses
    it, so it must stay out.
    """
    test_client = TestClient(api.create_app(make_test_config()))

    def preflight(method: str):
        return test_client.options(
            "/api/students/jordanReyes/analyze/gap",
            headers={
                "Origin": "https://frontend.example",
                "Access-Control-Request-Method": method,
            },
        )

    # Every method any route actually declares, read off the router itself.
    exposed = {
        method
        for route in api.router.routes
        for method in getattr(route, "methods", set())
        if method not in {"HEAD", "OPTIONS"}
    }
    assert {"GET", "POST", "PATCH", "DELETE"} <= exposed, (
        f"router no longer exposes the methods this test assumes: {sorted(exposed)}"
    )

    for method in sorted(exposed):
        response = preflight(method)
        allowed = response.headers.get("access-control-allow-methods", "")
        assert method in allowed, f"{method} should be allowed, got {allowed!r}"

    # Methods the app exposes no route for stay out.
    for method in ("PUT", "TRACE"):
        assert method not in exposed, f"{method} now has a route; update this test"
        response = preflight(method)
        assert method not in response.headers.get("access-control-allow-methods", "")


def test_rate_limiter_rejects_excess_and_expires_old_state(monkeypatch):
    builds = 0

    def counted_build():
        nonlocal builds
        builds += 1
        return FakeClient('{"data": {}}')

    monkeypatch.setattr(api, "build_client", counted_build)
    limited = TestClient(
        api.create_app(make_test_config(rate_limit_requests=1, rate_limit_window_seconds=10.0)),
        headers=PROXY_HEADERS,
    )

    first = limited.post("/api/students/jordanReyes/analyze/fit")
    second = limited.post("/api/students/jordanReyes/analyze/fit")

    assert first.status_code == 200
    assert second.status_code == 429
    assert builds == 1
    limiter = api.SlidingWindowRateLimiter(limit=1, window_seconds=10.0)
    assert limiter.allow(now=0.0) is True
    assert limiter.allow(now=5.0) is False
    assert limiter.allow(now=11.0) is True


def test_concurrency_limit_rejects_excess_live_work_and_releases_slot(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(api, "build_client", lambda: object())

    def blocking_run(*args, **kwargs):
        entered.set()
        release.wait(timeout=5)
        return {"feature": "FIT", "status": "success", "summary": "ok", "data": {}, "errors": []}

    monkeypatch.setattr(api, "run_feature_with_fallback", blocking_run)
    app = api.create_app(make_test_config(max_concurrent_ai_requests=1))

    def request_analysis():
        return TestClient(app, headers=PROXY_HEADERS).post("/api/students/jordanReyes/analyze/fit")

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(request_analysis)
        assert entered.wait(timeout=2)
        second = request_analysis()
        release.set()
        first = first_future.result(timeout=5)

    assert first.status_code == 200
    assert second.status_code == 429

    monkeypatch.setattr(api, "run_feature_with_fallback", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    failed = request_analysis()
    assert failed.status_code == 502
    monkeypatch.setattr(
        api,
        "run_feature_with_fallback",
        lambda *args, **kwargs: {"feature": "FIT", "status": "success", "summary": "ok", "data": {}, "errors": []},
    )
    assert request_analysis().status_code == 200


def test_analyze_gap_success(client, monkeypatch):
    fake = FakeClient(
        """
        {
          "summary": "Solid readiness with one clear gap.",
          "data": {
            "readiness_score": 7,
            "strengths": ["Excel"],
            "must_have_gaps": [{"gap":"SQL","why_it_matters":"Required.","how_to_close":"Build a project."}],
            "nice_to_have_gaps": [{"gap":"dashboarding","why_it_helps":"Useful.","how_to_close":"Build a dashboard."}],
            "recommended_next_steps": ["Build a small SQL project"]
          }
        }
        """
    )
    monkeypatch.setattr(api, "build_client", lambda: fake)

    response = client.post("/api/students/jordanReyes/analyze/gap")

    assert response.status_code == 200
    body = response.json()
    assert body["feature"] == "GAP"
    assert body["status"] == "success"
    assert body["data"]["readiness_score"] == 7
    assert fake.calls[0]["role"] == "career"


def test_analyze_fit_success(client, monkeypatch):
    fake = FakeClient(
        """
        {
          "summary": "Strong fit for data analyst, weaker for data engineer.",
          "data": {
            "role_matches": [
              {
                "role": "Data Analyst",
                "fit_level": "high",
                "rationale": "Coursework and projects align closely.",
                "supporting_signals": ["Excel", "Intro statistics"],
                "missing_signals": ["SQL"]
              }
            ],
            "overall_fit_summary": "Best aligned with analytics roles."
          }
        }
        """
    )
    monkeypatch.setattr(api, "build_client", lambda: fake)

    response = client.post("/api/students/jordanReyes/analyze/fit")

    assert response.status_code == 200
    body = response.json()
    assert body["feature"] == "FIT"
    assert body["status"] == "success"
    assert body["data"]["role_matches"][0]["role"] == "Data Analyst"
    assert body["data"]["role_matches"][0]["fit_level"] == "high"
    assert fake.calls[0]["role"] == "career"


def test_analyze_shift_success(client, monkeypatch):
    fake = FakeClient(
        """
        {
          "summary": "AI tooling fluency is increasingly expected in this role family.",
          "data": {
            "role_evolution_summary": "AI tooling fluency is increasingly expected in this role family.",
            "task_shifts": [
              {
                "task": "Manual data entry",
                "changing": "Increasingly automated by AI tools.",
                "meaning": "Less time on rote entry, more on interpretation."
              }
            ],
            "durable_skills": [
              {
                "task": "Stakeholder communication",
                "reason": "AI cannot replace judgment-driven, relationship-based work."
              }
            ],
            "adjacent_paths": [
              {
                "path": "Data Analyst",
                "relevance": "Builds on existing Excel and SQL foundation.",
                "driver": "Growing demand for analytics-literate generalists."
              }
            ],
            "ai_fluency_guidance": ["Learn to prompt and evaluate AI tool output critically."]
          }
        }
        """
    )
    monkeypatch.setattr(api, "build_client", lambda: fake)

    response = client.post("/api/students/jordanReyes/analyze/shift")

    assert response.status_code == 200
    body = response.json()
    assert body["feature"] == "SHIFT"
    assert body["status"] == "success"
    assert body["data"]["task_shifts"][0]["task"] == "Manual data entry"
    assert fake.calls[0]["role"] == "career"


def test_analyze_professor_comments_success(client, monkeypatch):
    # The cited courses must be ones sofiaRamirez actually has professor
    # comments from -- CHEM 237 and PHYS 201 are two of hers. This canned
    # response previously cited ENGR 102, copied from the Ethan Brooks
    # fixture, which is a course she is not enrolled in; the route returned
    # status="success" on that cross-student citation because nothing
    # validated it. AcademicRunner.validate_data now rejects it.
    fake = FakeClient(
        """
        {
          "summary": "Professors consistently want more documentation.",
          "data": {
            "themes": [
              {
                "theme": "Documentation habits",
                "category": "concern",
                "summary": "Multiple professors want clearer explanations.",
                "supporting_references": [
                  {
                    "course_code": "CHEM 237",
                    "course_name": "Organic Chemistry I Laboratory",
                    "paraphrase": "Asked for fuller write-ups of your procedure."
                  },
                  {
                    "course_code": "PHYS 201",
                    "course_name": "College Physics I",
                    "paraphrase": "Wanted your reasoning shown, not just the answer."
                  }
                ]
              }
            ],
            "overall_summary": "Document your process more."
          }
        }
        """
    )
    monkeypatch.setattr(api, "build_client", lambda: fake)

    response = client.post("/api/students/sofiaRamirez/analyze/professor-comments")

    assert response.status_code == 200
    body = response.json()
    assert body["feature"] == "PROFESSOR_COMMENTS"
    assert body["status"] == "success"
    assert body["data"]["themes"][0]["theme"] == "Documentation habits"
    assert fake.calls[0]["role"] == "academic"


def test_analyze_gap_unknown_student_is_rejected_before_any_profile_lookup(client, monkeypatch):
    # BEHAVIOR CHANGE (authorize_student_access): an unknown slug used to reach
    # load_student_profile and come back 404. It is now rejected at 401 first,
    # because it is not a demo fixture and carries no token. That is stricter,
    # and deliberately stops leaking which slugs exist to unauthenticated
    # callers -- a 404-vs-401 split would be an existence oracle.
    monkeypatch.setattr(api, "build_client", lambda: FakeClient('{"data": {}}'))

    response = client.post("/api/students/doesNotExist/analyze/gap")

    assert response.status_code == 401
    # Still never a success, which is what the original test guarded.
    assert response.status_code != 200


def test_analyze_gap_missing_api_key_returns_503(client, monkeypatch):
    def raise_config_error(*args, **kwargs):
        raise AIConfigError("OPENROUTER_API_KEY is required for OpenRouter AI calls.")

    # Exercise the real build_client() (not a monkeypatched replacement) so the
    # AIConfigError -> HTTPException(503) translation inside it is what's tested.
    monkeypatch.setattr(api, "OpenRouterClient", raise_config_error)

    response = client.post("/api/students/jordanReyes/analyze/gap")

    assert response.status_code == 503


def test_cached_success_without_api_key_skips_live_client_and_concurrency(client, monkeypatch, tmp_path):
    write_gap_cache(tmp_path, overall_status="partial_success")
    monkeypatch.setattr(api, "build_client", lambda: pytest.fail("live client must not be built"))

    class RejectAllConcurrency:
        @contextmanager
        def slot(self):
            raise AssertionError("cache hit must not consume live concurrency")
            yield

    client.app.state.ai_concurrency = RejectAllConcurrency()

    response = client.post("/api/students/jordanReyes/analyze/gap")

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["summary"] == "Cached GAP result."


@pytest.mark.parametrize(
    "cache_variant",
    ["missing", "failed", "student_mismatch", "feature_mismatch", "malformed"],
)
def test_invalid_or_missing_cache_with_no_api_key_returns_503(
    cache_variant, client, monkeypatch, tmp_path
):
    if cache_variant == "failed":
        write_gap_cache(tmp_path, result_status="failed")
    elif cache_variant == "student_mismatch":
        write_gap_cache(tmp_path, student_id=999)
    elif cache_variant == "feature_mismatch":
        write_gap_cache(tmp_path, result_feature="FIT")
    elif cache_variant == "malformed":
        (tmp_path / "analysis_jordanReyes.json").write_text("{not-json", encoding="utf-8")

    def unavailable_client():
        raise api.HTTPException(status_code=503, detail="OPENROUTER_API_KEY is required.")

    monkeypatch.setattr(api, "build_client", unavailable_client)

    response = client.post("/api/students/jordanReyes/analyze/gap")

    assert response.status_code == 503


def test_unknown_student_never_receives_another_students_cache(client, monkeypatch, tmp_path):
    # A cache file exists for this slug carrying ANOTHER student's id (601).
    # The original guarantee -- that it is never served -- still holds; the
    # request is now stopped even earlier, at authorization rather than at the
    # profile lookup. See the behavior-change note above.
    write_gap_cache(tmp_path, slug="doesNotExist", student_id=601)
    monkeypatch.setattr(api, "build_client", lambda: pytest.fail("unknown student stops first"))

    response = client.post("/api/students/doesNotExist/analyze/gap")

    assert response.status_code == 401
    assert response.status_code != 200
    assert "Cached GAP result." not in response.text


def test_authentication_and_rate_limit_still_apply_to_cache_hits(monkeypatch, tmp_path):
    write_gap_cache(tmp_path)
    app = api.create_app(make_test_config(rate_limit_requests=1))
    unauthenticated = TestClient(app).post("/api/students/jordanReyes/analyze/gap")
    authenticated = TestClient(app, headers=PROXY_HEADERS)
    first = authenticated.post("/api/students/jordanReyes/analyze/gap")
    second = authenticated.post("/api/students/jordanReyes/analyze/gap")

    assert unauthenticated.status_code == 401
    assert first.status_code == 200
    assert second.status_code == 429


def test_analyze_gap_malformed_ai_json_returns_failed_status(client, monkeypatch, tmp_path):
    # Isolate from the real production cache dir (frontend/public/data) --
    # jordanReyes's real cache now has a genuine "success" GAP entry from the
    # demo regeneration work (build_demo_cache.py), which collided with this
    # test's "no fallback available" assumption: run_feature_with_fallback
    # would find that real success entry and serve it, masking the malformed-
    # JSON live failure this test exists to check. That was a test-isolation
    # bug, not a production one -- this fixture cache deliberately has no GAP
    # entry for jordanReyes, so load_cached_feature_result() misses and the
    # live failure passes through unchanged, exactly as the test name
    # describes, regardless of what the real cache holds now or later.
    (tmp_path / "analysis_jordanReyes.json").write_text(
        json.dumps({"results": {}}), encoding="utf-8"
    )
    monkeypatch.setattr(api, "CACHED_ANALYSIS_DIR", tmp_path)
    monkeypatch.setattr(api, "build_client", lambda: FakeClient("{not-json"))

    response = client.post("/api/students/jordanReyes/analyze/gap")

    assert response.status_code == 200
    body = response.json()
    assert body["feature"] == "GAP"
    assert body["status"] == "failed"


def test_run_feature_with_fallback_cache_miss_returns_live_failure(monkeypatch):
    live_failure = {
        "feature": "GAP",
        "status": "failed",
        "summary": "GAP analysis failed.",
        "data": {},
        "errors": ["OpenRouter request failed: timed out"],
    }
    monkeypatch.setattr(api, "run_feature", lambda feature, profile, client: live_failure)
    monkeypatch.setattr(api, "load_cached_feature_result", lambda *args: None)

    result = api.run_feature_with_fallback("GAP", "noCacheStudent", profile={}, client=None)

    assert result == live_failure


def test_run_feature_with_fallback_cached_success_is_served(monkeypatch):
    live_failure = {
        "feature": "GAP",
        "status": "failed",
        "summary": "GAP analysis failed.",
        "data": {},
        "errors": ["OpenRouter request failed: timed out"],
    }
    cached_success = {
        "feature": "GAP",
        "status": "success",
        "summary": "You've built a solid foundation.",
        "data": {"readiness_score": 7},
        "errors": [],
    }
    monkeypatch.setattr(api, "run_feature", lambda feature, profile, client: live_failure)
    monkeypatch.setattr(api, "load_cached_feature_result", lambda *args: cached_success)

    result = api.run_feature_with_fallback("GAP", "jordanReyes", profile={}, client=None)

    assert result == cached_success
    assert result["status"] == "success"


def test_run_feature_with_fallback_cached_failure_is_not_served_as_success(monkeypatch):
    live_failure = {
        "feature": "GAP",
        "status": "failed",
        "summary": "GAP analysis failed.",
        "data": {},
        "errors": ["OpenRouter request failed: live timeout"],
    }
    cached_failure = {
        "feature": "GAP",
        "status": "failed",
        "summary": "GAP analysis failed.",
        "data": {},
        "errors": ["OpenRouter request failed: HTTPSConnectionPool read timed out (300.0)"],
    }
    monkeypatch.setattr(api, "run_feature", lambda feature, profile, client: live_failure)
    monkeypatch.setattr(api, "load_cached_feature_result", lambda *args: cached_failure)

    result = api.run_feature_with_fallback("GAP", "ethanBrooks", profile={}, client=None)

    assert result["status"] == "failed"
    assert result["data"] == {}
    # The cached failure's own summary/errors are surfaced, not a generic message.
    assert result["summary"] == cached_failure["summary"]
    assert result["errors"] == cached_failure["errors"]


def test_run_feature_with_fallback_cached_status_missing_fails_closed(monkeypatch):
    live_failure = {
        "feature": "GAP",
        "status": "failed",
        "summary": "GAP analysis failed.",
        "data": {},
        "errors": ["OpenRouter request failed: live timeout"],
    }
    # Schema-drift case: a cached entry with no recognizable "status" at all.
    cached_malformed = {"feature": "GAP", "data": {}}
    monkeypatch.setattr(api, "run_feature", lambda feature, profile, client: live_failure)
    monkeypatch.setattr(api, "load_cached_feature_result", lambda *args: cached_malformed)

    result = api.run_feature_with_fallback("GAP", "someStudent", profile={}, client=None)

    assert result["status"] == "failed"


# ═══════════════════════════════════════════════════════════════════════════
# Cross-student authorization (authorize_student_access)
#
# These five routes previously accepted any slug from any caller. The five
# demo fixtures stay open (their records are already world-readable at
# frontend/public/data/); every other slug now requires a session and is
# denied, because `students` has no slug column to map a session onto.
# ═══════════════════════════════════════════════════════════════════════════

NON_DEMO_SLUG = "someRealStudent"

# (path suffix, json body or None) for each of the five protected routes.
PROTECTED_ROUTES = [
    ("analyze/gap", None),
    ("analyze/fit", None),
    ("analyze/shift", None),
    ("analyze/professor-comments", None),
    ("chat", {"message": "hello", "history": []}),
]
ROUTE_IDS = ["gap", "fit", "shift", "professor-comments", "chat"]

FEATURE_JSON = json.dumps(
    {
        "summary": "ok",
        "data": {
            "readiness_score": 7,
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


def _post(test_client, slug, suffix, body, headers=None):
    kwargs = {"headers": headers} if headers else {}
    if body is not None:
        kwargs["json"] = body
    return test_client.post(f"/api/students/{slug}/{suffix}", **kwargs)


class _NoopPostgrest:
    def auth(self, token):
        self.token = token


class _StudentsOnlyClient:
    """Session-scoped Supabase stand-in returning one `students` row.

    Mirrors the .table(...).select(...).execute() chain authorize_student_access
    uses. The row stands for the *caller's own* student -- never the requested
    slug, which is the whole point of the 403.
    """

    def __init__(self, rows):
        self._rows = rows
        # build_client_for_token calls client.postgrest.auth(token) when it is
        # allowed to run for real (see test_supabase_secret_key_is_never_read).
        self.postgrest = _NoopPostgrest()

    def table(self, name):
        return self

    def select(self, *args, **kwargs):
        return self

    def eq(self, *args, **kwargs):
        return self

    def execute(self):
        class _Resp:
            data = self._rows

        return _Resp()


# 1a. Every protected route still serves a demo slug with proxy headers only.
@pytest.mark.parametrize(("suffix", "body"), PROTECTED_ROUTES, ids=ROUTE_IDS)
def test_demo_slug_succeeds_on_every_route_without_a_token(suffix, body, client, monkeypatch):
    monkeypatch.setattr(api, "build_client", lambda: FakeClient(FEATURE_JSON))

    response = _post(client, "jordanReyes", suffix, body)

    assert response.status_code == 200
    # No Authorization header was sent anywhere in this request.
    assert "Authorization" not in response.request.headers


# 1b. Each of the five demo slugs individually is still servable.
@pytest.mark.parametrize("slug", sorted(api.DEMO_STUDENT_SLUGS))
def test_each_demo_slug_succeeds_without_a_token(slug, client, monkeypatch):
    monkeypatch.setattr(api, "build_client", lambda: FakeClient(FEATURE_JSON))

    response = _post(client, slug, "analyze/gap", None)

    assert response.status_code == 200


def test_demo_slug_allowlist_matches_files_on_disk():
    on_disk = {
        path.name[len("student_") : -len(".json")]
        for path in api.STUDENTS_DIR.glob("student_*.json")
    }
    assert api.DEMO_STUDENT_SLUGS == on_disk


# 2. Non-demo slug with no Authorization header -> 401, on all five routes.
@pytest.mark.parametrize(("suffix", "body"), PROTECTED_ROUTES, ids=ROUTE_IDS)
def test_non_demo_slug_without_token_is_401(suffix, body, client, monkeypatch):
    monkeypatch.setattr(api, "build_client", lambda: pytest.fail("must not reach the AI client"))
    monkeypatch.setattr(
        api, "build_client_for_token", lambda token: pytest.fail("must not build a DB client")
    )

    response = _post(client, NON_DEMO_SLUG, suffix, body)

    assert response.status_code == 401


# 3. Non-demo slug with a malformed Authorization header -> 401.
@pytest.mark.parametrize("header_value", ["", "Token abc123", "Bearer", "Bearer   ", "abc123"])
@pytest.mark.parametrize(("suffix", "body"), PROTECTED_ROUTES, ids=ROUTE_IDS)
def test_non_demo_slug_with_malformed_authorization_is_401(
    suffix, body, header_value, client, monkeypatch
):
    monkeypatch.setattr(api, "build_client", lambda: pytest.fail("must not reach the AI client"))
    monkeypatch.setattr(
        api, "build_client_for_token", lambda token: pytest.fail("must not build a DB client")
    )

    response = _post(
        client,
        NON_DEMO_SLUG,
        suffix,
        body,
        headers={**PROXY_HEADERS, "Authorization": header_value},
    )

    assert response.status_code == 401


# 4. Valid token resolving to a DIFFERENT student -> never 200, and the
#    requested student's record must not leak into the response.
@pytest.mark.parametrize(("suffix", "body"), PROTECTED_ROUTES, ids=ROUTE_IDS)
def test_valid_token_for_another_student_is_denied_and_leaks_nothing(
    suffix, body, client, monkeypatch, tmp_path
):
    # Give the requested (non-demo) slug a real profile on disk, so there is
    # genuinely something that *could* leak if authorization were bypassed.
    secret_name = "Zzyzx Quartermain"
    secret_gpa = 1.23
    secret_goal = "pineapple-flavored actuarial science"
    students_dir = tmp_path / "students"
    students_dir.mkdir()
    (students_dir / f"student_{NON_DEMO_SLUG}.json").write_text(
        json.dumps(
            {
                "student": {
                    "id": 9001,
                    "name": secret_name,
                    "gpa_current": secret_gpa,
                    "major_current": "Actuarial Science",
                    "classification": "Senior",
                },
                "career": {
                    "target_roles": ["Actuary"],
                    "career_goals": secret_goal,
                    "interests": ["risk"],
                    "skills_self_reported": {"technical": [], "soft": []},
                    "certifications": [],
                    "work_experience": [],
                    "projects": [],
                    "ai_anxiety_level": "low",
                },
                "courses": [],
                "assignments": [],
                "submissions": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(api, "STUDENTS_DIR", students_dir)

    # The caller's token resolves to a different student entirely.
    caller_row = [{"id": "caller-uuid", "name": "Someone Else", "auth_user_id": "auth-uuid"}]
    monkeypatch.setattr(
        api, "build_client_for_token", lambda token: _StudentsOnlyClient(caller_row)
    )
    monkeypatch.setattr(api, "build_client", lambda: pytest.fail("must not reach the AI client"))

    response = _post(
        client,
        NON_DEMO_SLUG,
        suffix,
        body,
        headers={**PROXY_HEADERS, "Authorization": "Bearer valid-token-for-someone-else"},
    )

    assert response.status_code in (403, 404)
    assert response.status_code != 200

    body_text = response.text
    assert secret_name not in body_text
    assert secret_goal not in body_text
    assert str(secret_gpa) not in body_text
    assert "Actuarial Science" not in body_text
    assert "9001" not in body_text
    # Only an error envelope comes back.
    assert set(response.json()) == {"detail"}


# 5. SUPABASE_SECRET_KEY must never be read on any of these paths.
#
#    Unlike tests/test_api_v2_gpa.py:123, this does NOT stub the module that
#    would read it: build_client_for_token runs for real, so its _required_env
#    calls execute under the spy. Only the supabase SDK's create_client is
#    replaced, to keep the test off the network.
@pytest.mark.parametrize(("suffix", "body"), PROTECTED_ROUTES, ids=ROUTE_IDS)
def test_supabase_secret_key_is_never_read(suffix, body, client, monkeypatch):
    import os

    from GradusIQ_career import supabase_client as supabase_client_module

    reads = []
    original_get = os.environ.get

    def spying_get(key, *args, **kwargs):
        reads.append(key)
        if key == "SUPABASE_SECRET_KEY":
            raise AssertionError("SUPABASE_SECRET_KEY must never be read by these routes")
        return original_get(key, *args, **kwargs)

    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-publishable-key")
    # Replace only the SDK entrypoint, so build_client_for_token's own env reads
    # still happen and remain visible to the spy.
    monkeypatch.setattr(
        supabase_client_module,
        "create_client",
        lambda url, key: _StudentsOnlyClient([{"id": "caller-uuid"}]),
    )
    monkeypatch.setattr(api, "build_client", lambda: FakeClient(FEATURE_JSON))
    monkeypatch.setattr(os.environ, "get", spying_get)

    response = _post(
        client,
        NON_DEMO_SLUG,
        suffix,
        body,
        headers={**PROXY_HEADERS, "Authorization": "Bearer some-token"},
    )

    assert response.status_code in (403, 404)
    # Prove the spy was actually on the path the real code takes -- otherwise
    # "never read" would be vacuously true.
    assert "SUPABASE_URL" in reads
    assert "SUPABASE_PUBLISHABLE_KEY" in reads


# ═══════════════════════════════════════════════════════════════════════════
# 6. Chat route coverage (previously zero)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("message", ["", "   ", "\n\t "])
def test_chat_requires_a_nonempty_message(message, client, monkeypatch):
    monkeypatch.setattr(api, "build_client", lambda: pytest.fail("must not reach the AI client"))

    response = client.post(
        "/api/students/jordanReyes/chat", json={"message": message, "history": []}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Message is required."


def test_chat_demo_slug_returns_a_reply(client, monkeypatch):
    fake = FakeClient("Here is your advice.")
    monkeypatch.setattr(api, "build_client", lambda: fake)

    response = client.post(
        "/api/students/jordanReyes/chat",
        json={"message": "How ready am I?", "history": []},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "Here is your advice."
    assert body["model"] == "fake-model"
    assert fake.calls[0]["role"] == "chat"
    # The student's own record is what grounds the reply.
    system_prompt = fake.calls[0]["messages"][0]["content"]
    assert "Jordan Reyes" in system_prompt


def test_chat_client_failure_returns_502(client, monkeypatch):
    def exploding_client():
        class _Boom:
            def complete(self, **kwargs):
                raise RuntimeError("upstream exploded")

        return _Boom()

    monkeypatch.setattr(api, "build_client", exploding_client)

    response = client.post(
        "/api/students/jordanReyes/chat",
        json={"message": "Hello", "history": []},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Chat service is unavailable."


# ═══════════════════════════════════════════════════════════════════════════
# Single-worker pinning.
#
# SlidingWindowRateLimiter and AIConcurrencyGate are process-local, so extra
# workers silently multiply both ceilings. The Procfile pins --workers 1;
# this guard catches the platforms that set worker count via env var instead.
# ═══════════════════════════════════════════════════════════════════════════


def test_web_concurrency_above_one_fails_app_construction(monkeypatch):
    monkeypatch.setenv("WEB_CONCURRENCY", "4")

    with pytest.raises(AIConfigError, match="WEB_CONCURRENCY"):
        api.create_app(make_test_config())


@pytest.mark.parametrize("value", ["2", "0", "8", "-1", "many", "1.0", " 2 "])
def test_web_concurrency_any_non_one_value_fails(value, monkeypatch):
    monkeypatch.setenv("WEB_CONCURRENCY", value)

    with pytest.raises(AIConfigError):
        api.create_app(make_test_config())


def test_web_concurrency_unset_succeeds(monkeypatch):
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)

    app = api.create_app(make_test_config())

    assert app is not None
    assert TestClient(app).get("/health").status_code == 200


def test_web_concurrency_exactly_one_succeeds(monkeypatch):
    monkeypatch.setenv("WEB_CONCURRENCY", "1")

    app = api.create_app(make_test_config())

    assert app is not None
    assert TestClient(app).get("/health").status_code == 200


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_blank_web_concurrency_is_treated_as_unset(blank, monkeypatch):
    # Platforms routinely inject empty strings for undefined vars; that must
    # not be read as "some worker count other than 1".
    monkeypatch.setenv("WEB_CONCURRENCY", blank)

    app = api.create_app(make_test_config())

    assert app is not None


def test_web_concurrency_one_with_surrounding_whitespace_succeeds(monkeypatch):
    monkeypatch.setenv("WEB_CONCURRENCY", "  1  ")

    assert api.create_app(make_test_config()) is not None


def test_procfile_pins_one_worker():
    """The Procfile is the primary enforcement; assert it says what it must.

    A start command that lost --workers 1 would leave only the env-var guard,
    which does not fire when the platform uses a start-command flag instead.
    """
    procfile = Path(__file__).resolve().parents[1] / "Procfile"
    assert procfile.exists(), "Procfile is the deployment pin; it must be committed"

    text = procfile.read_text(encoding="utf-8")
    command = next(
        line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")
    )
    assert command.startswith("web:")
    assert "--workers 1" in command
    assert "GradusIQ_career.api:app" in command


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/students/{slug}/profile
#
# Replaces the old frontend/public/data/student_<slug>.json static files,
# which were served unauthenticated at a guessable URL. Same two controls as
# the analyze/chat routes: proxy secret + authorize_student_access.
# ═══════════════════════════════════════════════════════════════════════════


# Demo slugs are served with proxy headers only, no bearer token.
@pytest.mark.parametrize("slug", sorted(api.DEMO_STUDENT_SLUGS))
def test_profile_route_serves_every_demo_slug_without_a_token(slug, client):
    response = client.get(f"/api/students/{slug}/profile")

    assert response.status_code == 200
    body = response.json()
    assert "student" in body
    assert body["student"]["name"]
    assert "Authorization" not in response.request.headers


def test_profile_route_returns_the_full_record():
    test_client = TestClient(api.create_app(make_test_config()), headers=PROXY_HEADERS)

    response = test_client.get("/api/students/jordanReyes/profile")

    assert response.status_code == 200
    body = response.json()
    # Same shape the frontend used to fetch from the public static file.
    for key in ("student", "career", "courses", "submissions"):
        assert key in body
    assert body["student"]["name"] == "Jordan Reyes"


def test_profile_route_requires_the_proxy_secret():
    unauthenticated = TestClient(api.create_app(make_test_config()))

    response = unauthenticated.get("/api/students/jordanReyes/profile")

    assert response.status_code == 401


# A non-demo slug with no Authorization header -> 401.
def test_profile_route_non_demo_slug_without_token_is_401(client, monkeypatch):
    monkeypatch.setattr(
        api, "build_client_for_token", lambda token: pytest.fail("must not build a DB client")
    )

    response = client.get(f"/api/students/{NON_DEMO_SLUG}/profile")

    assert response.status_code == 401


@pytest.mark.parametrize("header_value", ["", "Token abc123", "Bearer", "Bearer   ", "abc123"])
def test_profile_route_malformed_authorization_is_401(header_value, client):
    response = client.get(
        f"/api/students/{NON_DEMO_SLUG}/profile",
        headers={**PROXY_HEADERS, "Authorization": header_value},
    )

    assert response.status_code == 401


# A valid token resolving to a DIFFERENT student -> never 200, and the
# requested record must not leak. Mirrors the analyze/chat cross-student test.
def test_profile_route_valid_token_for_another_student_leaks_nothing(
    client, monkeypatch, tmp_path
):
    secret_name = "Zzyzx Quartermain"
    secret_goal = "pineapple-flavored actuarial science"
    secret_gpa = 1.23
    students_dir = tmp_path / "students"
    students_dir.mkdir()
    (students_dir / f"student_{NON_DEMO_SLUG}.json").write_text(
        json.dumps(
            {
                "student": {
                    "id": 9001,
                    "name": secret_name,
                    "gpa_current": secret_gpa,
                    "major_current": "Actuarial Science",
                },
                "career": {"career_goals": secret_goal, "target_roles": ["Actuary"]},
                "courses": [],
                "submissions": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(api, "STUDENTS_DIR", students_dir)

    caller_row = [{"id": "caller-uuid", "name": "Someone Else", "auth_user_id": "auth-uuid"}]
    monkeypatch.setattr(
        api, "build_client_for_token", lambda token: _StudentsOnlyClient(caller_row)
    )

    response = client.get(
        f"/api/students/{NON_DEMO_SLUG}/profile",
        headers={**PROXY_HEADERS, "Authorization": "Bearer valid-token-for-someone-else"},
    )

    assert response.status_code in (403, 404)
    assert response.status_code != 200

    body_text = response.text
    assert secret_name not in body_text
    assert secret_goal not in body_text
    assert str(secret_gpa) not in body_text
    assert "Actuarial Science" not in body_text
    assert "9001" not in body_text
    assert set(response.json()) == {"detail"}


def test_profile_route_unknown_slug_is_rejected_before_any_file_read(client):
    # Not a demo slug and no token -> stopped at authorization, so an unknown
    # slug never reveals whether a file exists.
    response = client.get("/api/students/doesNotExist/profile")

    assert response.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════
# Regression guard: no student data may return to frontend/public/.
# ═══════════════════════════════════════════════════════════════════════════

_KNOWN_STUDENT_NAMES = (
    "Jordan Reyes",
    "Ethan Brooks",
    "Marcus Webb",
    "Priya Nair",
    "Sofia Ramirez",
)


def test_frontend_public_contains_no_student_data():
    """frontend/public/ is served unauthenticated at a predictable URL.

    Student records and analysis bundles lived there until they were moved to
    data/demo_cache/ behind authorized routes. This asserts they do not come
    back -- by content, not filename, so a rename cannot slip past it.
    """
    public_dir = Path(__file__).resolve().parents[1] / "frontend" / "public"
    if not public_dir.exists():
        return  # nothing served statically at all; trivially safe

    offenders = []
    for path in public_dir.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "submissions" in text or any(name in text for name in _KNOWN_STUDENT_NAMES):
            offenders.append(str(path.relative_to(public_dir)))

    assert not offenders, (
        f"student data found under frontend/public/: {offenders}. "
        "These files are served unauthenticated; move them to data/demo_cache/."
    )


def test_demo_cache_lives_outside_frontend_public():
    repo_root = Path(__file__).resolve().parents[1]

    assert REAL_CACHED_ANALYSIS_DIR == repo_root / "data" / "demo_cache"
    assert "public" not in REAL_CACHED_ANALYSIS_DIR.parts
    assert "frontend" not in REAL_CACHED_ANALYSIS_DIR.parts
    # And the generator writes to the same place the reader reads from.
    from GradusIQ_career.demo import build_demo_cache as bdc

    assert bdc._OUTPUT_DIR == REAL_CACHED_ANALYSIS_DIR


# ═══════════════════════════════════════════════════════════════════════════
# Postgres-backed profile wiring: demo slugs must stay on the JSON path, and
# build_client_for_token failures must map to 503 everywhere.
# ═══════════════════════════════════════════════════════════════════════════


# 5. A demo slug never invokes the Postgres builder at any of the three sites.
@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("get", "profile", None),
        ("post", "analyze/gap", None),
        ("post", "chat", {"message": "hi", "history": []}),
    ],
    ids=["profile", "analyze", "chat"],
)
def test_demo_slug_never_calls_the_postgres_builder(method, suffix, body, client, monkeypatch):
    monkeypatch.setattr(
        api,
        "build_profile_from_supabase",
        lambda *a, **k: pytest.fail("demo slugs must not hit Postgres"),
    )
    monkeypatch.setattr(
        api,
        "build_client_for_token",
        lambda t: pytest.fail("demo slugs must not build a DB client"),
    )
    monkeypatch.setattr(api, "build_client", lambda: FakeClient(FEATURE_JSON))

    kwargs = {"json": body} if body is not None else {}
    response = getattr(client, method)(f"/api/students/jordanReyes/{suffix}", **kwargs)

    assert response.status_code == 200


# 8. SupabaseConfigError -> 503, including at the pre-existing GPA route.
def test_supabase_config_error_maps_to_503_on_gpa_route(client, monkeypatch):
    from GradusIQ_career.supabase_client import SupabaseConfigError

    def boom(token):
        raise SupabaseConfigError("SUPABASE_URL is not set.")

    monkeypatch.setattr(api, "build_client_for_token", boom)

    response = client.get("/api/v2/student/me/gpa", headers={"Authorization": "Bearer tok"})

    assert response.status_code == 503
    assert "SUPABASE_URL" in response.json()["detail"]


def test_supabase_config_error_maps_to_503_not_500(client, monkeypatch):
    """Regression guard: this previously surfaced as an unhandled 500."""
    from GradusIQ_career.supabase_client import SupabaseConfigError

    monkeypatch.setattr(
        api,
        "build_client_for_token",
        lambda t: (_ for _ in ()).throw(SupabaseConfigError("SUPABASE_PUBLISHABLE_KEY is not set.")),
    )

    response = client.get("/api/v2/student/me/gpa", headers={"Authorization": "Bearer tok"})

    assert response.status_code == 503
    assert response.status_code != 500


# Structural finding, pinned as a test: the Postgres path is currently
# unreachable through the three slug-addressed routes, because
# authorize_student_access denies every non-demo slug with 403 before any
# profile is loaded. If that changes, this test fails and the wiring above
# becomes live -- which is the intended signal, not a regression.
def test_non_demo_slug_is_denied_before_the_postgres_path_is_reached(client, monkeypatch):
    calls = {"builder": 0}

    def counting_builder(*args, **kwargs):
        calls["builder"] += 1
        raise AssertionError("unreachable today")

    monkeypatch.setattr(api, "build_profile_from_supabase", counting_builder)
    monkeypatch.setattr(
        api, "build_client_for_token", lambda t: _StudentsOnlyClient([{"id": "uuid-1"}])
    )

    response = client.get(
        f"/api/students/{NON_DEMO_SLUG}/profile",
        headers={**PROXY_HEADERS, "Authorization": "Bearer tok"},
    )

    assert response.status_code == 403
    assert calls["builder"] == 0
