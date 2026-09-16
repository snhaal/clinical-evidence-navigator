"""
Repository for trials and trial_criteria. Trials are upserted (a trial
may be retrieved again in a later query and should refresh its cached
metadata); criteria are upserted per (nct_id, criterion_type,
criterion_index) so re-running Ground on the same trial doesn't create
duplicate rows.
"""

import json
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.pipeline.schemas import NormalizedTrial, TrialCriterion

CriterionKey = tuple[str, int]  # (criterion_type, criterion_index)


async def upsert_trial(conn: AsyncConnection, trial: NormalizedTrial) -> None:
    await conn.execute(
        text(
            """
            insert into trials (nct_id, title, status, phase, conditions, raw_payload, last_synced_at)
            values (:nct_id, :title, :status, :phase, :conditions, :raw_payload, now())
            on conflict (nct_id) do update set
                title = excluded.title,
                status = excluded.status,
                phase = excluded.phase,
                conditions = excluded.conditions,
                last_synced_at = now()
            """
        ),
        {
            "nct_id": trial.nct_id,
            "title": trial.title,
            "status": trial.status,
            "phase": ", ".join(trial.phase) if trial.phase else None,
            "conditions": trial.conditions,
            "raw_payload": json.dumps({"eligibility_text": trial.eligibility_text}),
        },
    )


async def insert_trial_criteria(
    conn: AsyncConnection,
    criteria: list[TrialCriterion],
) -> dict[CriterionKey, uuid.UUID]:
    """
    Upserts each criterion and returns a lookup from (criterion_type,
    criterion_index) -> criterion_id, so the caller can attach
    criterion_verdicts to the correct row without a second round-trip.
    """
    criterion_ids: dict[CriterionKey, uuid.UUID] = {}

    for criterion in criteria:
        result = await conn.execute(
            text(
                """
                insert into trial_criteria (nct_id, criterion_type, criterion_index, raw_text)
                values (:nct_id, :criterion_type, :criterion_index, :raw_text)
                on conflict (nct_id, criterion_type, criterion_index) do update set
                    raw_text = excluded.raw_text
                returning id
                """
            ),
            {
                "nct_id": criterion.nct_id,
                "criterion_type": criterion.criterion_type,
                "criterion_index": criterion.criterion_index,
                "raw_text": criterion.raw_text,
            },
        )
        criterion_ids[(criterion.criterion_type, criterion.criterion_index)] = (
            result.scalar_one()
        )

    return criterion_ids
