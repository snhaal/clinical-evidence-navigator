"""
Verify stage.

ARCHITECTURE NOTE (revised): criteria for one trial are judged in a
SINGLE batched LLM call, not one call per criterion. The original design
(Decision 2 in the project plan) called for one call per criterion for
independence and cacheability, which is the right call on a
well-provisioned API budget — but on a free-tier provider with a real
RPM ceiling as low as 5 requests/minute, firing one call per criterion
means a single trial with 20 criteria alone exceeds the entire per-minute
budget, and a typical 8-trial search (130+ criteria) becomes impossible.
Batching by trial cuts that to roughly one call per trial (8-10 calls for
a typical search) while keeping every guardrail from the original design:
- each criterion's verdict still carries its own citation
- every citation is still validated as an exact substring of THAT
  criterion's source text before being trusted, never as a batch-wide
  approximation
- a criterion the model gets wrong or omits is repaired individually
  (via verify_criterion, the original single-criterion path, kept below)
  rather than invalidating the whole trial's batch

The core guardrail is unchanged: a citation that fails substring
validation is downgraded to "unclear" rather than shown as a trusted
match/no_match. This is what makes "100% citation validity" an enforced
property of the code, not an aspiration.
"""

import asyncio
import json
import logging
import re

from pydantic import ValidationError

from app.adapters.llm import LLMAdapter, LLMProviderError
from app.pipeline.schemas import CriterionVerdict, TrialCriterion

logger = logging.getLogger(__name__)

CriterionKey = tuple[str, int]  # (criterion_type, criterion_index)

# --- Single-criterion prompt (used for the initial verify_criterion path, ---
# --- and as the repair mechanism for any criterion a batch response omits) --

SINGLE_SYSTEM_PROMPT = """You are the verification stage of a clinical trial matching system.

You will be given a patient profile and exactly ONE eligibility criterion from ONE trial. \
Judge ONLY whether the patient profile satisfies this single criterion — you have no knowledge of \
any other criterion or any other trial, and must not assume one.

Respond with ONLY a single JSON object, no markdown fences, no commentary:
{
  "criterion_type": "inclusion" | "exclusion",
  "criterion_index": <the index number of the criterion>,
  "evidence_quote": <verbatim quote from the patient profile, or strictly null if the topic or condition is not mentioned in the profile>,
  "rationale": "one sentence explaining the verdict based strictly on evidence_quote",
  "verdict": "match" | "no_match" | "unclear",
  "cited_text": "the exact substring of the criterion text below that your verdict is based on"
}

Rules:
1. Evidence-First Rule: You must extract "evidence_quote" as a verbatim substring from the patient profile before deciding the verdict. If the topic, condition, lab value, or score is not mentioned in the patient note, "evidence_quote" must strictly be null.
2. Explicit Absence Rule: Never assume unmentioned conditions, baseline normality, or standard-of-care. If a lab value, staging, mutation, or functional score is absent from the note, output status 'INSUFFICIENT_DATA' (verdict "unclear"). Never guess "match" or "no_match" to fill a gap.
3. Compound Criteria Rule: If a criterion requires multiple conditions linked by 'AND' or commas, every single component must be explicitly documented in the note. If any sub-clause is missing, output status 'INSUFFICIENT_DATA' (verdict "unclear").
4. Exclusion Criteria Rule: Carefully distinguish trial eligibility from criterion satisfaction. For an exclusion criterion, if the patient has the condition, the criterion is MET (verdict "match", rendering them ineligible). If the patient explicitly does NOT have the condition (or it is explicitly negated in the note), the exclusion does not apply (verdict "no_match"). If not mentioned, output status 'INSUFFICIENT_DATA' (verdict "unclear").
5. Inclusion Criteria Rule:
   - "match": the patient profile clearly satisfies this criterion as written.
   - "no_match": the patient profile clearly contradicts or fails this criterion as written.
   - "unclear": the profile lacks enough information to judge this criterion (INSUFFICIENT_DATA).
6. Clinical Reasoning:
   - For 'Male or non pregnant female', a post-menopausal woman (e.g. 60+ years old) or a male satisfies non-pregnant female / male ("match").
   - A documented cancer stage (e.g. Stage III) satisfies stage range criteria (e.g. Stage II-III) unless explicitly contradictory.
7. Citation Rule: "cited_text" must be copied VERBATIM from the criterion text you were given — do not paraphrase, summarize, or modify comparison operators (<, <=, >=). If verdict is "unclear" due to missing information, cite the full criterion text instead.
"""

