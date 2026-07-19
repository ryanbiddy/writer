from __future__ import annotations

import json
from pathlib import Path

import pytest

from writer.schemas import (
    Beat,
    DraftContract,
    SourceSnapshot,
    VoiceSampleContract,
)
from writer.scripts import ScriptService
from writer.storage import WriterStore
from writer.writing import WritingService, validate_composition

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "cm7-parity-v1.json")
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_fixture_pins_all_three_cm7_characterization_surfaces():
    assert FIXTURE["_upstream"] == {
        "repository": "ryanbiddy/uoink",
        "commit": "1895899d3eb51a70d6ec0f75f03f5bdef43c5ee6",
        "characterization_commit": "5d9564e2",
        "fixtures": {
            "writing.json": {
                "sha256": (
                    "f6c1e6f6382aa9bccd0d43c6b419d4b"
                    "2a3d7b21ed2600e51dc36529e91ed089c"
                ),
                "interactions": 10,
            },
            "scripts.json": {
                "sha256": (
                    "49eba8561898d636b347076b484607045"
                    "d35cee0f9c997e0b694de534b867d76"
                ),
                "interactions": 7,
            },
            "workspace-assembly.json": {
                "sha256": (
                    "5351b5a9b4eef255845d09f62c5ba59b"
                    "287e300d28bfcd40987460ffc03def88"
                ),
                "interactions": 6,
            },
        },
    }


def test_cm7_writing_semantics_pass_in_writer(tmp_path):
    store = WriterStore.open(tmp_path / "writer.db")
    source = SourceSnapshot.from_dict(FIXTURE["source"])
    writing = FIXTURE["writing"]
    try:
        service = WritingService(store)
        sample = store.add_voice_sample(
            VoiceSampleContract.from_dict(FIXTURE["voice_sample"]))
        assert sample.id == 1

        draft = store.save_draft(DraftContract(
            kind=writing["kind"],
            body=writing["draft_body"],
            sources=[source],
            voice_sample_ids=[sample.id],
        ))
        assert store.get_draft(draft.id).body == writing["draft_body"]

        first = service.save_piece(
            kind=writing["kind"],
            body=writing["body"],
            sources=[source],
            credit_lines=[source.credit_line],
            voice_sample_ids=[sample.id],
            angle=writing["angle"],
            target_length=writing["target_length"],
        )
        revised = service.save_piece(
            kind=writing["kind"],
            body=writing["revision_body"],
            sources=[source],
            credit_lines=[source.credit_line],
            voice_sample_ids=[sample.id],
            parent_id=first.id,
        )
        assert revised.version == 2
        assert revised.parent_id == first.id

        with pytest.raises(
                ValueError, match="retain every required"):
            service.save_piece(
                kind=writing["kind"],
                body=writing["invalid_body"],
                sources=[source],
            )

        report = validate_composition(
            kind=writing["kind"],
            blocks=writing["composition_blocks"],
            credit_lines=[source.credit_line],
        )
        assert report["limit"] == 280
        assert report["over_limit_any"] is False
    finally:
        store.close()


def test_cm7_script_and_critique_semantics_pass_in_writer(tmp_path):
    store = WriterStore.open(tmp_path / "writer.db")
    fixture = FIXTURE["script"]
    source = SourceSnapshot.from_dict(FIXTURE["source"])
    try:
        service = ScriptService(store)
        first = service.save_script(
            hook=fixture["hook"],
            format=fixture["format"],
            target_length_sec=fixture["target_length_sec"],
            beats=[
                Beat.from_dict(item) for item in fixture["beats"]],
            body=fixture["body"],
            cta=fixture["cta"],
            sources=[source],
        )
        with_shots = service.derive_shots(first.id)
        assert [shot.label for shot in with_shots.shots] == [
            "setup", "proof"]
        assert with_shots.shots[0].cues == [
            "close-up host", "b-roll cutaway", "lower-third tag"]

        critique = service.save_critique(
            first.id,
            findings=fixture["critique_findings"],
        )
        assert store.get_critique(critique.id).findings == {
            "pacing": "Cut the setup."}

        revision = fixture["revision"]
        revised = service.save_script(
            hook=revision["hook"],
            target_length_sec=revision["target_length_sec"],
            beats=[
                Beat.from_dict(item)
                for item in revision["beats"]
            ],
            body=revision["body"],
            cta=revision["cta"],
            parent_id=first.id,
        )
        assert revised.version == 2
        assert revised.parent_id == first.id
    finally:
        store.close()


def test_cm7_assembly_shape_maps_to_writer_query_and_source_ids():
    fixture = FIXTURE["assembly"]
    from writer.schemas import AssemblyQuery

    query = AssemblyQuery.from_dict(fixture["query"])
    assert query.format == "talking_head"
    assert query.n_examples == 2
    assert fixture["selected_ids"] == [
        "video-over", "video-average"]
    assert fixture["audience_questions"][0]["likes"] == 12
