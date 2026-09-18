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


def test_build_query_params_enforces_primary_biomarker_in_term():
    # When biomarkers are present, pass the primary biomarker directly in query.term
    query_with_bm = StructuredQuery(
        condition="non-small cell lung cancer",
        stage="Stage IV",
        prior_therapy=["carboplatin/pemetrexed"],
        biomarkers=["EGFR exon 19 deletion"],
    )
    params_bm = build_query_params(query_with_bm)

    assert params_bm["query.cond"] == "non-small cell lung cancer"
    assert params_bm["query.term"] == "EGFR"
    assert params_bm.get("has_actionable_biomarker") is True

    # When no biomarkers are present, pass stage and prior therapy in query.term
    query_no_bm = StructuredQuery(
        condition="esophageal squamous cell carcinoma",
        stage="Stage III",
        prior_therapy=["neoadjuvant chemoradiation"],
    )
    params_no_bm = build_query_params(query_no_bm)

    assert params_no_bm["query.cond"] == "esophageal squamous cell carcinoma"
    assert "Stage III" in params_no_bm["query.term"]
    assert "neoadjuvant chemoradiation" in params_no_bm["query.term"]


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


def test_line_of_therapy_aware_filtering_and_boost():
    """
    When the patient has received prior chemotherapy (e.g. platinum doublet):
    - A trial strictly requiring treatment-naive / previously untreated is heavily penalized.
    - A trial targeting 2nd-line (2L+) or recurrent/metastatic EGFR inhibitor is boosted.
    """
    pre_treated_query = StructuredQuery(
        condition="non-small cell lung cancer",
        stage="Stage IV",
        biomarkers=["EGFR exon 19 deletion"],
        prior_therapy=["carboplatin/pemetrexed doublet chemotherapy"],
    )

    # 1. 2L+ trial targeting resistant/pre-treated EGFR NSCLC
    trial_2l = NormalizedTrial(
        nct_id="NCT_2L",
        title="Amivantamab and Lazertinib in Previously Treated EGFR-Mutated NSCLC Following Platinum-Based Chemotherapy",
        status="RECRUITING",
        phase=["Phase 3"],
        conditions=["Non-Small Cell Lung Cancer"],
        eligibility_text="Inclusion Criteria: Must have received prior platinum-based chemotherapy and progressed. Confirmed EGFR exon 19 deletion.",
        brief_summary="Evaluating second-line combination therapy post-platinum.",
    )

    # 2. 1L trial strictly requiring treatment-naive
    trial_1l = NormalizedTrial(
        nct_id="NCT_1L",
        title="First-Line Osimertinib in Treatment-Naive Patients with EGFR-Mutated Advanced NSCLC",
        status="RECRUITING",
        phase=["Phase 3"],
        conditions=["Non-Small Cell Lung Cancer"],
        eligibility_text="Inclusion Criteria: Must be previously untreated with no prior systemic chemotherapy for metastatic disease. Confirmed EGFR exon 19 deletion.",
        brief_summary="Front-line study in previously untreated patients.",
    )

    score_2l = score_candidate_trial(trial_2l, pre_treated_query)
    score_1l = score_candidate_trial(trial_1l, pre_treated_query)

    # 2L+ trial should score significantly higher than the 1L treatment-naive trial
    assert score_2l > 40.0
    assert score_2l > score_1l + 30.0


def test_prioritize_biomarker_inclusion_over_phase1_basket_trials():
    """
    Trials where the primary biomarker (e.g. EGFR) is an active inclusion criterion
    must rank above Phase 1 basket / safety trials.
    """
    query = StructuredQuery(
        condition="non-small cell lung cancer",
        stage="Stage IV",
        biomarkers=["EGFR exon 19 deletion"],
    )

    # 1. Targeted Phase 2 study with EGFR as active inclusion criterion
    targeted_trial = NormalizedTrial(
        nct_id="NCT_TARGETED",
        title="Phase 2 Study of Targeted EGFR TKI in EGFR-Mutant NSCLC",
        status="RECRUITING",
        phase=["Phase 2"],
        conditions=["Non-Small Cell Lung Cancer"],
        eligibility_text="Inclusion Criteria:\n- Documented EGFR exon 19 deletion\n- Stage IV NSCLC\nExclusion Criteria:\n- Prior severe toxicity",
        brief_summary="Assessing efficacy in EGFR-positive patients.",
    )

    # 2. Phase 1 basket / dose-escalation trial in advanced solid tumors
    basket_trial = NormalizedTrial(
        nct_id="NCT_BASKET",
        title="Phase 1 Dose Escalation and Safety Study of Novel Agent in Advanced Solid Tumors",
        status="RECRUITING",
        phase=["Phase 1"],
        conditions=["Advanced Solid Tumors"],
        eligibility_text="Inclusion Criteria:\n- Histologically confirmed advanced solid tumor\n- ECOG 0-1\nExclusion Criteria:\n- Active infection",
        brief_summary="First-in-human dose-escalation study evaluating safety and tolerability.",
    )

    score_targeted = score_candidate_trial(targeted_trial, query)
    score_basket = score_candidate_trial(basket_trial, query)

    assert score_targeted > score_basket + 30.0

    ranked = pre_rank_candidate_trials([basket_trial, targeted_trial], query)
    assert ranked[0].nct_id == "NCT_TARGETED"
    assert ranked[1].nct_id == "NCT_BASKET"


