"""
Unit tests for app.pipeline.verify.

Covers the batched-by-trial design: one LLM call judges every criterion
for a trial at once. The core guardrail under test is unchanged from the
original per-criterion design: a citation that is not an exact substring
of the criterion's source text must NEVER be trusted or displayed — the
verdict gets downgraded to "unclear" instead. New coverage: a batch
response that's missing an item gets that one criterion individually
repaired rather than the whole batch being discarded, and a batch that
fails entirely degrades to "unclear" for everything without raising.
"""

import json

import pytest

from app.adapters.llm import CompletionResult, LLMProviderError
from app.pipeline.schemas import TrialCriterion
from app.pipeline.verify import verify_all_criteria, verify_criterion


class FakeLLM:
    def __init__(self, responses: list[str] | None = None, raise_error: bool = False):
        self._responses = responses or []
        self._raise_error = raise_error
        self.calls: list[str] = []

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        json_schema: dict | None = None,
    ):
        self.calls.append(user_prompt)
        if self._raise_error:
            raise LLMProviderError("simulated provider failure")
        text = self._responses[len(self.calls) - 1]
        return CompletionResult(
            text=text, input_tokens=50, output_tokens=20, model="fake-model"
        )


def make_criterion(
    text: str, criterion_type: str = "inclusion", index: int = 0, nct_id: str = "NCT001"
) -> TrialCriterion:
    return TrialCriterion(
        nct_id=nct_id,
        criterion_type=criterion_type,
        criterion_index=index,
        raw_text=text,
    )


# --- verify_all_criteria: the batched path -----------------------------------


@pytest.mark.asyncio
async def test_batch_makes_exactly_one_call_for_multiple_criteria():
    """The whole point of batching: N criteria -> 1 LLM call, not N."""
    criteria = [make_criterion(f"Criterion {i}", index=i) for i in range(5)]
    batch_response = json.dumps(
        [
            {
                "criterion_type": "inclusion",
                "criterion_index": i,
                "verdict": "match",
                "rationale": "ok",
                "cited_text": f"Criterion {i}",
            }
            for i in range(5)
        ]
    )
    llm = FakeLLM(responses=[batch_response])

    verdicts = await verify_all_criteria("some profile", criteria, llm=llm)

    assert len(llm.calls) == 1
    assert len(verdicts) == 5
    assert all(v.verdict == "match" for v in verdicts)


@pytest.mark.asyncio
async def test_batch_preserves_input_order_in_output():
    criteria = [
        make_criterion("First", index=0),
        make_criterion("Second", index=1),
        make_criterion("Third", index=2),
    ]
    # Response deliberately out of order.
    batch_response = json.dumps(
        [
            {
                "criterion_type": "inclusion",
                "criterion_index": 2,
                "verdict": "no_match",
                "rationale": "x",
                "cited_text": "Third",
            },
            {
                "criterion_type": "inclusion",
                "criterion_index": 0,
                "verdict": "match",
                "rationale": "x",
                "cited_text": "First",
            },
            {
                "criterion_type": "inclusion",
                "criterion_index": 1,
                "verdict": "unclear",
                "rationale": "x",
                "cited_text": "Second",
            },
        ]
    )
    llm = FakeLLM(responses=[batch_response])

    verdicts = await verify_all_criteria("profile", criteria, llm=llm)

    assert [v.criterion_index for v in verdicts] == [0, 1, 2]
    assert [v.verdict for v in verdicts] == ["match", "unclear", "no_match"]


@pytest.mark.asyncio
async def test_batch_citation_not_a_substring_downgrades_only_that_criterion():
    """Core guardrail, batched version: one bad citation doesn't poison the rest of the batch."""
    criteria = [
        make_criterion("Histologically confirmed breast cancer", index=0),
        make_criterion("Age 18 years or older", index=1),
    ]
    batch_response = json.dumps(
        [
            {
                "criterion_type": "inclusion",
                "criterion_index": 0,
                "verdict": "match",
                "rationale": "x",
                "cited_text": "confirmed diagnosis of lung cancer",
            },  # NOT a substring
            {
                "criterion_type": "inclusion",
                "criterion_index": 1,
                "verdict": "match",
                "rationale": "x",
                "cited_text": "Age 18 years or older",
            },  # valid
        ]
    )
    llm = FakeLLM(responses=[batch_response])

    verdicts = await verify_all_criteria("profile", criteria, llm=llm)

    bad, good = verdicts[0], verdicts[1]
    assert bad.verdict == "unclear"
    assert bad.citation_validated is False
    assert (
        bad.cited_text == criteria[0].raw_text
    )  # falls back to the full, trivially-valid text
    assert good.verdict == "match"
    assert good.citation_validated is True


