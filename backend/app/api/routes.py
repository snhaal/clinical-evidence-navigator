"""
The clinical trial matching, verification, and per-user history routes.

Flow for /match: Plan -> (early return if clarification needed) -> Act -> per-trial
[Ground -> persist -> Verify] -> Synthesize -> persist match_runs -> respond.

Authentication:
- /match accepts optional authentication (Guest mode when unauthenticated).
- /history and /history/{match_run_id} strictly require Supabase authentication.
"""

import asyncio
import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.adapters.clinicaltrials import ClinicalTrialsClient
from app.adapters.tracking import TrackingLLMAdapter
from app.api.schemas import (
    HistoryDetailResponse,
    HistoryItemResponse,
    HistoryListResponse,
    MatchRequest,
    MatchResponse,
)
from app.auth import User, get_optional_user, get_required_user
from app.config import get_settings
from app.db import get_engine
from app.pipeline.act import ActStageError, retrieve_candidate_trials
from app.pipeline.ground import decompose_eligibility_criteria
from app.pipeline.plan import plan_patient_profile
from app.pipeline.synthesize import synthesize_results
from app.pipeline.verify import verify_all_criteria
from app.rate_limit import get_rate_limiter
from app.repositories.match_runs import (
    get_match_run_detail,
    get_user_match_history,
    insert_criterion_verdicts,
    insert_match_run,
)
from app.repositories.patient_profiles import (
    delete_patient_profile,
    insert_patient_profile,
)
from app.repositories.trials import insert_trial_criteria, upsert_trial

logger = logging.getLogger(__name__)
router = APIRouter()


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("/match", response_model=MatchResponse)
async def match_patient(
    request: Request,
    body: MatchRequest,
    current_user: Annotated[User | None, Depends(get_optional_user)] = None,
) -> MatchResponse:
    settings = get_settings()
    started_at = time.monotonic()
    user_id = current_user.id if current_user else None

    # --- Rate limiting (Risk: free-tier LLM cost overrun) -----------------
    client_ip = _client_ip(request)
    if not get_rate_limiter().check_and_record(client_ip):
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded ({settings.max_requests_per_ip_per_hour} requests/hour). Please try again later.",
        )

    # --- Input validation (Security NFR: cap input length) ----------------
    if len(body.patient_profile) > settings.max_patient_profile_chars:
        raise HTTPException(
            status_code=400,
            detail=f"Patient profile exceeds the {settings.max_patient_profile_chars}-character limit.",
        )

    # --- Plan stage ---------------------------------------------------------
    plan_llm = TrackingLLMAdapter()
    plan_result = await plan_patient_profile(body.patient_profile, llm=plan_llm)
    logger.info(
        "Plan stage: %d tokens, %.0fms",
        plan_llm.total_tokens,
        sum(plan_llm.latencies_ms),
    )

    engine = get_engine()
    async with engine.begin() as conn:
        patient_profile_id = await insert_patient_profile(
            conn,
            raw_text=body.patient_profile,
            structured_query=plan_result.structured_query.model_dump()
            if plan_result.structured_query
            else None,
            clarifying_question=plan_result.clarifying_question,
            user_id=user_id,
        )

    if plan_result.needs_clarification:
        return MatchResponse(
            patient_profile_id=str(patient_profile_id),
            needs_clarification=True,
            clarifying_question=plan_result.clarifying_question,
            structured_query=None,
            trials=[],
            latency_ms=int((time.monotonic() - started_at) * 1000),
        )

    # --- Act stage ------------------------------------------------------------
    try:
        trials = await retrieve_candidate_trials(
            plan_result.structured_query, client=ClinicalTrialsClient()
        )
    except ActStageError as exc:
        # Visible, specific error state — never a silent empty result (NFR: Reliability).
        raise HTTPException(
            status_code=502, detail=f"Trial retrieval failed: {exc}"
        ) from exc

    if not trials:
        return MatchResponse(
            patient_profile_id=str(patient_profile_id),
            needs_clarification=False,
            structured_query=plan_result.structured_query,
            trials=[],
            latency_ms=int((time.monotonic() - started_at) * 1000),
        )

    # --- Ground + Verify per trial ----------------------------------------
    # Cooldown pause to allow Groq rolling TPM window to slide down after Plan stage
    await asyncio.sleep(4.0)

    # For live match verification, evaluate strictly the top 3 candidate studies
    # to protect LLM token quotas and rate limits
    candidate_trials = trials[:3]

    verdicts_by_nct_id: dict = {}
    criterion_ids_by_nct_id: dict = {}
    trial_stats: dict = {}  # nct_id -> {"latency_ms": int, "token_cost": int}

    for idx, trial in enumerate(candidate_trials):
        if idx > 0:
            # Enforce 2.0s cooldown between candidate study verifications to allow rolling token window to clear
            await asyncio.sleep(2.0)

        async with engine.begin() as conn:
            await upsert_trial(conn, trial)
            criteria = decompose_eligibility_criteria(
                trial.nct_id, trial.eligibility_text
            )
            criterion_ids_by_nct_id[trial.nct_id] = await insert_trial_criteria(
                conn, criteria
            )

        if not criteria:
            verdicts_by_nct_id[trial.nct_id] = []
            trial_stats[trial.nct_id] = {"latency_ms": 0, "token_cost": 0}
            continue

        trial_llm = TrackingLLMAdapter()
        trial_started_at = time.monotonic()
        try:
            verdicts_by_nct_id[trial.nct_id] = await verify_all_criteria(
                body.patient_profile, criteria, llm=trial_llm
            )
        except Exception as exc:  # Verify stage itself never raises in normal operation; this is a last-resort guard.
            logger.error(
                "Unexpected Verify stage failure for %s: %s", trial.nct_id, exc
            )
            verdicts_by_nct_id[trial.nct_id] = []
        trial_stats[trial.nct_id] = {
            "latency_ms": int((time.monotonic() - trial_started_at) * 1000),
            "token_cost": trial_llm.total_tokens,
        }

    # --- Synthesize -------------------------------------------------------------
    summaries = synthesize_results(candidate_trials, verdicts_by_nct_id)

    # --- Persist match_runs + criterion_verdicts (observability requirement) --
    # latency_ms/token_cost are per-trial Verify-stage figures (one batched
    # LLM call per trial as of app/pipeline/verify.py's rate-limit-aware
    # design — see verify_trial_criteria). Plan-stage cost is request-scoped,
    # not per-trial, and is logged above rather than stored on any one row.
    async with engine.begin() as conn:
        for summary in summaries:
            stats = trial_stats.get(summary.nct_id, {})
            match_run_id = await insert_match_run(
                conn,
                patient_profile_id,
                summary,
                latency_ms=stats.get("latency_ms"),
                token_cost=stats.get("token_cost"),
                user_id=user_id,
            )
            await insert_criterion_verdicts(
                conn,
                match_run_id,
                verdicts_by_nct_id.get(summary.nct_id, []),
                criterion_ids_by_nct_id.get(summary.nct_id, {}),
            )

    return MatchResponse(
        patient_profile_id=str(patient_profile_id),
        needs_clarification=False,
        structured_query=plan_result.structured_query,
        trials=summaries,
        latency_ms=int((time.monotonic() - started_at) * 1000),
    )


