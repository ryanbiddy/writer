PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    brief TEXT NOT NULL DEFAULT '',
    sources_json TEXT NOT NULL DEFAULT '[]',
    voice_sample_ids_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_drafts_updated_at
    ON drafts(updated_at);

CREATE TABLE IF NOT EXISTS pieces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    parent_id INTEGER,
    title TEXT NOT NULL DEFAULT '',
    dek TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL,
    tags_json TEXT NOT NULL DEFAULT '[]',
    sources_json TEXT NOT NULL DEFAULT '[]',
    credit_lines_json TEXT NOT NULL DEFAULT '[]',
    voice_warnings_json TEXT NOT NULL DEFAULT '[]',
    voice_sample_ids_json TEXT NOT NULL DEFAULT '[]',
    angle TEXT NOT NULL DEFAULT '',
    target_length INTEGER,
    created_at TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (parent_id) REFERENCES pieces(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_pieces_created_at
    ON pieces(created_at);
CREATE INDEX IF NOT EXISTS idx_pieces_parent
    ON pieces(parent_id);

CREATE TABLE IF NOT EXISTS voice_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_url TEXT NOT NULL DEFAULT '',
    raw_text TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    is_default INTEGER NOT NULL DEFAULT 0,
    added_at TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_voice_samples_active
    ON voice_samples(active);

CREATE TABLE IF NOT EXISTS scripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version INTEGER NOT NULL DEFAULT 1,
    parent_id INTEGER,
    format TEXT NOT NULL DEFAULT '',
    target_length_sec INTEGER,
    hook TEXT NOT NULL,
    beats_json TEXT NOT NULL DEFAULT '[]',
    body TEXT NOT NULL DEFAULT '',
    cta TEXT NOT NULL DEFAULT '',
    shots_json TEXT NOT NULL DEFAULT '[]',
    sources_json TEXT NOT NULL DEFAULT '[]',
    assembly_query_json TEXT,
    created_at TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (parent_id) REFERENCES scripts(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_scripts_created_at
    ON scripts(created_at);
CREATE INDEX IF NOT EXISTS idx_scripts_parent
    ON scripts(parent_id);

CREATE TABLE IF NOT EXISTS critiques (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    script_id INTEGER,
    piece_id INTEGER,
    draft_text TEXT NOT NULL,
    findings_json TEXT NOT NULL DEFAULT '{}',
    mode TEXT NOT NULL DEFAULT 'agent',
    created_at TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (script_id) REFERENCES scripts(id) ON DELETE CASCADE,
    FOREIGN KEY (piece_id) REFERENCES pieces(id) ON DELETE CASCADE,
    CHECK (script_id IS NOT NULL OR piece_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_critiques_script
    ON critiques(script_id);
CREATE INDEX IF NOT EXISTS idx_critiques_piece
    ON critiques(piece_id);

