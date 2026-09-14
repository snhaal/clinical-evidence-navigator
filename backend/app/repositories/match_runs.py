"""
Repository for match_runs and criterion_verdicts — the persisted record
of one Synthesize-stage result, used for the observability requirement
(every run logs its verdicts, latency, and token cost) and later reused
as the evaluation harness's data source.
"""

import logging
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.pipeline.schemas import CriterionVerdict, TrialMatchSummary
from app.repositories.trials import CriterionKey

logger = logging.getLogger(__name__)


async def insert_match_run(
    conn: AsyncConnection,
    patient_profile_id: uuid.UUID,
    summary: TrialMatchSummary,
    latency_ms: int | None = None,
    token_cost: int | None = None,
) -> uuid.UUID:
    result = await conn.execute(
        text(
            """
            insert into match_runs
                (patient_profile_id, nct_id, overall_verdict, satisfied_count,
                 unclear_count, hard_exclusion_hit, latency_ms, token_cost)
            values
                (:patient_profile_id, :nct_id, :overall_verdict, :satisfied_count,
                 :unclear_count, :hard_exclusion_hit, :latency_ms, :token_cost)
            returning id
            """
        ),
        {
            "patient_profile_id": patient_profile_id,
            "nct_id": summary.nct_id,
            "overall_verdict": summary.overall_verdict,
            "satisfied_count": summary.satisfied_count,
            "unclear_count": summary.unclear_count,
            "hard_exclusion_hit": summary.hard_exclusion_hit,
            "latency_ms": latency_ms,
            "token_cost": token_cost,
        },
    )
    return result.scalar_one()


async def insert_criterion_verdicts(
    conn: AsyncConnection,
    match_run_id: uuid.UUID,
    verdicts: list[CriterionVerdict],
    criterion_id_by_key: dict[CriterionKey, uuid.UUID],
) -> None:
    """
    Silently skips any verdict whose criterion_id can't be found in the
    lookup (should not happen in practice — it would mean Ground/Verify
    disagreed on which criteria exist — but we log rather than crash the
    whole persistence step over one orphaned verdict).
    """
    for verdict in verdicts:
        key = (verdict.criterion_type, verdict.criterion_index)
        criterion_id = criterion_id_by_key.get(key)
        if criterion_id is None:
            logger.warning("No stored criterion_id found for %s %s; skipping verdict persistence.", verdict.nct_id, key)
            continue

        await conn.execute(
            text(
                """
                insert into criterion_verdicts (match_run_id, criterion_id, verdict, rationale, cited_text)
                values (:match_run_id, :criterion_id, :verdict, :rationale, :cited_text)
                """
            ),
            {
                "match_run_id": match_run_id,
                "criterion_id": criterion_id,
                "verdict": verdict.verdict,
                "rationale": verdict.rationale,
                "cited_text": verdict.cited_text,
            },
        )
