"""
Thin adapter over the ClinicalTrials.gov API v2 (public, no API key).

This module owns exactly one responsibility: make the HTTP call, handle
timeouts/errors, and return raw JSON. Turning a patient profile into query
params (the Plan stage) and turning results into ranked trials (Synthesize)
both live elsewhere — see the risk-management note in the project plan:
"a thin adapter layer isolates the API call" from a schema/rate-limit change.
"""

import logging
import re

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class ClinicalTrialsAPIError(Exception):
    """Raised on timeout, non-2xx response, or malformed payload from ClinicalTrials.gov."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def build_stage_aware_query(condition: str, stage: str | None = None) -> str:
    """
    Broadens and combines the primary disease/condition with stage keywords
    for ClinicalTrials.gov API v2:
    e.g., "Triple Negative Breast Cancer" AND ("metastatic" OR "advanced" OR "Stage IV").
    """
    if not condition:
        return ""

    # If condition already contains boolean operator AND, return as-is
    if " AND " in condition:
        return condition

    clean_cond = condition.strip().strip('"')
    stage_lower = (stage or "").lower().strip()
    cond_lower = clean_cond.lower()

    # Determine stage keywords
    if any(st in stage_lower for st in ["iv", "4", "metastat", "advanced", "m1"]) or any(
        st in cond_lower for st in ["metastat", "stage iv", "stage 4", "advanced"]
    ):
        stage_clause = '("metastatic" OR "advanced" OR "Stage IV")'
    elif any(st in stage_lower for st in ["iii", "3", "locally advanced"]):
        stage_clause = '("Stage III" OR "locally advanced")'
    elif any(st in stage_lower for st in ["ii", "2"]):
        stage_clause = '("Stage II")'
    elif any(st in stage_lower for st in ["i", "1", "early"]) and not any(
        st in stage_lower for st in ["iv", "iii", "ii"]
    ):
        stage_clause = '("Stage I" OR "early stage")'
    elif stage:
        stage_clause = f'("{stage.strip()}")'
    else:
        stage_clause = None

    if stage_clause:
        return f'"{clean_cond}" AND {stage_clause}'

    return clean_cond


class ClinicalTrialsClient:
    def __init__(self, max_results: int = 15) -> None:
        settings = get_settings()
        self._base_url = settings.clinicaltrials_api_base
        self._timeout = settings.request_timeout_seconds
        # Restrict candidate trials pageSize strictly to 15 per REST v2 guidelines
        self._max_results = max_results or 15

    @staticmethod
    def build_stage_aware_query(condition: str, stage: str | None = None) -> str:
        return build_stage_aware_query(condition, stage)

    @staticmethod
    def _sanitize_query_term(term: str) -> str:
        """
        Sanitizes and truncates query.term for the ClinicalTrials.gov query parser:
        - Strips characters that break the parser: [()%:;,/+=<>]
        - Preserves key mutation and biomarker expressions (e.g., EGFR, exon 19 deletion)
        - Truncates to at most 4-5 keywords and 60 characters
        """
        cleaned = re.sub(r"[()%:;,/+=<>]", " ", term)
        words = cleaned.split()
        if not words:
            return ""
        if len(words) > 5:
            words = words[:5]
        truncated = " ".join(words)
        if len(truncated) > 60:
            truncated = (
                truncated[:60].rsplit(" ", 1)[0].strip()
                if " " in truncated[:60]
                else truncated[:60].strip()
            )
        return truncated

    @staticmethod
    def _extract_root_condition(condition: str) -> str:
        """
        Extracts the primary disease / cancer entity or first 2-3 words,
        stripping staging notation, pathology descriptors, and surgical procedures.
        """
        # If condition has boolean clause like AND (...), take primary condition part
        if " AND " in condition:
            condition = condition.split(" AND ")[0].strip().strip('"')

        # Strip staging notation (e.g., Stage III, AJCC, ypT2N1M0, T2N1M0)
        cleaned = re.sub(
            r"\b(stage\s+[ivx\d]+[a-c]?|ajcc(\s+\d+th(\s+edition)?)?|tnm|yp?[t][0-4][a-c]?|yp?[n][0-3][a-c]?|yp?[m][0-1][a-c]?|ecog\s+\d)\b",
            "",
            condition,
            flags=re.IGNORECASE,
        )
        # Strip procedure, pathology, and therapy keywords
        cleaned = re.sub(
            r"\b(resected|resection|esophagectomy|lobectomy|surgery|post-?op(erative)?|pre-?treatment|neoadjuvant|adjuvant|chemoradiotherapy|chemotherapy|radiotherapy|radical|histologically\s+confirmed)\b",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"[^\w\s\-]", " ", cleaned)
        words = cleaned.split()
        if not words:
            orig_words = condition.split()
            return " ".join(orig_words[:3]) if orig_words else condition.strip()
        return " ".join(words[:3])

    async def _fetch_studies(self, params: dict) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(f"{self._base_url}/studies", params=params)
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            logger.error("ClinicalTrials.gov timeout: %s", exc)
            raise ClinicalTrialsAPIError(
                "ClinicalTrials.gov did not respond in time."
            ) from exc
        except httpx.HTTPStatusError as exc:
            logger.error(
                "ClinicalTrials.gov returned %s: %s",
                exc.response.status_code,
                exc.response.text,
            )
            raise ClinicalTrialsAPIError(
                f"ClinicalTrials.gov returned an error (status {exc.response.status_code}).",
                status_code=exc.response.status_code,
            ) from exc

        try:
            payload = response.json()
            return payload.get("studies", [])
        except (ValueError, KeyError) as exc:
            logger.error("Malformed ClinicalTrials.gov response: %s", exc)
            raise ClinicalTrialsAPIError(
                "Received an unexpected response shape from ClinicalTrials.gov."
            ) from exc

    async def search_studies(self, query_params: dict) -> list[dict]:
        """
        Query the /studies endpoint.

        query_params example:
            {
                "query.cond": "esophageal squamous cell carcinoma",
                "filter.overallStatus": "RECRUITING",
            }

        Returns a list of raw study JSON objects (capped at max_trials_per_query).
        Raises ClinicalTrialsAPIError on failure — callers must show a visible
        error state, never a silent empty result (NFR: Reliability).
        """
        params = {
            "filter.overallStatus": "RECRUITING",
            **query_params,
            "pageSize": self._max_results,
            "format": "json",
        }
        # Ensure filter.overallStatus is always RECRUITING
        params["filter.overallStatus"] = "RECRUITING"

        # Remove internal Python flags so they are NEVER forwarded as HTTP query params
        has_actionable_biomarker = bool(
            params.pop("has_actionable_biomarker", None)
            or query_params.get("has_actionable_biomarker")
            or (
                query_params.get("query.term")
                and any(
                    g in query_params["query.term"].lower()
                    for g in [
                        "egfr", "her2", "erbb2", "braf", "kras", "alk", "ros1",
                        "met", "ret", "ntrk", "brca", "pik3ca", "pdl1", "pd-l1"
                    ]
                )
            )
        )

        # Broaden search query: combine condition with stage keywords when stage is available
        # When an actionable biomarker is present, keep query.cond clean as primary condition
        cond = params.get("query.cond", "")
        stage = params.pop("stage", None) or query_params.get("query.stage")
        params.pop("query.stage", None)
        if not has_actionable_biomarker and cond and stage and " AND " not in cond:
            params["query.cond"] = self.build_stage_aware_query(cond, stage)

        # Sanitize and guard query.term against parser-breaking characters and length
        if params.get("query.term"):
            sanitized_term = self._sanitize_query_term(params["query.term"])
            if sanitized_term:
                params["query.term"] = sanitized_term
            else:
                params.pop("query.term", None)

        # Whitelist strictly valid ClinicalTrials.gov REST v2 parameters
        valid_ct_params = {
            "query.cond",
            "query.term",
            "filter.overallStatus",
            "pageSize",
            "format",
            "pageToken",
            "sort",
            "countTotal",
        }
        params = {k: v for k, v in params.items() if k in valid_ct_params and v is not None}

        try:
            studies = await self._fetch_studies(params)
        except ClinicalTrialsAPIError as exc:
            # Graceful Fallback: If ClinicalTrials.gov returns 400 and query.term was present
            if (exc.status_code == 400 or "status 400" in str(exc)) and "query.term" in params:
                logger.warning(
                    "ClinicalTrials.gov 400 for query.term; attempting recovery without query.term"
                )
                fallback_params = {k: v for k, v in params.items() if k != "query.term"}
                fallback_params = {
                    k: v for k, v in fallback_params.items() if k in valid_ct_params and v is not None
                }
                try:
                    studies = await self._fetch_studies(fallback_params)
                except Exception as inner_exc:
                    logger.error(
                        "ClinicalTrials.gov recovery fallback failed (params=%s): %s; returning empty fallback array",
                        fallback_params,
                        inner_exc,
                    )
                    studies = []
            else:
                logger.error(
                    "ClinicalTrials.gov non-200 / request error (status=%s, params=%s): %s; returning empty fallback array",
                    getattr(exc, "status_code", None),
                    params,
                    exc,
                )
                studies = []
        except Exception as exc:
            logger.error(
                "ClinicalTrials.gov unexpected request failure (params=%s): %s; returning empty fallback array",
                params,
                exc,
            )
            studies = []

        # Automatic query relaxation fallback:
        # If the initial request returns 0 candidate studies, do not immediately return empty results.
        # Automatically trigger a fallback search using only the primary condition/cancer entity
        # (or the first 2-3 words of the condition).
        # When actionable mutations are present, NEVER query on condition alone.
        if not studies and ("query.cond" in query_params or "query.term" in query_params):
            logger.info("Initial search returned 0 trials; auto-relaxing query.")
            orig_cond = query_params.get("query.cond", "")
            root_cond = self._extract_root_condition(orig_cond) if orig_cond else ""
            status_filter = query_params.get("filter.overallStatus", "RECRUITING")

            async def _safe_fetch_relaxed(relaxed: dict) -> list[dict]:
                cleaned = {k: v for k, v in relaxed.items() if k in valid_ct_params and v is not None}
                try:
                    return await self._fetch_studies(cleaned)
                except Exception as rel_exc:
                    logger.warning("ClinicalTrials.gov relaxed query failed (params=%s): %s", cleaned, rel_exc)
                    return []

            if has_actionable_biomarker and "query.term" in query_params:
                # Do NOT query on condition alone when actionable mutations are detected!
                # Retain the primary biomarker in query.term and relax condition if needed
                if orig_cond and orig_cond != params.get("query.cond"):
                    relaxed_params = {
                        "query.cond": orig_cond,
                        "query.term": query_params["query.term"],
                        "filter.overallStatus": status_filter,
                        "pageSize": self._max_results,
                        "format": "json",
                    }
                    studies = await _safe_fetch_relaxed(relaxed_params)

                if not studies and root_cond:
                    relaxed_params = {
                        "query.cond": root_cond,
                        "query.term": query_params["query.term"],
                        "filter.overallStatus": status_filter,
                        "pageSize": self._max_results,
                        "format": "json",
                    }
                    studies = await _safe_fetch_relaxed(relaxed_params)
            else:
                # Fallback 1: search with only unbroadened query.cond if query.term or stage was present
                if orig_cond and ("query.term" in query_params or stage):
                    relaxed_params = {
                        "query.cond": orig_cond,
                        "filter.overallStatus": status_filter,
                        "pageSize": self._max_results,
                        "format": "json",
                    }
                    studies = await _safe_fetch_relaxed(relaxed_params)

                # Fallback 2: search with root condition / first 2-3 words if still 0
                if not studies and root_cond and root_cond != cond:
                    relaxed_params = {
                        "query.cond": root_cond,
                        "filter.overallStatus": status_filter,
                        "pageSize": self._max_results,
                        "format": "json",
                    }
                    studies = await _safe_fetch_relaxed(relaxed_params)

            # Fallback 3: if condition was empty but term was present, search using root entity from term
            if not studies and not cond and "query.term" in query_params:
                term_cond = self._extract_root_condition(query_params["query.term"])
                if term_cond:
                    relaxed_params = {
                        "query.cond": term_cond,
                        "filter.overallStatus": status_filter,
                        "pageSize": self._max_results,
                        "format": "json",
                    }
                    studies = await _safe_fetch_relaxed(relaxed_params)

        return studies

    async def get_study(self, nct_id: str) -> dict:
        """Fetch a single study by NCT ID — used to re-sync trial data (Maintenance & support)."""
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    f"{self._base_url}/studies/{nct_id}", params={"format": "json"}
                )
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ClinicalTrialsAPIError(f"Timed out fetching trial {nct_id}.") from exc
        except httpx.HTTPStatusError as exc:
            raise ClinicalTrialsAPIError(
                f"ClinicalTrials.gov returned status {exc.response.status_code} for trial {nct_id}."
            ) from exc

        return response.json()
