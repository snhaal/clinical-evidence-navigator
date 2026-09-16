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
    retrieve_candidate_trials,
)
from app.pipeline.schemas import StructuredQuery


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
