"""
Eval harness runner.

For each gold case: run Plan (to get a structured query, for context) and
Act (to check retrieval recall), then fetch each expected trial directly
by NCT ID, run Ground to decompose its eligibility text, run Verify to
get predicted verdicts, and match each hand-labeled gold criterion to the
parsed criterion whose raw_text corresponds to it (matched by substring
containment — gold text is copied verbatim from the same live listing
Ground parses, so this should be an exact or near-exact match; a case
that can't be matched is reported, not silently dropped).

Usage:
    python -m evals.run_eval                  # full run, requires DATABASE_URL unset OK, needs LLM key + network
    python -m evals.run_eval --skip-retrieval  # skip the Plan/Act retrieval-recall check
    python -m evals.run_eval --persist         # also write evaluation_runs rows to Postgres

Requires the same environment variables as the backend (LLM_PROVIDER_API_KEY
at minimum; DATABASE_URL only if --persist is passed).
"""

import argparse
import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.adapters.clinicaltrials import ClinicalTrialsAPIError, ClinicalTrialsClient
from app.pipeline.act import normalize_study, retrieve_candidate_trials
from app.pipeline.ground import decompose_eligibility_criteria
from app.pipeline.plan import plan_patient_profile
from app.pipeline.verify import verify_all_criteria
from evals.schemas import GoldCase, GoldCaseSet, GoldCriterion
from evals.scoring import (
    CriterionComparison,
    abstention_stats,
    agreement_rate,
    citation_validity,
    false_match_rate,
    latency_stats,
    retrieval_recall,
)
from evals.tracking_llm import TrackingLLMAdapter

logger = logging.getLogger(__name__)

GOLD_CASES_PATH = Path(__file__).parent / "gold_cases.json"
REPORTS_DIR = Path(__file__).parent / "reports"


def _normalize_for_match(text: str) -> str:
    return " ".join(text.lower().split())


def _find_matching_criterion(
    gold: GoldCriterion, parsed_criteria: list
) -> object | None:
    """
    Matches a hand-labeled gold criterion to a Ground-stage-parsed criterion
    by normalized substring containment (either direction), restricted to
    the same criterion_type. Returns None if nothing matches closely enough
    — the caller reports this rather than guessing.
    """
    gold_norm = _normalize_for_match(gold.raw_text)
    candidates = [c for c in parsed_criteria if c.criterion_type == gold.criterion_type]

    for c in candidates:
        c_norm = _normalize_for_match(c.raw_text)
        if gold_norm in c_norm or c_norm in gold_norm:
            return c
    return None


