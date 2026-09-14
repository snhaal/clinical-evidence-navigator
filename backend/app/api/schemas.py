"""
API-layer contracts. Kept separate from app.pipeline.schemas so the
public HTTP contract can stay stable even if internal pipeline schemas
change shape.
"""

from pydantic import BaseModel, Field

from app.pipeline.schemas import StructuredQuery, TrialMatchSummary

DISCLAIMER = (
    "This is a portfolio engineering project demonstrating agentic RAG architecture. "
    "It is not a medical device, does not provide medical advice, and must never be "
    "positioned as a tool for real clinical decisions."
)


class MatchRequest(BaseModel):
    patient_profile: str = Field(..., min_length=1, description="Free-text patient profile")


class MatchResponse(BaseModel):
    patient_profile_id: str
    needs_clarification: bool
    clarifying_question: str | None = None
    structured_query: StructuredQuery | None = None
    trials: list[TrialMatchSummary] = Field(default_factory=list)
    latency_ms: int
    disclaimer: str = DISCLAIMER
