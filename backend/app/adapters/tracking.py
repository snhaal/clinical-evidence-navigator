"""
Wraps LLMAdapter to record per-call latency and token usage.

Used by two callers: the eval harness (evals/run_eval.py, for aggregate
p50/p95 latency and total token cost across a run) and the /match route
(app/api/routes.py, to populate match_runs.latency_ms / token_cost per
trial — see the Observability NFR: "every run logs its plan, retrieved
trial IDs, per-criterion verdicts, latency, and token cost"). Kept out of
the pipeline stages themselves so Plan/Verify stay unaware of who's
counting their tokens.
"""

import time
from dataclasses import dataclass, field

from app.adapters.llm import CompletionResult, LLMAdapter


@dataclass
class CallRecord:
    latency_ms: float
    input_tokens: int
    output_tokens: int


@dataclass
class TrackingLLMAdapter:
    """
    Duck-types LLMAdapter.complete() so it can be passed anywhere a
    pipeline stage accepts an `llm` argument (plan_patient_profile,
    verify_criterion, verify_all_criteria all accept any object with a
    matching complete() coroutine).
    """

    inner: LLMAdapter = field(default_factory=LLMAdapter)
    calls: list[CallRecord] = field(default_factory=list)

    async def complete(self, *args, **kwargs) -> CompletionResult:
        start = time.monotonic()
        result = await self.inner.complete(*args, **kwargs)
        elapsed_ms = (time.monotonic() - start) * 1000
        self.calls.append(
            CallRecord(latency_ms=elapsed_ms, input_tokens=result.input_tokens, output_tokens=result.output_tokens)
        )
        return result

    @property
    def total_tokens(self) -> int:
        return sum(c.input_tokens + c.output_tokens for c in self.calls)

    @property
    def latencies_ms(self) -> list[float]:
        return [c.latency_ms for c in self.calls]
