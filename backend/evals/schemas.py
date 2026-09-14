"""
Schema for hand-labeled gold evaluation cases.

Per the project plan: 8-12 synthetic patient profiles x 3-5 real trials
each (30-50 profile x trial x criterion labels total). Each case pins a
patient profile to one or more trials you expect retrieval to surface,
and a ground-truth verdict for individual criteria you've read yourself
against the live ClinicalTrials.gov listing.
"""

from pydantic import BaseModel, Field


class GoldCriterion(BaseModel):
    """
    One hand-labeled ground truth verdict. `raw_text` should be copied
    verbatim from the trial's actual eligibility text (matching what the
    Ground stage will produce) so citation-validity checks are meaningful.
    """

    nct_id: str
    criterion_type: str = Field(..., pattern="^(inclusion|exclusion)$")
    raw_text: str
    expected_verdict: str = Field(..., pattern="^(match|no_match|unclear)$")
    notes: str | None = Field(default=None, description="Why you labeled it this way — useful when a run disagrees")


class GoldCase(BaseModel):
    gold_case_id: str
    patient_profile: str
    expected_trial_nct_ids: list[str] = Field(
        ..., description="Trials retrieval SHOULD surface for this profile (for retrieval-recall scoring)"
    )
    criteria: list[GoldCriterion] = Field(
        default_factory=list,
        description="Hand-labeled criteria across the expected trials, used for agreement/false-match/citation scoring",
    )


class GoldCaseSet(BaseModel):
    cases: list[GoldCase]