def test_build_stage_aware_query_broadens_with_stage_keywords():
    from app.adapters.clinicaltrials import (
        ClinicalTrialsClient,
        build_stage_aware_query,
    )

    # Combines TNBC with Stage IV / metastatic keywords
    q1 = build_stage_aware_query("Triple Negative Breast Cancer", "Stage IV")
    assert q1 == '"Triple Negative Breast Cancer" AND ("metastatic" OR "advanced" OR "Stage IV")'

    # Preserves boolean query if already present
    assert build_stage_aware_query(q1, "Stage IV") == q1

    # Stage III clause
    q3 = ClinicalTrialsClient.build_stage_aware_query("esophageal adenocarcinoma", "Stage III")
    assert q3 == '"esophageal adenocarcinoma" AND ("Stage III" OR "locally advanced")'

    # Condition without stage returns clean condition
    assert build_stage_aware_query("breast cancer", None) == "breast cancer"


@pytest.mark.asyncio
async def test_search_studies_fetches_20_and_broadens_with_stage(monkeypatch):
    from app.adapters.clinicaltrials import ClinicalTrialsClient

    client = ClinicalTrialsClient(max_results=20)
    calls = []

    async def fake_fetch(params):
        calls.append(dict(params))
        return [SAMPLE_STUDY]

    monkeypatch.setattr(client, "_fetch_studies", fake_fetch)

    await client.search_studies({
        "query.cond": "Triple Negative Breast Cancer",
        "stage": "Stage IV",
        "filter.overallStatus": "RECRUITING",
    })

    assert len(calls) == 1
    assert calls[0]["pageSize"] == 20
    assert calls[0]["query.cond"] == '"Triple Negative Breast Cancer" AND ("metastatic" OR "advanced" OR "Stage IV")'


@pytest.mark.asyncio
async def test_search_studies_removes_internal_flags_from_http_params(monkeypatch):
    from app.adapters.clinicaltrials import ClinicalTrialsClient

    client = ClinicalTrialsClient()
    calls = []

    async def fake_fetch(params):
        calls.append(dict(params))
        return [SAMPLE_STUDY]

    monkeypatch.setattr(client, "_fetch_studies", fake_fetch)

    await client.search_studies({
        "query.cond": "Non-small cell lung cancer",
        "query.term": "EGFR",
        "has_actionable_biomarker": True,
        "stage": "Stage IV",
        "filter.overallStatus": "RECRUITING",
    })

    assert len(calls) == 1
    sent_params = calls[0]
    assert "has_actionable_biomarker" not in sent_params
    assert "stage" not in sent_params
    assert sent_params["query.cond"] == "Non-small cell lung cancer"
    assert sent_params["query.term"] == "EGFR"
    assert sent_params["filter.overallStatus"] == "RECRUITING"
    assert sent_params["pageSize"] == 20
    assert sent_params["format"] == "json"


