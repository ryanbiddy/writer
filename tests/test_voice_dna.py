from __future__ import annotations

from writer import voice_dna


def test_canonical_prompt_is_writer_owned_and_packaged():
    assert voice_dna.VOICE_DNA_PROMPT.startswith("# Voice DNA")
    assert "Writer" in voice_dna.VOICE_DNA_PROMPT
    assert "Uoink produces" not in voice_dna.VOICE_DNA_PROMPT


def test_scan_returns_original_position_and_category():
    text = "A robust plan can leverage the saved context."
    warnings = voice_dna.scan(text)
    by_phrase = {warning["phrase"]: warning for warning in warnings}
    assert by_phrase["robust"] == {
        "phrase": "robust",
        "position": [2, 8],
        "category": "Dead AI Language",
        "matched_text": "robust",
    }
    assert by_phrase["leverage"]["matched_text"] == "leverage"


def test_big_one_is_detected():
    warnings = voice_dna.scan(
        "This isn't a faster draft. This is a clearer one.")
    assert any(
        warning["category"] == "The Big One"
        for warning in warnings)


def test_clean_copy_stays_clean():
    assert voice_dna.scan(
        "The local test selected 2 references and kept both credits."
    ) == []


def test_warning_copy_and_prompt_prepend_use_writer_identity():
    warning = voice_dna.warning_copy()
    assert "Writer spotted" in warning
    assert "Uoink" not in warning
    combined = voice_dna.prepend_system_prompt(
        "Write a 5-line outline.")
    assert combined.startswith("# Voice DNA")
    assert combined.endswith("Write a 5-line outline.")
