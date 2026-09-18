"""
Act stage.

Owns exactly one translation: StructuredQuery -> ClinicalTrials.gov API v2
query params, and raw study JSON -> NormalizedTrial. It calls the thin
ClinicalTrialsClient adapter (app/adapters/clinicaltrials.py) for the
actual HTTP request; this module never touches httpx directly, so a
schema/rate-limit change on the ClinicalTrials.gov side is isolated to
the adapter (Risk register: "thin adapter layer isolates the API call").
"""

import logging
import re

from app.adapters.clinicaltrials import ClinicalTrialsAPIError, ClinicalTrialsClient
from app.pipeline.schemas import NormalizedTrial, StructuredQuery

logger = logging.getLogger(__name__)


class ActStageError(Exception):
    """
    Raised when retrieval fails outright. Callers must surface a visible,
    specific error state — never a silent empty result (NFR: Reliability).
    """


COMMON_CANCER_GENES = {
    "egfr", "her2", "erbb2", "braf", "kras", "alk", "ros1", "met",
    "ret", "ntrk", "brca1", "brca2", "pik3ca", "pdl1", "pd-l1", "msi-h", "dmmr"
}

COMMON_CANCER_GENES_MAP = {
    "egfr": "EGFR",
    "her2": "HER2",
    "erbb2": "HER2",
    "braf": "BRAF",
    "kras": "KRAS",
    "alk": "ALK",
    "ros1": "ROS1",
    "met": "MET",
    "ret": "RET",
    "ntrk": "NTRK",
    "brca1": "BRCA1",
    "brca2": "BRCA2",
    "pik3ca": "PIK3CA",
    "pdl1": "PD-L1",
    "pd-l1": "PD-L1",
    "msi-h": "MSI-H",
    "dmmr": "dMMR",
}


def extract_primary_biomarker(biomarkers: list[str]) -> str | None:
    """
    Extracts the primary actionable biomarker symbol (e.g. 'EGFR', 'HER2', 'PD-L1')
    from the patient's detected biomarkers.
    """
    if not biomarkers:
        return None
    for bm in biomarkers:
        bm_clean = re.sub(r"[^\w\-]", " ", bm.lower())
        for token in bm_clean.split():
            if token in COMMON_CANCER_GENES_MAP:
                return COMMON_CANCER_GENES_MAP[token]
    first_bm = biomarkers[0].strip()
    clean_first = re.sub(r"[()%:;,/+=<>]", " ", first_bm).strip()
    words = clean_first.split()
    if words:
        return " ".join(words[:2])
    return None


def build_query_params(query: StructuredQuery) -> dict:
    """
    Maps StructuredQuery fields onto the API v2 search fields:
    - When patient biomarkers are present (e.g., 'EGFR', 'Exon 19 deletion', 'HER2', 'PD-L1'),
      passes the primary biomarker directly into ClinicalTrials.gov API parameters:
      * `query.cond`: Primary condition (e.g., 'Non-small cell lung cancer').
      * `query.term`: Primary actionable biomarker (e.g., 'EGFR').
      Do NOT query only on condition alone when actionable mutations are detected.
    - When no biomarkers are present, uses condition and stage/prior therapy terms.
    """
    params: dict = {"query.cond": query.condition}

    primary_bm = extract_primary_biomarker(query.biomarkers)
    if primary_bm:
        params["query.term"] = primary_bm
        params["has_actionable_biomarker"] = True
    else:
        if query.stage:
            params["stage"] = query.stage

        term_parts: list[str] = []
        if query.stage:
            term_parts.append(query.stage)
        if query.prior_therapy:
            term_parts.extend(query.prior_therapy)

        if term_parts:
            params["query.term"] = " ".join(term_parts)

    if query.status_filter:
        params["filter.overallStatus"] = query.status_filter

    return params


def _first_or_none(value) -> str | None:
    if isinstance(value, list) and value:
        return value[0]
    if isinstance(value, str):
        return value
    return None


