BEGIN IMMEDIATE;

ALTER TABLE engagement_outbox
    ADD COLUMN next_attempt_at TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_engagement_outbox_due
    ON engagement_outbox(next_attempt_at, created_at, event_id);

INSERT OR IGNORE INTO schema_migrations(version, applied_at)
VALUES (3, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));

COMMIT;
