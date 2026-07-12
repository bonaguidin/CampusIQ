"""OpenRouter client for Campus IQ AI calls."""

import os
from typing import Any, Mapping, Sequence

import requests

from .errors import AIConfigError, AIRequestError, AIResponseParseError
from .model_config import get_model_for_role
from .types import AIMessage, AIResponse, AgentRole


OPENROUTER_CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"

# DeepSeek R1's reasoning traces routinely run 100-200s+ (confirmed via real
# validation calls) -- the class default below is too short for any caller
# that actually invokes the "career"/"academic" DeepSeek R1 roles. Callers
# making real (non-mock) calls should pass this explicitly.
DEEPSEEK_R1_REASONING_TIMEOUT_SECONDS = 300.0


class OpenRouterClient:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = OPENROUTER_CHAT_COMPLETIONS_URL,
        timeout: float = 30.0,
        session: Any = requests,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("OPENROUTER_API_KEY")
        if not self.api_key or not self.api_key.strip():
            raise AIConfigError("OPENROUTER_API_KEY is required for OpenRouter AI calls.")
        self.base_url = base_url
        self.timeout = timeout
        self.session = session

    def complete(
        self,
        *,
        messages: Sequence[AIMessage | Mapping[str, Any]],
        role: AgentRole | str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        extra_body: Mapping[str, Any] | None = None,
    ) -> AIResponse:
        raw, selected_model = self._send(
            messages=messages,
            role=role,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            extra_body=extra_body,
        )
        text = self.extract_text(raw)
        return AIResponse(text=text, raw=raw, model=selected_model)

    def complete_message(
        self,
        *,
        messages: Sequence[AIMessage | Mapping[str, Any]],
        role: AgentRole | str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        extra_body: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        """Like complete(), but returns the raw assistant message unparsed.

        Skips extract_text() so tool-calling callers doing their own
        tool_calls parsing don't hit AIResponseParseError when the assistant
        responds with tool_calls and null/empty content -- a normal shape for
        tool-calling turns that complete()'s text-only contract can't
        represent.
        """
        raw, _selected_model = self._send(
            messages=messages,
            role=role,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            extra_body=extra_body,
            timeout=timeout,
        )
        try:
            message = raw["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIResponseParseError("OpenRouter response is missing choices[0].message.") from exc
        if not isinstance(message, Mapping):
            raise AIResponseParseError("OpenRouter response message must be an object.")
        return message

    def _send(
        self,
        *,
        messages: Sequence[AIMessage | Mapping[str, Any]],
        role: AgentRole | str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        extra_body: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> tuple[Mapping[str, Any], str]:
        selected_model = self._select_model(role=role, model=model)
        body: dict[str, Any] = {
            "model": selected_model,
            "messages": [self._message_to_dict(message) for message in messages],
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if temperature is not None:
            body["temperature"] = temperature
        if extra_body:
            body.update(extra_body)

        try:
            response = self.session.post(
                self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key.strip()}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=timeout if timeout is not None else self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise AIRequestError(f"OpenRouter request failed: {exc}") from exc

        raw = self._response_json(response)
        return raw, selected_model

    def raw_complete(
        self,
        *,
        messages: Sequence[AIMessage | Mapping[str, Any]],
        role: AgentRole | str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        extra_body: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        return self.complete(
            messages=messages,
            role=role,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            extra_body=extra_body,
        ).raw

    @staticmethod
    def extract_text(raw: Mapping[str, Any]) -> str:
        try:
            choices = raw["choices"]
            first_choice = choices[0]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIResponseParseError("OpenRouter response is missing choices[0].") from exc

        message = first_choice.get("message") if isinstance(first_choice, Mapping) else None
        content = message.get("content") if isinstance(message, Mapping) else None

        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            text_parts = [
                part.get("text", "")
                for part in content
                if isinstance(part, Mapping) and isinstance(part.get("text"), str)
            ]
            text = "".join(text_parts).strip()
            if text:
                return text

        text = first_choice.get("text") if isinstance(first_choice, Mapping) else None
        if isinstance(text, str) and text.strip():
            return text

        raise AIResponseParseError("OpenRouter response does not contain response text.")

    @staticmethod
    def _message_to_dict(message: AIMessage | Mapping[str, Any]) -> dict[str, Any]:
        if isinstance(message, AIMessage):
            return {"role": message.role, "content": message.content}
        if isinstance(message, Mapping):
            role = message.get("role")
            content = message.get("content")
            if not isinstance(role, str) or not isinstance(content, str):
                raise AIConfigError("Each AI message must include string 'role' and 'content'.")
            return {"role": role, "content": content}
        raise AIConfigError("AI messages must be AIMessage objects or mappings.")

    @staticmethod
    def _response_json(response: Any) -> Mapping[str, Any]:
        try:
            raw = response.json()
        except ValueError as exc:
            raise AIResponseParseError("OpenRouter response body is not valid JSON.") from exc
        if not isinstance(raw, Mapping):
            raise AIResponseParseError("OpenRouter response JSON must be an object.")
        return raw

    @staticmethod
    def _select_model(*, role: AgentRole | str | None, model: str | None) -> str:
        if model and model.strip():
            return model.strip()
        if role is None:
            raise AIConfigError("Either an explicit model or an agent role is required.")
        return get_model_for_role(role)
