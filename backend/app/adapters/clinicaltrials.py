"""
Thin adapter over the ClinicalTrials.gov API v2 (public, no API key).

This module owns exactly one responsibility: make the HTTP call, handle
timeouts/errors, and return raw JSON. Turning a patient profile into query
params (the Plan stage) and turning results into ranked trials (Synthesize)
both live elsewhere — see the risk-management note in the project plan:
"a thin adapter layer isolates the API call" from a schema/rate-limit change.
"""

import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class ClinicalTrialsAPIError(Exception):
    """Raised on timeout, non-2xx response, or malformed payload from ClinicalTrials.gov."""


class ClinicalTrialsClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.clinicaltrials_api_base
        self._timeout = settings.request_timeout_seconds
        self._max_results = settings.max_trials_per_query

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
        params = {**query_params, "pageSize": self._max_results, "format": "json"}

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
                f"ClinicalTrials.gov returned an error (status {exc.response.status_code})."
            ) from exc

        try:
            payload = response.json()
            studies = payload.get("studies", [])
        except (ValueError, KeyError) as exc:
            logger.error("Malformed ClinicalTrials.gov response: %s", exc)
            raise ClinicalTrialsAPIError(
                "Received an unexpected response shape from ClinicalTrials.gov."
            ) from exc

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
