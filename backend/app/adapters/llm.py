"""
Thin adapter over the LLM provider.

Every Plan / Verify stage call goes through `complete()` so that:
  - swapping providers later touches one file, not the pipeline logic
  - token usage is logged in one place for the observability requirement
  - a hard cost cap can be enforced centrally (Risk: "free-tier LLM cost overrun")
  - every call is paced through one shared, process-wide rate limiter
    (see app/adapters/rate_limiter.py) — required because free-tier RPM
    quotas are enforced per-project by the provider, not per-request

This module does NOT contain prompts — those belong to the pipeline stages
(Plan, Verify) that call this adapter. Keeping prompts out of the adapter
is what makes the adapter provider-agnostic.

Supported providers: "anthropic", "gemini", and "groq". Set LLM_PROVIDER in .env.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from app.adapters.rate_limiter import get_llm_rate_limiter
from app.config import get_settings

logger = logging.getLogger(__name__)
# Limit simultaneous in-flight requests to Groq to prevent instant burst 429s
_RATE_SEMAPHORE = asyncio.Semaphore(2)

class LLMProviderError(Exception):
    """Raised when the provider call fails or returns an unusable response."""


class LLMRateLimitError(LLMProviderError):
    """
    Raised specifically when the provider rejected the call for being over
    quota (HTTP 429 / RESOURCE_EXHAUSTED), AFTER internal retries with
    backoff were already exhausted. Callers (Plan, Verify) can treat this
    the same as any other LLMProviderError — it's a distinct subclass
    mainly so logs and future callers can tell "genuinely rate-limited
    despite our own pacing" apart from "the provider is broken."
    """


@dataclass
class CompletionResult:
    text: str
    input_tokens: int
    output_tokens: int
    model: str

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def _get_finish_reason(response: Any) -> str | None:
    """
    Best-effort extraction of why generation stopped, for a clearer error
    message when response.text comes back empty. Defensive against SDK
    shape differences (candidates list could be empty, finish_reason may
    be an enum or a plain string depending on SDK version) — never raises,
    just returns None if it can't figure it out.
    """
    try:
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return None
        return str(candidates[0].finish_reason)
    except (AttributeError, IndexError):
        return None


def _unwrap_array_field(raw_text: str, key: str) -> str:
    """
    Used by the Groq branch to undo the object-wrapping applied to
    array-shaped schemas before they're sent to an OpenAI-style API (see
    _complete_groq's docstring for why). Extracts the array under `key`
    and re-serializes it, so the caller always gets back plain array JSON
    text regardless of which provider answered — the wrapping is fully
    contained inside this adapter. Raises LLMProviderError (not a bare
    JSON/KeyError) on failure so it's caught by the same retry path every
    other malformed-response case goes through.
    """
    try:
        parsed = json.loads(raw_text)
        return json.dumps(parsed[key])
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise LLMProviderError(f"Groq response did not match the expected wrapped-array shape: {exc}") from exc
    
def _sanitize_gemini_schema(schema: Any) -> Any:
    """Recursively removes OpenAPI / Pydantic fields rejected by Gemini's schema parser."""
    if isinstance(schema, dict):
        forbidden = {"additionalProperties", "additional_properties", "title", "$defs"}
        return {
            k: _sanitize_gemini_schema(v)
            for k, v in schema.items()
            if k not in forbidden
        }
    elif isinstance(schema, list):
        return [_sanitize_gemini_schema(item) for item in schema]
    return schema