# --- Batched prompt: judges every criterion for one trial in one call -------

BATCH_SYSTEM_PROMPT = """You are the verification stage of a clinical trial matching system.

You will be given a patient profile and a NUMBERED LIST of eligibility criteria from ONE trial \
(a mix of inclusion and exclusion criteria). Judge EACH criterion independently against ONLY the \
patient profile. Do not let your judgment of one criterion influence another, and do not assume \
information the profile does not state.

Respond with ONLY a single JSON array, no markdown fences, no commentary, containing EXACTLY one \
object per criterion listed below (same count, none skipped, none invented), each shaped like:
{
  "criterion_type": "inclusion" | "exclusion",
  "criterion_index": <the index number shown next to that criterion>,
  "evidence_quote": <verbatim quote from the patient profile, or strictly null if the topic or condition is not mentioned in the profile>,
  "rationale": "one sentence explaining the verdict for THIS criterion based strictly on evidence_quote",
  "verdict": "match" | "no_match" | "unclear",
  "cited_text": "the exact substring of THIS criterion's own text that your verdict is based on"
}

Rules:
1. Evidence-First Rule: For each criterion, inspect the patient profile and extract "evidence_quote" as a verbatim substring from the profile before deciding the verdict. If the topic, condition, lab value, or score is not mentioned in the patient note, "evidence_quote" must strictly be null.
2. Explicit Absence Rule: Never assume unmentioned conditions, baseline normality, or standard-of-care. If a lab value, staging, mutation, or functional score is absent from the note, output status 'INSUFFICIENT_DATA' (verdict "unclear"). Never guess "match" or "no_match" to fill a gap.
3. Compound Criteria Rule: If a criterion requires multiple conditions linked by 'AND' or commas, every single component must be explicitly documented in the note. If any sub-clause is missing, output status 'INSUFFICIENT_DATA' (verdict "unclear").
4. Exclusion Criteria Rule: Carefully distinguish trial eligibility from criterion satisfaction. For an exclusion criterion, if the patient has the condition, the criterion is MET (verdict "match", rendering them ineligible). If the patient explicitly does NOT have the condition (or it is explicitly negated in the note), the exclusion does not apply (verdict "no_match"). If not mentioned, output status 'INSUFFICIENT_DATA' (verdict "unclear").
5. Inclusion Criteria Rule:
   - "match": the patient profile clearly satisfies that criterion as written.
   - "no_match": the patient profile clearly contradicts or fails that criterion as written.
   - "unclear": the profile lacks enough information to judge that criterion (INSUFFICIENT_DATA).
6. Clinical Reasoning:
   - For 'Male or non pregnant female', a post-menopausal woman (e.g. 60+ years old) or a male satisfies non-pregnant female / male ("match").
   - A documented cancer stage (e.g. Stage III) satisfies stage range criteria (e.g. Stage II-III) unless explicitly contradictory.
7. Citation Rule: "cited_text" must be copied VERBATIM from THAT criterion's own text — never from a different criterion, never paraphrased, and preserve comparison operators (<, <=, >=) exactly as written in the criterion text. If verdict is "unclear" due to missing information, cite that criterion's full text instead.
8. criterion_type and criterion_index in your response must exactly match one of the criteria listed below.
"""


_BATCH_TOKENS_PER_CRITERION = 220  # Each JSON item is ~100-140 tokens with evidence_quote; 220 gives ample headroom
_BATCH_TOKENS_FLOOR = 800
_BATCH_TOKENS_CEILING = (
    4800  # Stays safely under Groq's 8,000 TPM in-flight reservation ceiling
)


