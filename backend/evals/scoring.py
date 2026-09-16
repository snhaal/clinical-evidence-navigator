"""
Pure scoring logic for the gold evaluation set. Deliberately has zero
dependency on the LLM adapter or the database — every function here takes
plain data in and returns a plain number/dict out, so the metric
definitions themselves can be unit-tested without an API key or network
access. Orchestration (running the real pipeline against gold cases) is
run_eval.py's job, not this module's.
"""

import statistics
from dataclasses import dataclass


@dataclass
class CriterionComparison:
    """One (predicted, gold) pair for a single criterion, plus enough
    context to check citation validity independently of the pipeline."""

    nct_id: str
    criterion_type: str
    criterion_index: int
    predicted_verdict: str
    expected_verdict: str
    cited_text: str
    criterion_raw_text: str


def agreement_rate(comparisons: list[CriterionComparison]) -> float | None:
    """Criterion agreement rate: predicted verdict matches the gold label."""
    if not comparisons:
        return None
    matches = sum(1 for c in comparisons if c.predicted_verdict == c.expected_verdict)
    return matches / len(comparisons)


def false_match_rate(comparisons: list[CriterionComparison]) -> float | None:
    """
    False-match rate: of all criteria the gold label says are a genuine
    "no_match", what fraction did the model wrongly call "match"?
    This is the single most important number per the project plan —
    returns None (not 0.0) when there are no gold no_match cases to
    measure against, so a report never silently implies a perfect score
    on an empty denominator.
    """
    no_match_gold = [c for c in comparisons if c.expected_verdict == "no_match"]
    if not no_match_gold:
        return None
    false_matches = sum(1 for c in no_match_gold if c.predicted_verdict == "match")
    return false_matches / len(no_match_gold)


def abstention_stats(comparisons: list[CriterionComparison]) -> dict:
    """
    Abstention precision proper requires a human to judge whether
    information was "genuinely missing" for each case the model abstained
    on — that's not automatable from labels alone. What IS automatable,
    and reported here as an explicit proxy, is: of the criteria the model
    called "unclear", how many does the gold label also call "unclear"?
    A low proxy score means the model is abstaining on criteria the gold
    set considers answerable — worth a manual look, not a final verdict.
    """
    predicted_unclear = [c for c in comparisons if c.predicted_verdict == "unclear"]
    if not predicted_unclear:
        return {
            "predicted_unclear_count": 0,
            "agreed_unclear_count": 0,
            "unnecessary_abstention_count": 0,
            "proxy_precision": None,
        }
    agreed = sum(1 for c in predicted_unclear if c.expected_verdict == "unclear")
    return {
        "predicted_unclear_count": len(predicted_unclear),
        "agreed_unclear_count": agreed,
        "unnecessary_abstention_count": len(predicted_unclear) - agreed,
        "proxy_precision": agreed / len(predicted_unclear),
    }


def citation_validity(comparisons: list[CriterionComparison]) -> float | None:
    """
    Fraction of predicted citations that are an exact substring of the
    criterion's source text. This should be 100% by construction (the
    Verify stage already enforces it — see app/pipeline/verify.py) —
    this function exists as an independent regression check on the eval
    set, not as the primary enforcement mechanism.
    """
    if not comparisons:
        return None
    valid = sum(1 for c in comparisons if c.cited_text in c.criterion_raw_text)
    return valid / len(comparisons)


def latency_stats(latencies_ms: list[float]) -> dict:
    """p50/p95/mean latency in milliseconds. Returns Nones for an empty input rather than raising."""
    if not latencies_ms:
        return {"p50_ms": None, "p95_ms": None, "mean_ms": None, "count": 0}

    sorted_latencies = sorted(latencies_ms)
    return {
        "p50_ms": statistics.median(sorted_latencies),
        "p95_ms": sorted_latencies[
            min(len(sorted_latencies) - 1, int(len(sorted_latencies) * 0.95))
        ],
        "mean_ms": statistics.mean(sorted_latencies),
        "count": len(sorted_latencies),
    }


def retrieval_recall(hits: list[bool]) -> float | None:
    """Fraction of patient cases where the gold-correct trial appeared in the retrieved candidate set."""
    if not hits:
        return None
    return sum(1 for h in hits if h) / len(hits)