def normalize_study(raw_study: dict) -> NormalizedTrial | None:
    """
    Reduces one raw ClinicalTrials.gov API v2 study object to a
    NormalizedTrial. Returns None (rather than raising) for a study
    missing an NCT ID or title — malformed individual records shouldn't
    fail the whole retrieval, they should just be skipped and logged.
    """
    protocol = raw_study.get("protocolSection", {})
    identification = protocol.get("identificationModule", {})
    status_module = protocol.get("statusModule", {})
    design_module = protocol.get("designModule", {})
    conditions_module = protocol.get("conditionsModule", {})
    description_module = protocol.get("descriptionModule", {})
    eligibility_module = protocol.get("eligibilityModule", {})

    nct_id = identification.get("nctId")
    title = identification.get("briefTitle") or identification.get("officialTitle")

    if not nct_id or not title:
        logger.warning("Skipping study with missing nctId/title: %s", identification)
        return None

    brief_summary = description_module.get("briefSummary", "") or ""

    return NormalizedTrial(
        nct_id=nct_id,
        title=title,
        status=status_module.get("overallStatus"),
        phase=design_module.get("phases", []) or [],
        conditions=conditions_module.get("conditions", []) or [],
        brief_summary=brief_summary,
        eligibility_text=eligibility_module.get("eligibilityCriteria", "") or "",
    )


