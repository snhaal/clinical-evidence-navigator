"""
Ground stage.

Splits a trial's free-text eligibility criteria into atomic, numbered
statements the Verify stage can reason over one at a time. This is a
one-time, deterministic, non-LLM step — no model call, no cost, fully
unit-testable in isolation (per the architecture doc: "Bad split -> caught
by unit tests on criterion boundaries before it reaches the model").

ClinicalTrials.gov eligibility text is unstructured prose with loose
conventions (an "Inclusion Criteria:" header, a "Exclusion Criteria:"
header, bullet or numbered lines, occasional wrapped continuation lines).
This parser is intentionally conservative: when it can't confidently find
section headers, it treats the whole text as inclusion criteria and logs
a warning, rather than guessing at a split that could misclassify a
criterion's polarity.
"""

import logging
import re

from app.pipeline.schemas import TrialCriterion

logger = logging.getLogger(__name__)

_INCLUSION_HEADER = re.compile(r"inclusion criteria\s*:?", re.IGNORECASE)
_EXCLUSION_HEADER = re.compile(r"exclusion criteria\s*:?", re.IGNORECASE)

# A line starts a NEW criterion if it opens with a bullet (-, *, •) or a
# numbered/lettered list marker (1., 1), a)). Anything else is treated as
# a continuation of the previous criterion (handles line-wrapped text).
_NEW_ITEM_MARKER = re.compile(r"^\s*(?:[-*•]|\d+[.)]|[a-zA-Z][.)])\s+")


def _strip_marker(line: str) -> str:
    return _NEW_ITEM_MARKER.sub("", line, count=1).strip()


def _split_into_items(block_text: str) -> list[str]:
    """
    Given one section's raw text (inclusion-only or exclusion-only),
    return a list of individual criterion strings, each an exact,
    whitespace-normalized substring of the original wording — continuation
    lines are joined with a single space, never silently dropped.
    """
    lines = [line for line in block_text.splitlines()]
    items: list[str] = []
    current: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _NEW_ITEM_MARKER.match(line):
            if current:
                items.append(" ".join(current).strip())
            current = [_strip_marker(line)]
        else:
            if current:
                current.append(stripped)
            # A stray line before any marker is dropped (typically a
            # leftover header fragment, e.g. "Key inclusion criteria include:").

    if current:
        items.append(" ".join(current).strip())

    # Defensive de-duplication of whitespace introduced by joining lines.
    return [re.sub(r"\s+", " ", item).strip() for item in items if item.strip()]


def decompose_eligibility_criteria(
    nct_id: str, eligibility_text: str
) -> list[TrialCriterion]:
    """
    Main entry point for the Ground stage.

    Returns an empty list (not an error) if eligibility_text is empty —
    some trials legitimately have no structured eligibility text yet, and
    that's a data gap for the Verify stage to report as "unclear" per
    criterion count, not a pipeline failure.
    """
    text = (eligibility_text or "").strip()
    if not text:
        return []

    inclusion_match = _INCLUSION_HEADER.search(text)
    exclusion_match = _EXCLUSION_HEADER.search(text)

    if (
        inclusion_match
        and exclusion_match
        and exclusion_match.start() > inclusion_match.end()
    ):
        inclusion_block = text[inclusion_match.end() : exclusion_match.start()]
        exclusion_block = text[exclusion_match.end() :]
    elif exclusion_match:
        # Exclusion header present but no (or misplaced) inclusion header —
        # treat everything before it as inclusion, per the conservative
        # fallback described above.
        inclusion_block = text[: exclusion_match.start()]
        exclusion_block = text[exclusion_match.end() :]
    else:
        logger.warning(
            "No 'Exclusion Criteria' header found for %s; treating entire "
            "eligibility text as inclusion criteria.",
            nct_id,
        )
        inclusion_block = text
        exclusion_block = ""

    criteria: list[TrialCriterion] = []

    for index, item in enumerate(_split_into_items(inclusion_block)):
        criteria.append(
            TrialCriterion(
                nct_id=nct_id,
                criterion_type="inclusion",
                criterion_index=index,
                raw_text=item,
            )
        )

    for index, item in enumerate(_split_into_items(exclusion_block)):
        criteria.append(
            TrialCriterion(
                nct_id=nct_id,
                criterion_type="exclusion",
                criterion_index=index,
                raw_text=item,
            )
        )

    return criteria