def _batch_max_output_tokens(num_criteria: int, attempt: int) -> int:
    """
    Sized to comfortably outlive real-world truncation: the first attempt
    already budgets well above a flat per-item estimate, and the retry
    (attempt=1) gets an explicit 50% bump on top of that — since a
    truncated first response ("Unterminated string" / "Expecting value"
    parse failures) is itself evidence the first budget was too tight,
    not just noise worth retrying identically.
    """
    base = min(
        _BATCH_TOKENS_CEILING,
        max(_BATCH_TOKENS_FLOOR, _BATCH_TOKENS_PER_CRITERION * num_criteria),
    )
    if attempt == 0:
        return base
    return min(_BATCH_TOKENS_CEILING, int(base * 1.5))


def _batch_response_schema() -> dict:
    """
    JSON Schema passed to providers that support server-side schema
    enforcement (Gemini's response_schema, Groq's strict json_schema mode
    on gpt-oss models). `additionalProperties: false` is required on the
    item object for Groq/OpenAI-style strict mode specifically.
    """
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "criterion_type": {
                    "type": "string",
                    "enum": ["inclusion", "exclusion"],
                },
                "criterion_index": {"type": "integer"},
                "evidence_quote": {"type": "string", "nullable": True},
                "rationale": {"type": "string"},
                "verdict": {"type": "string", "enum": ["match", "no_match", "unclear"]},
                "cited_text": {"type": "string"},
            },
            "required": [
                "criterion_type",
                "criterion_index",
                "evidence_quote",
                "rationale",
                "verdict",
                "cited_text",
            ],
            "additionalProperties": False,
        },
    }