async def evaluate_case(
    case: GoldCase,
    llm: TrackingLLMAdapter,
    client: ClinicalTrialsClient,
    skip_retrieval: bool,
) -> dict:
    """Runs one gold case end-to-end and returns per-case results plus any warnings."""
    warnings: list[str] = []
    comparisons: list[CriterionComparison] = []
    retrieval_hit: bool | None = None

    # --- Retrieval recall (optional) ---------------------------------------
    if not skip_retrieval:
        try:
            plan_result = await plan_patient_profile(case.patient_profile, llm=llm)
            if plan_result.structured_query is not None:
                retrieved = await retrieve_candidate_trials(
                    plan_result.structured_query, client=client
                )
                retrieved_ids = {t.nct_id for t in retrieved}
                retrieval_hit = any(
                    nct_id in retrieved_ids for nct_id in case.expected_trial_nct_ids
                )
            else:
                warnings.append(
                    f"{case.gold_case_id}: Plan stage asked for clarification; skipped retrieval check."
                )
        except Exception as exc:
            warnings.append(
                f"{case.gold_case_id}: retrieval-recall check failed: {exc}"
            )

    # --- Per-trial Ground + Verify, matched against gold criteria ----------
    criteria_by_nct_id: dict[str, list[GoldCriterion]] = {}
    for criterion in case.criteria:
        criteria_by_nct_id.setdefault(criterion.nct_id, []).append(criterion)

    for nct_id, gold_criteria in criteria_by_nct_id.items():
        try:
            raw_study = await client.get_study(nct_id)
        except ClinicalTrialsAPIError as exc:
            warnings.append(
                f"{case.gold_case_id}/{nct_id}: could not fetch trial ({exc}). "
                f"If this is a placeholder NCT ID, replace it with a real trial in gold_cases.json."
            )
            continue

        trial = normalize_study(raw_study)
        if trial is None:
            warnings.append(
                f"{case.gold_case_id}/{nct_id}: fetched study was missing required fields."
            )
            continue

        parsed_criteria = decompose_eligibility_criteria(
            trial.nct_id, trial.eligibility_text
        )
        if not parsed_criteria:
            warnings.append(
                f"{case.gold_case_id}/{nct_id}: Ground stage produced zero criteria."
            )
            continue

        predicted_verdicts = await verify_all_criteria(
            case.patient_profile, parsed_criteria, llm=llm
        )
        await asyncio.sleep(4.0)  # Rate-limit pacing
        predicted_by_key = {
            (v.criterion_type, v.criterion_index): v for v in predicted_verdicts
        }

        for gold_criterion in gold_criteria:
            matched_parsed = _find_matching_criterion(gold_criterion, parsed_criteria)
            if matched_parsed is None:
                warnings.append(
                    f"{case.gold_case_id}/{nct_id}: no parsed criterion matched gold text "
                    f"'{gold_criterion.raw_text[:60]}...'"
                )
                continue

            key = (matched_parsed.criterion_type, matched_parsed.criterion_index)
            predicted = predicted_by_key.get(key)
            if predicted is None:
                warnings.append(
                    f"{case.gold_case_id}/{nct_id}: matched criterion had no predicted verdict."
                )
                continue

            comparisons.append(
                CriterionComparison(
                    nct_id=nct_id,
                    criterion_type=matched_parsed.criterion_type,
                    criterion_index=matched_parsed.criterion_index,
                    predicted_verdict=predicted.verdict,
                    expected_verdict=gold_criterion.expected_verdict,
                    cited_text=predicted.cited_text,
                    criterion_raw_text=matched_parsed.raw_text,
                )
            )

    return {
        "case_id": case.gold_case_id,
        "comparisons": comparisons,
        "retrieval_hit": retrieval_hit,
        "warnings": warnings,
    }


async def run(skip_retrieval: bool, persist: bool) -> dict:
    with open(GOLD_CASES_PATH) as f:  # noqa: ASYNC230
        gold_case_set = GoldCaseSet(**json.load(f))

    llm = TrackingLLMAdapter()
    client = ClinicalTrialsClient()

    all_comparisons: list[CriterionComparison] = []
    all_warnings: list[str] = []
    retrieval_hits: list[bool] = []
    per_case_results: list[dict] = []

    for case in gold_case_set.cases:
        result = await evaluate_case(case, llm, client, skip_retrieval)
        per_case_results.append(result)
        all_comparisons.extend(result["comparisons"])
        all_warnings.extend(result["warnings"])
        if result["retrieval_hit"] is not None:
            retrieval_hits.append(result["retrieval_hit"])

    report = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "gold_cases_evaluated": len(gold_case_set.cases),
        "criteria_compared": len(all_comparisons),
        "metrics": {
            "criterion_agreement_rate": agreement_rate(all_comparisons),
            "false_match_rate": false_match_rate(all_comparisons),
            "abstention_stats": abstention_stats(all_comparisons),
            "citation_validity": citation_validity(all_comparisons),
            "retrieval_recall": retrieval_recall(retrieval_hits)
            if retrieval_hits
            else None,
            "latency": latency_stats(llm.latencies_ms),
            "total_tokens": llm.total_tokens,
        },
        "warnings": all_warnings,
        "per_case": [
            {
                "case_id": r["case_id"],
                "comparisons": len(r["comparisons"]),
                "retrieval_hit": r["retrieval_hit"],
                "warning_count": len(r["warnings"]),
            }
            for r in per_case_results
        ],
        "comparisons": [
            {
                "nct_id": c.nct_id,
                "criterion_type": c.criterion_type,
                "criterion_index": c.criterion_index,
                "predicted": c.predicted_verdict,
                "expected": c.expected_verdict,
                "cited_text": c.cited_text,
                "criterion": c.criterion_raw_text,
            }
            for c in all_comparisons
        ],
    }

    if persist:
        await _persist_report(gold_case_set, per_case_results)

    return report


