"""
Synthesize stage.

Pure aggregation logic, no LLM call: given a trial's criterion verdicts,
compute an overall verdict and rank trials. The one guardrail called out
explicitly in the project plan lives here: "a single unmet hard-exclusion
criterion should override an otherwise high match score."
"""

from app.pipeline.schemas import CriterionVerdict, NormalizedTrial, TrialMatchSummary

_VERDICT_RANK_PRIORITY = {"match": 0, "unclear": 1, "no_match": 2}


def summarize_trial(trial: NormalizedTrial, verdicts: list[CriterionVerdict]) -> TrialMatchSummary:
    """
    Aggregates one trial's per-criterion verdicts into an overall verdict.

    Logic:
      - hard_exclusion_hit = True if ANY exclusion criterion verdict is "match"
        (the patient matches something they should be excluded for).
        This alone forces overall_verdict = "no_match", regardless of how
        many inclusion criteria were satisfied.
      - Otherwise, if any inclusion criterion is a confirmed "no_match",
        overall_verdict = "no_match".
      - Otherwise, if any criterion is "unclear", overall_verdict = "unclear"
        (we don't have enough information to call it a full match).
      - Otherwise (all inclusion criteria matched, no exclusion matched,
        nothing unclear), overall_verdict = "match".
    """
    inclusion_verdicts = [v for v in verdicts if v.criterion_type == "inclusion"]
    exclusion_verdicts = [v for v in verdicts if v.criterion_type == "exclusion"]

    hard_exclusion_hit = any(v.verdict == "match" for v in exclusion_verdicts)
    satisfied_count = sum(1 for v in inclusion_verdicts if v.verdict == "match")
    unclear_count = sum(1 for v in verdicts if v.verdict == "unclear")
    inclusion_no_match = any(v.verdict == "no_match" for v in inclusion_verdicts)

    if not verdicts:
        # No criteria were ever evaluated (e.g. Ground stage found none) —
        # a data gap to surface as unclear, never a default "match".
        overall_verdict = "unclear"
    elif hard_exclusion_hit or inclusion_no_match:
        overall_verdict = "no_match"
    elif unclear_count > 0:
        overall_verdict = "unclear"
    else:
        overall_verdict = "match"

    return TrialMatchSummary(
        nct_id=trial.nct_id,
        title=trial.title,
        overall_verdict=overall_verdict,
        satisfied_count=satisfied_count,
        unclear_count=unclear_count,
        hard_exclusion_hit=hard_exclusion_hit,
        criterion_verdicts=verdicts,
    )


def rank_trials(summaries: list[TrialMatchSummary]) -> list[TrialMatchSummary]:
    """
    Sort order (FR-5): trials that survive a hard exclusion rank above
    those that don't, then by overall verdict (match before unclear before
    no_match), then by satisfied-criteria count descending, then by fewer
    unclear criteria (a more completely-evaluated trial ranks slightly
    higher than an equally-scored but more ambiguous one).

    Hard-excluded trials are never dropped from the list — a user should
    still be able to see *why* a trial was excluded — they're just always
    ranked last.
    """
    return sorted(
        summaries,
        key=lambda s: (
            s.hard_exclusion_hit,                       # False (0) sorts before True (1)
            _VERDICT_RANK_PRIORITY[s.overall_verdict],
            -s.satisfied_count,
            s.unclear_count,
        ),
    )


def synthesize_results(
    trials: list[NormalizedTrial],
    verdicts_by_nct_id: dict[str, list[CriterionVerdict]],
) -> list[TrialMatchSummary]:
    """
    Main entry point for the Synthesize stage. Trials with no verdicts
    recorded (e.g. Ground stage found zero criteria) still appear in the
    output as fully "unclear" with satisfied_count 0, rather than being
    silently dropped — an empty verdict list is a data gap to surface,
    not a reason to hide the trial.
    """
    summaries = [
        summarize_trial(trial, verdicts_by_nct_id.get(trial.nct_id, []))
        for trial in trials
    ]
    return rank_trials(summaries)