@pytest.mark.asyncio
async def test_batch_missing_criterion_is_repaired_individually_not_marked_unclear_outright():
    """A batch response covering only some criteria triggers a targeted repair call for the rest."""
    criteria = [make_criterion("A", index=0), make_criterion("B", index=1)]
    # Batch response only covers criterion 0.
    batch_response = json.dumps(
        [
            {
                "criterion_type": "inclusion",
                "criterion_index": 0,
                "verdict": "match",
                "rationale": "x",
                "cited_text": "A",
            },
        ]
    )
    repair_response = json.dumps(
        {"verdict": "unclear", "rationale": "missing info", "cited_text": "B"}
    )
    llm = FakeLLM(responses=[batch_response, repair_response])

    verdicts = await verify_all_criteria("profile", criteria, llm=llm)

    assert len(llm.calls) == 2  # 1 batch call + 1 individual repair call
    assert verdicts[0].verdict == "match"
    assert verdicts[1].verdict == "unclear"
    assert verdicts[1].cited_text == "B"


@pytest.mark.asyncio
async def test_entire_batch_failure_falls_back_to_unclear_for_everything_without_repair_storm():
    """
    If the WHOLE batch fails both attempts, don't spend N more individual
    calls we already have reason to believe will also fail — just degrade
    everything to unclear. This matters specifically on a low-RPM budget.
    """
    criteria = [make_criterion(f"C{i}", index=i) for i in range(4)]
    llm = FakeLLM(raise_error=True)

    verdicts = await verify_all_criteria("profile", criteria, llm=llm)

    assert (
        len(llm.calls) == 2
    )  # exactly 2 batch attempts, no per-criterion repair calls
    assert all(v.verdict == "unclear" for v in verdicts)
    assert all(v.citation_validated is False for v in verdicts)


@pytest.mark.asyncio
async def test_malformed_batch_json_retries_once_then_repairs_or_falls_back():
    criteria = [make_criterion("A", index=0)]
    llm = FakeLLM(responses=["not json at all", "still not json"])

    verdicts = await verify_all_criteria("profile", criteria, llm=llm)

    assert len(verdicts) == 1
    assert verdicts[0].verdict == "unclear"


@pytest.mark.asyncio
async def test_empty_criteria_list_returns_empty_without_calling_llm():
    llm = FakeLLM()
    verdicts = await verify_all_criteria("profile", [], llm=llm)
    assert verdicts == []
    assert llm.calls == []


@pytest.mark.asyncio
async def test_batch_ignores_items_referencing_unknown_criteria():
    """A response item that doesn't match any known (type, index) is ignored, not crashed on."""
    criteria = [make_criterion("A", index=0)]
    batch_response = json.dumps(
        [
            {
                "criterion_type": "inclusion",
                "criterion_index": 0,
                "verdict": "match",
                "rationale": "x",
                "cited_text": "A",
            },
            {
                "criterion_type": "exclusion",
                "criterion_index": 99,
                "verdict": "match",
                "rationale": "x",
                "cited_text": "ghost",
            },
        ]
    )
    llm = FakeLLM(responses=[batch_response])

    verdicts = await verify_all_criteria("profile", criteria, llm=llm)

    assert len(verdicts) == 1
    assert verdicts[0].verdict == "match"


@pytest.mark.asyncio
async def test_exclusion_match_verdict_is_trusted_with_valid_citation():
    criteria = [
        make_criterion("No prior immunotherapy", criterion_type="exclusion", index=0)
    ]
    batch_response = json.dumps(
        [
            {
                "criterion_type": "exclusion",
                "criterion_index": 0,
                "verdict": "match",
                "rationale": "Patient received prior immunotherapy.",
                "cited_text": "No prior immunotherapy",
            },
        ]
    )
    llm = FakeLLM(responses=[batch_response])

    verdicts = await verify_all_criteria(
        "Patient previously received immunotherapy", criteria, llm=llm
    )

    assert verdicts[0].verdict == "match"
    assert verdicts[0].criterion_type == "exclusion"


