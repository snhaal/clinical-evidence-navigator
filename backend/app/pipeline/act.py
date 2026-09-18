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


def build_query_params(query: StructuredQuery) -> dict:
    """
    Maps StructuredQuery fields onto the API v2 search fields:
    `query.cond` for the primary condition/diagnosis,
    `query.term` prioritizing detected biomarkers/mutations (e.g., EGFR, exon 19 deletion, HER2, BRAF),
    disease stage, and prior therapies. Exclusions are checked in Verify stage.
    """
    params: dict = {"query.cond": query.condition}

    term_parts: list[str] = []
    # Prioritize detected positive biomarkers/mutations first
    if query.biomarkers:
        term_parts.extend(query.biomarkers)
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


def score_candidate_trial(trial: NormalizedTrial, query: StructuredQuery) -> float:
    """
    Deterministic pre-ranking score for candidate trials before LLM verification:
    - Heavily rewards matching biomarkers/mutations (title, summary, criteria).
    - Penalizes trials centered on conflicting driver mutations (e.g. KRAS for an EGFR patient).
    - Rewards histology and stage alignment.
    """
    score = 0.0
    title_lower = trial.title.lower()
    summary_lower = trial.brief_summary.lower()
    eligibility_lower = trial.eligibility_text.lower()
    conditions_text = " ".join(trial.conditions).lower()

    # Identify patient driver genes
    patient_genes = set()
    for bm in query.biomarkers:
        bm_clean = re.sub(r"[^\w\s\-]", " ", bm.lower())
        for word in bm_clean.split():
            if word in COMMON_CANCER_GENES:
                patient_genes.add(word)

    # 1. Biomarker scoring & conflicting mutation detection
    for bm in query.biomarkers:
        bm_lower = bm.lower().strip()
        if not bm_lower:
            continue

        # Check full biomarker phrase or sub-phrases
        if bm_lower in title_lower:
            score += 15.0
        elif bm_lower in summary_lower:
            score += 8.0
        elif bm_lower in eligibility_lower:
            score += 6.0

        # Sub-token matching (e.g., "exon 19", "l858r", "t790m", "v600e")
        for token in re.split(r"[,\s]+", bm_lower):
            if len(token) >= 3:
                if token in title_lower:
                    score += 6.0
                elif token in summary_lower or token in eligibility_lower:
                    score += 3.0

    # Conflicting driver mutation penalty
    # e.g., if patient has EGFR, penalize trials targeting other mutually exclusive drivers (like KRAS)
    if patient_genes:
        conflicting_genes = (COMMON_CANCER_GENES - patient_genes) - {"pdl1", "pd-l1", "msi-h", "dmmr"}
        for cg in conflicting_genes:
            # If trial explicitly headlines a conflicting gene without patient's gene
            if re.search(rf"\b{re.escape(cg)}\b", title_lower) and not any(
                pg in title_lower for pg in patient_genes
            ):
                score -= 12.0
            # Explicit wild-type restriction against patient's gene
            for pg in patient_genes:
                if re.search(rf"{re.escape(pg)}[\s\-]+wild[\s\-]*type|without[\s\-]+{re.escape(pg)}", eligibility_lower):
                    score -= 15.0

    # 2. Histology / Condition matching
    histology_terms = [
        "adenocarcinoma", "squamous", "non-small cell", "nsclc", "small cell", "sclc",
        "melanoma", "carcinoma", "sarcoma", "glioblastoma", "cholangiocarcinoma",
        "leukemia", "lymphoma", "myeloma", "colorectal", "breast", "prostate", "lung"
    ]
    cond_lower = query.condition.lower()
    for ht in histology_terms:
        if ht in cond_lower:
            if ht in title_lower:
                score += 6.0
            elif ht in conditions_text or ht in summary_lower:
                score += 4.0
            elif ht in eligibility_lower:
                score += 2.0

    # 3. Stage matching
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

    # 4. Phase preference (Phase 2 or 3 slightly preferred for active therapeutic evaluation)
    for p in trial.phase:
        p_lower = p.lower()
        if "phase 2" in p_lower or "phase 3" in p_lower:
            score += 1.0
            break

    return score


def pre_rank_candidate_trials(
    trials: list[NormalizedTrial], query: StructuredQuery
) -> list[NormalizedTrial]:
    """
    Ranks candidates by relevance score descending so the most biomarker- and
    histology-aligned studies are verified first.
    """
    if not trials or not query:
        return trials

    scored_trials = [(trial, score_candidate_trial(trial, query)) for trial in trials]
    scored_trials.sort(key=lambda item: item[1], reverse=True)
    return [trial for trial, _score in scored_trials]


async def retrieve_candidate_trials(
    query: StructuredQuery,
    client: ClinicalTrialsClient | None = None,
) -> list[NormalizedTrial]:
    """
    Main entry point for the Act stage. Retrieves recruiting studies from
    ClinicalTrials.gov, normalizes them, and deterministically pre-ranks them
    based on biomarker, condition, and stage alignment.
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

    # Deterministic biomarker-aware pre-ranking
    ranked_trials = pre_rank_candidate_trials(valid_trials, query)
    return ranked_trials
