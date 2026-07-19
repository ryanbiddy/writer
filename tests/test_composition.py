from writer.writing import validate_composition


def test_tweet_validation_counts_credit_on_last_block_only():
    report = validate_composition(
        kind="thread",
        blocks=["First block.", "Second block."],
        credit_lines=["via A Creator"],
    )
    assert report["limit"] == 280
    assert report["blocks"][0]["char_count_with_footer"] == len(
        "First block.")
    assert report["blocks"][1]["char_count_with_footer"] == len(
        "Second block.\n\nvia A Creator")
    assert report["footer_target_index"] == 1
    assert report["over_limit_any"] is False


def test_source_free_validation_adds_no_brand_or_attribution():
    report = validate_composition(
        kind="tweet",
        blocks=["Original note."],
    )
    assert report["footer_text"] == ""
    assert report["blocks"][0]["char_count_with_footer"] == len(
        "Original note.")
    assert "uoink" not in str(report).casefold()
    assert "writer" not in str(report).casefold()
