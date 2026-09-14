"""
Unit tests for app.pipeline.ground.

This is the module the architecture doc calls out explicitly: "Bad split
-> caught by unit tests on criterion boundaries before it reaches the
model." These tests exist to catch exactly that class of bug before any
LLM call is ever made against a malformed criterion.
"""

from app.pipeline.ground import decompose_eligibility_criteria


def test_splits_inclusion_and_exclusion_with_bullet_markers():
    text = (
        "Inclusion Criteria:\n\n"
        "- Age 18 years or older\n"
        "- Histologically confirmed diagnosis\n\n"
        "Exclusion Criteria:\n\n"
        "- Pregnant or breastfeeding\n"
        "- Prior treatment with the study drug"
    )
    criteria = decompose_eligibility_criteria("NCT001", text)

    inclusion = [c for c in criteria if c.criterion_type == "inclusion"]
    exclusion = [c for c in criteria if c.criterion_type == "exclusion"]

    assert len(inclusion) == 2
    assert len(exclusion) == 2
    assert inclusion[0].raw_text == "Age 18 years or older"
    assert inclusion[1].raw_text == "Histologically confirmed diagnosis"
    assert exclusion[0].raw_text == "Pregnant or breastfeeding"
    assert exclusion[1].raw_text == "Prior treatment with the study drug"


def test_criterion_index_is_sequential_and_zero_based_per_type():
    text = "Inclusion Criteria:\n- A\n- B\n- C\n\nExclusion Criteria:\n- X"
    criteria = decompose_eligibility_criteria("NCT002", text)

    inclusion_indexes = [c.criterion_index for c in criteria if c.criterion_type == "inclusion"]
    exclusion_indexes = [c.criterion_index for c in criteria if c.criterion_type == "exclusion"]

    assert inclusion_indexes == [0, 1, 2]
    assert exclusion_indexes == [0]


def test_wrapped_continuation_lines_are_joined_not_split():
    """A criterion that wraps across lines without a new bullet must stay one item."""
    text = (
        "Inclusion Criteria:\n"
        "- Patients with histologically or cytologically confirmed\n"
        "  locally advanced or metastatic solid tumor\n"
        "- ECOG performance status 0 or 1"
    )
    criteria = decompose_eligibility_criteria("NCT003", text)
    inclusion = [c for c in criteria if c.criterion_type == "inclusion"]

    assert len(inclusion) == 2
    assert inclusion[0].raw_text == "Patients with histologically or cytologically confirmed locally advanced or metastatic solid tumor"
    assert inclusion[1].raw_text == "ECOG performance status 0 or 1"


def test_numbered_list_markers_are_recognized():
    text = "Inclusion Criteria:\n1. Age 18+\n2. Confirmed diagnosis\n\nExclusion Criteria:\n1. Pregnant"
    criteria = decompose_eligibility_criteria("NCT004", text)
    inclusion = [c for c in criteria if c.criterion_type == "inclusion"]

    assert len(inclusion) == 2
    assert inclusion[0].raw_text == "Age 18+"
    assert inclusion[1].raw_text == "Confirmed diagnosis"


def test_missing_exclusion_header_falls_back_to_all_inclusion():
    """No 'Exclusion Criteria' header at all -> everything is treated as inclusion, never guessed as exclusion."""
    text = "Inclusion Criteria:\n- Age 18+\n- Confirmed diagnosis"
    criteria = decompose_eligibility_criteria("NCT005", text)

    assert all(c.criterion_type == "inclusion" for c in criteria)
    assert len(criteria) == 2


def test_empty_eligibility_text_returns_empty_list_not_error():
    assert decompose_eligibility_criteria("NCT006", "") == []
    assert decompose_eligibility_criteria("NCT006", "   ") == []


def test_raw_text_never_contains_the_bullet_marker():
    text = "Inclusion Criteria:\n- Age 18+\n* Confirmed diagnosis\n1. Third item\na) Fourth item"
    criteria = decompose_eligibility_criteria("NCT007", text)

    for c in criteria:
        assert not c.raw_text.startswith("-")
        assert not c.raw_text.startswith("*")
        assert not c.raw_text[0].isdigit() or "." not in c.raw_text[:3]


def test_stray_preamble_line_before_first_marker_is_dropped_not_merged():
    """A header fragment with no marker (e.g. 'Key criteria include:') must not become part of the first real item."""
    text = "Inclusion Criteria:\nKey criteria include the following:\n- Age 18+"
    criteria = decompose_eligibility_criteria("NCT008", text)
    inclusion = [c for c in criteria if c.criterion_type == "inclusion"]

    assert len(inclusion) == 1
    assert inclusion[0].raw_text == "Age 18+"


def test_criteria_are_valid_pydantic_models_with_expected_fields():
    text = "Inclusion Criteria:\n- Age 18+\n\nExclusion Criteria:\n- Pregnant"
    criteria = decompose_eligibility_criteria("NCT009", text)

    for c in criteria:
        assert c.nct_id == "NCT009"
        assert c.criterion_type in {"inclusion", "exclusion"}
        assert c.criterion_index >= 0
        assert len(c.raw_text) > 0
