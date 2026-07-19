from __future__ import annotations

from pathlib import Path

import pytest

from writer.schemas import AssemblyQuery, Beat
from writer.scripts import ScriptService
from writer.storage import WriterStore
from writer.uoink_client import UoinkUnavailable


class FixtureUoink:
    def __init__(self):
        self.assembled = 0
        self.attached = []

    def assemble(self, query):
        self.assembled += 1
        assert query.topic == "Local AI"
        return {
            "filters": query.to_dict(),
            "assembled": [
                {
                    "video_id": "source-1",
                    "slug": "source-1",
                    "title": "A measured workflow",
                    "channel": "A Creator",
                    "topic": "Local AI",
                    "hook_type": "result_first",
                    "format": "talking_head",
                    "performance_tier": "over",
                    "length_bucket": "short",
                    "yoinked_at": "2030-01-02T03:04:05Z",
                }
            ],
            "audience_questions": [
                {
                    "video_id": "source-1",
                    "question": "What did the local run measure?",
                    "likes": 3,
                }
            ],
            "self_snapshot": None,
            "taste_anchors": "# Taste\n\nOpen on the result.",
        }

    def attach_source(self, item_id):
        from writer.schemas import SourceSnapshot

        self.attached.append(item_id)
        return SourceSnapshot(
            provider="uoink",
            provider_ref=f"uoink://item/{item_id}",
            title="A measured workflow",
            creator="A Creator",
            source_url="https://example.test/source-1",
            credit_line=(
                "Source: A measured workflow by A Creator -- "
                "https://example.test/source-1"
            ),
            excerpt="The local run measured 42 saved minutes.",
            credit_required=True,
        )


def test_source_free_script_never_needs_uoink(tmp_path):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        service = ScriptService(store)
        prepared = service.prepare_script(
            brief="A 30 second note about my own process.")
        assert prepared.sources == []
        assert prepared.dependency_status == {"uoink": "not_requested"}
        assert prepared.context["assembly"] is None
    finally:
        store.close()


def test_assembly_uses_only_client_contract_and_snapshots_sources(tmp_path):
    store = WriterStore.open(tmp_path / "writer.db")
    client = FixtureUoink()
    try:
        service = ScriptService(store, uoink=client)
        prepared = service.prepare_script(
            brief="Use the strongest local example.",
            assembly_query=AssemblyQuery(
                format="talking_head",
                topic="Local AI",
                n_examples=5,
            ),
        )
        assert client.assembled == 1
        assert client.attached == ["source-1"]
        assert prepared.dependency_status == {"uoink": "available"}
        assert prepared.sources[0].provider_ref == (
            "uoink://item/source-1")
        assert prepared.context["assembly"]["audience_questions"][0][
            "likes"] == 3
    finally:
        store.close()


def test_explicit_assembly_request_fails_calmly_when_uoink_is_down(tmp_path):
    class DownUoink:
        def assemble(self, query):
            raise UoinkUnavailable("Uoink is unavailable")

    store = WriterStore.open(tmp_path / "writer.db")
    try:
        service = ScriptService(store, uoink=DownUoink())
        with pytest.raises(UoinkUnavailable, match="unavailable"):
            service.prepare_script(
                brief="Ground this.",
                assembly_query=AssemblyQuery(topic="Local AI"),
            )
    finally:
        store.close()


def test_save_reopen_critique_and_revise_without_zing(tmp_path):
    path = tmp_path / "writer.db"
    store = WriterStore.open(path)
    service = ScriptService(store)
    saved = service.save_script(
        hook="The local test took 12 seconds.",
        format="talking_head",
        beats=[Beat("proof", "Name the measured result.")],
        body="A complete script.",
        cta="Measure one repeated step.",
    )
    critique_prompt = service.prepare_critique(
        saved.id, focus="pacing")
    assert critique_prompt.context["script"]["id"] == saved.id
    critique = service.save_critique(
        saved.id,
        findings={"pacing": "Cut 1 setup sentence."},
    )
    revision = service.prepare_revision(
        saved.id, critique_id=critique.id)
    assert revision.context["critique"]["id"] == critique.id
    revised = service.save_script(
        hook="The test took 12 seconds.",
        body="A shorter complete script.",
        parent_id=saved.id,
    )
    store.close()

    reopened = WriterStore.open(path)
    try:
        assert reopened.get_script(revised.id).version == 2
        assert reopened.list_critiques(
            script_id=saved.id)[0].id == critique.id
    finally:
        reopened.close()


def test_derive_shots_and_versioned_file_handoff_work_without_zing(
        tmp_path):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        service = ScriptService(store)
        script = service.save_script(
            hook="One save path fixed the handoff.",
            format="tutorial",
            beats=[
                Beat("hook", "Show the failed handoff.", "0:00-0:05"),
                Beat("fix", "Show the saved file.", "0:05-0:20"),
            ],
            body="The complete script body.",
            cta="Open the saved file.",
        )
        derived = service.derive_shots(script.id)
        assert len(derived.shots) == 2
        assert derived.shots[0].cues == [
            "screen recording", "annotated overlay", "close-up hands"]

        output = tmp_path / "handoff.md"
        document = service.export_shot_list(derived.id, output)
        text = output.read_text(encoding="utf-8")
        assert document.document_type == "writer.shot-list"
        for heading in (
                "# ", "## Hook", "## Beats", "## Script", "## CTA",
                "## Shots", "## Credits"):
            assert heading in text
        assert "schema_version: 1" in text
        assert "Zing" not in text
        assert Path(output).is_file()
    finally:
        store.close()
