import pytest
import requests

from GradusIQ_career.ai.errors import AIConfigError, AIRequestError, AIResponseParseError
from GradusIQ_career.ai.model_config import OPENROUTER_DEEPSEEK_R1, get_model_for_role
from GradusIQ_career.ai.openrouter_client import OpenRouterClient
from GradusIQ_career.ai.parser import parse_ai_json_response
from GradusIQ_career.ai.types import AIResponse
from GradusIQ_career import ai_services


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
    monkeypatch.delenv("GRADUSIQ_MODEL_CAREER", raising=False)

    assert get_model_for_role("career") == OPENROUTER_DEEPSEEK_R1


def test_env_model_override_wins_for_role(monkeypatch):
    monkeypatch.setenv("GRADUSIQ_MODEL_CAREER", "openrouter/test-career-model")

    assert get_model_for_role("career") == "openrouter/test-career-model"


def test_explicit_model_override_wins_over_role_default(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("GRADUSIQ_MODEL_CAREER", "openrouter/test-career-model")
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


def test_complete_message_returns_raw_message_with_tool_calls_and_null_content(monkeypatch):
    # This is the exact shape that broke the role-research tool loop when it
    # called complete(): tool_calls present, content null -- extract_text()
    # would raise AIResponseParseError since there's no text to extract.
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    session = FakeSession(
        payload={
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {"id": "call_1", "function": {"name": "web_search", "arguments": "{}"}}
                        ],
                    }
                }
            ]
        }
    )
    client = OpenRouterClient(session=session)

    message = client.complete_message(messages=[{"role": "user", "content": "hello"}], model="test-model")

    assert message["content"] is None
    assert message["tool_calls"][0]["function"]["name"] == "web_search"
    assert len(session.calls) == 1


def test_complete_message_still_raises_ai_request_error_on_network_failure(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    session = FakeSession(error=requests.Timeout("too slow"))
    client = OpenRouterClient(session=session)

    with pytest.raises(AIRequestError, match="OpenRouter request failed"):
        client.complete_message(messages=[{"role": "user", "content": "hello"}], model="test-model")


def test_standard_messages_serialize_exactly_without_mutating_input():
    message = {"role": "user", "content": "hello", "internal": "discard me"}
    original = dict(message)

    serialized = OpenRouterClient._message_to_dict(message)

    assert serialized == {"role": "user", "content": "hello"}
    assert message == original


def test_assistant_tool_calls_and_empty_content_survive_serialization():
    message = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "call_123",
                "type": "function",
                "function": {"name": "search_roles", "arguments": '{"query":"analyst"}'},
            }
        ],
    }
    original_tool_calls = message["tool_calls"]

    serialized = OpenRouterClient._message_to_dict(message)

    assert serialized == message
    assert serialized["tool_calls"] is not original_tool_calls


def test_tool_result_id_survives_and_none_optional_fields_are_omitted():
    message = {
        "role": "tool",
        "content": '{"results":[]}',
        "tool_call_id": "call_123",
        "name": None,
        "tool_calls": None,
    }

    assert OpenRouterClient._message_to_dict(message) == {
        "role": "tool",
        "content": '{"results":[]}',
        "tool_call_id": "call_123",
    }


def test_assistant_tool_calls_may_omit_none_content():
    message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": "call_123", "function": {"name": "search_roles", "arguments": "{}"}}],
    }

    assert OpenRouterClient._message_to_dict(message) == {
        "role": "assistant",
        "tool_calls": message["tool_calls"],
    }


@pytest.mark.parametrize(
    ("message", "match"),
    [
        ({"role": "assistant", "content": "", "tool_calls": "bad"}, "tool_calls"),
        ({"role": "tool", "content": "{}"}, "tool_call_id"),
        ({"role": "tool", "content": "{}", "tool_call_id": 123}, "tool_call_id"),
        ({"role": "user", "content": None}, "content.*or tool calls"),
    ],
)
def test_malformed_tool_message_fields_are_rejected_explicitly(message, match):
    with pytest.raises(AIConfigError, match=match):
        OpenRouterClient._message_to_dict(message)


def test_complete_unaffected_by_complete_message_addition(monkeypatch):
    # Guards against the refactor of complete()'s internals into _send()
    # changing complete()'s existing text-extraction behavior.
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    session = FakeSession()
    client = OpenRouterClient(session=session)

    response = client.complete(messages=[{"role": "user", "content": "hello"}], role="chat")

    assert response.text == '{"ok": true}'


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