@router.get("/history", response_model=HistoryListResponse)
async def list_match_history(
    current_user: Annotated[User, Depends(get_required_user)],
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> HistoryListResponse:
    """
    Returns paginated match history strictly for the authenticated user.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        items_data, total = await get_user_match_history(
            conn, user_id=current_user.id, limit=limit, offset=offset
        )

    return HistoryListResponse(
        items=[HistoryItemResponse(**item) for item in items_data],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/history/{match_run_id}", response_model=HistoryDetailResponse)
async def get_match_history_detail(
    match_run_id: str,
    current_user: Annotated[User, Depends(get_required_user)],
) -> HistoryDetailResponse:
    """
    Retrieves complete execution details: patient profile, full trial evaluation
    criteria records, reasoning, and verdicts.
    Enforces tenancy: returns 404 if not found, 403 if user is not the owner.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        detail_data = await get_match_run_detail(
            conn, match_run_id=match_run_id, user_id=current_user.id
        )

    if detail_data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Match run '{match_run_id}' not found.",
        )

    if detail_data.get("forbidden"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You do not have permission to view this match run.",
        )

    return HistoryDetailResponse(**detail_data)


@router.delete("/history/{profile_id}")
async def delete_history_session(
    profile_id: str,
    current_user: Annotated[User, Depends(get_required_user)],
) -> dict:
    """
    Deletes an evaluation session and all cascade-linked match_runs.
    Enforces tenancy: returns 404 if not found, 403 if user is not the owner.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        result = await delete_patient_profile(
            conn, profile_id=profile_id, user_id=current_user.id
        )

    if result == "not_found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Evaluation session '{profile_id}' not found.",
        )

    if result == "forbidden":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You do not have permission to delete this record.",
        )

    return {"deleted": True, "patient_profile_id": profile_id}
