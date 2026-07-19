from __future__ import annotations

import sqlite3

import pytest

from writer.schemas import (
    AssemblyQuery,
    Beat,
    CritiqueContract,
    DraftContract,
    PieceContract,
    ScriptContract,
    Shot,
    SourceSnapshot,
    VoiceSampleContract,
)
from writer.storage import WriterStore


def external_source() -> SourceSnapshot:
    return SourceSnapshot(
        provider="uoink",
        provider_ref="uoink://item/video-contract",
        title="The saved hour",
        creator="Fixture Creator",
        source_url="https://example.test/video-contract",
        credit_line=(
            "Source: The saved hour by Fixture Creator -- "
            "https://example.test/video-contract"
        ),
        excerpt="A local workflow removed one repeated task.",
        credit_required=True,
    )


def test_migration_creates_only_writer_tables(tmp_path):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        names = {
            row[0]
            for row in store.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        store.close()
    assert {
        "schema_migrations", "drafts", "pieces", "voice_samples",
        "scripts", "critiques",
    }.issubset(names)
    assert {
        "yoinks", "workspaces", "style_anchors",
        "workspace_critique_log",
    }.isdisjoint(names)


def test_source_free_draft_saves_and_updates_without_uoink(tmp_path):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        draft = store.save_draft(DraftContract(
            kind="blog",
            title="Original",
            body="Manual text.",
        ))
        assert draft.id == 1
        assert draft.sources == []
        updated = store.save_draft(DraftContract(
            id=draft.id,
            kind="blog",
            title="Original",
            body="Manual text, revised.",
            created_at=draft.created_at,
        ))
        assert updated.id == draft.id
        assert updated.created_at == draft.created_at
        assert updated.body.endswith("revised.")
        assert store.get_draft(draft.id) == updated
    finally:
        store.close()


def test_attached_snapshot_survives_reopen(tmp_path):
    path = tmp_path / "writer.db"
    store = WriterStore.open(path)
    draft = store.save_draft(DraftContract(
        kind="thread",
        body="Grounded draft.",
        sources=[external_source()],
    ))
    store.close()

    reopened = WriterStore.open(path)
    try:
        restored = reopened.get_draft(draft.id)
        assert restored is not None
        assert restored.sources[0].provider_ref == (
            "uoink://item/video-contract")
        assert restored.sources[0].excerpt.startswith("A local workflow")
    finally:
        reopened.close()


def test_piece_revision_keeps_credit_and_version_chain(tmp_path):
    store = WriterStore.open(tmp_path / "writer.db")
    source = external_source()
    try:
        first = store.save_piece(PieceContract(
            kind="thread",
            body="First pass.\n\n" + source.credit_line,
            sources=[source],
            credit_lines=[source.credit_line],
        ))
        second = store.save_piece(PieceContract(
            kind="thread",
            body="Second pass.\n\n" + source.credit_line,
            sources=[source],
            credit_lines=[source.credit_line],
            parent_id=first.id,
        ))
        assert first.version == 1
        assert second.version == 2
        assert second.parent_id == first.id
        assert store.get_piece(second.id) == second
    finally:
        store.close()


def test_script_critique_and_shots_are_one_domain(tmp_path):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        script = store.save_script(ScriptContract(
            hook="The slow part was not the model.",
            format="talking_head",
            target_length_sec=45,
            beats=[Beat("setup", "Name the repeated task.")],
            body="A complete script.",
            cta="Try one repeatable step.",
            shots=[Shot(1, "setup", ["close-up host"])],
            assembly_query=AssemblyQuery(
                topic="AI", n_examples=8),
        ))
        critique = store.save_critique(CritiqueContract(
            script_id=script.id,
            draft_text=script.body,
            findings={"hook_strength": "specific"},
        ))
        assert critique.id == 1
        assert store.list_critiques(
            script_id=script.id)[0].findings == {
                "hook_strength": "specific"}
        assert store.get_script(script.id).shots[0].scene == 1
    finally:
        store.close()


def test_active_voice_samples_are_capped_at_ten(tmp_path):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        for index in range(10):
            sample = store.add_voice_sample(VoiceSampleContract(
                name=f"Sample {index}",
                source_type="text",
                raw_text=f"Specific prose {index}.",
            ))
            assert sample.id == index + 1
        with pytest.raises(ValueError, match="capped at 10"):
            store.add_voice_sample(VoiceSampleContract(
                name="One too many",
                source_type="text",
                raw_text="Specific prose.",
            ))
        inactive = store.update_voice_sample(1, active=False)
        assert inactive.active is False
        allowed = store.add_voice_sample(VoiceSampleContract(
            name="Replacement",
            source_type="text",
            raw_text="Specific replacement prose.",
        ))
        assert allowed.id == 11
    finally:
        store.close()


def test_foreign_key_and_wal_are_enabled(tmp_path):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        assert store.connection.execute(
            "PRAGMA foreign_keys").fetchone()[0] == 1
        assert store.connection.execute(
            "PRAGMA journal_mode").fetchone()[0].casefold() == "wal"
        with pytest.raises(sqlite3.IntegrityError):
            store.save_critique(CritiqueContract(
                script_id=999,
                draft_text="Missing script.",
                findings={},
            ))
    finally:
        store.close()

