"""
Repository for match_runs and criterion_verdicts — the persisted record
of one Synthesize-stage result, used for the observability requirement
(every run logs its verdicts, latency, and token cost) and later reused
as the evaluation harness's data source and per-user history tracking.
"""

import json
import logging
import uuid
from typing import Any

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
    user_id: str | None = None,
) -> uuid.UUID:
    parsed_user_id = uuid.UUID(user_id) if user_id else None
    result = await conn.execute(
        text(
            """
            insert into match_runs
                (patient_profile_id, nct_id, overall_verdict, satisfied_count,
                 unclear_count, hard_exclusion_hit, latency_ms, token_cost, user_id)
            values
                (:patient_profile_id, :nct_id, :overall_verdict, :satisfied_count,
                 :unclear_count, :hard_exclusion_hit, :latency_ms, :token_cost, :user_id)
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
            "user_id": parsed_user_id,
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
            logger.warning(
                "No stored criterion_id found for %s %s; skipping verdict persistence.",
                verdict.nct_id,
                key,
            )
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


async def get_user_match_history(
    conn: AsyncConnection,
    user_id: str,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """
    Queries match_runs and associated patient_profiles strictly filtered
    by WHERE user_id = :user_id ORDER BY created_at DESC.
    Returns (items, total_count).
    """
    parsed_user_id = uuid.UUID(user_id) if isinstance(user_id, str) else user_id

    # Total count for pagination
    count_res = await conn.execute(
        text("select count(*) from match_runs where user_id = :user_id"),
        {"user_id": parsed_user_id},
    )
    total = count_res.scalar_one()

    # Query match runs joined with patient profile and trial info
    rows = await conn.execute(
        text(
            """
            select
                mr.id,
                mr.created_at,
                mr.overall_verdict,
                mr.nct_id,
                mr.satisfied_count,
                mr.unclear_count,
                mr.hard_exclusion_hit,
                mr.latency_ms,
                mr.token_cost,
                t.title as trial_title,
                pp.id as patient_profile_id,
                pp.raw_text as patient_raw_text,
                pp.structured_query
            from match_runs mr
            join patient_profiles pp on mr.patient_profile_id = pp.id
            left join trials t on mr.nct_id = t.nct_id
            where mr.user_id = :user_id
            order by mr.created_at desc
            limit :limit offset :offset
            """
        ),
        {"user_id": parsed_user_id, "limit": limit, "offset": offset},
    )

    items: list[dict[str, Any]] = []
    for r in rows.mappings():
        sq = r["structured_query"]
        if isinstance(sq, str):
            try:
                sq = json.loads(sq)
            except Exception:
                sq = None

        condition = "Clinical Query"
        if isinstance(sq, dict) and sq.get("condition"):
            condition = str(sq["condition"])
        elif r.get("patient_raw_text"):
            raw = str(r["patient_raw_text"]).strip()
            condition = (raw[:47] + "...") if len(raw) > 50 else raw

        trial_title = r["trial_title"] or r["nct_id"]
        items.append(
            {
                "id": str(r["id"]),
                "created_at": r["created_at"],
                "condition": condition,
                "trial_title": trial_title,
                "nct_id": r["nct_id"],
                "top_trials": [trial_title] if trial_title else [],
                "status": r["overall_verdict"] or "unknown",
                "overall_verdict": r["overall_verdict"],
            }
        )

    return items, total


async def get_match_run_detail(
    conn: AsyncConnection,
    match_run_id: str | uuid.UUID,
    user_id: str,
) -> dict[str, Any] | None:
    """
    Retrieves complete execution details: patient profile, full trial evaluation
    criteria records, reasoning, and verdicts.
    Enforces tenancy: returns None if not found, or dict with {"forbidden": True}
    if owned by a different user.
    """
    parsed_run_id = (
        uuid.UUID(str(match_run_id))
        if not isinstance(match_run_id, uuid.UUID)
        else match_run_id
    )

    run_res = await conn.execute(
        text(
            """
            select
                mr.id,
                mr.patient_profile_id,
                mr.nct_id,
                mr.overall_verdict,
                mr.satisfied_count,
                mr.unclear_count,
                mr.hard_exclusion_hit,
                mr.latency_ms,
                mr.token_cost,
                mr.created_at,
                mr.user_id,
                t.title as trial_title,
                t.status as trial_status,
                t.phase as trial_phase,
                pp.raw_text as patient_raw_text,
                pp.structured_query
            from match_runs mr
            join patient_profiles pp on mr.patient_profile_id = pp.id
            left join trials t on mr.nct_id = t.nct_id
            where mr.id = :match_run_id
            """
        ),
        {"match_run_id": parsed_run_id},
    )
    row = run_res.mappings().first()
    if not row:
        return None

    # Tenancy check: verify ownership
    if row["user_id"] is None or str(row["user_id"]) != str(user_id):
        return {"forbidden": True}

    # Fetch criterion verdicts for this match run
    verdicts_res = await conn.execute(
        text(
            """
            select
                cv.verdict,
                cv.rationale,
                cv.cited_text,
                tc.nct_id,
                tc.criterion_type,
                tc.criterion_index,
                tc.raw_text
            from criterion_verdicts cv
            join trial_criteria tc on cv.criterion_id = tc.id
            where cv.match_run_id = :match_run_id
            order by tc.criterion_type, tc.criterion_index
            """
        ),
        {"match_run_id": parsed_run_id},
    )

    criterion_verdicts: list[CriterionVerdict] = []
    for vr in verdicts_res.mappings():
        criterion_verdicts.append(
            CriterionVerdict(
                nct_id=vr["nct_id"],
                criterion_type=vr["criterion_type"],
                criterion_index=vr["criterion_index"],
                verdict=vr["verdict"],
                rationale=vr["rationale"],
                cited_text=vr["cited_text"],
                citation_validated=True,
            )
        )

    sq = row["structured_query"]
    if isinstance(sq, str):
        try:
            sq = json.loads(sq)
        except Exception:
            sq = None

    primary_trial = TrialMatchSummary(
        nct_id=row["nct_id"],
        title=row["trial_title"] or row["nct_id"],
        overall_verdict=row["overall_verdict"],
        satisfied_count=row["satisfied_count"],
        unclear_count=row["unclear_count"],
        hard_exclusion_hit=row["hard_exclusion_hit"],
        criterion_verdicts=criterion_verdicts,
    )

    # Fetch any sibling trials evaluated in the same matching session
    sibling_res = await conn.execute(
        text(
            """
            select
                mr.id,
                mr.nct_id,
                mr.overall_verdict,
                mr.satisfied_count,
                mr.unclear_count,
                mr.hard_exclusion_hit,
                t.title as trial_title
            from match_runs mr
            left join trials t on mr.nct_id = t.nct_id
            where mr.patient_profile_id = :profile_id and mr.id != :match_run_id
            order by mr.created_at asc
            """
        ),
        {"profile_id": row["patient_profile_id"], "match_run_id": parsed_run_id},
    )

    all_trials = [primary_trial]
    for sr in sibling_res.mappings():
        sib_verdicts_res = await conn.execute(
            text(
                """
                select
                    cv.verdict,
                    cv.rationale,
                    cv.cited_text,
                    tc.nct_id,
                    tc.criterion_type,
                    tc.criterion_index
                from criterion_verdicts cv
                join trial_criteria tc on cv.criterion_id = tc.id
                where cv.match_run_id = :sib_run_id
                order by tc.criterion_type, tc.criterion_index
                """
            ),
            {"sib_run_id": sr["id"]},
        )
        sib_verdicts = [
            CriterionVerdict(
                nct_id=svr["nct_id"],
                criterion_type=svr["criterion_type"],
                criterion_index=svr["criterion_index"],
                verdict=svr["verdict"],
                rationale=svr["rationale"],
                cited_text=svr["cited_text"],
                citation_validated=True,
            )
            for svr in sib_verdicts_res.mappings()
        ]
        all_trials.append(
            TrialMatchSummary(
                nct_id=sr["nct_id"],
                title=sr["trial_title"] or sr["nct_id"],
                overall_verdict=sr["overall_verdict"],
                satisfied_count=sr["satisfied_count"],
                unclear_count=sr["unclear_count"],
                hard_exclusion_hit=sr["hard_exclusion_hit"],
                criterion_verdicts=sib_verdicts,
            )
        )

    return {
        "id": str(row["id"]),
        "patient_profile_id": str(row["patient_profile_id"]),
        "created_at": row["created_at"],
        "patient_profile": row["patient_raw_text"],
        "structured_query": sq,
        "nct_id": row["nct_id"],
        "trial_title": row["trial_title"] or row["nct_id"],
        "overall_verdict": row["overall_verdict"],
        "satisfied_count": row["satisfied_count"],
        "unclear_count": row["unclear_count"],
        "hard_exclusion_hit": row["hard_exclusion_hit"],
        "latency_ms": row["latency_ms"],
        "token_cost": row["token_cost"],
        "criterion_verdicts": [v.model_dump() for v in criterion_verdicts],
        "trials": [t.model_dump() for t in all_trials],
    }
