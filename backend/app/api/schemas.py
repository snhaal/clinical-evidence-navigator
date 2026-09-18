"""
API-layer contracts. Kept separate from app.pipeline.schemas so the
public HTTP contract can stay stable even if internal pipeline schemas
change shape.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.pipeline.schemas import CriterionVerdict, StructuredQuery, TrialMatchSummary

DISCLAIMER = (
    "This is a portfolio engineering project demonstrating agentic RAG architecture. "
    "It is not a medical device, does not provide medical advice, and must never be "
    "positioned as a tool for real clinical decisions."
)


class MatchRequest(BaseModel):
    patient_profile: str = Field(
        ..., min_length=1, description="Free-text patient profile"
    )


class MatchResponse(BaseModel):
    patient_profile_id: str
    needs_clarification: bool
    clarifying_question: str | None = None
    structured_query: StructuredQuery | None = None
    trials: list[TrialMatchSummary] = Field(default_factory=list)
    latency_ms: int
    disclaimer: str = DISCLAIMER


class HistoryItemResponse(BaseModel):
    id: str
    created_at: datetime
    condition: str
    trial_title: str | None = None
    nct_id: str | None = None
    top_trials: list[str] = Field(default_factory=list)
    status: str
    overall_verdict: str | None = None


class HistoryListResponse(BaseModel):
    items: list[HistoryItemResponse] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class HistoryDetailResponse(BaseModel):
    id: str
    patient_profile_id: str
    created_at: datetime
    patient_profile: str
    structured_query: StructuredQuery | None = None
    nct_id: str
    trial_title: str
    overall_verdict: str
    satisfied_count: int
    unclear_count: int
    hard_exclusion_hit: bool
    latency_ms: int | None = None
    token_cost: int | None = None
    criterion_verdicts: list[CriterionVerdict] = Field(default_factory=list)
    trials: list[TrialMatchSummary] = Field(default_factory=list)
    disclaimer: str = DISCLAIMER
