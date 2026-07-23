"""Writer-owned durable delivery for Uoink engagement events."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Callable

from writer.uoink_client import UoinkContractError, UoinkUnavailable


def _receipt(
    state: str,
    *,
    submitted: int,
    accepted: int = 0,
    duplicates: int = 0,
    spooled: int = 0,
    rejected: int = 0,
) -> dict[str, Any]:
    return {
        "state": state,
        "submitted": submitted,
        "accepted": accepted,
        "duplicates": duplicates,
        "spooled": spooled,
        "rejected": rejected,
    }


class EngagementDelivery:
    """Attempt one bounded batch; keep every uncertain event in Writer."""

    def __init__(
        self,
        store,
        uoink=None,
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        self.store = store
        self.uoink = uoink
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._delivery_lock = threading.RLock()

    def deliver_entity(
        self,
        entity_kind: str,
        entity_id: int,
    ) -> dict[str, Any]:
        """Deliver the newly saved entity, then one older due batch."""
        with self._delivery_lock:
            attempted_at = self.clock()
            if self.uoink is None:
                rows = self.store.pending_engagement(
                    entity_kind=entity_kind,
                    entity_id=entity_id,
                    limit=100,
                )
            else:
                rows = self.store.claim_engagement(
                    entity_kind=entity_kind,
                    entity_id=entity_id,
                    limit=100,
                    claimed_at=attempted_at,
                )
            receipt = self._deliver_rows(rows, attempted_at=attempted_at)
            if receipt["state"] != "spooled":
                self._deliver_pending_locked(
                    limit=25,
                    attempted_at=attempted_at,
                )
            return receipt

    def deliver_pending(self, *, limit: int = 25) -> dict[str, Any]:
        """Attempt one due global batch, serialized within this process."""
        with self._delivery_lock:
            return self._deliver_pending_locked(
                limit=limit,
                attempted_at=self.clock(),
            )

    def _deliver_pending_locked(
        self,
        *,
        limit: int,
        attempted_at: datetime,
    ) -> dict[str, Any]:
        if self.uoink is None:
            rows = self.store.pending_engagement(
                limit=limit,
                due_at=attempted_at,
            )
        else:
            rows = self.store.claim_engagement(
                limit=limit,
                claimed_at=attempted_at,
            )
        return self._deliver_rows(rows, attempted_at=attempted_at)

    def _deliver_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        attempted_at: datetime,
    ) -> dict[str, Any]:
        submitted = len(rows)
        if not rows:
            return _receipt("not_applicable", submitted=0)
        event_ids = [row["event"]["event_id"] for row in rows]
        if self.uoink is None:
            return _receipt(
                "spooled",
                submitted=submitted,
                spooled=submitted,
            )
        try:
            result = self.uoink.ingest_engagement(
                [row["event"] for row in rows]
            )
        except UoinkContractError as error:
            if error.retryable:
                self.store.mark_engagement_attempt(
                    event_ids,
                    error.code,
                    attempted_at=attempted_at,
                )
                return _receipt(
                    "spooled",
                    submitted=submitted,
                    spooled=submitted,
                )
            rejections = [
                {
                    "event_id": event_id,
                    "code": error.code,
                    "message": error.message,
                    "retryable": False,
                }
                for event_id in event_ids
            ]
            self.store.record_engagement_rejections(rejections)
            return _receipt(
                "rejected",
                submitted=submitted,
                rejected=submitted,
            )
        except (UoinkUnavailable, OSError, TimeoutError) as error:
            self.store.mark_engagement_attempt(
                event_ids,
                getattr(error, "code", "unavailable"),
                attempted_at=attempted_at,
            )
            return _receipt(
                "spooled",
                submitted=submitted,
                spooled=submitted,
            )

        rejected = list(result["rejected"])
        rejected_ids = {item["event_id"] for item in rejected}
        completed_ids = [
            event_id for event_id in event_ids
            if event_id not in rejected_ids
        ]
        self.store.complete_engagement(completed_ids)
        permanent = [
            item for item in rejected
            if not item["retryable"]
        ]
        retryable = [
            item for item in rejected
            if item["retryable"]
        ]
        if permanent:
            self.store.record_engagement_rejections(permanent)
        if retryable:
            self.store.mark_engagement_attempt(
                [item["event_id"] for item in retryable],
                retryable[0]["code"],
                attempted_at=attempted_at,
            )
        spooled = len(retryable)
        rejected_count = len(permanent)
        if spooled:
            state = "spooled"
        elif rejected_count:
            state = "rejected"
        else:
            state = "accepted"
        return _receipt(
            state,
            submitted=submitted,
            accepted=int(result["accepted"]),
            duplicates=int(result["duplicates"]),
            spooled=spooled,
            rejected=rejected_count,
        )