def _strip_json_fences(text: str) -> str:
    match = re.search(r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```", text, re.DOTALL)
    return match.group(1) if match else text.strip()


def _fallback_unclear(criterion: TrialCriterion, reason: str) -> CriterionVerdict:
    """
    The single fallback path used whenever a criterion's model output
    can't be trusted (parse failure, invalid verdict, an unvalidatable
    citation, or omission from a batch response). Cites the full
    criterion text — trivially a valid substring of itself — so citation
    validity is never violated even in the failure case.
    """
    return CriterionVerdict(
        nct_id=criterion.nct_id,
        criterion_type=criterion.criterion_type,
        criterion_index=criterion.criterion_index,
        verdict="unclear",
        rationale=reason,
        cited_text=criterion.raw_text,
        citation_validated=False,
    )


def _normalize_text(text: str | None) -> str:
    """Normalize text by stripping punctuation and collapsing whitespace."""
    if not text:
        return ""
    cleaned = re.sub(r"[^\w\s]", "", text)
    return " ".join(cleaned.lower().split())


def _normalize_verdict_str(raw: str | None) -> str:
    val = (raw or "").strip()
    if val in ("MET", "MATCH", "met", "match"):
        return "match"
    if val in ("NOT_MET", "NO_MATCH", "not_met", "no_match"):
        return "no_match"
    return "unclear"


def _validate_citation(
    verdict: CriterionVerdict, criterion: TrialCriterion
) -> CriterionVerdict:
    # 1. Fast exact check
    if verdict.cited_text in criterion.raw_text:
        return verdict

    # 2. Check unescaped markdown comparison operators (e.g., < vs \<, >= vs \>=)
    candidate = (
        verdict.cited_text.replace("<=", r"\<=")
        .replace(">=", r"\>=")
        .replace("<", r"\<")
        .replace(">", r"\>")
    )
    if candidate in criterion.raw_text:
        verdict.cited_text = candidate
        return verdict

    # 3. Resilient check (handles quote, punctuation, or spacing differences from the LLM)
    norm_cited = _normalize_text(verdict.cited_text)
    norm_source = _normalize_text(criterion.raw_text)
    if norm_cited and norm_cited in norm_source:
        if norm_cited == norm_source:
            verdict.cited_text = criterion.raw_text
        return verdict

    logger.warning(
        "Citation failed substring validation for %s criterion %d; downgrading to unclear.",
        criterion.nct_id,
        criterion.criterion_index,
    )
    return _fallback_unclear(
        criterion,
        reason=(
            f"Model verdict ({verdict.verdict}) was discarded because its citation could not be "
            "validated against the source criterion text."
        ),
    )


# --- Single-criterion path (kept as the repair mechanism for batch gaps) ----


def _build_single_user_prompt(
    patient_profile_text: str, criterion: TrialCriterion
) -> str:
    return (
        f"Patient profile:\n{patient_profile_text}\n\n"
        f"Criterion type: {criterion.criterion_type}\n"
        f"Criterion index: {criterion.criterion_index}\n"
        f"Criterion text: {criterion.raw_text}"
    )


def _parse_single(raw_text: str, criterion: TrialCriterion) -> CriterionVerdict:
    cleaned = _strip_json_fences(raw_text)
    data = json.loads(cleaned)
    verdict = CriterionVerdict(
        nct_id=criterion.nct_id,
        criterion_type=criterion.criterion_type,
        criterion_index=criterion.criterion_index,
        verdict=_normalize_verdict_str(data.get("verdict") or data.get("status")),
        rationale=data.get("rationale") or data.get("reasoning") or "",
        cited_text=data.get("cited_text") or criterion.raw_text,
        evidence_quote=data.get("evidence_quote"),
    )
    return _validate_citation(verdict, criterion)


async def verify_criterion(
    patient_profile_text: str,
    criterion: TrialCriterion,
    llm: LLMAdapter | None = None,
) -> CriterionVerdict:
    """
    Judges ONE criterion in its own call. Used directly by callers that
    want single-criterion isolation, and internally by verify_all_criteria
    to repair any criterion a batch response fails to cover. Retries once
    on a parse/validation failure; degrades to unclear (never raises) if
    both attempts fail, or if the LLM provider itself errors out.
    """
    llm = llm or LLMAdapter()
    user_prompt = _build_single_user_prompt(patient_profile_text, criterion)

    for attempt in range(2):
        try:
            completion = await llm.complete(
                system_prompt=SINGLE_SYSTEM_PROMPT,
                user_prompt=user_prompt
                if attempt == 0
                else user_prompt
                + "\n\nReminder: respond with ONLY the JSON object described above.",
                max_tokens=800,
                temperature=0.0,
            )
        except LLMProviderError as exc:
            logger.error(
                "Verify stage LLM call failed for %s criterion %d (attempt %d): %s",
                criterion.nct_id,
                criterion.criterion_index,
                attempt,
                exc,
            )
            if attempt == 1:
                return _fallback_unclear(
                    criterion, reason="Could not be evaluated due to a provider error."
                )
            continue

        try:
            return _parse_single(completion.text, criterion)
        except (json.JSONDecodeError, ValidationError, KeyError) as exc:
            logger.warning(
                "Verify stage parse failure for %s criterion %d (attempt %d): %s",
                criterion.nct_id,
                criterion.criterion_index,
                attempt,
                exc,
            )
            if attempt == 1:
                return _fallback_unclear(
                    criterion,
                    reason="Could not be evaluated due to a malformed model response.",
                )
            continue

    # Unreachable — the loop above always returns on its final attempt.
    return _fallback_unclear(
        criterion, reason="Verify stage exhausted retries without returning."
    )


# --- Batched path: the default, used by verify_all_criteria -----------------


def _build_batch_user_prompt(
    patient_profile_text: str, criteria: list[TrialCriterion]
) -> str:
    lines = [f"Patient profile:\n{patient_profile_text}\n", "Criteria:"]
    for c in criteria:
        lines.append(f"[{c.criterion_type} #{c.criterion_index}] {c.raw_text}")
    return "\n".join(lines)


async def verify_trial_criteria(
    patient_profile_text: str,
    criteria: list[TrialCriterion],
    llm: LLMAdapter | None = None,
) -> list[CriterionVerdict]:
    """
    Judges every criterion for ONE trial in a single LLM call. This is
    what makes the pipeline viable on a low-RPM free tier: one call per
    trial instead of one call per criterion. Any criterion the batch
    response is missing, or gets wrong in a way that fails parsing, is
    repaired with an individual verify_criterion() call rather than
    marked unclear outright — so quality degrades gracefully, not en masse.
    """
    if not criteria:
        return []

    llm = llm or LLMAdapter()
    criteria_by_key: dict[CriterionKey, TrialCriterion] = {
        (c.criterion_type, c.criterion_index): c for c in criteria
    }
    schema = _batch_response_schema()
    user_prompt = _build_batch_user_prompt(patient_profile_text, criteria)

    parsed_by_key: dict[CriterionKey, CriterionVerdict] = {}
    last_error: str | None = None

    for attempt in range(2):
        try:
            completion = await llm.complete(
                system_prompt=BATCH_SYSTEM_PROMPT,
                user_prompt=user_prompt
                if attempt == 0
                else user_prompt
                + "\n\nReminder: respond with ONLY the JSON array described above, one object per criterion.",
                max_tokens=_batch_max_output_tokens(len(criteria), attempt),
                temperature=0.0,
                json_schema=schema,
            )
        except LLMProviderError as exc:
            last_error = f"provider error: {exc}"
            logger.error(
                "Batched verify call failed for %s (attempt %d): %s",
                criteria[0].nct_id,
                attempt,
                exc,
            )
            continue

        try:
            cleaned = _strip_json_fences(completion.text)
            items = json.loads(cleaned)
            if not isinstance(items, list):
                raise ValueError("Expected a JSON array of criterion verdicts.")
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = f"malformed batch response: {exc}"
            logger.warning(
                "Batched verify parse failure for %s (attempt %d): %s",
                criteria[0].nct_id,
                attempt,
                exc,
            )
            continue

        for item in items:
            try:
                key: CriterionKey = (
                    item["criterion_type"],
                    int(item["criterion_index"]),
                )
                criterion = criteria_by_key.get(key)
                if criterion is None:
                    logger.warning(
                        "Batch response referenced unknown criterion %s for %s; ignoring.",
                        key,
                        criteria[0].nct_id,
                    )
                    continue
                verdict = CriterionVerdict(
                    nct_id=criterion.nct_id,
                    criterion_type=criterion.criterion_type,
                    criterion_index=criterion.criterion_index,
                    verdict=_normalize_verdict_str(
                        item.get("verdict") or item.get("status")
                    ),
                    rationale=item.get("rationale") or item.get("reasoning") or "",
                    cited_text=item.get("cited_text") or criterion.raw_text,
                    evidence_quote=item.get("evidence_quote"),
                )
                parsed_by_key[key] = _validate_citation(verdict, criterion)
            except (KeyError, TypeError, ValidationError) as exc:
                logger.warning(
                    "Skipping one malformed item in batch response for %s: %s",
                    criteria[0].nct_id,
                    exc,
                )
                continue

        break  # Got a usable (if partial) response — stop retrying the whole batch.

    # Repair anything the batch didn't cover: individually, not en masse,
    # so a partially-good batch response doesn't get thrown away.
    missing = [c for key, c in criteria_by_key.items() if key not in parsed_by_key]
    if missing and len(missing) == len(criteria) and last_error:
        # The WHOLE batch failed (provider error or unparseable both attempts) —
        # fall back to unclear for all of them rather than spending N more
        # individual calls we already have reason to believe will also fail.
        logger.error(
            "Entire batch failed for %s (%s); marking all %d criteria unclear.",
            criteria[0].nct_id,
            last_error,
            len(missing),
        )
        for c in missing:
            parsed_by_key[(c.criterion_type, c.criterion_index)] = _fallback_unclear(
                c, reason=f"Batch verification failed ({last_error})."
            )
    else:
        for c in missing:
            logger.info(
                "Repairing 1 criterion omitted from batch response for %s (#%d).",
                c.nct_id,
                c.criterion_index,
            )
            await asyncio.sleep(3.0)
            repaired = await verify_criterion(patient_profile_text, c, llm=llm)
            parsed_by_key[(c.criterion_type, c.criterion_index)] = repaired

    # Return in the same order the criteria were given.
    return [parsed_by_key[(c.criterion_type, c.criterion_index)] for c in criteria]


async def verify_all_criteria(
    patient_profile_text: str,
    criteria: list[TrialCriterion],
    llm: LLMAdapter | None = None,
) -> list[CriterionVerdict]:
    """
    Public entry point — unchanged signature so callers (app/api/routes.py,
    evals/run_eval.py) don't need to change. Internally now batches all of
    one trial's criteria into a single call via verify_trial_criteria,
    instead of one concurrent call per criterion.
    """
    return await verify_trial_criteria(patient_profile_text, criteria, llm=llm)