# ═══════════════════════════════════════════════════════════════════════════
# validate_configured_models: placeholder model IDs must fail at startup,
# not on the first live request.
# ═══════════════════════════════════════════════════════════════════════════


def _clear_model_env(monkeypatch):
    """Drop every GRADUSIQ_MODEL_* override so defaults are what resolve.

    .env carries real overrides for GRADUSIQ_MODEL_CAREER / _ACADEMIC and
    api.py calls load_dotenv() on import, so without this a test asserting on
    hardcoded defaults would silently be asserting on the developer's .env.
    """
    from GradusIQ_career.ai.model_config import ENV_BY_ROLE

    for env_name in ENV_BY_ROLE.values():
        monkeypatch.delenv(env_name, raising=False)


# 1. A role in roles_in_use resolving to a placeholder raises AIConfigError.
def test_validate_configured_models_raises_on_placeholder(monkeypatch):
    from GradusIQ_career.ai.model_config import validate_configured_models

    _clear_model_env(monkeypatch)

    # 'orchestrator' still carries a TODO_ default by design (it is excluded
    # from the startup set because ai_services.call_agent has no production
    # caller). These validator tests used to use 'chat' as their placeholder
    # fixture; chat now resolves to a real model and is validated at startup,
    # so orchestrator is the remaining genuine placeholder role.
    with pytest.raises(AIConfigError, match="Placeholder model ID"):
        validate_configured_models({"orchestrator"})


def test_validate_configured_models_error_names_role_and_placeholder(monkeypatch):
    from GradusIQ_career.ai.model_config import validate_configured_models

    _clear_model_env(monkeypatch)

    with pytest.raises(AIConfigError) as excinfo:
        validate_configured_models({"orchestrator"})

    message = str(excinfo.value)
    assert "orchestrator" in message
    assert "TODO_OPENROUTER_MODEL_GEMINI_2_5_PRO" in message


def test_validate_configured_models_reports_every_offending_role(monkeypatch):
    from GradusIQ_career.ai.model_config import validate_configured_models

    _clear_model_env(monkeypatch)

    # Both remaining excluded roles at once: the error must name every
    # offender, not just the first one sorted().
    with pytest.raises(AIConfigError) as excinfo:
        validate_configured_models({"orchestrator", "report"})

    message = str(excinfo.value)
    for role in ("orchestrator", "report"):
        assert role in message


# 2. The five in-use roles pass cleanly against today's config.
def test_validate_configured_models_passes_for_roles_in_use(monkeypatch):
    from GradusIQ_career.ai.model_config import (
        ROLES_VALIDATED_AT_STARTUP,
        validate_configured_models,
    )

    _clear_model_env(monkeypatch)

    # Must not raise, with no env overrides in play.
    validate_configured_models(set(ROLES_VALIDATED_AT_STARTUP))


def test_roles_validated_at_startup_excludes_the_two_documented_roles():
    from GradusIQ_career.ai.model_config import ROLES_VALIDATED_AT_STARTUP

    assert ROLES_VALIDATED_AT_STARTUP == {
        "career",
        "academic",
        "role_research",
        "parsing",
        "chat",
    }
    # Deliberate exclusions -- see the comment above the frozenset. 'chat' was
    # a third exclusion until its "@preset/chat" hardcode was removed; it is
    # now validated like any other role.
    for excluded in ("orchestrator", "report"):
        assert excluded not in ROLES_VALIDATED_AT_STARTUP


# 3. An env override supplying a real model clears the check even when the
#    hardcoded default is still a placeholder -- proves precedence is honored
#    rather than MODEL_BY_ROLE being read directly.
def test_env_override_clears_placeholder_check(monkeypatch):
    from GradusIQ_career.ai.model_config import MODEL_BY_ROLE, validate_configured_models

    _clear_model_env(monkeypatch)

    # Precondition: orchestrator's hardcoded default really is still a placeholder.
    assert MODEL_BY_ROLE["orchestrator"].startswith("TODO_")
    with pytest.raises(AIConfigError):
        validate_configured_models({"orchestrator"})

    monkeypatch.setenv("GRADUSIQ_MODEL_ORCHESTRATOR", "openrouter/real-orchestrator-model")

    # Same role, same untouched default -- now passes purely via the override.
    validate_configured_models({"orchestrator"})
    assert MODEL_BY_ROLE["orchestrator"].startswith("TODO_")