# --- verify_criterion: the single-criterion path (still used for repairs) ---


@pytest.mark.asyncio
async def test_single_criterion_valid_match_is_trusted():
    criterion = make_criterion("Age 18 years or older")
    response = json.dumps(
        {
            "verdict": "match",
            "rationale": "64yo satisfies this.",
            "cited_text": "Age 18 years or older",
        }
    )
    llm = FakeLLM(responses=[response])

    verdict = await verify_criterion("64-year-old patient", criterion, llm=llm)

    assert verdict.verdict == "match"
    assert verdict.citation_validated is True


@pytest.mark.asyncio
async def test_single_criterion_malformed_json_retries_then_falls_back():
    llm = FakeLLM(responses=["not json", "still not json"])
    criterion = make_criterion("Some criterion")

    verdict = await verify_criterion("some profile", criterion, llm=llm)

    assert verdict.verdict == "unclear"
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_single_criterion_provider_error_degrades_to_unclear():
    llm = FakeLLM(raise_error=True)
    criterion = make_criterion("Some criterion")

    verdict = await verify_criterion("some profile", criterion, llm=llm)

    assert verdict.verdict == "unclear"
    assert verdict.citation_validated is False


# --- Token-budget sizing (the truncation fix) --------------------------------


def test_batch_max_output_tokens_scales_with_criteria_count():
    from app.pipeline.verify import _batch_max_output_tokens

    small = _batch_max_output_tokens(2, attempt=0)
    large = _batch_max_output_tokens(20, attempt=0)
    assert small < large


def test_batch_max_output_tokens_respects_floor():
    from app.pipeline.verify import _batch_max_output_tokens

    assert _batch_max_output_tokens(1, attempt=0) >= 600


def test_batch_max_output_tokens_respects_ceiling():
    from app.pipeline.verify import _batch_max_output_tokens

    assert _batch_max_output_tokens(1000, attempt=0) <= 1500


def test_batch_max_output_tokens_retry_gets_more_room_than_first_attempt():
    from app.pipeline.verify import _batch_max_output_tokens

    first = _batch_max_output_tokens(5, attempt=0)
    retry = _batch_max_output_tokens(5, attempt=1)
    assert retry > first


@pytest.mark.asyncio
async def test_batch_chunks_criteria_into_groups_of_five(monkeypatch):
    """Criteria count > 5 is chunked into sequential batches of at most 5."""
    sleep_calls = []

    async def fake_sleep(duration):
        sleep_calls.append(duration)

    monkeypatch.setattr("app.pipeline.verify.asyncio.sleep", fake_sleep)

    criteria = [make_criterion(f"Criterion {i}", index=i) for i in range(12)]
    # 12 criteria -> 3 chunks: [0..4], [5..9], [10..11]
    chunk_1 = json.dumps(
        [
            {
                "criterion_type": "inclusion",
                "criterion_index": i,
                "verdict": "match",
                "rationale": "ok",
                "cited_text": f"Criterion {i}",
            }
            for i in range(5)
        ]
    )
    chunk_2 = json.dumps(
        [
            {
                "criterion_type": "inclusion",
                "criterion_index": i,
                "verdict": "no_match",
                "rationale": "ok",
                "cited_text": f"Criterion {i}",
            }
            for i in range(5, 10)
        ]
    )
    chunk_3 = json.dumps(
        [
            {
                "criterion_type": "inclusion",
                "criterion_index": i,
                "verdict": "unclear",
                "rationale": "ok",
                "cited_text": f"Criterion {i}",
            }
            for i in range(10, 12)
        ]
    )
    llm = FakeLLM(responses=[chunk_1, chunk_2, chunk_3])

    verdicts = await verify_all_criteria("some profile", criteria, llm=llm)

    assert len(llm.calls) == 3
    assert len(verdicts) == 12
    assert [v.criterion_index for v in verdicts] == list(range(12))
    assert [v.verdict for v in verdicts[:5]] == ["match"] * 5
    assert [v.verdict for v in verdicts[5:10]] == ["no_match"] * 5
    assert [v.verdict for v in verdicts[10:12]] == ["unclear"] * 2
    # 2 sleep calls of 2.0s between the 3 chunks
    assert sleep_calls == [2.0, 2.0]

