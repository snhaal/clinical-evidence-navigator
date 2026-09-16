"""
Unit tests for app.pipeline.synthesize.

Covers the guardrail called out explicitly in the project plan: "a single
unmet hard-exclusion criterion should override an otherwise high match
score," plus the FR-5 ranking order.
"""

from app.pipeline.schemas import CriterionVerdict, NormalizedTrial
from app.pipeline.synthesize import rank_trials, summarize_trial, synthesize_results


def make_trial(nct_id: str, title: str = "A Trial") -> NormalizedTrial:
    return NormalizedTrial(nct_id=nct_id, title=title)


def make_verdict(
    nct_id: str, criterion_type: str, verdict: str, index: int = 0
) -> CriterionVerdict:
    return CriterionVerdict(
        nct_id=nct_id,
        criterion_type=criterion_type,
        criterion_index=index,
        verdict=verdict,
        rationale="test rationale",
        cited_text="test citation",
    )


def test_all_inclusion_matched_no_exclusion_matched_is_overall_match():
    trial = make_trial("NCT001")
    verdicts = [
        make_verdict("NCT001", "inclusion", "match", 0),
        make_verdict("NCT001", "inclusion", "match", 1),
        make_verdict("NCT001", "exclusion", "no_match", 0),
    ]
    summary = summarize_trial(trial, verdicts)

    assert summary.overall_verdict == "match"
    assert summary.satisfied_count == 2
    assert summary.hard_exclusion_hit is False


def test_hard_exclusion_overrides_otherwise_perfect_inclusion_score():
    """The core guardrail: high inclusion satisfaction must NOT save a trial with a matched exclusion."""
    trial = make_trial("NCT002")
    verdicts = [
        make_verdict("NCT002", "inclusion", "match", 0),
        make_verdict("NCT002", "inclusion", "match", 1),
        make_verdict("NCT002", "inclusion", "match", 2),
        make_verdict(
            "NCT002", "exclusion", "match", 0
        ),  # patient matches something they should be excluded for
    ]
    summary = summarize_trial(trial, verdicts)

    assert summary.hard_exclusion_hit is True
    assert summary.overall_verdict == "no_match"
    assert (
        summary.satisfied_count == 3
    )  # still reported accurately, just doesn't win overall


def test_confirmed_inclusion_no_match_is_overall_no_match():
    trial = make_trial("NCT003")
    verdicts = [
        make_verdict("NCT003", "inclusion", "no_match", 0),
        make_verdict("NCT003", "inclusion", "match", 1),
    ]
    summary = summarize_trial(trial, verdicts)

    assert summary.overall_verdict == "no_match"
    assert summary.hard_exclusion_hit is False


def test_unclear_criterion_with_no_confirmed_failures_is_overall_unclear():
    trial = make_trial("NCT004")
    verdicts = [
        make_verdict("NCT004", "inclusion", "match", 0),
        make_verdict("NCT004", "inclusion", "unclear", 1),
    ]
    summary = summarize_trial(trial, verdicts)

    assert summary.overall_verdict == "unclear"
    assert summary.unclear_count == 1


def test_trial_with_no_criteria_at_all_is_unclear_not_a_default_match():
    trial = make_trial("NCT005")
    summary = summarize_trial(trial, [])

    assert summary.overall_verdict == "unclear"
    assert summary.satisfied_count == 0


def test_rank_trials_orders_hard_exclusions_last():
    trial_a = summarize_trial(
        make_trial("NCT_A"), [make_verdict("NCT_A", "exclusion", "match")]
    )
    trial_b = summarize_trial(
        make_trial("NCT_B"), [make_verdict("NCT_B", "inclusion", "match")]
    )

    ranked = rank_trials([trial_a, trial_b])

    assert ranked[0].nct_id == "NCT_B"
    assert ranked[1].nct_id == "NCT_A"


def test_rank_trials_orders_match_before_unclear_before_no_match():
    matched = summarize_trial(
        make_trial("NCT_MATCH"), [make_verdict("NCT_MATCH", "inclusion", "match")]
    )
    unclear = summarize_trial(
        make_trial("NCT_UNCLEAR"), [make_verdict("NCT_UNCLEAR", "inclusion", "unclear")]
    )
    no_match = summarize_trial(
        make_trial("NCT_NOMATCH"),
        [make_verdict("NCT_NOMATCH", "inclusion", "no_match")],
    )

    ranked = rank_trials([no_match, unclear, matched])

    assert [t.nct_id for t in ranked] == ["NCT_MATCH", "NCT_UNCLEAR", "NCT_NOMATCH"]


def test_rank_trials_orders_by_satisfied_count_within_same_verdict():
    high = summarize_trial(
        make_trial("NCT_HIGH"),
        [
            make_verdict("NCT_HIGH", "inclusion", "match", 0),
            make_verdict("NCT_HIGH", "inclusion", "match", 1),
        ],
    )
    low = summarize_trial(
        make_trial("NCT_LOW"), [make_verdict("NCT_LOW", "inclusion", "match", 0)]
    )

    ranked = rank_trials([low, high])

    assert ranked[0].nct_id == "NCT_HIGH"
    assert ranked[1].nct_id == "NCT_LOW"


def test_synthesize_results_end_to_end():
    trials = [make_trial("NCT_A"), make_trial("NCT_B")]
    verdicts_by_nct_id = {
        "NCT_A": [make_verdict("NCT_A", "exclusion", "match")],  # hard-excluded
        "NCT_B": [make_verdict("NCT_B", "inclusion", "match")],  # clean match
    }

    results = synthesize_results(trials, verdicts_by_nct_id)

    assert [r.nct_id for r in results] == ["NCT_B", "NCT_A"]
    assert results[1].hard_exclusion_hit is True


def test_synthesize_results_includes_trials_with_no_recorded_verdicts():
    """A trial the Ground stage found zero criteria for should still appear, flagged unclear — never silently dropped."""
    trials = [make_trial("NCT_EMPTY")]
    results = synthesize_results(trials, verdicts_by_nct_id={})

    assert len(results) == 1
    assert results[0].overall_verdict == "unclear"
