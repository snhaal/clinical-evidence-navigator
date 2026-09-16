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
import re
from dataclasses import dataclass
from typing import Any

from app.adapters.rate_limiter import get_llm_rate_limiter
from app.config import get_settings

logger = logging.getLogger(__name__)
# Limit simultaneous in-flight requests to Groq to prevent instant burst 429s
_RATE_SEMAPHORE = asyncio.Semaphore(2)
_GLOBAL_OUTBOUND_CALL_COUNT = 0


def get_outbound_call_count() -> int:
    return _GLOBAL_OUTBOUND_CALL_COUNT


def reset_outbound_call_count() -> None:
    global _GLOBAL_OUTBOUND_CALL_COUNT
    _GLOBAL_OUTBOUND_CALL_COUNT = 0




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
        raise LLMProviderError(
            f"Groq response did not match the expected wrapped-array shape: {exc}"
        ) from exc


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
    _BACKOFF_INITIAL_SECONDS = 8.0
    _BACKOFF_MAX_SECONDS = 32.0

    def __init__(self) -> None:
        settings = get_settings()
        self._provider = settings.llm_provider
        self._model = settings.llm_model
        self._timeout = settings.request_timeout_seconds
        self._rate_limiter = get_llm_rate_limiter()

        if self._provider == "anthropic":
            import anthropic

            self._client = anthropic.AsyncAnthropic(
                api_key=settings.llm_provider_api_key
            )
        elif self._provider == "gemini":
            from google import genai

            api_key = settings.gemini_api_key or settings.llm_provider_api_key
            self._client = genai.Client(api_key=api_key)
        elif self._provider == "groq":
            from openai import AsyncOpenAI

            api_key = settings.groq_api_key or settings.llm_provider_api_key
            self._client = AsyncOpenAI(
                api_key=api_key,
                base_url="https://api.groq.com/openai/v1",
            )
        else:
            raise NotImplementedError(
                f"LLM provider '{self._provider}' is not wired up. Supported: 'anthropic', 'gemini', 'groq'."
            )

        # Optional Groq fallback client for transient 429/503 under Gemini
        self._groq_client = None
        self._groq_model = "openai/gpt-oss-120b"
        groq_key = settings.groq_api_key or (
            settings.llm_provider_api_key if settings.llm_provider == "groq" else None
        )
        if not groq_key:
            import os

            groq_key = os.environ.get("GROQ_API_KEY")
        if groq_key and self._provider != "groq":
            try:
                from openai import AsyncOpenAI

                self._groq_client = AsyncOpenAI(
                    api_key=groq_key,
                    base_url="https://api.groq.com/openai/v1",
                )
            except Exception as e:
                logger.warning("Could not initialize optional Groq fallback client: %s", e)

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
                    global _GLOBAL_OUTBOUND_CALL_COUNT
                    _GLOBAL_OUTBOUND_CALL_COUNT += 1
                    logger.info(
                        "[Outbound LLM Call #%d] provider=%s model=%s (attempt=%d)",
                        _GLOBAL_OUTBOUND_CALL_COUNT,
                        self._provider,
                        self._model,
                        attempt + 1,
                    )
                    await asyncio.sleep(0.2)

                    if self._provider == "anthropic":
                        return await self._complete_anthropic(
                            system_prompt, user_prompt, max_tokens, temperature
                        )
                    elif self._provider == "groq":
                        return await self._complete_groq(
                            system_prompt,
                            user_prompt,
                            max_tokens,
                            temperature,
                            json_schema,
                        )
                    else:
                        try:
                            return await self._complete_gemini(
                                system_prompt,
                                user_prompt,
                                max_tokens,
                                temperature,
                                json_schema,
                            )
                        except _RateLimitSignal as exc:
                            if self._groq_client is not None:
                                logger.warning(
                                    "Gemini rate limited or unavailable (%s); attempting fallback to Groq (%s)...",
                                    exc,
                                    self._groq_model,
                                )
                                try:
                                    return await self._complete_groq(
                                        system_prompt,
                                        user_prompt,
                                        min(max_tokens, 2200),
                                        temperature,
                                        json_schema,
                                        client=self._groq_client,
                                        model=self._groq_model,
                                    )
                                except Exception as fallback_exc:
                                    logger.warning(
                                        "Groq fallback also failed: %s; proceeding with backoff retry on Gemini.",
                                        fallback_exc,
                                    )
                            raise
            except _RateLimitSignal as exc:
                last_error = exc
                if attempt >= self._MAX_RATE_LIMIT_RETRIES:
                    break

                header_wait = _parse_retry_after(exc)
                if header_wait is not None and header_wait >= 1.0:
                    wait_seconds = header_wait + 0.5
                    logger.warning(
                        "Rate limited by %s (attempt %d/%d) — provider specified wait of %.2fs (+0.5s margin) = %.2fs before retrying.",
                        self._provider,
                        attempt + 1,
                        self._MAX_RATE_LIMIT_RETRIES,
                        header_wait,
                        wait_seconds,
                    )
                else:
                    wait_seconds = delay
                    logger.warning(
                        "Rate limited by %s (attempt %d/%d) — backing off %.1fs before retrying.",
                        self._provider,
                        attempt + 1,
                        self._MAX_RATE_LIMIT_RETRIES,
                        wait_seconds,
                    )
                    delay = min(delay * 2, self._BACKOFF_MAX_SECONDS)

                await asyncio.sleep(wait_seconds)

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
            raise _RateLimitSignal(str(exc), original_exc=exc) from exc
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
        client: Any = None,
        model: str | None = None,
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

        groq_client = client or self._client
        groq_model = model or self._model

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
                "json_schema": {
                    "name": "response",
                    "strict": True,
                    "schema": schema_for_api,
                },
            }

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # Rate pacing for Groq's rolling 8,000 TPM limit
        await asyncio.sleep(3.0)

        try:
            response = await groq_client.chat.completions.create(
                model=groq_model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                response_format=response_format,
                timeout=self._timeout,
            )
        except RateLimitError as exc:
            raise _RateLimitSignal(str(exc), original_exc=exc) from exc
        except APITimeoutError as exc:
            raise LLMProviderError("Groq provider timed out.") from exc
        except APIStatusError as exc:
            if (
                exc.status_code == 400
                and response_format is not None
                and "max completion tokens" not in str(exc).lower()
            ):
                # Most likely cause: the configured model doesn't support
                # strict json_schema mode (see docstring above). Retry once,
                # this call only, with plain JSON object mode instead of
                # failing outright — the caller's own prompt already asks
                # for JSON, so this degrades gracefully rather than crashing.
                logger.warning(
                    "Groq rejected strict json_schema (model may not support it); "
                    "retrying this call with plain prompt-instructed JSON instead: %s",
                    exc,
                )
                return await self._complete_groq_plain_json_fallback(
                    messages,
                    max_tokens,
                    temperature,
                    client=groq_client,
                    model=groq_model,
                )
            raise LLMProviderError(
                f"Groq API error ({exc.status_code}): {exc}"
            ) from exc

        except APIError as exc:
            raise LLMProviderError(f"Groq API error: {exc}") from exc

        choice = response.choices[0] if response.choices else None
        text = None
        if choice and choice.message:
            text = choice.message.content or getattr(
                choice.message, "reasoning_content", None
            )

        if text:
            match = re.search(r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```", text, re.DOTALL)
            text = match.group(1).strip() if match else text.strip()

        if not text:
            finish_reason = choice.finish_reason if choice else None
            raise LLMProviderError(
                f"Groq provider returned no text content (finish_reason={finish_reason})."
            )

        if wrapped_array:
            text = _unwrap_array_field(text, key="verdicts")

        usage = response.usage
        return CompletionResult(
            text=text,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            model=groq_model,
        )

    async def _complete_groq_plain_json_fallback(
        self,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
        client: Any = None,
        model: str | None = None,
    ) -> CompletionResult:
        """
        Used only when strict json_schema mode is rejected outright by the
        configured model (see _complete_groq). Enforces json_object mode,
        ensures 'JSON' is in the prompt, checks both content and reasoning_content,
        and strips markdown fences.
        """
        from openai import APIError, APITimeoutError, RateLimitError

        groq_client = client or self._client
        groq_model = model or self._model

        # Rate pacing for Groq's rolling 8,000 TPM limit
        await asyncio.sleep(3.0)

        # Ensure system or user prompt explicitly contains the word "JSON"
        # (required by Groq when using json_object mode).
        formatted_messages = [dict(m) for m in messages]
        has_json = any(
            "json" in (m.get("content") or "").lower() for m in formatted_messages
        )
        if not has_json and formatted_messages:
            formatted_messages[0]["content"] = (
                formatted_messages[0].get("content") or ""
            ) + "\n\nRespond with valid JSON."

        is_array_prompt = any(
            "json array" in (m.get("content") or "").lower() for m in formatted_messages
        )
        if is_array_prompt and formatted_messages:
            formatted_messages[0]["content"] = (
                formatted_messages[0].get("content") or ""
            ) + "\n\nImportant: Return a JSON object containing a 'verdicts' key with the list: {\"verdicts\": [...]}. Must be valid JSON."

        try:
            response = await groq_client.chat.completions.create(
                model=groq_model,
                messages=formatted_messages,
                max_tokens=max_tokens,
                temperature=temperature,
                response_format={"type": "json_object"},
                timeout=self._timeout,
            )
        except RateLimitError as exc:
            raise _RateLimitSignal(str(exc), original_exc=exc) from exc
        except APITimeoutError as exc:
            raise LLMProviderError("Groq provider timed out.") from exc
        except APIError as exc:
            raise LLMProviderError(f"Groq API error: {exc}") from exc

        choice = response.choices[0] if response.choices else None
        text = None
        if choice and choice.message:
            text = choice.message.content or getattr(
                choice.message, "reasoning_content", None
            )

        if text:
            # Strip markdown code fences (```json ... ```) so text content is never flagged as empty
            match = re.search(r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```", text, re.DOTALL)
            text = match.group(1).strip() if match else text.strip()
            if is_array_prompt and text.startswith("{"):
                text = _unwrap_array_field(text, key="verdicts")

        if not text:
            finish_reason = choice.finish_reason if choice else None
            raise LLMProviderError(
                f"Groq provider returned no text content (plain JSON fallback, finish_reason={finish_reason})."
            )

        usage = response.usage
        return CompletionResult(
            text=text,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            model=groq_model,
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
                raise _RateLimitSignal(
                    f"{exc.status}: {exc.message}", original_exc=exc
                ) from exc
            raise LLMProviderError(
                f"Gemini client error ({exc.code} {exc.status}): {exc.message}"
            ) from exc
        except ServerError as exc:
            # 5xx from Gemini is transient, same as a rate limit from the
            # caller's point of view — worth a backed-off retry, not a
            # straight failure.
            raise _RateLimitSignal(
                f"{exc.status}: {exc.message}", original_exc=exc
            ) from exc
        except APIError as exc:
            raise LLMProviderError(
                f"Gemini API error ({exc.code}): {exc.message}"
            ) from exc
        except asyncio.TimeoutError as exc:
            raise LLMProviderError("Gemini provider timed out.") from exc

        text = getattr(response, "text", None)
        if text:
            match = re.search(r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```", text, re.DOTALL)
            text = match.group(1).strip() if match else text.strip()

        if not text:
            finish_reason = _get_finish_reason(response)
            if finish_reason and "MAX_TOKENS" in str(finish_reason):
                raise LLMProviderError(
                    "Gemini response was truncated (hit max_output_tokens) before any usable text was produced. "
                    "Consider raising max_tokens for this call."
                )
            raise LLMProviderError(
                f"Gemini provider returned no text content (finish_reason={finish_reason})."
            )

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

    def __init__(self, message: str, original_exc: Exception | None = None) -> None:
        super().__init__(message)
        self.original_exc = original_exc


def _parse_duration_str(val: Any) -> float | None:
    if not val:
        return None
    s = str(val).strip().lower()
    try:
        return float(s)
    except ValueError:
        pass
    match = re.match(r"^([\d\.]+)\s*(ms|s)?$", s)
    if match:
        amount = float(match.group(1))
        unit = match.group(2) or "s"
        if unit == "ms":
            return amount / 1000.0
        return amount
    return None


def _parse_retry_after(exc: Exception) -> float | None:
    """
    Extracts the recommended wait duration in seconds from rate-limit response headers
    (`retry-after` or `x-ratelimit-reset-tokens`). Returns None if unparseable or excessive.
    """
    candidates = [exc]
    if isinstance(exc, _RateLimitSignal) and getattr(exc, "original_exc", None):
        candidates.append(exc.original_exc)
    cause = getattr(exc, "__cause__", None)
    if cause:
        candidates.append(cause)

    for cand in candidates:
        # Check HTTP response headers for retry-after or x-ratelimit-reset-tokens
        resp = getattr(cand, "response", None)
        if resp is not None:
            headers = getattr(resp, "headers", None) or {}
            # 1. x-ratelimit-reset-tokens (e.g. "3.57s" or "250ms")
            reset_tokens = headers.get("x-ratelimit-reset-tokens")
            val = _parse_duration_str(reset_tokens)
            if val is not None and 0 < val <= 30.0:
                return val

            # 2. retry-after (e.g. "4")
            retry_after = headers.get("retry-after")
            val = _parse_duration_str(retry_after)
            if val is not None and 0 < val <= 30.0:
                return val

        # Check error message text for "try again in X.Xs"
        msg = str(cand)
        match = re.search(r"try again in ([\d\.]+)\s*(s|ms)", msg, re.IGNORECASE)
        if match:
            amount = float(match.group(1))
            unit = match.group(2).lower()
            val = amount / 1000.0 if unit == "ms" else amount
            if 0 < val <= 30.0:
                return val

    return None
