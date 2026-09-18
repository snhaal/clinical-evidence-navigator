"""
Unit tests for app.pipeline.act.

No network calls: build_query_params and normalize_study are pure
functions, and retrieve_candidate_trials is tested against a fake client.
"""

import pytest

from app.adapters.clinicaltrials import ClinicalTrialsAPIError
from app.pipeline.act import (
    ActStageError,
    build_query_params,
    normalize_study,
    pre_rank_candidate_trials,
    retrieve_candidate_trials,
    score_candidate_trial,
)
from app.pipeline.schemas import NormalizedTrial, StructuredQuery


def test_build_query_params_condition_only():
    query = StructuredQuery(condition="breast cancer")
    params = build_query_params(query)

    assert params["query.cond"] == "breast cancer"
    assert params["filter.overallStatus"] == "RECRUITING"
    assert "query.term" not in params


def test_build_query_params_includes_stage_and_prior_therapy_in_term():
    query = StructuredQuery(
        condition="esophageal squamous cell carcinoma",
        stage="Stage III",
        prior_therapy=["neoadjuvant chemoradiation"],
        biomarkers=["HER2-positive"],
    )
    params = build_query_params(query)

    assert params["query.cond"] == "esophageal squamous cell carcinoma"
    assert "Stage III" in params["query.term"]
    assert "neoadjuvant chemoradiation" in params["query.term"]
    assert "HER2-positive" in params["query.term"]


def test_build_query_params_never_uses_exclusions_as_a_filter():
    """Exclusions are patient-side facts for the Verify stage, not a search filter."""
    query = StructuredQuery(condition="lung cancer", exclusions=["distant metastasis"])
    params = build_query_params(query)

    assert "distant metastasis" not in str(params)


SAMPLE_STUDY = {
    "protocolSection": {
        "identificationModule": {
            "nctId": "NCT01234567",
            "briefTitle": "A Study of Something",
        },
        "statusModule": {"overallStatus": "RECRUITING"},
        "designModule": {"phases": ["PHASE3"]},
        "conditionsModule": {"conditions": ["Breast Cancer"]},
        "eligibilityModule": {
            "eligibilityCriteria": "Inclusion Criteria:\n\n- Age 18+\n\nExclusion Criteria:\n\n- Pregnant"
        },
    }
}


def test_normalize_study_extracts_expected_fields():
    trial = normalize_study(SAMPLE_STUDY)

    assert trial is not None
    assert trial.nct_id == "NCT01234567"
    assert trial.title == "A Study of Something"
    assert trial.status == "RECRUITING"
    assert trial.phase == ["PHASE3"]
    assert "Breast Cancer" in trial.conditions
    assert "Inclusion Criteria" in trial.eligibility_text


def test_normalize_study_returns_none_for_missing_nct_id():
    broken = {
        "protocolSection": {"identificationModule": {"briefTitle": "No ID Study"}}
    }
    assert normalize_study(broken) is None


def test_normalize_study_returns_none_for_missing_title():
    broken = {"protocolSection": {"identificationModule": {"nctId": "NCT99999999"}}}
    assert normalize_study(broken) is None


class FakeClinicalTrialsClient:
    def __init__(self, studies=None, raise_error=False):
        self._studies = studies or []
        self._raise_error = raise_error

    async def search_studies(self, query_params: dict) -> list[dict]:
        if self._raise_error:
            raise ClinicalTrialsAPIError("simulated failure")
        return self._studies


@pytest.mark.asyncio
async def test_retrieve_candidate_trials_normalizes_and_filters_bad_records():
    broken_record = {
        "protocolSection": {"identificationModule": {"briefTitle": "missing id"}}
    }
    client = FakeClinicalTrialsClient(studies=[SAMPLE_STUDY, broken_record])

    trials = await retrieve_candidate_trials(
        StructuredQuery(condition="breast cancer"), client=client
    )

    assert len(trials) == 1
    assert trials[0].nct_id == "NCT01234567"


@pytest.mark.asyncio
async def test_retrieve_candidate_trials_empty_result_is_not_an_error():
    client = FakeClinicalTrialsClient(studies=[])
    trials = await retrieve_candidate_trials(
        StructuredQuery(condition="an extremely rare condition"), client=client
    )
    assert trials == []


@pytest.mark.asyncio
async def test_retrieve_candidate_trials_raises_act_stage_error_on_api_failure():
    client = FakeClinicalTrialsClient(raise_error=True)
    with pytest.raises(ActStageError):
        await retrieve_candidate_trials(
            StructuredQuery(condition="lung cancer"), client=client
        )


