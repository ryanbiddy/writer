"""Writer-owned durable delivery for Uoink engagement events."""

from __future__ import annotations

from typing import Any

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

    def __init__(self, store, uoink=None):
        self.store = store
        self.uoink = uoink

    def deliver_entity(
        self,
        entity_kind: str,
        entity_id: int,
    ) -> dict[str, Any]:
        rows = self.store.pending_engagement(
            entity_kind=entity_kind,
            entity_id=entity_id,
            limit=100,
        )
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
