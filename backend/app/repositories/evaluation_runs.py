"""Repository for evaluation_runs — the eval harness's persisted scoring record."""

import json
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def insert_evaluation_run(
    conn: AsyncConnection,
    gold_case_id: str,
    predicted_verdicts: dict,
    expected_verdicts: dict,
    agreement_score: float | None,
    false_match_count: int,
    citation_valid: bool | None,
) -> uuid.UUID:
    result = await conn.execute(
        text(
            """
            insert into evaluation_runs
                (gold_case_id, predicted_verdicts, expected_verdicts, agreement_score,
                 false_match_count, citation_valid)
            values
                (:gold_case_id, :predicted_verdicts, :expected_verdicts, :agreement_score,
                 :false_match_count, :citation_valid)
            returning id
            """
        ),
        {
            "gold_case_id": gold_case_id,
            "predicted_verdicts": json.dumps(predicted_verdicts),
            "expected_verdicts": json.dumps(expected_verdicts),
            "agreement_score": agreement_score,
            "false_match_count": false_match_count,
            "citation_valid": citation_valid,
        },
    )
    return result.scalar_one()
