"""
Schemas shared across pipeline stages.

StructuredQuery is the Plan stage's output contract. Keeping it as a
validated Pydantic model (rather than trusting raw LLM JSON) is what
lets the Act stage build ClinicalTrials.gov query params with confidence
instead of defensively checking dict keys everywhere.
"""

from pydantic import BaseModel, Field, field_validator


class StructuredQuery(BaseModel):
    """
    Fields map to ClinicalTrials.gov API v2 search fields where possible
    (condition -> query.cond, status -> filter.overallStatus, etc.).
    The Act stage (Module 4) owns that mapping; this schema just captures
    what was extracted from the free-text profile.
    """

    condition: str = Field(..., min_length=1, description="Primary diagnosis/condition, e.g. 'esophageal squamous cell carcinoma'")
    stage: str | None = Field(default=None, description="Disease stage, e.g. 'Stage III'")
    prior_therapy: list[str] = Field(default_factory=list, description="Treatments already received, e.g. ['neoadjuvant chemoradiation']")
    biomarkers: list[str] = Field(default_factory=list, description="Known biomarker status, e.g. ['HER2-positive']")
    exclusions: list[str] = Field(default_factory=list, description="Patient-stated exclusions/comorbidities relevant to eligibility")
    age: int | None = Field(default=None, ge=0, le=120)
    sex: str | None = Field(default=None, description="As stated in the profile; used only if a trial restricts by sex")
    status_filter: str = Field(default="RECRUITING", description="ClinicalTrials.gov overallStatus filter")

    @field_validator("condition")
    @classmethod
    def condition_not_placeholder(cls, v: str) -> str:
        if v.strip().lower() in {"unknown", "n/a", "none", ""}:
            raise ValueError("condition must be a real diagnosis, not a placeholder")
        return v.strip()


class PlanResult(BaseModel):
    """
    What the Plan stage returns to the caller. Exactly one of
    `structured_query` / `clarifying_question` is set — never both,
    never neither. This mirrors FR-1 (must) and FR-7 (should): extract
    confidently, or ask one targeted question rather than guess.
    """

    structured_query: StructuredQuery | None = None
    clarifying_question: str | None = None
    raw_model_output: str = Field(exclude=True, default="")  # kept for logging/debugging, not returned to the client

    @field_validator("clarifying_question")
    @classmethod
    def exactly_one_of_query_or_question(cls, v, info):
        query = info.data.get("structured_query")
        if (query is None) == (v is None):
            raise ValueError("PlanResult must set exactly one of structured_query or clarifying_question")
        return v

    @property
    def needs_clarification(self) -> bool:
        return self.clarifying_question is not None


class NormalizedTrial(BaseModel):
    """
    Act stage output: a ClinicalTrials.gov study reduced to the fields the
    rest of the pipeline needs. Keeping this separate from the raw API
    payload means Ground/Verify/Synthesize never touch the API's nested
    protocolSection/... shape directly.
    """

    nct_id: str
    title: str
    status: str | None = None
    phase: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    eligibility_text: str = Field(default="", description="Raw eligibility criteria text, unmodified, for the Ground stage to split")


class TrialCriterion(BaseModel):
    """
    Ground stage output: one atomic, citable eligibility statement.
    `raw_text` must be an exact substring of the trial's eligibility_text
    (modulo leading bullet/number stripping) so downstream citation
    validation (Verify stage) can confirm a cited_text against it.
    """

    nct_id: str
    criterion_type: str = Field(..., pattern="^(inclusion|exclusion)$")
    criterion_index: int = Field(..., ge=0)
    raw_text: str = Field(..., min_length=1)


class CriterionVerdict(BaseModel):
    """
    Verify stage output: one criterion's match/no_match/unclear verdict.
    `cited_text` MUST be an exact substring of the corresponding
    TrialCriterion.raw_text — this is enforced by the Verify stage itself
    (not just hoped for), since citation validity is the project's
    single most important trust guarantee.
    """

    nct_id: str
    criterion_type: str = Field(..., pattern="^(inclusion|exclusion)$")
    criterion_index: int = Field(..., ge=0)
    verdict: str = Field(..., pattern="^(match|no_match|unclear)$")
    rationale: str = Field(..., min_length=1)
    cited_text: str = Field(..., min_length=1)
    evidence_quote: str | None = Field(
        default=None,
        description="Verbatim quote from the patient note, or None/null if not mentioned.",
    )
    citation_validated: bool = Field(
        default=True,
        description="False if the model's original citation failed substring validation and had to be overridden.",
    )


class TrialMatchSummary(BaseModel):
    """Synthesize stage output: one trial's aggregated verdict, ready to render."""

    nct_id: str
    title: str
    overall_verdict: str = Field(..., pattern="^(match|no_match|unclear)$")
    satisfied_count: int = Field(..., ge=0)
    unclear_count: int = Field(..., ge=0)
    hard_exclusion_hit: bool
    criterion_verdicts: list[CriterionVerdict] = Field(default_factory=list)
