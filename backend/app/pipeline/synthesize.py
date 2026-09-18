"""
Synthesize stage.

Pure aggregation logic, no LLM call: given a trial's criterion verdicts,
compute an overall verdict and rank trials. The one guardrail called out
explicitly in the project plan lives here: "a single unmet hard-exclusion
criterion should override an otherwise high match score."
"""

import re

from app.pipeline.schemas import CriterionVerdict, NormalizedTrial, TrialMatchSummary

_TIER_RANK_PRIORITY = {
    "eligible": 0,
    "candidate_match": 1,
    "likely_match": 1,
    "match": 1,
    "unclear": 2,
    "no_match": 3,
}

CORE_ONCOLOGIC_PATTERNS = [
    # Histology, Diagnosis & Cancer Type
    r"\b(cancer|carcinoma|adenocarcinoma|squamous|sarcoma|melanoma|leukemia|lymphoma|myeloma|neoplasm|malignan\w+|tumor|tumour|nsclc|sclc|tnbc)\b",
    # Staging & Metastatic Status
    r"\b(stage\s+[i|1|2|3|4|iv|iii|ii]+|metastat\w+|locally\s+advanced|advanced\s+disease|unresectable|resectable|m0|m1)\b",
    # Biomarkers, Genes & Molecular Targets
    r"\b(egfr|her2|erbb2|braf|kras|alk|ros1|met|ret|ntrk|brca[12]?|pik3ca|pdl1|pd-l1|msi-h|dmmr)\b",
    r"\b(mutation|alteration|amplification|deletion|rearrangement|fusion|exon\s*\d+|wild[\s\-]*type|wt)\b",
    # Line of Therapy & Prior Treatment
    r"\b(prior\s+(?:systemic|therapy|line|lines|treatment|chemo\w*|platinum|tki)|line\s+of\s+therapy|1l|2l|3l|treatment[\s\-]+na[iï]ve|previously\s+untreated|recurrent|relapsed|refractory|resistant|progressed|progression|osimertinib|tki)\b",
]

ROUTINE_LAB_SCREENING_PATTERNS = [
    # Hematology / Bone marrow
    r"\b(anc|neutrophils?|absolute\s+neutrophil\s+count)\b",
    r"\b(platelets?|thrombocytes?)\b",
    r"\b(hemoglobin|hgb|hematocrit)\b",
    r"\b(wbc|white\s+blood\s+cells?)\b",
    r"\b(coagulation|inr|aptt|pt/inr)\b",
    r"\bbone\s+marrow\s+function\b",
    # Hepatic / Liver function
    r"\b(alt|ast|sgpt|sgot|transaminases?)\b",
    r"\b(bilirubin|total\s+bilirubin)\b",
    r"\b(alkaline\s+phosphatase|alp)\b",
    r"\b(liver\s+function|hepatic\s+function|lfts?)\b",
    # Renal / Kidney function
    r"\b(creatinine|crcl|creatinine\s+clearance|estimated\s+glomerular\s+filtration\s+rate|gfr)\b",
    r"\b(bun|blood\s+urea\s+nitrogen|renal\s+function)\b",
    r"\bproteinuria\b",
    # Performance status
    r"\b(ecog|karnofsky|zubrod|performance\s+status|ps\s*[0-2])\b",
    # Cardiac / Pulmonary
    r"\b(lvef|left\s+ventricular\s+ejection\s+fraction)\b",
    r"\b(qtc|ecg|electrocardiogram)\b",
    r"\bcardiac\s+function\b",
    # Routine screening / logistics / safety
    r"\b(pregnancy\s+test|contraception|barrier\s+method)\b",
    r"\b(informed\s+consent|ability\s+to\s+swallow)\b",
    r"\b(life\s+expectancy|recovery\s+from\s+(prior\s+)?toxicities?)\b",
    r"\bwashout\s+period\b",
]


def is_core_oncologic_criterion(verdict: CriterionVerdict) -> bool:
    """
    Returns True if the criterion corresponds to primary disease histology,
    cancer stage, target driver biomarkers, or line-of-therapy requirements.
    """
    text = f"{verdict.cited_text} {verdict.rationale}".lower()
    return any(re.search(pat, text) for pat in CORE_ONCOLOGIC_PATTERNS)


def is_routine_lab_or_screening_criterion(verdict: CriterionVerdict) -> bool:
    """
    Returns True if the criterion corresponds to routine laboratory, organ function,
    performance status, or standard protocol screening requirements (which are
    frequently pending or unstated in clinical referral summaries).
    Core oncologic criteria (condition, stage, biomarkers, therapy line) are NEVER routine.
    """
    if is_core_oncologic_criterion(verdict):
        return False
    text = f"{verdict.cited_text} {verdict.rationale}".lower()
    return any(re.search(pat, text) for pat in ROUTINE_LAB_SCREENING_PATTERNS)


