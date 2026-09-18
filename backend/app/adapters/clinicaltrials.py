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


class ClinicalTrialsClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.clinicaltrials_api_base
        self._timeout = settings.request_timeout_seconds
        # Fetch a robust pool of 15-20 candidates for pre-ranking
        self._max_results = max(settings.max_trials_per_query, 20)

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

        # Sanitize and guard query.term against parser-breaking characters and length
        if params.get("query.term"):
            sanitized_term = self._sanitize_query_term(params["query.term"])
            if sanitized_term:
                params["query.term"] = sanitized_term
            else:
                params.pop("query.term", None)

        try:
            studies = await self._fetch_studies(params)
        except ClinicalTrialsAPIError as exc:
            # Graceful Fallback: If ClinicalTrials.gov returns 400 and query.term was present,
            # retry immediately using only query.cond to ensure retrieval doesn't crash the pipeline.
            if (exc.status_code == 400 or "status 400" in str(exc)) and "query.term" in params:
                logger.warning(
                    "ClinicalTrials.gov 400 for query.term; falling back to query.cond only"
                )
                fallback_params = {k: v for k, v in params.items() if k != "query.term"}
                studies = await self._fetch_studies(fallback_params)
            else:
                raise

        # Automatic query relaxation fallback:
        # If the initial request returns 0 candidate studies, do not immediately return empty results.
        # Automatically trigger a fallback search using only the primary condition/cancer entity
        # (or the first 2-3 words of the condition).
        if not studies and ("query.cond" in query_params or "query.term" in query_params):
            logger.info("Initial search returned 0 trials; auto-relaxing query to root condition.")
            cond = query_params.get("query.cond", "")
            root_cond = self._extract_root_condition(cond) if cond else ""
            status_filter = query_params.get("filter.overallStatus", "RECRUITING")

            # Fallback 1: search with only query.cond if query.term was present
            if cond and "query.term" in query_params:
                relaxed_params = {
                    "query.cond": cond,
                    "filter.overallStatus": status_filter,
                    "pageSize": self._max_results,
                    "format": "json",
                }
                studies = await self._fetch_studies(relaxed_params)

            # Fallback 2: search with root condition / first 2-3 words if still 0
            if not studies and root_cond and root_cond != cond:
                relaxed_params = {
                    "query.cond": root_cond,
                    "filter.overallStatus": status_filter,
                    "pageSize": self._max_results,
                    "format": "json",
                }
                studies = await self._fetch_studies(relaxed_params)

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
                    studies = await self._fetch_studies(relaxed_params)

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
