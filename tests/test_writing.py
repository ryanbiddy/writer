from __future__ import annotations

import pytest

from writer.schemas import SourceSnapshot, VoiceSampleContract
from writer.storage import WriterStore
from writer.writing import WritingService


class ExplodingUoink:
    def attach_source(self, item_id):
        raise AssertionError("source-free drafting must not call Uoink")


def source() -> SourceSnapshot:
    return SourceSnapshot(
        provider="uoink",
        provider_ref="uoink://item/source-1",
        title="A measured workflow",
        creator="A Creator",
        source_url="https://example.test/source-1",
        credit_line=(
            "Source: A measured workflow by A Creator -- "
            "https://example.test/source-1"
        ),
        excerpt="The measured workflow saved 42 minutes.",
        credit_required=True,
    )


def test_blank_manual_draft_never_calls_uoink(tmp_path):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        service = WritingService(store, uoink=ExplodingUoink())
        prepared = service.prepare_draft(
            kind="blog",
            brief="Explain one local workflow.",
            draft_text="My opening stays here.",
        )
        assert prepared.operation == "prepare_draft"
        assert prepared.sources == []
        assert prepared.context["draft_text"] == "My opening stays here."
        assert prepared.context["required_credits"] == []
        assert prepared.dependency_status == {"uoink": "not_requested"}
        assert "My opening stays here." in prepared.instruction
    finally:
        store.close()


def test_attach_is_explicit_and_does_not_replace_manual_text(tmp_path):
    class FixtureUoink:
        def attach_source(self, item_id):
            assert item_id == "source-1"
            return source()

    store = WriterStore.open(tmp_path / "writer.db")
    try:
        service = WritingService(store, uoink=FixtureUoink())
        attached = service.attach_uoink_source("source-1")
        prepared = service.prepare_draft(
            kind="thread",
            brief="Keep it concrete.",
            draft_text="User text must survive attachment.",
            sources=[attached],
        )
        assert prepared.context["draft_text"] == (
            "User text must survive attachment.")
        assert prepared.sources[0].provider_ref == (
            "uoink://item/source-1")
        assert prepared.dependency_status == {"uoink": "not_required"}
        assert prepared.context["required_credits"] == [
            source().credit_line]
    finally:
        store.close()


def test_save_source_free_piece_has_no_false_attribution(tmp_path):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        service = WritingService(store)
        piece = service.save_piece(
            kind="newsletter",
            body="I removed one repeated step.",
        )
        assert piece.sources == []
        assert piece.credit_lines == []
        assert "Source:" not in piece.body
    finally:
        store.close()


def test_save_grounded_piece_requires_and_keeps_credit(tmp_path):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        service = WritingService(store)
        with pytest.raises(ValueError, match="retain every required"):
            service.save_piece(
                kind="blog",
                body="A claim without its source.",
                sources=[source()],
            )
        piece = service.save_piece(
            kind="blog",
            body="A claim with its source.\n\n" + source().credit_line,
            sources=[source()],
            credit_lines=[source().credit_line],
        )
        assert piece.credit_lines == [source().credit_line]
        assert piece.sources[0].excerpt.startswith("The measured")
    finally:
        store.close()


def test_voice_samples_and_warnings_are_writer_owned(tmp_path):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        sample = store.add_voice_sample(VoiceSampleContract(
            name="Ryan sample",
            source_type="text",
            raw_text="I measured the local run before changing it.",
        ))
        service = WritingService(store, uoink=ExplodingUoink())
        prepared = service.prepare_draft(
            kind="tweet",
            brief="Write one line.",
            voice_sample_ids=[sample.id],
        )
        assert "I measured the local run" in prepared.system_prompt
        saved = service.save_piece(
            kind="tweet",
            body="A robust workflow.",
            voice_sample_ids=[sample.id],
        )
        assert saved.voice_warnings[0]["phrase"] == "robust"
    finally:
        store.close()


def test_revision_is_immutable_and_uses_previous_copy(tmp_path):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        service = WritingService(store)
        first = service.save_piece(
            kind="blog", body="First complete draft.")
        prepared = service.prepare_revision(
            first.id, "Cut the opening to 2 sentences.")
        assert prepared.operation == "revise_piece"
        assert prepared.context["previous_piece"]["id"] == first.id
        second = service.save_piece(
            kind="blog",
            body="Second complete draft.",
            parent_id=first.id,
        )
        assert second.parent_id == first.id
        assert second.version == 2
        assert store.get_piece(first.id).body == "First complete draft."
    finally:
        store.close()