def summarize_trial(
    trial: NormalizedTrial, verdicts: list[CriterionVerdict]
) -> TrialMatchSummary:
    """
    Aggregates one trial's per-criterion verdicts into an overall verdict with
    calibrated clinical match tiering.

    Logic:
      - hard_exclusion_hit = True if ANY exclusion criterion verdict is "match"
        (the patient matches something they should be excluded for).
        This alone forces overall_verdict = "no_match" and match_tier = "no_match".
      - Otherwise, if any inclusion criterion is a confirmed "no_match",
        overall_verdict = "no_match" and match_tier = "no_match".
      - Otherwise, if zero disease / inclusion criteria matched,
        overall_verdict = "no_match" and match_tier = "no_match".
      - Otherwise, if all inclusion criteria matched (unclear_count == 0),
        overall_verdict = "match" and match_tier = "eligible".
      - Otherwise (unclear_count > 0):
        * If ALL unclear criteria are routine screening labs / organ function /
          performance status parameters (LFTs, CBC, ECOG, etc.), the trial is
          marked as a positive match: overall_verdict = "match" and
          match_tier = "candidate_match" (Likely Eligible / Candidate Match).
        * If any core clinical criterion (condition, stage, biomarker, histology)
          is unclear, overall_verdict = "unclear" and match_tier = "unclear".
    """
    inclusion_verdicts = [v for v in verdicts if v.criterion_type == "inclusion"]
    exclusion_verdicts = [v for v in verdicts if v.criterion_type == "exclusion"]

    hard_exclusion_hit = any(v.verdict == "match" for v in exclusion_verdicts)
    satisfied_count = sum(1 for v in inclusion_verdicts if v.verdict == "match")
    unclear_count = sum(1 for v in verdicts if v.verdict == "unclear")
    inclusion_no_match = any(v.verdict == "no_match" for v in inclusion_verdicts)

    if not verdicts:
        overall_verdict = "unclear"
        match_tier = "unclear"
    elif hard_exclusion_hit or inclusion_no_match:
        overall_verdict = "no_match"
        match_tier = "no_match"
    elif satisfied_count > 0:
        if unclear_count == 0:
            overall_verdict = "match"
            match_tier = "eligible"
        else:
            unclear_verdicts = [v for v in verdicts if v.verdict == "unclear"]
            non_routine_unclears = [
                v
                for v in unclear_verdicts
                if not is_routine_lab_or_screening_criterion(v)
            ]

            if not non_routine_unclears:
                # ALL specified clinical criteria (condition, stage, histology, target biomarkers)
                # are satisfied, and the only unclear criteria are routine screening labs!
                overall_verdict = "match"
                match_tier = "candidate_match"
            else:
                overall_verdict = "unclear"
                match_tier = "unclear"
    else:
        # satisfied_count == 0 with only unclear criteria and no confirmed hard exclusion or no_match
        overall_verdict = "unclear"
        match_tier = "unclear"

    return TrialMatchSummary(
        nct_id=trial.nct_id,
        title=trial.title,
        overall_verdict=overall_verdict,
        satisfied_count=satisfied_count,
        unclear_count=unclear_count,
        hard_exclusion_hit=hard_exclusion_hit,
        criterion_verdicts=verdicts,
        phase=trial.phase,
        status=trial.status,
        match_tier=match_tier,
    )


def rank_trials(summaries: list[TrialMatchSummary]) -> list[TrialMatchSummary]:
    """
    Sort final evaluated trials by clinical relevance:
      1. Hard exclusion hit: False (0) before True (1).
      2. Primary tier: Eligible (eligible: 0, candidate_match/match: 1)
                       > Unclear (2)
                       > No Match (3).
      3. Secondary score: Criteria satisfaction ratio (satisfied_criteria / total_extracted_criteria) descending
         (so a 5/5 match ranks above a 6/20 match).
      4. Tie-breaker 1: raw satisfied_count descending.
      5. Tie-breaker 2: unclear_count ascending.
    """
    def _sort_key(s: TrialMatchSummary):
        total_criteria = len(s.criterion_verdicts)
        satisfaction_ratio = (
            (s.satisfied_count / total_criteria) if total_criteria > 0 else 0.0
        )
        tier_val = _TIER_RANK_PRIORITY.get(s.match_tier or s.overall_verdict, 2)
        return (
            s.hard_exclusion_hit,  # False (0) sorts before True (1)
            tier_val,             # Eligible (0/1) > Unclear (2) > No Match (3)
            -satisfaction_ratio,  # Satisfaction ratio descending (e.g. 5/5 > 6/20)
            -s.satisfied_count,   # Tie-breaker 1: raw satisfied count descending
            s.unclear_count,      # Tie-breaker 2: unclear criteria ascending
        )

    return sorted(summaries, key=_sort_key)


def synthesize_results(
    trials: list[NormalizedTrial],
    verdicts_by_nct_id: dict[str, list[CriterionVerdict]],
) -> list[TrialMatchSummary]:
    """
    Main entry point for the Synthesize stage. Trials with no verdicts
    recorded (e.g. Ground stage found zero criteria) still appear in the
    output as fully "unclear" with satisfied_count 0, rather than being
    silently dropped — an empty verdict list is a data gap to surface,
    not a reason to hide the trial.
    """
    summaries = [
        summarize_trial(trial, verdicts_by_nct_id.get(trial.nct_id, []))
        for trial in trials
    ]
    return rank_trials(summaries)