def test_whitespace_only_env_override_does_not_satisfy_the_check(monkeypatch):
    from GradusIQ_career.ai.model_config import validate_configured_models

    _clear_model_env(monkeypatch)
    monkeypatch.setenv("GRADUSIQ_MODEL_ORCHESTRATOR", "   ")

    # get_model_for_role ignores a blank override, so the placeholder still wins.
    with pytest.raises(AIConfigError):
        validate_configured_models({"orchestrator"})


# 4. parsing now resolves to the already-validated Flash model.
def test_parsing_resolves_to_deepseek_v4_flash(monkeypatch):
    _clear_model_env(monkeypatch)

    assert get_model_for_role("parsing") == "deepseek/deepseek-v4-flash"


def test_parsing_and_role_research_share_the_validated_flash_model(monkeypatch):
    _clear_model_env(monkeypatch)

    assert get_model_for_role("parsing") == get_model_for_role("role_research")


def test_qwen3_placeholder_constant_is_gone():
    from GradusIQ_career.ai import model_config

    # Removed rather than left dangling: nothing references it once parsing
    # repoints, and a stray TODO_ constant is what the validator exists to catch.
    assert not hasattr(model_config, "OPENROUTER_QWEN3_32B")


# 5. Startup wiring is real: monkeypatch parsing's default back to a
#    placeholder and create_app() must refuse to build the app.
def test_create_app_raises_when_an_in_use_role_has_a_placeholder(monkeypatch):
    from GradusIQ_career import api
    from GradusIQ_career.ai import model_config

    _clear_model_env(monkeypatch)

    # Sanity: the app builds fine before we break anything.
    api.create_app(
        api.APIConfig(
            proxy_secret="s",
            allowed_origins=(),
            rate_limit_requests=10,
            rate_limit_window_seconds=60.0,
            max_concurrent_ai_requests=2,
        )
    )

    broken = dict(model_config.MODEL_BY_ROLE)
    broken["parsing"] = "TODO_OPENROUTER_MODEL_QWEN3_32B"
    monkeypatch.setattr(model_config, "MODEL_BY_ROLE", broken)

    with pytest.raises(AIConfigError, match="parsing"):
        api.create_app(
            api.APIConfig(
                proxy_secret="s",
                allowed_origins=(),
                rate_limit_requests=10,
                rate_limit_window_seconds=60.0,
                max_concurrent_ai_requests=2,
            )
        )


def test_create_app_placeholder_failure_happens_before_any_route_is_served(monkeypatch):
    from GradusIQ_career import api
    from GradusIQ_career.ai import model_config

    _clear_model_env(monkeypatch)
    broken = dict(model_config.MODEL_BY_ROLE)
    broken["career"] = "TODO_OPENROUTER_MODEL_SOMETHING"
    monkeypatch.setattr(model_config, "MODEL_BY_ROLE", broken)

    # No app object is produced at all -- there is nothing to serve /health from.
    with pytest.raises(AIConfigError, match="career"):
        api.create_app(
            api.APIConfig(
                proxy_secret="s",
                allowed_origins=(),
                rate_limit_requests=10,
                rate_limit_window_seconds=60.0,
                max_concurrent_ai_requests=2,
            )
        )


# ═══════════════════════════════════════════════════════════════════════════
# 6. chat: repointed off the "@preset/chat" hardcode.
#
# api.py used to call complete(role="chat", model="@preset/chat"). OpenRouter
# presets are account-specific named configurations created in their dashboard,
# not built-in aliases; no preset named "chat" existed on this account, so every
# chat call came back 404 preset_not_found and both chat routes returned 502 --
# verified live on the slug-addressed and /me paths alike.
#
# The explicit model= is gone, so chat now resolves through get_model_for_role
# like every other role, and chat has been added to ROLES_VALIDATED_AT_STARTUP
# so a regression fails the deploy instead of the first student message.
# ═══════════════════════════════════════════════════════════════════════════


def test_chat_resolves_to_the_validated_flash_model(monkeypatch):
    _clear_model_env(monkeypatch)

    assert get_model_for_role("chat") == "deepseek/deepseek-v4-flash"
    assert not get_model_for_role("chat").startswith("TODO_")


def test_chat_and_parsing_share_the_validated_flash_model(monkeypatch):
    _clear_model_env(monkeypatch)

    assert get_model_for_role("chat") == get_model_for_role("parsing")


