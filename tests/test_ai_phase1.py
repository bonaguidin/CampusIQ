import pytest
import requests

from CampusIQ_career.ai.errors import AIConfigError, AIRequestError, AIResponseParseError
from CampusIQ_career.ai.model_config import OPENROUTER_DEEPSEEK_R1, get_model_for_role
from CampusIQ_career.ai.openrouter_client import OpenRouterClient
from CampusIQ_career.ai.parser import parse_ai_json_response
from CampusIQ_career.ai.types import AIResponse
from CampusIQ_career import ai_services


class FakeResponse:
    def __init__(self, payload, status_error=None):
        self.payload = payload
        self.status_error = status_error

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_error:
            raise self.status_error


class FakeSession:
    def __init__(self, payload=None, error=None):
        self.payload = payload or {
            "choices": [{"message": {"content": '{"ok": true}'}}],
        }
        self.error = error
        self.calls = []

    def post(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        if self.error:
            raise self.error
        return FakeResponse(self.payload)


def test_missing_openrouter_api_key_raises_config_error(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with pytest.raises(AIConfigError, match="OPENROUTER_API_KEY"):
        OpenRouterClient()


def test_role_based_model_routing_returns_configured_model(monkeypatch):
    monkeypatch.delenv("CAMPUSIQ_MODEL_CAREER", raising=False)

    assert get_model_for_role("career") == OPENROUTER_DEEPSEEK_R1


def test_env_model_override_wins_for_role(monkeypatch):
    monkeypatch.setenv("CAMPUSIQ_MODEL_CAREER", "openrouter/test-career-model")

    assert get_model_for_role("career") == "openrouter/test-career-model"


def test_explicit_model_override_wins_over_role_default(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("CAMPUSIQ_MODEL_CAREER", "openrouter/test-career-model")
    session = FakeSession()
    client = OpenRouterClient(session=session)

    client.complete(
        messages=[{"role": "user", "content": "hello"}],
        role="career",
        model="openrouter/explicit-model",
    )

    assert session.calls[0]["kwargs"]["json"]["model"] == "openrouter/explicit-model"


def test_unknown_role_is_rejected_clearly():
    with pytest.raises(AIConfigError, match="Unknown agent role"):
        get_model_for_role("unknown")


def test_openrouter_client_uses_fake_session_without_real_network(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    session = FakeSession()
    client = OpenRouterClient(session=session)

    response = client.complete(messages=[{"role": "user", "content": "hello"}], role="chat")

    assert response.text == '{"ok": true}'
    assert len(session.calls) == 1
    assert session.calls[0]["kwargs"]["headers"]["Authorization"] == "Bearer test-key"


def test_network_failure_becomes_ai_request_error(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    session = FakeSession(error=requests.Timeout("too slow"))
    client = OpenRouterClient(session=session)

    with pytest.raises(AIRequestError, match="OpenRouter request failed"):
        client.complete(messages=[{"role": "user", "content": "hello"}], role="chat")


def test_malformed_provider_response_becomes_parse_error(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    session = FakeSession(payload={"choices": []})
    client = OpenRouterClient(session=session)

    with pytest.raises(AIResponseParseError, match="choices"):
        client.complete(messages=[{"role": "user", "content": "hello"}], role="chat")


def test_parser_handles_plain_json():
    assert parse_ai_json_response('{"feature": "FIT", "status": "success"}') == {
        "feature": "FIT",
        "status": "success",
    }


def test_parser_handles_fenced_json():
    text = """Here is the result:

```json
{"feature": "GAP", "status": "success"}
```
"""
    assert parse_ai_json_response(text) == {"feature": "GAP", "status": "success"}


def test_parser_rejects_invalid_json():
    with pytest.raises(AIResponseParseError):
        parse_ai_json_response("{not-json")


def test_ai_services_call_agent_works_with_mocked_client():
    class FakeClient:
        def __init__(self):
            self.role = None

        def complete(self, **kwargs):
            self.role = kwargs["role"]
            return AIResponse(
                text="ok",
                raw={"choices": [{"message": {"content": "ok"}}]},
                model="fake-model",
            )

    client = FakeClient()
    raw = ai_services.call_agent(
        "fit",
        [{"role": "user", "content": "student"}],
        client=client,
    )

    assert client.role == "career"
    assert raw["choices"][0]["message"]["content"] == "ok"


@pytest.mark.parametrize("feature", ["FIT", "GAP", "SHIFT"])
def test_fit_gap_shift_map_to_career_role(feature):
    assert ai_services.get_role_for_agent(feature) == "career"
