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

from app.adapters.clinicaltrials import ClinicalTrialsAPIError, ClinicalTrialsClient
from app.pipeline.schemas import NormalizedTrial, StructuredQuery

logger = logging.getLogger(__name__)


class ActStageError(Exception):
    """
    Raised when retrieval fails outright. Callers must surface a visible,
    specific error state — never a silent empty result (NFR: Reliability).
    """


def build_query_params(query: StructuredQuery) -> dict:
    """
    Maps StructuredQuery fields onto the API v2 search fields we actually
    have: `query.cond` for the primary condition/diagnosis, `query.term`
    for everything else worth surfacing (stage, prior therapy, biomarkers),
    and `filter.overallStatus` for recruiting status. Exclusions are
    deliberately NOT used to filter retrieval — they're patient-side facts
    checked per-criterion in the Verify stage, not a valid search filter.
    """
    params: dict = {"query.cond": query.condition}

    term_parts: list[str] = []
    if query.stage:
        term_parts.append(query.stage)
    term_parts.extend(query.prior_therapy)
    term_parts.extend(query.biomarkers)
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
    eligibility_module = protocol.get("eligibilityModule", {})

    nct_id = identification.get("nctId")
    title = identification.get("briefTitle") or identification.get("officialTitle")

    if not nct_id or not title:
        logger.warning("Skipping study with missing nctId/title: %s", identification)
        return None

    return NormalizedTrial(
        nct_id=nct_id,
        title=title,
        status=status_module.get("overallStatus"),
        phase=design_module.get("phases", []) or [],
        conditions=conditions_module.get("conditions", []) or [],
        eligibility_text=eligibility_module.get("eligibilityCriteria", "") or "",
    )


async def retrieve_candidate_trials(
    query: StructuredQuery,
    client: ClinicalTrialsClient | None = None,
) -> list[NormalizedTrial]:
    """
    Main entry point for the Act stage. Raises ActStageError on outright
    API failure (timeout, non-2xx, malformed payload); returns an empty
    list (not an error) if the API responds successfully with zero
    matching studies — that's a legitimate "no candidate trials" outcome
    for the Synthesize stage to report, not a failure.
    """
    client = client or ClinicalTrialsClient()
    params = build_query_params(query)

    try:
        raw_studies = await client.search_studies(params)
    except ClinicalTrialsAPIError as exc:
        logger.error("Act stage retrieval failed: %s", exc)
        raise ActStageError(str(exc)) from exc

    trials = [normalize_study(s) for s in raw_studies]
    return [t for t in trials if t is not None]
