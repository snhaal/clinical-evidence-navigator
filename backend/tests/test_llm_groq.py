"""
Unit tests for the Groq-specific logic in app.adapters.llm — the parts
that don't apply to Anthropic or Gemini: wrapping/unwrapping an
array-shaped JSON schema for OpenAI-style structured output (which
requires an object root), and falling back to plain prompt-instructed
JSON when a model doesn't support strict schema enforcement.

These test the pure helper function directly, plus the adapter's
end-to-end behavior against a monkeypatched OpenAI client — no real
network calls, no real API key needed.
"""

import json
from types import SimpleNamespace

import pytest

from app.adapters.llm import LLMAdapter, LLMProviderError, _unwrap_array_field

# --- _unwrap_array_field: pure logic -----------------------------------------


def test_unwrap_array_field_extracts_and_reserializes():
    wrapped = json.dumps({"verdicts": [{"a": 1}, {"a": 2}]})
    result = _unwrap_array_field(wrapped, key="verdicts")
    assert json.loads(result) == [{"a": 1}, {"a": 2}]


def test_unwrap_array_field_raises_llm_provider_error_on_malformed_json():
    with pytest.raises(LLMProviderError):
        _unwrap_array_field("not json at all", key="verdicts")


def test_unwrap_array_field_raises_llm_provider_error_on_missing_key():
    wrapped = json.dumps({"something_else": [1, 2, 3]})
    with pytest.raises(LLMProviderError):
        _unwrap_array_field(wrapped, key="verdicts")


# --- LLMAdapter._complete_groq: end-to-end against a fake OpenAI client -----


class FakeChoice:
    def __init__(self, content: str, finish_reason: str = "stop"):
        self.message = SimpleNamespace(content=content)
        self.finish_reason = finish_reason


class FakeResponse:
    def __init__(self, content: str, finish_reason: str = "stop"):
        self.choices = [FakeChoice(content, finish_reason)]
        self.usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5)


class FakeGroqClient:
    """Stands in for openai.AsyncOpenAI, recording every call's kwargs."""

    def __init__(self, responses: list, status_errors: list | None = None):
        self._responses = responses
        self._status_errors = status_errors or []
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        call_index = len(self.calls) - 1
        if call_index < len(self._status_errors) and self._status_errors[call_index] is not None:
            raise self._status_errors[call_index]
        return self._responses[call_index]


def make_adapter_with_fake_client(fake_client) -> LLMAdapter:
    """Builds an LLMAdapter for the groq provider without touching real settings/env."""
    adapter = object.__new__(LLMAdapter)
    adapter._provider = "groq"
    adapter._model = "openai/gpt-oss-120b"
    adapter._timeout = 12
    from app.adapters.rate_limiter import AsyncRateLimiter

    adapter._rate_limiter = AsyncRateLimiter(max_per_minute=1000)  # generous, not under test here
    adapter._client = fake_client
    return adapter


@pytest.mark.asyncio
async def test_groq_array_schema_is_wrapped_in_request_and_unwrapped_in_response():
    array_schema = {"type": "array", "items": {"type": "object", "properties": {"x": {"type": "string"}}}}
    fake_response = FakeResponse(json.dumps({"verdicts": [{"x": "a"}, {"x": "b"}]}))
    client = FakeGroqClient(responses=[fake_response])
    adapter = make_adapter_with_fake_client(client)

    result = await adapter.complete("system", "user", max_tokens=100, json_schema=array_schema)

    # Request: the schema sent to the API must be object-rooted, wrapping the array.
    sent_schema = client.calls[0]["response_format"]["json_schema"]["schema"]
    assert sent_schema["type"] == "object"
    assert sent_schema["properties"]["verdicts"] == array_schema

    # Response: the caller gets back plain array JSON, no wrapping.
    assert json.loads(result.text) == [{"x": "a"}, {"x": "b"}]
    assert result.input_tokens == 10
    assert result.output_tokens == 5


@pytest.mark.asyncio
async def test_groq_object_schema_is_not_wrapped():
    object_schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    fake_response = FakeResponse(json.dumps({"x": "hello"}))
    client = FakeGroqClient(responses=[fake_response])
    adapter = make_adapter_with_fake_client(client)

    result = await adapter.complete("system", "user", max_tokens=100, json_schema=object_schema)

    sent_schema = client.calls[0]["response_format"]["json_schema"]["schema"]
    assert sent_schema == object_schema  # passed through unchanged, no "verdicts" wrapper
    assert json.loads(result.text) == {"x": "hello"}


@pytest.mark.asyncio
async def test_groq_no_schema_means_no_response_format():
    fake_response = FakeResponse("plain text response")
    client = FakeGroqClient(responses=[fake_response])
    adapter = make_adapter_with_fake_client(client)

    result = await adapter.complete("system", "user", max_tokens=100)

    assert client.calls[0]["response_format"] is None
    assert result.text == "plain text response"


@pytest.mark.asyncio
async def test_groq_falls_back_to_plain_json_when_strict_schema_rejected():
    """A model that doesn't support strict json_schema (e.g. llama-3.3-70b-versatile) gets a graceful, same-call fallback."""
    import openai

    class FakeStatusError(openai.APIStatusError):
        def __init__(self):
            self.status_code = 400
            self.message = "model does not support response_format json_schema"

    array_schema = {"type": "array", "items": {"type": "object"}}
    first_call_error = FakeStatusError()
    fallback_response = FakeResponse(json.dumps([{"verdict": "match"}]))  # plain array, no wrapping this time
    client = FakeGroqClient(responses=[None, fallback_response], status_errors=[first_call_error, None])
    adapter = make_adapter_with_fake_client(client)

    result = await adapter.complete("system", "user", max_tokens=100, json_schema=array_schema)

    assert len(client.calls) == 2
    assert client.calls[0]["response_format"] is not None  # first attempt: strict schema
    assert "response_format" not in client.calls[1]  # fallback: no response_format at all
    assert json.loads(result.text) == [{"verdict": "match"}]  # returned as-is, no unwrap attempted
