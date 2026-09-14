"""
Unit tests for evals.scoring. These run with no LLM key, no network, no
DB — the whole point of keeping scoring logic pure and separate from
run_eval.py's orchestration.
"""

from evals.scoring import (
    CriterionComparison,
    abstention_stats,
    agreement_rate,
    citation_validity,
    false_match_rate,
    latency_stats,
    retrieval_recall,
)


def make_comparison(predicted: str, expected: str, cited_text: str = "x", raw_text: str = "x criterion") -> CriterionComparison:
    return CriterionComparison(
        nct_id="NCT001",
        criterion_type="inclusion",
        criterion_index=0,
        predicted_verdict=predicted,
        expected_verdict=expected,
        cited_text=cited_text,
        criterion_raw_text=raw_text,
    )


def test_agreement_rate_all_correct():
    comparisons = [make_comparison("match", "match"), make_comparison("no_match", "no_match")]
    assert agreement_rate(comparisons) == 1.0


def test_agreement_rate_partial():
    comparisons = [make_comparison("match", "match"), make_comparison("match", "no_match")]
    assert agreement_rate(comparisons) == 0.5


def test_agreement_rate_empty_returns_none():
    assert agreement_rate([]) is None


def test_false_match_rate_counts_only_gold_no_match_criteria():
    comparisons = [
        make_comparison("match", "no_match"),   # false match
        make_comparison("no_match", "no_match"),  # correct
        make_comparison("match", "match"),      # not counted — gold isn't no_match
        make_comparison("unclear", "unclear"),  # not counted
    ]
    assert false_match_rate(comparisons) == 0.5  # 1 false match / 2 gold no_match cases


def test_false_match_rate_none_when_no_gold_no_match_cases():
    comparisons = [make_comparison("match", "match"), make_comparison("unclear", "unclear")]
    assert false_match_rate(comparisons) is None


def test_false_match_rate_zero_when_no_false_matches():
    comparisons = [make_comparison("no_match", "no_match"), make_comparison("unclear", "no_match")]
    assert false_match_rate(comparisons) == 0.0


def test_abstention_stats_no_unclear_predictions():
    comparisons = [make_comparison("match", "match")]
    stats = abstention_stats(comparisons)
    assert stats["predicted_unclear_count"] == 0
    assert stats["proxy_precision"] is None


def test_abstention_stats_computes_proxy_precision():
    comparisons = [
        make_comparison("unclear", "unclear"),  # correct abstention
        make_comparison("unclear", "unclear"),  # correct abstention
        make_comparison("unclear", "match"),    # unnecessary abstention
    ]
    stats = abstention_stats(comparisons)
    assert stats["predicted_unclear_count"] == 3
    assert stats["agreed_unclear_count"] == 2
    assert stats["unnecessary_abstention_count"] == 1
    assert stats["proxy_precision"] == 2 / 3


def test_citation_validity_all_valid_substrings():
    comparisons = [
        make_comparison("match", "match", cited_text="Age 18+", raw_text="Age 18+ required for enrollment"),
    ]
    assert citation_validity(comparisons) == 1.0


def test_citation_validity_detects_invalid_citation():
    comparisons = [
        make_comparison("match", "match", cited_text="totally fabricated quote", raw_text="Age 18+ required"),
    ]
    assert citation_validity(comparisons) == 0.0


def test_citation_validity_empty_returns_none():
    assert citation_validity([]) is None


def test_latency_stats_basic():
    stats = latency_stats([100.0, 200.0, 300.0, 400.0])
    assert stats["count"] == 4
    assert stats["mean_ms"] == 250.0
    assert stats["p50_ms"] == 250.0


def test_latency_stats_empty_returns_nones():
    stats = latency_stats([])
    assert stats["p50_ms"] is None
    assert stats["count"] == 0


def test_retrieval_recall_basic():
    assert retrieval_recall([True, True, False, True]) == 0.75


def test_retrieval_recall_empty_returns_none():
    assert retrieval_recall([]) is None