def test_stage_alignment_penalizes_neoadjuvant_and_resectable_for_stage_iv():
    stage_iv_query = StructuredQuery(
        condition="Triple Negative Breast Cancer",
        stage="Stage IV",
        biomarkers=["TNBC"],
    )

    t_neoadjuvant = NormalizedTrial(
        nct_id="NCT_NEO",
        title="Neoadjuvant Chemotherapy for Early Triple-Negative Breast Cancer",
        status="RECRUITING",
        phase=["Phase 3"],
        conditions=["Triple Negative Breast Cancer"],
        eligibility_text="Inclusion: Stage II-III resectable breast cancer.",
        brief_summary="Evaluating neoadjuvant therapy prior to surgery.",
    )

    t_metastatic = NormalizedTrial(
        nct_id="NCT_META",
        title="Sacituzumab Govitecan in Metastatic Triple-Negative Breast Cancer",
        status="RECRUITING",
        phase=["Phase 3"],
        conditions=["Triple Negative Breast Cancer"],
        eligibility_text="Inclusion: Documented metastatic or unresectable Stage IV TNBC.",
        brief_summary="Evaluating targeted ADC in metastatic setting.",
    )

    score_neo = score_candidate_trial(t_neoadjuvant, stage_iv_query)
    score_meta = score_candidate_trial(t_metastatic, stage_iv_query)

    # Metastatic study should strongly outrank neoadjuvant study for Stage IV patient
    assert score_meta > score_neo + 40.0
    ranked = pre_rank_candidate_trials([t_neoadjuvant, t_metastatic], stage_iv_query)
    assert ranked[0].nct_id == "NCT_META"


def test_cohort_specificity_penalizes_brain_metastases_when_patient_has_none():
    query_no_brain_mets = StructuredQuery(
        condition="Triple Negative Breast Cancer",
        stage="Stage IV",
        biomarkers=["TNBC"],
        exclusions=["no brain metastases"],
    )

    t_brain_mets = NormalizedTrial(
        nct_id="NCT_BRAIN",
        title="A Study of Systemic Therapy in Patients with Active Brain Metastases from Breast Cancer",
        status="RECRUITING",
        phase=["Phase 2"],
        conditions=["Breast Cancer"],
        eligibility_text="Inclusion: Documented active brain metastases.",
        brief_summary="Evaluating CNS-penetrant therapy.",
    )

    t_systemic = NormalizedTrial(
        nct_id="NCT_SYS",
        title="Standard Chemotherapy as First-line Treatment for Metastatic TNBC",
        status="RECRUITING",
        phase=["Phase 3"],
        conditions=["Triple Negative Breast Cancer"],
        eligibility_text="Inclusion: Metastatic TNBC.",
        brief_summary="Evaluating front-line metastatic therapy.",
    )

    score_brain = score_candidate_trial(t_brain_mets, query_no_brain_mets)
    score_sys = score_candidate_trial(t_systemic, query_no_brain_mets)

    # Systemic study should outrank specialized brain metastasis trial
    assert score_sys > score_brain + 40.0
    ranked = pre_rank_candidate_trials([t_brain_mets, t_systemic], query_no_brain_mets)
    assert ranked[0].nct_id == "NCT_SYS"


def test_biomarker_matching_in_brief_summary_and_tnbc_regimens():
    query = StructuredQuery(
        condition="Triple Negative Breast Cancer",
        stage="Stage IV",
        biomarkers=["PD-L1 positive", "CPS >= 10"],
    )

    t_with_summary_biomarker = NormalizedTrial(
        nct_id="NCT_PBL",
        title="Phase 3 Study of Pembrolizumab in Metastatic TNBC",
        status="RECRUITING",
        phase=["Phase 3"],
        conditions=["Triple Negative Breast Cancer"],
        eligibility_text="Inclusion: Advanced TNBC.",
        brief_summary="Evaluating pembrolizumab in PD-L1 positive patients.",
    )

    t_generic = NormalizedTrial(
        nct_id="NCT_GEN",
        title="Phase 3 Study in Advanced Breast Cancer",
        status="RECRUITING",
        phase=["Phase 3"],
        conditions=["Breast Cancer"],
        eligibility_text="Inclusion: Advanced breast cancer.",
        brief_summary="Comparing standard regimens.",
    )

    score_pbl = score_candidate_trial(t_with_summary_biomarker, query)
    score_gen = score_candidate_trial(t_generic, query)

    assert score_pbl > 35.0
    assert score_pbl > score_gen + 25.0