async def _persist_report(
    gold_case_set: GoldCaseSet, per_case_results: list[dict]
) -> None:
    from app.db import get_engine
    from app.repositories.evaluation_runs import insert_evaluation_run

    engine = get_engine()
    async with engine.begin() as conn:
        for result in per_case_results:
            comparisons = result["comparisons"]
            if not comparisons:
                continue
            await insert_evaluation_run(
                conn,
                gold_case_id=result["case_id"],
                predicted_verdicts={
                    f"{c.nct_id}:{c.criterion_type}:{c.criterion_index}": c.predicted_verdict
                    for c in comparisons
                },
                expected_verdicts={
                    f"{c.nct_id}:{c.criterion_type}:{c.criterion_index}": c.expected_verdict
                    for c in comparisons
                },
                agreement_score=agreement_rate(comparisons),
                false_match_count=sum(
                    1
                    for c in comparisons
                    if c.expected_verdict == "no_match"
                    and c.predicted_verdict == "match"
                ),
                citation_valid=citation_validity(comparisons) == 1.0,
            )


def print_report(report: dict) -> None:
    metrics = report["metrics"]
    print("\n=== Clinical Evidence Navigator — Eval Report ===")
    print(f"Gold cases evaluated: {report['gold_cases_evaluated']}")
    print(f"Criteria compared:    {report['criteria_compared']}")
    print()
    print(f"Criterion agreement rate: {_fmt_pct(metrics['criterion_agreement_rate'])}")
    print(
        f"False-match rate:         {_fmt_pct(metrics['false_match_rate'])}  (lower is better — most important number)"
    )
    print(f"Citation validity:        {_fmt_pct(metrics['citation_validity'])}")
    print(f"Retrieval recall:         {_fmt_pct(metrics['retrieval_recall'])}")
    abst = metrics["abstention_stats"]
    print(
        f"Abstention proxy precision: {_fmt_pct(abst['proxy_precision'])} "
        f"({abst['agreed_unclear_count']}/{abst['predicted_unclear_count']} unclear predictions agreed with gold) "
        f"— manual review still needed for true precision"
    )
    lat = metrics["latency"]
    if lat["count"]:
        print(
            f"Verify-call latency: p50={lat['p50_ms']:.0f}ms  p95={lat['p95_ms']:.0f}ms  n={lat['count']}"
        )
    print(f"Total tokens used: {metrics['total_tokens']}")

    if report["warnings"]:
        print(f"\n{len(report['warnings'])} warning(s):")
        for w in report["warnings"]:
            print(f"  - {w}")


def _fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the gold evaluation set against the live pipeline."
    )
    parser.add_argument(
        "--skip-retrieval",
        action="store_true",
        help="Skip the Plan/Act retrieval-recall check",
    )
    parser.add_argument(
        "--persist", action="store_true", help="Write evaluation_runs rows to Postgres"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    report = asyncio.run(run(skip_retrieval=args.skip_retrieval, persist=args.persist))
    print_report(report)

    REPORTS_DIR.mkdir(exist_ok=True)
    report_path = (
        REPORTS_DIR
        / f"run_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nFull report written to {report_path}")


if __name__ == "__main__":
    main()