def score_candidate_trial(
    trial: NormalizedTrial,
    query: StructuredQuery,
    has_targeted_phase_2_3: bool = False,
) -> float:
    """
    Deterministic pre-ranking score for candidate trials before LLM verification:
    - Heavily rewards matching biomarkers/mutations, prioritizing trials where the
      primary biomarker is an active inclusion criterion.
    - Penalizes Phase 1 basket / safety / dose-escalation trials in favor of targeted studies.
    - Filters/penalizes trials requiring treatment-naive / first-line when patient has prior
      therapy, and boosts 2nd-line (2L+) / recurrent / refractory studies.
    - Penalizes trials centered on conflicting driver mutations (e.g. KRAS for an EGFR patient).
    - Rewards histology and stage alignment.
    """
    score = 0.0
    title_lower = trial.title.lower()
    summary_lower = trial.brief_summary.lower()
    eligibility_lower = trial.eligibility_text.lower()
    conditions_text = " ".join(trial.conditions).lower()

    # Split eligibility text into inclusion and exclusion sections
    eligibility_parts = re.split(r"\b(?:key\s+)?exclusion(?:\s+criteria)?:?", eligibility_lower)
    inclusion_text = eligibility_parts[0] if eligibility_parts else eligibility_lower
    exclusion_text = eligibility_parts[1] if len(eligibility_parts) > 1 else ""

    # Identify patient driver genes
    patient_genes = set()
    for bm in query.biomarkers:
        bm_clean = re.sub(r"[^\w\s\-]", " ", bm.lower())
        for word in bm_clean.split():
            if word in COMMON_CANCER_GENES:
                patient_genes.add(word)

    # 1. Biomarker scoring: Active inclusion criteria and brief summary prioritized
    for bm in query.biomarkers:
        bm_lower = bm.lower().strip()
        if not bm_lower:
            continue

        # Check full biomarker phrase
        if bm_lower in title_lower:
            score += 18.0
        elif bm_lower in summary_lower:
            score += 15.0

        if bm_lower in inclusion_text:
            score += 12.0
        elif bm_lower in eligibility_lower and not (exclusion_text and bm_lower in exclusion_text):
            score += 6.0

        # Sub-token matching (e.g., "exon 19", "l858r", "t790m", "v600e")
        for token in re.split(r"[,\s]+", bm_lower):
            if len(token) >= 3:
                if token in title_lower:
                    score += 6.0
                elif token in inclusion_text or token in summary_lower:
                    score += 5.0

    # Primary biomarker active inclusion criterion bonus vs exclusion penalty
    for pg in patient_genes:
        if re.search(rf"\b{re.escape(pg)}\b", inclusion_text):
            score += 16.0
            if re.search(rf"\b{re.escape(pg)}\b", title_lower):
                score += 12.0
        # If trial explicitly lists patient's gene under exclusion criteria
        if exclusion_text and re.search(rf"\b{re.escape(pg)}\b", exclusion_text):
            score -= 25.0

    # Conflicting driver mutation penalty
    # e.g., if patient has EGFR, penalize trials targeting other mutually exclusive drivers (like KRAS)
    if patient_genes:
        conflicting_genes = (COMMON_CANCER_GENES - patient_genes) - {"pdl1", "pd-l1", "msi-h", "dmmr"}
        for cg in conflicting_genes:
            # If trial explicitly headlines a conflicting gene without patient's gene
            if re.search(rf"\b{re.escape(cg)}\b", title_lower) and not any(
                pg in title_lower for pg in patient_genes
            ):
                score -= 15.0
            # Explicit wild-type restriction against patient's gene
            for pg in patient_genes:
                if re.search(rf"{re.escape(pg)}[\s\-]+wild[\s\-]*type|without[\s\-]+{re.escape(pg)}", eligibility_lower):
                    score -= 18.0

    # 2. Line-of-therapy aware retrieval & filtering
    patient_pre_treated = bool(query.prior_therapy) and not all(
        pt.strip().lower() in {"none", "no prior therapy", "naive", "treatment-naive", "untreated"}
        for pt in query.prior_therapy
    )

    is_trial_treatment_naive = bool(
        re.search(
            r"\b(treatment[\s\-]+na[iï]ve|previously[\s\-]+untreated|no\s+prior\s+(systemic|chemo\w*|therapy|treatment)|first[\s\-]+line|1st[\s\-]+line|\b1l\b|front[\s\-]+line)\b",
            title_lower,
        )
        or re.search(
            r"\b(treatment[\s\-]+na[iï]ve|previously[\s\-]+untreated|no\s+prior\s+(systemic|chemo\w*|therapy|treatment))\b",
            inclusion_text,
        )
    )

    is_trial_pre_treated = bool(
        re.search(
            r"\b(second[\s\-]+line|2nd[\s\-]+line|\b2l\+?\b|third[\s\-]+line|\b3l\+?\b|subsequent[\s\-]+line|previously[\s\-]+treated|prior\s+(systemic|chemo\w*|platinum|therapy|treatment|lines?|tki)|recurrent|relapsed|refractory|resistant|progressed|progression|post[\s\-]+platinum|after\s+(prior|platinum|chemo\w*|osimertinib|tki))\b",
            title_lower + " " + summary_lower + " " + inclusion_text,
        )
    )

    if patient_pre_treated:
        # Pre-treated patient: filter/penalize naive trials, target 2L+ / resistant / recurrent studies
        if is_trial_treatment_naive:
            score -= 35.0
        if is_trial_pre_treated:
            score += 16.0
            # Target 2nd-line (2L+) or recurrent/metastatic EGFR inhibitor trials for pre-treated patients
            if "egfr" in patient_genes and (
                re.search(
                    r"\b(osimertinib|t790m|c797s|amivantamab|lazertinib|egfr[\s\-]+tki|her3|adc)\b",
                    title_lower + " " + summary_lower,
                )
                or re.search(
                    r"\b(resistant|refractory|progressed|post[\s\-]+platinum)\b",
                    title_lower,
                )
            ):
                score += 14.0
    else:
        # Treatment-naive patient
        if is_trial_treatment_naive:
            score += 12.0
        elif is_trial_pre_treated:
            score -= 22.0

    # 3. Penalize Phase 1 basket/safety trials in favor of disease/biomarker targeted studies
    is_strictly_phase_1 = any("phase 1" in p.lower() or "phase1" in p.lower() for p in trial.phase) and not any(
        "phase 2" in p.lower() or "phase 3" in p.lower() for p in trial.phase
    )
    is_basket_or_dose_escalation = bool(
        re.search(
            r"\b(basket|dose[\s\-]+escalation|dose[\s\-]+finding|first[\s\-]+in[\s\-]+human|\bfih\b|safety\s+(and|&)\s+tolerability|maximum\s+tolerated\s+dose)\b",
            title_lower,
        )
        or re.search(r"\b(solid\s+tumors?|advanced\s+solid\s+tumors?|advanced\s+malignancies?)\b", conditions_text)
    )

    if is_strictly_phase_1 and is_basket_or_dose_escalation:
        has_specific_patient_gene_focus = any(pg in title_lower for pg in patient_genes)
        if not has_specific_patient_gene_focus:
            score -= 25.0
        # Deprioritize Phase 1 first-in-human / dose-escalation basket studies if targeted Phase 2/3 trials exist
        if has_targeted_phase_2_3:
            score -= 40.0

    # 4. Stage Alignment: If patient is Stage IV / metastatic, penalize or exclude trials
    # mentioning "neoadjuvant", "resectable", "stage I-III", or "M0" in title/summary
    cond_lower = query.condition.lower()
    stage_lower = (query.stage or "").lower().strip()
    patient_is_metastatic = bool(
        stage_lower
        and any(
            st in stage_lower
            for st in ["iv", "4", "metastat", "advanced", "m1"]
        )
    ) or any(
        st in cond_lower
        for st in ["stage iv", "stage 4", "metastat", "advanced"]
    )

    if patient_is_metastatic:
        early_pattern = (
            r"\b(neoadjuvant|(?<!un)resectable|stage\s+(?:i{1,3}|[1-3])\b|"
            r"stage\s+[i|1]\s*-\s*(?:iii|3)\b|\bm0\b|[t][0-4][n][0-3]m0\b|early[\s\-]+stage)\b"
        )
        has_early_title = bool(re.search(early_pattern, title_lower)) and not bool(
            re.search(r"\b(unresectable|non-resectable)\b", title_lower)
        )
        has_early_summary = bool(re.search(early_pattern, summary_lower)) and not bool(
            re.search(r"\b(unresectable|non-resectable)\b", summary_lower)
        )
        if has_early_title:
            score -= 50.0
        elif has_early_summary:
            score -= 35.0

    # 5. Cohort Specificity: If patient has NO brain metastases, exclude/deprioritize trials with "brain metastases" in title
    patient_has_brain_mets = any(
        "brain" in x.lower() or "cns" in x.lower() or "leptomeningeal" in x.lower()
        for x in [query.condition, *query.biomarkers]
    )
    has_explicit_no_brain_mets = any(
        re.search(
            r"\b(no|without|negative|denies|free\s+of)\s+(?:active\s+)?(?:brain|cns|leptomeningeal)\b",
            ex.lower(),
        )
        for ex in query.exclusions
    ) or any(
        ex.strip().lower()
        in {"no brain metastases", "brain metastases", "cns metastases", "leptomeningeal disease"}
        for ex in query.exclusions
    )

    if not patient_has_brain_mets or has_explicit_no_brain_mets:
        if re.search(r"\b(brain\s+metasta\w+|cns\s+metasta\w+|leptomeningeal)\b", title_lower):
            score -= 50.0
        elif re.search(r"\b(brain\s+metasta\w+|cns\s+metasta\w+)\b", summary_lower):
            score -= 25.0

    # 6. Generic TNBC first-line regimens
    is_tnbc = (
        "triple negative" in cond_lower
        or "tnbc" in cond_lower
        or any("tnbc" in bm.lower() or "triple negative" in bm.lower() for bm in query.biomarkers)
    )
    if is_tnbc:
        tnbc_regimens = [
            "pembrolizumab", "keytruda", "sacituzumab", "trodelvy", "atezolizumab",
            "carboplatin", "cisplatin", "paclitaxel", "nab-paclitaxel", "abraxane",
            "gemcitabine", "olaparib", "talazoparib", "datopotamab", "chemotherapy",
            "immunotherapy",
        ]
        regimen_hits = sum(1 for reg in tnbc_regimens if reg in title_lower or reg in summary_lower)
        if regimen_hits > 0:
            score += min(18.0, regimen_hits * 6.0)

    # 7. Histology / Condition matching
    histology_terms = [
        "adenocarcinoma", "squamous", "non-small cell", "nsclc", "small cell", "sclc",
        "melanoma", "carcinoma", "sarcoma", "glioblastoma", "cholangiocarcinoma",
        "leukemia", "lymphoma", "myeloma", "colorectal", "breast", "prostate", "lung"
    ]
    for ht in histology_terms:
        if ht in cond_lower:
            if ht in title_lower:
                score += 6.0
            elif ht in conditions_text or ht in summary_lower:
                score += 4.0
            elif ht in eligibility_lower:
                score += 2.0

    # 8. Stage matching
    if query.stage:
        stage_clean = query.stage.lower().strip()
        stage_terms = [stage_clean]
        if "iv" in stage_clean or "4" in stage_clean:
            stage_terms.extend(["metastatic", "advanced", "stage iv"])
        elif "iii" in stage_clean or "3" in stage_clean:
            stage_terms.extend(["stage iii", "locally advanced", "unresectable"])

        for st in stage_terms:
            if st in title_lower:
                score += 4.0
                break
            elif st in summary_lower or st in eligibility_lower:
                score += 2.0
                break

    # 9. Phase preference (Phase 2 or 3 preferred for active therapeutic evaluation)
    for p in trial.phase:
        p_lower = p.lower()
        if "phase 2" in p_lower or "phase 3" in p_lower:
            score += 3.0
            break

    # 10. Obvious biomarker negative penalty
    if is_obvious_biomarker_negative(trial, query):
        score -= 200.0

    return score


