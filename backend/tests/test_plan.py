"""
Unit tests for app.pipeline.plan.

Uses a fake LLM adapter so these run offline, deterministically, with no
API key and no network access — appropriate for CI on every pull request.
"""

import json

import pytest

from app.adapters.llm import CompletionResult, LLMProviderError
from app.pipeline.plan import plan_patient_profile


class FakeLLM:
    """Duck-types LLMAdapter.complete(); returns queued responses in order."""

    def __init__(self, responses: list[str] | None = None, raise_error: bool = False):
        self._responses = responses or []
        self._raise_error = raise_error
        self.calls: list[str] = []

    async def complete(self, system_prompt: str, user_prompt: str, max_tokens: int = 1024, temperature: float = 0.0):
        self.calls.append(user_prompt)
        if self._raise_error:
            raise LLMProviderError("simulated provider failure")
        text = self._responses[len(self.calls) - 1]
        return CompletionResult(text=text, input_tokens=100, output_tokens=50, model="fake-model")


@pytest.mark.asyncio
async def test_confident_extraction_returns_structured_query():
    response = json.dumps({
        "condition": "esophageal squamous cell carcinoma",
        "stage": "Stage III",
        "prior_therapy": ["neoadjuvant chemoradiation"],
        "biomarkers": [],
        "exclusions": ["distant metastasis"],
        "age": 64,
        "sex": "female",
        "status_filter": "RECRUITING",
    })
    llm = FakeLLM(responses=[response])

    result = await plan_patient_profile(
        "64-year-old female, Stage III esophageal squamous cell carcinoma, "
        "completed neoadjuvant chemoradiation, no distant metastasis",
        llm=llm,
    )

    assert not result.needs_clarification
    assert result.structured_query.condition == "esophageal squamous cell carcinoma"
    assert result.structured_query.stage == "Stage III"
    assert "neoadjuvant chemoradiation" in result.structured_query.prior_therapy
    assert len(llm.calls) == 1  # no retry needed


@pytest.mark.asyncio
async def test_model_requests_clarification_directly():
    response = json.dumps({"clarifying_question": "What is the patient's primary diagnosis?"})
    llm = FakeLLM(responses=[response])

    result = await plan_patient_profile("65-year-old patient, recently diagnosed, seeking options", llm=llm)

    assert result.needs_clarification
    assert result.structured_query is None
    assert "diagnosis" in result.clarifying_question.lower()


@pytest.mark.asyncio
async def test_malformed_json_retries_then_falls_back_to_clarification():
    llm = FakeLLM(responses=["not valid json at all", "still not json"])

    result = await plan_patient_profile("some vague profile", llm=llm)

    assert result.needs_clarification
    assert len(llm.calls) == 2  # confirms the retry actually happened


@pytest.mark.asyncio
async def test_second_attempt_succeeds_after_first_malformed_response():
    good_response = json.dumps({
        "condition": "non-small cell lung cancer",
        "stage": None,
        "prior_therapy": [],
        "biomarkers": [],
        "exclusions": [],
        "age": None,
        "sex": None,
        "status_filter": "RECRUITING",
    })
    llm = FakeLLM(responses=["```json\nnot actually valid```", good_response])

    result = await plan_patient_profile("patient with lung cancer", llm=llm)

    assert not result.needs_clarification
    assert result.structured_query.condition == "non-small cell lung cancer"
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_provider_error_degrades_to_clarification_not_exception():
    llm = FakeLLM(raise_error=True)

    result = await plan_patient_profile("any profile text", llm=llm)

    assert result.needs_clarification  # never raises — NFR: Reliability


@pytest.mark.asyncio
async def test_empty_profile_short_circuits_without_calling_llm():
    llm = FakeLLM(responses=["should never be used"])

    result = await plan_patient_profile("   ", llm=llm)

    assert result.needs_clarification
    assert len(llm.calls) == 0


@pytest.mark.asyncio
async def test_markdown_fenced_json_is_parsed():
    response = "```json\n" + json.dumps({
        "condition": "breast cancer",
        "stage": "II",
        "prior_therapy": [],
        "biomarkers": ["HER2-positive"],
        "exclusions": [],
        "age": 50,
        "sex": "female",
        "status_filter": "RECRUITING",
    }) + "\n```"
    llm = FakeLLM(responses=[response])

    result = await plan_patient_profile("50yo female, Stage II HER2-positive breast cancer", llm=llm)

    assert not result.needs_clarification
    assert result.structured_query.condition == "breast cancer"
    assert "HER2-positive" in result.structured_query.biomarkers
