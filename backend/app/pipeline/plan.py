"""
Plan stage.

Converts a free-text patient profile into a StructuredQuery the Act stage
can use to query ClinicalTrials.gov. Two failure modes are handled
explicitly, matching the architecture doc:

  1. The model returns JSON that doesn't parse / doesn't validate against
     StructuredQuery -> retried once with a stricter reminder, then falls
     back to a clarifying question rather than guessing.
  2. The model itself decides it can't confidently extract a condition
     (e.g. profile is too vague) -> it returns a clarifying_question in
     its JSON instead of a query, which we pass straight through.

Either way, the caller never receives a low-confidence guessed query.
"""

import json
import logging
import re

from pydantic import ValidationError

from app.adapters.llm import LLMAdapter, LLMProviderError
from app.pipeline.schemas import PlanResult, StructuredQuery

logger = logging.getLogger(__name__)

MAX_PROFILE_CHARS_FOR_PROMPT = (
    4000  # matches config.max_patient_profile_chars; enforced again defensively here
)

SYSTEM_PROMPT = """You are the query-planning stage of a clinical trial matching system.

Given a free-text patient profile, extract a structured search query. Respond with ONLY a single JSON object, no markdown fences, no commentary.

If you can confidently identify the patient's primary condition/diagnosis, respond with:
{
  "condition": "string, required",
  "stage": "string or null",
  "prior_therapy": ["list", "of", "strings"],
  "biomarkers": ["list", "of", "strings"],
  "exclusions": ["list", "of", "strings"],
  "age": integer or null,
  "sex": "string or null",
  "status_filter": "RECRUITING"
}

If the profile is too ambiguous to confidently identify a condition (e.g. no diagnosis mentioned at all), respond with:
{
  "clarifying_question": "one specific, short question that would resolve the ambiguity"
}

Rules:
- Never invent details not stated or clearly implied in the profile.
- Only ask a clarifying question if the CONDITION itself is missing or too vague to search on. Missing stage, prior therapy, or biomarkers is fine — leave those null/empty rather than asking.
- exclusions should list patient-stated comorbidities or exclusion-relevant facts (e.g. "prior immunotherapy", "distant metastasis"), not general commentary.
- status_filter defaults to "RECRUITING" unless the profile implies otherwise.
- SEARCH QUERY RULE: For ClinicalTrials.gov search terms, extract ONLY the primary disease / condition name (e.g., 'esophageal squamous cell carcinoma' or 'lung adenocarcinoma').
- Limit search terms and extracted keywords to 2–4 concise search tokens (e.g., "EGFR" or "Stage IV EGFR").
- Never output punctuation, percentages (%), parentheses, or full sentences in the search terms or keyword fields (stage, prior_therapy, biomarkers). Extract only concise individual drug names (e.g. "cisplatin") or key gene targets (e.g. "EGFR"), never descriptions or narrative sentences.
- DO NOT include staging notation (TNM, AJCC, Stage III), specific pathology descriptors (ypT2N1M0), lab thresholds, or surgical procedures in the search query keywords. Those are evaluated during verification, not retrieval.
"""


def _strip_json_fences(text: str) -> str:
    """Models sometimes wrap JSON in ```json ... ``` despite instructions not to. Strip defensively."""
    match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if match:
        return match.group(1)
    return text.strip()


def _parse_plan_response(raw_text: str) -> PlanResult:
    cleaned = _strip_json_fences(raw_text)
    data = json.loads(
        cleaned
    )  # raises json.JSONDecodeError on failure — caught by caller

    if data.get("clarifying_question"):
        return PlanResult(
            clarifying_question=data["clarifying_question"], raw_model_output=raw_text
        )

    structured_query = StructuredQuery(
        **data
    )  # raises pydantic.ValidationError on failure
    return PlanResult(structured_query=structured_query, raw_model_output=raw_text)


async def plan_patient_profile(
    raw_profile_text: str, llm: LLMAdapter | None = None
) -> PlanResult:
    """
    Main entry point for the Plan stage.

    Retries once on a parse/validation failure with a stricter follow-up
    prompt; if that also fails, degrades to a generic clarifying question
    rather than raising — a malformed model response should never crash
    the request (NFR: Reliability).
    """
    llm = llm or LLMAdapter()
    profile_text = raw_profile_text.strip()[:MAX_PROFILE_CHARS_FOR_PROMPT]

    if not profile_text:
        return PlanResult(
            clarifying_question="Please describe the patient's diagnosis and relevant clinical history.",
            raw_model_output="",
        )

    for attempt in range(2):
        user_prompt = (
            profile_text
            if attempt == 0
            else (
                f"{profile_text}\n\n"
                "Reminder: respond with ONLY the JSON object described in the system prompt. "
                "No markdown, no explanation."
            )
        )
        try:
            completion = await llm.complete(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_prompt,
                max_tokens=512,
                temperature=0.0,
            )
        except LLMProviderError as exc:
            logger.error("Plan stage LLM call failed (attempt %d): %s", attempt, exc)
            if attempt == 1:
                return PlanResult(
                    clarifying_question=(
                        "We couldn't process that profile right now. Could you rephrase it, "
                        "leading with the primary diagnosis?"
                    ),
                    raw_model_output="",
                )
            continue

        try:
            return _parse_plan_response(completion.text)
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning(
                "Plan stage parse/validation failed (attempt %d): %s", attempt, exc
            )
            if attempt == 1:
                return PlanResult(
                    clarifying_question=(
                        "Could you clarify the patient's primary diagnosis? "
                        "We weren't able to confidently parse that from the profile given."
                    ),
                    raw_model_output=completion.text,
                )
            continue

    # Unreachable, but keeps type checkers happy.
    raise RuntimeError("Plan stage exhausted retries without returning.")
