"""
API-layer contracts. Kept separate from app.pipeline.schemas so the
public HTTP contract can stay stable even if internal pipeline schemas
change shape.
"""

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

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


class HistoryTrialSummary(BaseModel):
    match_run_id: str
    nct_id: str
    trial_title: str
    overall_verdict: str
    satisfied_count: int = 0
    unclear_count: int = 0
    hard_exclusion_hit: bool = False
    criterion_verdicts: list[CriterionVerdict] = Field(default_factory=list)


class HistoryItemResponse(BaseModel):
    id: str  # patient_profile_id
    patient_profile_id: str = ""
    created_at: datetime
    condition: str
    biomarkers: list[str] = Field(default_factory=list)
    stage: str | None = None
    patient_profile: str | None = None
    trials: list[HistoryTrialSummary] = Field(default_factory=list)

    # Backwards compatibility fields
    trial_title: str | None = None
    nct_id: str | None = None
    top_trials: list[str] = Field(default_factory=list)
    status: str = "evaluated"
    overall_verdict: str | None = None

    @model_validator(mode="after")
    def populate_patient_profile_id(self):
        if not self.patient_profile_id:
            self.patient_profile_id = self.id
        return self


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
