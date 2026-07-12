import pytest
from fastapi.testclient import TestClient

from CampusIQ_career import api
from CampusIQ_career.ai.errors import AIConfigError
from CampusIQ_career.ai.types import AIResponse


class FakeClient:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return AIResponse(text=self.text, raw={"choices": []}, model="fake-model")


@pytest.fixture
def client():
    return TestClient(api.app)


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


def test_analyze_gap_malformed_ai_json_returns_failed_status(client, monkeypatch):
    monkeypatch.setattr(api, "build_client", lambda: FakeClient("{not-json"))

    response = client.post("/api/students/jordanReyes/analyze/gap")

    assert response.status_code == 200
    body = response.json()
    assert body["feature"] == "GAP"
    assert body["status"] == "failed"