def test_exclude_obvious_biomarker_negatives_for_egfr():
    from app.pipeline.act import is_obvious_biomarker_negative

    query_egfr = StructuredQuery(
        condition="non-small cell lung cancer",
        stage="Stage IV",
        biomarkers=["EGFR exon 19 deletion"],
    )

    t_without_actionable = NormalizedTrial(
        nct_id="NCT_NO_MUT",
        title="Chemotherapy in Advanced Non-Small Cell Lung Cancer Without Actionable Mutations",
        status="RECRUITING",
        phase=["Phase 3"],
        conditions=["Non-Small Cell Lung Cancer"],
    )

    t_egfr_wt = NormalizedTrial(
        nct_id="NCT_WT",
        title="Immunotherapy in Patients With EGFR-wild-type Advanced NSCLC",
        status="RECRUITING",
        phase=["Phase 3"],
        conditions=["Non-Small Cell Lung Cancer"],
    )

    t_kras = NormalizedTrial(
        nct_id="NCT_KRAS_MUT",
        title="Study of Sotorasib in KRAS G12C Advanced NSCLC",
        status="RECRUITING",
        phase=["Phase 2"],
        conditions=["Non-Small Cell Lung Cancer"],
    )

    t_targeted_egfr = NormalizedTrial(
        nct_id="NCT_TARGETED_EGFR",
        title="Osimertinib in Patients With Advanced EGFR Mutation-Positive NSCLC",
        status="RECRUITING",
        phase=["Phase 3"],
        conditions=["Non-Small Cell Lung Cancer"],
    )

    assert is_obvious_biomarker_negative(t_without_actionable, query_egfr) is True
    assert is_obvious_biomarker_negative(t_egfr_wt, query_egfr) is True
    assert is_obvious_biomarker_negative(t_kras, query_egfr) is True
    assert is_obvious_biomarker_negative(t_targeted_egfr, query_egfr) is False

    # Check that score_candidate_trial assigns massive penalty
    score_without_act = score_candidate_trial(t_without_actionable, query_egfr)
    score_egfr_target = score_candidate_trial(t_targeted_egfr, query_egfr)
    assert score_without_act < -100.0
    assert score_egfr_target > 20.0


def test_deprioritize_phase_1_basket_when_targeted_phase_2_3_exists():
    query_egfr = StructuredQuery(
        condition="non-small cell lung cancer",
        stage="Stage IV",
        biomarkers=["EGFR"],
    )

    t_targeted_p3 = NormalizedTrial(
        nct_id="NCT_TARGETED_P3",
        title="Phase 3 Study of Osimertinib in Advanced EGFR-Mutated NSCLC",
        status="RECRUITING",
        phase=["Phase 3"],
        conditions=["Non-Small Cell Lung Cancer"],
    )

    t_phase1_fih = NormalizedTrial(
        nct_id="NCT_FIH",
        title="A Phase 1 First-in-Human Dose Escalation and Safety Study in Advanced Solid Tumors",
        status="RECRUITING",
        phase=["Phase 1"],
        conditions=["Advanced Solid Tumors"],
    )

    # When ranked together, targeted Phase 3 study must rank first and FIH Phase 1 study must be deprioritized
    ranked = pre_rank_candidate_trials([t_phase1_fih, t_targeted_p3], query_egfr)
    assert ranked[0].nct_id == "NCT_TARGETED_P3"
    assert ranked[1].nct_id == "NCT_FIH"


@pytest.mark.asyncio
async def test_retrieve_candidate_trials_filters_obvious_biomarker_negatives():
    query_egfr = StructuredQuery(
        condition="non-small cell lung cancer",
        stage="Stage IV",
        biomarkers=["EGFR exon 19 deletion"],
    )

    neg_study = {
        "protocolSection": {
            "identificationModule": {
                "nctId": "NCT_NEG",
                "briefTitle": "A Study in NSCLC Without Actionable Mutations",
            },
            "statusModule": {"overallStatus": "RECRUITING"},
            "designModule": {"phases": ["PHASE3"]},
            "conditionsModule": {"conditions": ["Non-Small Cell Lung Cancer"]},
            "eligibilityModule": {"eligibilityCriteria": "Inclusion: NSCLC."},
        }
    }

    pos_study = {
        "protocolSection": {
            "identificationModule": {
                "nctId": "NCT_POS",
                "briefTitle": "A Study of Osimertinib in EGFR-Mutated NSCLC",
            },
            "statusModule": {"overallStatus": "RECRUITING"},
            "designModule": {"phases": ["PHASE3"]},
            "conditionsModule": {"conditions": ["Non-Small Cell Lung Cancer"]},
            "eligibilityModule": {"eligibilityCriteria": "Inclusion: Confirmed EGFR mutation."},
        }
    }

    client = FakeClinicalTrialsClient(studies=[neg_study, pos_study])
    retrieved = await retrieve_candidate_trials(query_egfr, client=client)

    # Obvious biomarker negative should be filtered out
    retrieved_nct_ids = [t.nct_id for t in retrieved]
    assert "NCT_NEG" not in retrieved_nct_ids
    assert "NCT_POS" in retrieved_nct_ids



