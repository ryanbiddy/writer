CREATE TABLE IF NOT EXISTS engagement_outbox (
    event_id TEXT PRIMARY KEY,
    entity_kind TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    entity_version INTEGER NOT NULL,
    item_ref TEXT NOT NULL,
    event_json TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error_code TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_engagement_outbox_entity
    ON engagement_outbox(entity_kind, entity_id);

CREATE TABLE IF NOT EXISTS engagement_rejections (
    event_id TEXT PRIMARY KEY,
    entity_kind TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    entity_version INTEGER NOT NULL,
    item_ref TEXT NOT NULL,
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    rejected_at TEXT NOT NULL
);