def test_gemini_flash_placeholder_constant_is_gone():
    from GradusIQ_career.ai import model_config

    # Removed rather than left dangling, matching the QWEN3 precedent above:
    # chat was its only consumer, and a stray TODO_ constant is what the
    # validator exists to catch. GEMINI_2_5_PRO stays -- orchestrator and
    # report still resolve to it.
    assert not hasattr(model_config, "OPENROUTER_GEMINI_2_5_FLASH")
    assert hasattr(model_config, "OPENROUTER_GEMINI_2_5_PRO")


# 6a. The closest thing to a live call the suite allows: a real
#     OpenRouterClient with a FakeSession, so the model that would go on the
#     wire is asserted without any network. Mirrors
#     test_explicit_model_override_wins_over_role_default, but with NO explicit
#     model -- which is the whole point, since that argument is what used to
#     carry "@preset/chat" and shadow the role.
def test_chat_role_puts_the_real_model_on_the_wire(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    _clear_model_env(monkeypatch)
    session = FakeSession()
    client = OpenRouterClient(session=session)

    client.complete(messages=[{"role": "user", "content": "hello"}], role="chat")

    sent_model = session.calls[0]["kwargs"]["json"]["model"]
    assert sent_model == "deepseek/deepseek-v4-flash"
    assert not sent_model.startswith("TODO_")
    assert not sent_model.startswith("@preset/")


# 6b. Startup validation now covers chat and passes against today's config.
def test_startup_validation_includes_chat_and_passes(monkeypatch):
    from GradusIQ_career.ai.model_config import (
        ROLES_VALIDATED_AT_STARTUP,
        validate_configured_models,
    )

    _clear_model_env(monkeypatch)

    assert "chat" in ROLES_VALIDATED_AT_STARTUP
    # Must not raise: chat's default is real now, with no env override in play.
    validate_configured_models(set(ROLES_VALIDATED_AT_STARTUP))


def test_create_app_succeeds_with_chat_in_the_validated_set(monkeypatch):
    from GradusIQ_career import api

    _clear_model_env(monkeypatch)

    api.create_app(
        api.APIConfig(
            proxy_secret="s",
            allowed_origins=(),
            rate_limit_requests=10,
            rate_limit_window_seconds=60.0,
            max_concurrent_ai_requests=2,
        )
    )


# 6c. THE REGRESSION TEST. Putting chat's default back the way it was must now
#     fail at startup -- this is what proves removing the exclusion actually
#     closed the gap, rather than just moving a string around.
@pytest.mark.parametrize(
    "regressed",
    ["TODO_OPENROUTER_MODEL_GEMINI_2_5_FLASH", "TODO_ANYTHING_AT_ALL"],
)
def test_create_app_raises_if_chat_regresses_to_a_placeholder(monkeypatch, regressed):
    from GradusIQ_career import api
    from GradusIQ_career.ai import model_config

    _clear_model_env(monkeypatch)

    broken = dict(model_config.MODEL_BY_ROLE)
    broken["chat"] = regressed
    monkeypatch.setattr(model_config, "MODEL_BY_ROLE", broken)

    with pytest.raises(AIConfigError, match="chat"):
        api.create_app(
            api.APIConfig(
                proxy_secret="s",
                allowed_origins=(),
                rate_limit_requests=10,
                rate_limit_window_seconds=60.0,
                max_concurrent_ai_requests=2,
            )
        )


def test_preset_string_would_still_slip_past_startup_validation(monkeypatch):
    """The honest limit of this fix, pinned so nobody over-trusts the validator.

    validate_configured_models is a TODO_ prefix test, not a reachability
    check. "@preset/chat" is well-formed and simply does not exist upstream, so
    startup validation would NOT have caught the original bug and still would
    not. What actually fixed chat was deleting the hardcoded model= in api.py
    (pinned by test_chat_route_sends_no_explicit_model_argument); adding chat to
    the validated set only closes the adjacent placeholder class.

    If this test ever starts failing because create_app() raises, that means
    someone added a real reachability check -- delete this test and celebrate.
    """
    from GradusIQ_career import api
    from GradusIQ_career.ai import model_config

    _clear_model_env(monkeypatch)

    broken = dict(model_config.MODEL_BY_ROLE)
    broken["chat"] = "@preset/chat"
    monkeypatch.setattr(model_config, "MODEL_BY_ROLE", broken)

    # Builds cleanly. The 404 would only surface on a live call.
    api.create_app(
        api.APIConfig(
            proxy_secret="s",
            allowed_origins=(),
            rate_limit_requests=10,
            rate_limit_window_seconds=60.0,
            max_concurrent_ai_requests=2,
        )
    )