def test_extract_root_condition():
    from app.adapters.clinicaltrials import ClinicalTrialsClient

    assert (
        ClinicalTrialsClient._extract_root_condition(
            "stage III thoracic esophageal squamous cell carcinoma ypT2N1M0"
        )
        == "thoracic esophageal squamous"
    )
    assert (
        ClinicalTrialsClient._extract_root_condition("lung adenocarcinoma")
        == "lung adenocarcinoma"
    )


@pytest.mark.asyncio
async def test_search_studies_auto_relaxes_query_on_zero_results(monkeypatch):
    from app.adapters.clinicaltrials import ClinicalTrialsClient

    client = ClinicalTrialsClient()
    calls = []

    async def fake_fetch(params):
        calls.append(params)
        # First call with query.term returns 0 studies
        if "query.term" in params:
            return []
        # Relaxed call returns 1 study
        return [SAMPLE_STUDY]

    monkeypatch.setattr(client, "_fetch_studies", fake_fetch)

    studies = await client.search_studies(
        {
            "query.cond": "thoracic esophageal squamous cell carcinoma",
            "query.term": "Stage III ypT2N1M0 esophagectomy",
            "filter.overallStatus": "RECRUITING",
        }
    )

    assert len(studies) == 1
    assert len(calls) == 2
    # The second call dropped query.term
    assert "query.term" not in calls[1]
    assert calls[1]["query.cond"] == "thoracic esophageal squamous cell carcinoma"


def test_sanitize_query_term():
    from app.adapters.clinicaltrials import ClinicalTrialsClient

    # Strips special parser-breaking characters [()%:;,/+=<>]
    raw = "Stage IVB (chemotherapy: cisplatin + pemetrexed) 45% [tested] <pos> / = ;"
    sanitized = ClinicalTrialsClient._sanitize_query_term(raw)
    assert "%" not in sanitized
    assert "(" not in sanitized
    assert ")" not in sanitized
    assert "+" not in sanitized
    assert ":" not in sanitized
    assert ";" not in sanitized
    assert "/" not in sanitized
    assert "=" not in sanitized
    assert "<" not in sanitized
    assert ">" not in sanitized

    # Truncates to at most 4-5 keywords
    assert len(sanitized.split()) <= 5

    # Enforces maximum 60 characters
    assert len(sanitized) <= 60

    # Handles empty / pure special characters
    assert ClinicalTrialsClient._sanitize_query_term("   ") == ""
    assert ClinicalTrialsClient._sanitize_query_term("%%++(())//") == ""


@pytest.mark.asyncio
async def test_search_studies_falls_back_to_cond_on_400_error(monkeypatch):
    """
    If ClinicalTrials.gov responds with HTTP 400 and query.term was present,
    it must log a warning and immediately retry using only query.cond.
    """
    from app.adapters.clinicaltrials import ClinicalTrialsAPIError, ClinicalTrialsClient

    client = ClinicalTrialsClient()
    calls = []

    async def fake_fetch(params):
        calls.append(dict(params))
        # Simulate ClinicalTrials.gov returning 400 when query.term is in params
        if "query.term" in params:
            raise ClinicalTrialsAPIError(
                "ClinicalTrials.gov returned an error (status 400).", status_code=400
            )
        return [SAMPLE_STUDY]

    monkeypatch.setattr(client, "_fetch_studies", fake_fetch)

    studies = await client.search_studies(
        {
            "query.cond": "non-small cell lung cancer",
            "query.term": "Stage IVB EGFR Exon 19 deletion ALK",
            "filter.overallStatus": "RECRUITING",
        }
    )

    assert len(studies) == 1
    assert len(calls) == 2
    # First call contained query.term
    assert "query.term" in calls[0]
    # Fallback call dropped query.term and kept query.cond
    assert "query.term" not in calls[1]
    assert calls[1]["query.cond"] == "non-small cell lung cancer"
    assert calls[1]["filter.overallStatus"] == "RECRUITING"