class LLMAdapter:
    """
    Every call made through this class:
      1. Waits its turn at the shared, process-wide rate limiter
         (app.adapters.rate_limiter.get_llm_rate_limiter()) — this is what
         actually prevents 429s, by pacing requests to stay under
         LLM_MAX_REQUESTS_PER_MINUTE instead of firing them all at once.
      2. On a 429/RESOURCE_EXHAUSTED response despite that pacing (the
         limiter's configured rate may still be optimistic relative to the
         provider's real, sometimes-undocumented quota), retries with
         real exponential backoff — not an immediate retry, which would
         almost certainly hit the same 429 again.
      3. Only after backoff is exhausted does it raise LLMRateLimitError,
         which the pipeline stage then handles by degrading to "unclear"
         (see app/pipeline/verify.py, app/pipeline/plan.py) rather than
         crashing the request.
    """

    _MAX_RATE_LIMIT_RETRIES = 3
    _BACKOFF_INITIAL_SECONDS = 3.0
    _BACKOFF_MAX_SECONDS = 30.0

    def __init__(self) -> None:
        settings = get_settings()
        self._provider = settings.llm_provider
        self._model = settings.llm_model
        self._timeout = settings.request_timeout_seconds
        self._rate_limiter = get_llm_rate_limiter()

        if self._provider == "anthropic":
            import anthropic

            self._client = anthropic.AsyncAnthropic(api_key=settings.llm_provider_api_key)
        elif self._provider == "gemini":
            from google import genai

            self._client = genai.Client(api_key=settings.llm_provider_api_key)
        elif self._provider == "groq":
            # Groq exposes an OpenAI-compatible endpoint, so the standard
            # `openai` SDK works unmodified — just point base_url at Groq
            # and use a Groq model name. This is deliberately the standard
            # OpenAI client, not a Groq-specific SDK: it's the more mature,
            # widely-used code path, which matters after hitting real
            # version-sensitivity issues with google-genai.
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                api_key=settings.llm_provider_api_key,
                base_url="https://api.groq.com/openai/v1",
            )
        else:
            raise NotImplementedError(
                f"LLM provider '{self._provider}' is not wired up. Supported: 'anthropic', 'gemini', 'groq'."
            )

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        json_schema: dict[str, Any] | None = None,
    ) -> CompletionResult:
        """
        Single-turn completion. Temperature defaults to 0 because every caller
        of this adapter (structured-query extraction, per-criterion verdicts)
        needs deterministic, reproducible output — not creative variation.

        `json_schema`: an optional JSON Schema dict describing the expected
        response shape. The Gemini and Groq branches enforce this server-side
        (Gemini via response_schema; Groq via OpenAI-style response_format
        json_schema on gpt-oss models specifically — see _complete_groq for
        why the model choice matters here), which is a meaningful reliability
        win for a large batched response — it eliminates most malformed-JSON
        retries, which matter more than usual when every retry also costs
        precious rate-limit budget. The Anthropic branch ignores this
        parameter; callers must keep instructing JSON format via the prompt
        itself for that provider, as before.
        """
        delay = self._BACKOFF_INITIAL_SECONDS
        last_error: Exception | None = None

        for attempt in range(self._MAX_RATE_LIMIT_RETRIES + 1):
            await self._rate_limiter.acquire()

            try:
                async with _RATE_SEMAPHORE:
                    await asyncio.sleep(0.2)
                    if self._provider == "anthropic":
                        return await self._complete_anthropic(system_prompt, user_prompt, max_tokens, temperature)
                    elif self._provider == "groq":
                        return await self._complete_groq(
                            system_prompt, user_prompt, max_tokens, temperature, json_schema
                        )
                    else:
                        return await self._complete_gemini(
                            system_prompt, user_prompt, max_tokens, temperature, json_schema
                        )
            except _RateLimitSignal as exc:
                last_error = exc
                if attempt >= self._MAX_RATE_LIMIT_RETRIES:
                    break
                logger.warning(
                    "Rate limited by %s (attempt %d/%d) — backing off %.1fs before retrying.",
                    self._provider,
                    attempt + 1,
                    self._MAX_RATE_LIMIT_RETRIES,
                    delay,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._BACKOFF_MAX_SECONDS)

        raise LLMRateLimitError(
            f"{self._provider} rate limit exceeded after {self._MAX_RATE_LIMIT_RETRIES} retries: {last_error}"
        ) from last_error

    async def _complete_anthropic(
        self, system_prompt: str, user_prompt: str, max_tokens: int, temperature: float
    ) -> CompletionResult:
        import anthropic

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except anthropic.RateLimitError as exc:
            raise _RateLimitSignal(str(exc)) from exc
        except anthropic.APITimeoutError as exc:
            raise LLMProviderError("LLM provider timed out.") from exc
        except anthropic.APIError as exc:
            logger.error("LLM provider error: %s", exc)
            raise LLMProviderError(f"LLM provider error: {exc}") from exc

        text_blocks = [block.text for block in response.content if block.type == "text"]
        if not text_blocks:
            raise LLMProviderError("LLM provider returned no text content.")

        return CompletionResult(
            text="".join(text_blocks),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=self._model,
        )

    async def _complete_groq(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
        json_schema: dict[str, Any] | None,
    ) -> CompletionResult:
        """
        Groq's OpenAI-compatible endpoint. Two things worth knowing if you
        change the model:

        1. Schema-ENFORCED structured output (`strict: true`, guaranteed
           schema-conformant) is currently only supported on Groq's
           `openai/gpt-oss-20b` / `openai/gpt-oss-120b` models — NOT on
           `llama-3.3-70b-versatile`, despite that being the more commonly
           recommended general-purpose Groq model. This is why LLM_MODEL
           defaults to `openai/gpt-oss-120b` in .env.example for this
           provider: our batched Verify call leans on schema enforcement
           for reliability, not just prompt instructions. If you switch to
           a model without structured-output support, this code still
           works (see the try/except below) — it just falls back to
           unenforced JSON, which is closer to the Anthropic path.
        2. OpenAI-style structured output requires the schema's ROOT to be
           an "object", not an "array" — unlike Gemini's response_schema,
           which accepts either. verify.py's batch schema is array-shaped
           (a list of verdict objects), so it's transparently wrapped in
           `{"verdicts": [...]}` for the API call and unwrapped again
           before being handed back as plain text — callers never see this
           wrapping, they always get back the same array-shaped JSON text
           regardless of provider.
        """
        from openai import APIError, APIStatusError, APITimeoutError, RateLimitError

        response_format: dict[str, Any] | None = None
        wrapped_array = json_schema is not None and json_schema.get("type") == "array"
        if json_schema is not None:
            # additionalProperties: false is required on EVERY object node for
            # Groq/OpenAI-style strict mode, not just the innermost one — this
            # wrapper object needs it too, or Groq rejects the whole request
            # with a 400 before even attempting generation (confirmed live:
            # this exact omission was silently doubling call volume, since
            # every batch fell through to the unenforced-JSON fallback).
            schema_for_api = (
                {
                    "type": "object",
                    "properties": {"verdicts": json_schema},
                    "required": ["verdicts"],
                    "additionalProperties": False,
                }
                if wrapped_array
                else json_schema
            )
            response_format = {
                "type": "json_schema",
                "json_schema": {"name": "response", "strict": True, "schema": schema_for_api},
            }

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                response_format=response_format,
                timeout=self._timeout,
            )
        except RateLimitError as exc:
            raise _RateLimitSignal(str(exc)) from exc
        except APITimeoutError as exc:
            raise LLMProviderError("Groq provider timed out.") from exc
        except APIStatusError as exc:
            if exc.status_code == 400 and response_format is not None:
                # Most likely cause: the configured model doesn't support
                # strict json_schema mode (see docstring above). Retry once,
                # this call only, with plain JSON object mode instead of
                # failing outright — the caller's own prompt already asks
                # for JSON, so this degrades gracefully rather than crashing.
                logger.warning(
                    "Groq rejected strict json_schema (model may not support it); "
                    "retrying this call with plain prompt-instructed JSON instead: %s", exc,
                )
                return await self._complete_groq_plain_json_fallback(messages, max_tokens, temperature)
            raise LLMProviderError(f"Groq API error ({exc.status_code}): {exc}") from exc
        except APIError as exc:
            raise LLMProviderError(f"Groq API error: {exc}") from exc

        choice = response.choices[0] if response.choices else None
        text = choice.message.content if choice and choice.message else None
        if not text:
            finish_reason = choice.finish_reason if choice else None
            raise LLMProviderError(f"Groq provider returned no text content (finish_reason={finish_reason}).")

        if wrapped_array:
            text = _unwrap_array_field(text, key="verdicts")

        usage = response.usage
        return CompletionResult(
            text=text,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            model=self._model,
        )

    async def _complete_groq_plain_json_fallback(
        self, messages: list[dict[str, str]], max_tokens: int, temperature: float
    ) -> CompletionResult:
        """
        Used only when strict json_schema mode is rejected outright by the
        configured model (see _complete_groq). Deliberately does NOT set
        response_format at all — not even json_object mode — because that
        mode's own top-level-must-be-an-object constraint would conflict
        with prompts (like the batch Verify prompt) that explicitly ask for
        a top-level JSON ARRAY. This falls back to exactly the same
        prompt-only JSON reliance the Anthropic branch already uses, which
        is safe because callers (verify.py, plan.py) already retry once and
        degrade to "unclear" on a parse failure — this isn't a new risk,
        just the same one Anthropic already lives with.
        """
        from openai import APIError, APITimeoutError, RateLimitError

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=self._timeout,
            )
        except RateLimitError as exc:
            raise _RateLimitSignal(str(exc)) from exc
        except APITimeoutError as exc:
            raise LLMProviderError("Groq provider timed out.") from exc
        except APIError as exc:
            raise LLMProviderError(f"Groq API error: {exc}") from exc

        choice = response.choices[0] if response.choices else None
        text = choice.message.content if choice and choice.message else None
        if not text:
            raise LLMProviderError("Groq provider returned no text content (plain JSON fallback).")

        usage = response.usage
        return CompletionResult(
            text=text,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            model=self._model,
        )

    async def _complete_gemini(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
        json_schema: dict[str, Any] | None,
    ) -> CompletionResult:
        from google.genai import types
        from google.genai.errors import APIError, ClientError, ServerError

        config_kwargs: dict[str, Any] = {
            "system_instruction": system_prompt,
            "temperature": temperature,
            "max_output_tokens": max_tokens,
            # Gemini 2.5 Flash "thinks" before answering by default, and
            # those thinking tokens count against max_output_tokens — which
            # silently truncates the actual JSON response before it's
            # finished, especially with response_schema (a widely reported
            # upstream issue: thoughts_token_count can exceed the requested
            # budget even with thinking_budget=0). This task needs fast,
            # deterministic extraction/verdicts, not step-by-step reasoning,
            # so we explicitly ask for zero thinking budget. This is NOT
            # 100% reliably honored by the API, which is why max_output_tokens
            # is also given generous headroom below rather than relying on
            # this alone.
            "thinking_config": types.ThinkingConfig(thinking_budget=0),
        }
        if json_schema is not None:
            config_kwargs["response_mime_type"] = "application/json"
            config_kwargs["response_schema"] = _sanitize_gemini_schema(json_schema)

        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=user_prompt,
                config=types.GenerateContentConfig(**config_kwargs),
            )
        except ClientError as exc:
            if exc.code == 429:
                raise _RateLimitSignal(f"{exc.status}: {exc.message}") from exc
            raise LLMProviderError(f"Gemini client error ({exc.code} {exc.status}): {exc.message}") from exc
        except ServerError as exc:
            # 5xx from Gemini is transient, same as a rate limit from the
            # caller's point of view — worth a backed-off retry, not a
            # straight failure.
            raise _RateLimitSignal(f"{exc.status}: {exc.message}") from exc
        except APIError as exc:
            raise LLMProviderError(f"Gemini API error ({exc.code}): {exc.message}") from exc
        except asyncio.TimeoutError as exc:
            raise LLMProviderError("Gemini provider timed out.") from exc

        text = getattr(response, "text", None)
        if not text:
            finish_reason = _get_finish_reason(response)
            if finish_reason and "MAX_TOKENS" in str(finish_reason):
                raise LLMProviderError(
                    "Gemini response was truncated (hit max_output_tokens, likely due to internal "
                    "'thinking' tokens eating the budget) before any usable text was produced. "
                    "Consider raising max_tokens for this call."
                )
            raise LLMProviderError(f"Gemini provider returned no text content (finish_reason={finish_reason}).")

        usage = getattr(response, "usage_metadata", None)
        input_tokens = getattr(usage, "prompt_token_count", 0) or 0
        output_tokens = getattr(usage, "candidates_token_count", 0) or 0

        return CompletionResult(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=self._model,
        )


class _RateLimitSignal(Exception):
    """Internal-only: signals `complete()`'s retry loop to back off and retry. Never escapes this module."""
