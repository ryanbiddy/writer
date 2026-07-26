from __future__ import annotations

import pytest

from writer.schemas import (
    SchemaError,
    SourceSnapshot,
    VoiceSampleContract,
)


@pytest.mark.parametrize("bad_value", ["false", 0, 1, None, [], {}])
def test_source_credit_required_is_a_strict_boolean(bad_value):
    with pytest.raises(
        SchemaError,
        match=r"^source\.credit_required must be a boolean$",
    ):
        SourceSnapshot.from_dict({
            "provider": "url",
            "source_url": "https://example.com/source",
            "credit_required": bad_value,
        })


@pytest.mark.parametrize("field", ["active", "default"])
@pytest.mark.parametrize("bad_value", ["false", 0, 1, None, [], {}])
def test_voice_sample_flags_are_strict_booleans(field, bad_value):
    payload = {
        "name": "Measured voice",
        "source_type": "text",
        "raw_text": "Name the measured result.",
        field: bad_value,
    }

    with pytest.raises(
        SchemaError,
        match=rf"^voice-sample\.{field} must be a boolean$",
    ):
        VoiceSampleContract.from_dict(payload)


def test_schema_version_rejects_boolean_integer_alias():
    with pytest.raises(
        SchemaError,
        match=r"^source\.schema_version must be 1$",
    ):
        SourceSnapshot.from_dict({
            "provider": "original",
            "schema_version": True,
        })


def test_real_booleans_remain_valid():
    source = SourceSnapshot.from_dict({
        "provider": "url",
        "source_url": "https://example.com/source",
        "credit_required": True,
        "credit_line": "via Example",
    })
    sample = VoiceSampleContract.from_dict({
        "name": "Measured voice",
        "source_type": "text",
        "raw_text": "Name the measured result.",
        "active": False,
        "default": True,
    })

    assert source.credit_required is True
    assert sample.active is False
    assert sample.default is True
