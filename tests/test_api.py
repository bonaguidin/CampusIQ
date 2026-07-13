import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from CampusIQ_career import api
from CampusIQ_career.ai.errors import AIConfigError
from CampusIQ_career.ai.types import AIResponse


TEST_PROXY_SECRET = "test-proxy-secret"
PROXY_HEADERS = {api.PROXY_SECRET_HEADER: TEST_PROXY_SECRET}


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


def test_public_health_route_requires_no_proxy_credential():
    response = TestClient(api.create_app(make_test_config())).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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
            "must_have_gaps": ["SQL"],
            "nice_to_have_gaps": ["dashboarding"],
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
                    "course_code": "ENGR 102",
                    "course_name": "Engineering Lab I: Computation",
                    "paraphrase": "Asked for more explanation of code logic."
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


def test_analyze_gap_unknown_student_returns_404(client, monkeypatch):
    monkeypatch.setattr(api, "build_client", lambda: FakeClient('{"data": {}}'))

    response = client.post("/api/students/doesNotExist/analyze/gap")

    assert response.status_code == 404


def test_analyze_gap_missing_api_key_returns_503(client, monkeypatch):
    def raise_config_error(*args, **kwargs):
        raise AIConfigError("OPENROUTER_API_KEY is required for OpenRouter AI calls.")

    # Exercise the real build_client() (not a monkeypatched replacement) so the
    # AIConfigError -> HTTPException(503) translation inside it is what's tested.
    monkeypatch.setattr(api, "OpenRouterClient", raise_config_error)

    response = client.post("/api/students/jordanReyes/analyze/gap")

    assert response.status_code == 503


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
    monkeypatch.setattr(api, "load_cached_feature_result", lambda student_slug, feature_name: None)

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
    monkeypatch.setattr(api, "load_cached_feature_result", lambda student_slug, feature_name: cached_success)

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
    monkeypatch.setattr(api, "load_cached_feature_result", lambda student_slug, feature_name: cached_failure)

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
    monkeypatch.setattr(api, "load_cached_feature_result", lambda student_slug, feature_name: cached_malformed)

    result = api.run_feature_with_fallback("GAP", "someStudent", profile={}, client=None)

    assert result["status"] == "failed"
