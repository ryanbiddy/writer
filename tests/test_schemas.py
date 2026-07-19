from __future__ import annotations

import json
from pathlib import Path

import pytest

from writer.schemas import (
    AssemblyQuery,
    Beat,
    DraftContract,
    PieceContract,
    SchemaError,
    ScriptContract,
    Shot,
    ShotListDocument,
    SourceSnapshot,
)

ROOT = Path(__file__).resolve().parent.parent


def test_source_free_draft_round_trips_without_false_credit():
    draft = DraftContract(
        kind="blog",
        title="Original idea",
        body="This is the user's own draft.",
    ).validate()

    restored = DraftContract.from_dict(
        json.loads(draft.to_json()))
    assert restored == draft
    assert restored.sources == []


def test_external_source_requires_display_credit():
    with pytest.raises(SchemaError, match="credit_line"):
        SourceSnapshot(
            provider="url",
            source_url="https://example.test/source",
            credit_required=True,
        ).validate()


def test_uoink_reference_is_opaque_and_portable():
    source = SourceSnapshot(
        provider="uoink",
        provider_ref="uoink://item/video-123",
        title="A saved reference",
        creator="Fixture Creator",
        source_url="https://example.test/video-123",
        credit_line="Source: A saved reference by Fixture Creator",
        excerpt="A local snapshot, not a corpus path.",
        credit_required=True,
    ).validate()
    assert source.provider_ref == "uoink://item/video-123"
    assert "path" not in source.to_dict()


def test_source_url_defaults_to_null():
    source = SourceSnapshot(provider="original").validate()
    assert source.source_url is None
    assert source.to_dict()["source_url"] is None


def test_legacy_blank_source_url_normalizes_to_null_on_read():
    source = SourceSnapshot.from_dict({
        "provider": "original",
        "source_url": "",
    })
    assert source.source_url is None
    assert source.to_dict()["source_url"] is None


@pytest.mark.parametrize("source_url", [
    "",
    "file:///tmp/source.md",
    "C:\\Users\\Ryan\\source.md",
    "/tmp/source.md",
    "ftp://example.test/source.md",
    "https://",
    "https://example.test/bad path",
])
def test_source_url_must_be_null_or_http(source_url):
    with pytest.raises(SchemaError, match=r"null or an HTTP\(S\) URL"):
        SourceSnapshot(
            provider="paste",
            source_url=source_url,
        ).validate()


@pytest.mark.parametrize(
    "provider_ref",
    (
        "uoink://item/",
        "uoink://item/one/two",
        "uoink://item/one%2Ftwo",
        "uoink://item/bad%ZZ",
        "uoink://item/one?path=two",
        "file:///private/item",
    ),
)
def test_uoink_reference_identifies_one_stable_item(provider_ref):
    with pytest.raises(SchemaError, match="identify one"):
        SourceSnapshot(
            provider="uoink",
            provider_ref=provider_ref,
        ).validate()


def test_piece_retains_every_required_credit():
    source = SourceSnapshot(
        provider="url",
        source_url="https://example.test/source",
        credit_line="Source: Fixture",
        credit_required=True,
    )
    with pytest.raises(SchemaError, match="retain"):
        PieceContract(
            kind="thread",
            body="A draft thread.",
            sources=[source],
        ).validate()


def test_script_and_shot_list_document_round_trip():
    script = ScriptContract(
        hook="The slow part was not the model.",
        format="talking_head",
        target_length_sec=45,
        beats=[Beat("setup", "Name the repeated task.")],
        body="A complete script.",
        cta="Try one repeatable step.",
        shots=[Shot(1, "setup", ["close-up host"])],
        assembly_query=AssemblyQuery(
            topic="AI workflows", n_examples=8),
    ).validate()
    restored = ScriptContract.from_dict(
        json.loads(script.to_json()))
    assert restored == script

    document = ShotListDocument(
        title="Saved hour",
        hook=script.hook,
        beats=script.beats,
        script=script.body,
        cta=script.cta,
        shots=script.shots,
        credits=[],
        generated_at="2030-01-02T03:04:05Z",
    ).validate()
    payload = json.loads(document.to_json())
    assert payload["document_type"] == "writer.shot-list"
    assert payload["schema_version"] == 1
    assert payload["hook"] == script.hook
    assert payload["beats"][0]["label"] == "setup"
    assert payload["shots"][0]["scene"] == 1


def test_initial_migration_owns_no_uoink_tables():
    sql = (
        ROOT / "src" / "writer" / "migrations" / "0001_initial.sql"
    ).read_text(encoding="utf-8")
    for owned in (
        "drafts", "pieces", "voice_samples", "scripts", "critiques",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {owned}" in sql
    for foreign in (
        "yoinks", "workspaces", "style_anchors",
        "workspace_critique_log",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {foreign}" not in sql