def is_obvious_biomarker_negative(trial: NormalizedTrial, query: StructuredQuery) -> bool:
    """
    Returns True if the trial explicitly excludes or contradicts the patient's
    actionable driver mutation in its title (e.g., 'Without Actionable Mutations',
    'EGFR-wild-type', or 'KRAS' for an EGFR patient).
    """
    title_lower = trial.title.lower()
    patient_genes = set()
    for bm in query.biomarkers:
        bm_clean = re.sub(r"[^\w\-]", " ", bm.lower())
        for word in bm_clean.split():
            if word in COMMON_CANCER_GENES:
                patient_genes.add(word)

    patient_has_egfr = "egfr" in patient_genes or any("egfr" in bm.lower() for bm in query.biomarkers)
    if patient_has_egfr:
        if re.search(r"\bwithout\s+actionable\s+(?:mutations?|alterations?|drivers?|oncogenes?)\b", title_lower):
            return True
        if re.search(r"\begfr[\s\-]+wild[\s\-]*type\b|\begfr[\s\-]+wt\b", title_lower):
            return True
        if re.search(r"\bkras\b", title_lower):
            return True
    return False


def pre_rank_candidate_trials(
    trials: list[NormalizedTrial], query: StructuredQuery
) -> list[NormalizedTrial]:
    """
    Ranks candidates by relevance score descending so the most biomarker- and
    histology-aligned studies are verified first.
    Deprioritizes Phase 1 first-in-human / dose-escalation basket studies
    if targeted Phase 2/3 trials exist for the condition.
    """
    if not trials or not query:
        return trials

    # Check if targeted Phase 2/3 trials exist in the candidate pool
    has_targeted_phase_2_3 = any(
        any("phase 2" in p.lower() or "phase 3" in p.lower() for p in t.phase)
        and not bool(
            re.search(
                r"\b(basket|dose[\s\-]+escalation|dose[\s\-]+finding|first[\s\-]+in[\s\-]+human|\bfih\b)\b",
                t.title.lower(),
            )
        )
        for t in trials
    )

    scored_trials = [
        (trial, score_candidate_trial(trial, query, has_targeted_phase_2_3=has_targeted_phase_2_3))
        for trial in trials
    ]
    scored_trials.sort(key=lambda item: item[1], reverse=True)
    return [trial for trial, _score in scored_trials]


async def retrieve_candidate_trials(
    query: StructuredQuery,
    client: ClinicalTrialsClient | None = None,
) -> list[NormalizedTrial]:
    """
    Main entry point for the Act stage. Retrieves recruiting studies from
    ClinicalTrials.gov, normalizes them, filters obvious biomarker negatives,
    and deterministically pre-ranks them based on biomarker, condition, and stage alignment.
    """
    client = client or ClinicalTrialsClient()
    params = build_query_params(query)

    try:
        raw_studies = await client.search_studies(params)
    except ClinicalTrialsAPIError as exc:
        logger.error("Act stage retrieval failed: %s", exc)
        raise ActStageError(str(exc)) from exc

    trials = [normalize_study(s) for s in raw_studies]
    valid_trials = [t for t in trials if t is not None]

    # Exclude obvious biomarker negatives from candidate pool if other candidates exist
    filtered_trials = [t for t in valid_trials if not is_obvious_biomarker_negative(t, query)]
    trials_to_rank = filtered_trials if filtered_trials else valid_trials

    # Deterministic biomarker-aware pre-ranking
    ranked_trials = pre_rank_candidate_trials(trials_to_rank, query)
    return ranked_trials
