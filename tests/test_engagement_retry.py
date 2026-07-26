"""Durable global engagement retry, restart, and idempotency guards."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from writer.engagement import EngagementDelivery
from writer.http_api import create_server
from writer.mcp_server import WriterTools
from writer.schemas import SourceSnapshot
from writer.storage import WriterStore
from writer.uoink_client import UoinkUnavailable


class ManualClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 23, 8, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


class RecordingUoink:
    def __init__(self, *, mode: str = "accept") -> None:
        self.mode = mode
        self.calls: list[list[str]] = []
        self._lock = threading.Lock()

    def ingest_engagement(self, events):
        event_ids = [event["event_id"] for event in events]
        with self._lock:
            self.calls.append(event_ids)
        if self.mode == "down":
            raise UoinkUnavailable("offline")
        if self.mode == "slow":
            time.sleep(0.05)
        if self.mode == "duplicate":
            return {
                "submitted": len(events),
                "accepted": 0,
                "duplicates": len(events),
                "rejected": [],
            }
        if self.mode == "reject":
            return {
                "submitted": len(events),
                "accepted": 0,
                "duplicates": 0,
                "rejected": [
                    {
                        "event_id": event["event_id"],
                        "code": "not_found",
                        "message": "corpus item not found",
                        "retryable": False,
                    }
                    for event in events
                ],
            }
        return {
            "submitted": len(events),
            "accepted": len(events),
            "duplicates": 0,
            "rejected": [],
        }


def piece_payload(item_id: str) -> dict:
    source = SourceSnapshot(
        provider="uoink",
        provider_ref=f"uoink://item/{item_id}",
        title="Fixture",
        creator="Fixture Creator",
        source_url=f"https://example.test/{item_id}",
        credit_line="Source: Fixture by Fixture Creator",
        excerpt="A bounded fixture.",
        attached_at="2026-07-23T08:00:00+00:00",
        credit_required=True,
    ).validate()
    return {
        "kind": "tweet",
        "body": f"One measured result for {item_id}.",
        "sources": [source.to_dict()],
        "credit_lines": [source.credit_line],
    }


def with_delivery(
    store: WriterStore,
    uoink: RecordingUoink | None,
    clock: ManualClock,
) -> WriterTools:
    tools = WriterTools(store, uoink=uoink)
    tools.engagement = EngagementDelivery(store, uoink=uoink, clock=clock)
    return tools


def test_offline_restart_peer_return_delivers_old_and_new_once(tmp_path) -> None:
    database = tmp_path / "writer.db"
    clock = ManualClock()
    offline = RecordingUoink(mode="down")
    store = WriterStore.open(database)
    first = with_delivery(store, offline, clock)
    saved_a = first.save_piece(piece_payload("event-a"))
    event_a = store.pending_engagement(limit=10)[0]["event"]["event_id"]
    assert saved_a["engagement"]["state"] == "spooled"
    assert offline.calls == [[event_a]]
    store.close()

    clock.advance(60)
    available = RecordingUoink()
    reopened = WriterStore.open(database)
    second = with_delivery(reopened, available, clock)
    saved_b = second.save_piece(piece_payload("event-b"))
    try:
        delivered = [event_id for batch in available.calls for event_id in batch]
        assert saved_b["engagement"]["state"] == "accepted"
        assert len(delivered) == 2
        assert len(set(delivered)) == 2
        assert delivered.count(event_a) == 1
        assert reopened.engagement_status() == {"pending": 0, "rejected": 0}
    finally:
        reopened.close()


def test_early_retry_makes_no_request_and_backoff_is_persisted(tmp_path) -> None:
    clock = ManualClock()
    offline = RecordingUoink(mode="down")
    store = WriterStore.open(tmp_path / "writer.db")
    tools = with_delivery(store, offline, clock)
    try:
        tools.save_piece(piece_payload("backoff"))
        assert len(offline.calls) == 1
        row = store.connection.execute(
            "SELECT attempts, next_attempt_at FROM engagement_outbox"
        ).fetchone()
        assert tuple(row) == (1, "2026-07-23T08:01:00Z")

        assert tools.engagement.deliver_pending()["state"] == "not_applicable"
        clock.advance(59)
        assert tools.engagement.deliver_pending()["state"] == "not_applicable"
        assert len(offline.calls) == 1

        clock.advance(1)
        assert tools.engagement.deliver_pending()["state"] == "spooled"
        row = store.connection.execute(
            "SELECT attempts, next_attempt_at FROM engagement_outbox"
        ).fetchone()
        assert tuple(row) == (2, "2026-07-23T08:03:00Z")
        assert len(offline.calls) == 2

        for attempts, expected_delay in (
            (3, 240),
            (4, 480),
            (5, 900),
            (6, 900),
        ):
            due = datetime.fromisoformat(
                str(row["next_attempt_at"]).replace("Z", "+00:00")
            )
            clock.value = due
            assert tools.engagement.deliver_pending()["state"] == "spooled"
            row = store.connection.execute(
                "SELECT attempts, next_attempt_at FROM engagement_outbox"
            ).fetchone()
            next_attempt = datetime.fromisoformat(
                str(row["next_attempt_at"]).replace("Z", "+00:00")
            )
            assert int(row["attempts"]) == attempts
            assert (next_attempt - due).total_seconds() == expected_delay
    finally:
        store.close()


def test_permanent_rejection_survives_restart(tmp_path) -> None:
    database = tmp_path / "writer.db"
    clock = ManualClock()
    store = WriterStore.open(database)
    with_delivery(store, None, clock).save_piece(piece_payload("rejected"))
    rejecting = EngagementDelivery(
        store,
        uoink=RecordingUoink(mode="reject"),
        clock=clock,
    )
    assert rejecting.deliver_pending()["state"] == "rejected"
    store.close()

    reopened = WriterStore.open(database)
    try:
        assert reopened.engagement_status() == {"pending": 0, "rejected": 1}
    finally:
        reopened.close()


def test_duplicate_receipt_completes_the_crash_window_event(tmp_path) -> None:
    database = tmp_path / "writer.db"
    clock = ManualClock()
    store = WriterStore.open(database)
    with_delivery(store, None, clock).save_piece(piece_payload("duplicate"))
    store.close()

    duplicate = RecordingUoink(mode="duplicate")
    reopened = WriterStore.open(database)
    delivery = EngagementDelivery(reopened, uoink=duplicate, clock=clock)
    try:
        receipt = delivery.deliver_pending()
        assert receipt["state"] == "accepted"
        assert receipt["accepted"] == 0
        assert receipt["duplicates"] == 1
        assert len(duplicate.calls) == 1
        assert reopened.engagement_status()["pending"] == 0
    finally:
        reopened.close()


def test_concurrent_process_stores_do_not_double_submit_one_event(
    tmp_path,
) -> None:
    clock = ManualClock()
    database = tmp_path / "writer.db"
    seed_store = WriterStore.open(database)
    with_delivery(seed_store, None, clock).save_piece(
        piece_payload("concurrent")
    )
    seed_store.close()

    stores = [WriterStore.open(database), WriterStore.open(database)]
    slow = RecordingUoink(mode="slow")
    deliveries = [
        EngagementDelivery(store, uoink=slow, clock=clock)
        for store in stores
    ]
    barrier = threading.Barrier(3)
    receipts = []

    def run(delivery: EngagementDelivery) -> None:
        barrier.wait()
        receipts.append(delivery.deliver_pending())

    threads = [
        threading.Thread(target=run, args=(delivery,))
        for delivery in deliveries
    ]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=2)
    try:
        assert all(not thread.is_alive() for thread in threads)
        assert len(slow.calls) == 1
        assert sorted(receipt["submitted"] for receipt in receipts) == [0, 1]
        assert stores[0].engagement_status()["pending"] == 0
    finally:
        for store in stores:
            store.close()


def test_http_startup_and_writer_status_each_drain_one_due_batch(
    tmp_path,
) -> None:
    database = tmp_path / "writer.db"
    clock = ManualClock()
    store = WriterStore.open(database)
    with_delivery(store, None, clock).save_piece(piece_payload("startup"))
    store.close()

    startup_peer = RecordingUoink()
    server = create_server(
        host="127.0.0.1",
        port=0,
        token="test-token",
        database=database,
        uoink=startup_peer,
    )
    try:
        assert len(startup_peer.calls) == 1
        assert server.store.engagement_status()["pending"] == 0
    finally:
        server.server_close()

    store = WriterStore.open(database)
    with_delivery(store, None, clock).save_piece(piece_payload("status"))
    status_peer = RecordingUoink()
    tools = with_delivery(store, status_peer, clock)
    try:
        status = tools.writer_status()
        assert len(status_peer.calls) == 1
        assert status["engagement"] == {"pending": 0, "rejected": 0}
    finally:
        store.close()


def test_v2_database_migrates_existing_outbox_rows_as_due(tmp_path) -> None:
    database = tmp_path / "writer.db"
    connection = sqlite3.connect(database)
    root = Path(__file__).resolve().parents[1] / "src" / "writer" / "migrations"
    connection.executescript(
        (root / "0001_initial.sql").read_text(encoding="utf-8")
    )
    connection.executescript(
        (root / "0002_engagement_outbox.sql").read_text(encoding="utf-8")
    )
    connection.executemany(
        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
        [(1, "2026-07-23T08:00:00Z"), (2, "2026-07-23T08:00:00Z")],
    )
    event = {
        "event_id": "writer-existing",
        "item_ref": "uoink://item/existing",
        "event_type": "cite",
        "source_product": "writer",
        "occurred_at": "2026-07-23T08:00:00Z",
    }
    connection.execute(
        "INSERT INTO engagement_outbox "
        "(event_id, entity_kind, entity_id, entity_version, item_ref, "
        "event_json, attempts, last_error_code, created_at, updated_at) "
        "VALUES (?, 'piece', 1, 1, ?, ?, 0, '', ?, ?)",
        (
            event["event_id"],
            event["item_ref"],
            json.dumps(event),
            event["occurred_at"],
            event["occurred_at"],
        ),
    )
    connection.commit()
    connection.close()

    migrated = WriterStore.open(database)
    try:
        row = migrated.connection.execute(
            "SELECT next_attempt_at FROM engagement_outbox "
            "WHERE event_id='writer-existing'"
        ).fetchone()
        version = migrated.connection.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()
        assert row["next_attempt_at"] == ""
        assert version[0] == 3
        assert migrated.pending_engagement(
            due_at=datetime(2026, 7, 23, 8, 0, tzinfo=timezone.utc)
        )[0]["event"]["event_id"] == "writer-existing"
    finally:
        migrated.close()