@pytest.mark.asyncio
async def test_search_studies_raises_400_if_no_query_term(monkeypatch):
    """
    If ClinicalTrials.gov responds with 400 and query.term was NOT present,
    the error should be raised normally rather than retrying.
    """
    from app.adapters.clinicaltrials import ClinicalTrialsAPIError, ClinicalTrialsClient

    client = ClinicalTrialsClient()

    async def fake_fetch(params):
        raise ClinicalTrialsAPIError(
            "ClinicalTrials.gov returned an error (status 400).", status_code=400
        )

    monkeypatch.setattr(client, "_fetch_studies", fake_fetch)

    with pytest.raises(ClinicalTrialsAPIError):
        await client.search_studies(
            {
                "query.cond": "malformed syntax",
                "filter.overallStatus": "RECRUITING",
            }
        )


def test_score_candidate_trial_biomarker_preference_and_conflict_penalty():
    query = StructuredQuery(
        condition="non-small cell lung cancer",
        stage="Stage IV",
        biomarkers=["EGFR exon 19 deletion"],
    )

    # 1. Matching EGFR trial
    egfr_trial = NormalizedTrial(
        nct_id="NCT00000001",
        title="Study of Osimertinib in EGFR Mutant Non-Small Cell Lung Cancer",
        status="RECRUITING",
        phase=["Phase 3"],
        conditions=["Non-Small Cell Lung Cancer"],
        eligibility_text="Inclusion Criteria: Must have documented EGFR exon 19 deletion.",
        brief_summary="Targeted therapy for patients with EGFR exon 19 deletion NSCLC.",
    )

    # 2. Conflicting KRAS trial
    kras_trial = NormalizedTrial(
        nct_id="NCT00000002",
        title="A Phase 2 Study of Sotorasib in KRAS G12C Non-Small Cell Lung Cancer",
        status="RECRUITING",
        phase=["Phase 2"],
        conditions=["Non-Small Cell Lung Cancer"],
        eligibility_text="Inclusion Criteria: Documented KRAS G12C mutation. Must be EGFR wild-type.",
        brief_summary="Evaluating KRAS G12C inhibition in advanced lung cancer.",
    )

    # 3. Generic trial without specific driver mutation headline
    generic_trial = NormalizedTrial(
        nct_id="NCT00000003",
        title="Chemotherapy vs Immunotherapy in Advanced Non-Small Cell Lung Cancer",
        status="RECRUITING",
        phase=["Phase 3"],
        conditions=["Non-Small Cell Lung Cancer"],
        eligibility_text="Inclusion Criteria: Patients with Stage IV NSCLC.",
        brief_summary="Comparing standard regimens.",
    )

    score_egfr = score_candidate_trial(egfr_trial, query)
    score_kras = score_candidate_trial(kras_trial, query)
    score_generic = score_candidate_trial(generic_trial, query)

    # Matching trial should score highly positive
    assert score_egfr > 20.0
    # Conflicting trial should be penalized heavily due to KRAS headline and EGFR wild-type restriction
    assert score_kras < 0.0
    # EGFR trial must score much higher than generic and conflicting trials
    assert score_egfr > score_generic > score_kras


def test_pre_rank_candidate_trials_sorts_by_score():
    query = StructuredQuery(
        condition="non-small cell lung cancer",
        stage="Stage IV",
        biomarkers=["EGFR"],
    )

    t_kras = NormalizedTrial(
        nct_id="NCT_KRAS",
        title="KRAS G12C Inhibitor in NSCLC",
        status="RECRUITING",
        phase=["Phase 2"],
        conditions=["NSCLC"],
        eligibility_text="Exclusion: EGFR mutation.",
    )
    t_generic = NormalizedTrial(
        nct_id="NCT_GENERIC",
        title="Pemetrexed Maintenance in Advanced Lung Adenocarcinoma",
        status="RECRUITING",
        phase=["Phase 3"],
        conditions=["Non-Small Cell Lung Cancer"],
        eligibility_text="Inclusion: Stage IV.",
    )
    t_egfr = NormalizedTrial(
        nct_id="NCT_EGFR",
        title="Osimertinib in Advanced EGFR-Mutated NSCLC",
        status="RECRUITING",
        phase=["Phase 3"],
        conditions=["Non-Small Cell Lung Cancer"],
        eligibility_text="Inclusion: Confirmed EGFR mutation, Stage IV.",
    )

    # Pass in scrambled order
    ranked = pre_rank_candidate_trials([t_kras, t_generic, t_egfr], query)

    assert len(ranked) == 3
    assert ranked[0].nct_id == "NCT_EGFR"
    assert ranked[1].nct_id == "NCT_GENERIC"
    assert ranked[2].nct_id == "NCT_KRAS"

