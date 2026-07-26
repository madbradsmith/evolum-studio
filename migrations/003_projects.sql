-- ============================================================================
-- 003_projects.sql — projects + project_assets + project_versions
-- Foundation for the connected studio flow: idea → script → deck → sizzle → deliverables.
-- All tables idempotent (CREATE TABLE IF NOT EXISTS) so this migration runs cleanly on every boot.
-- ============================================================================

CREATE TABLE IF NOT EXISTS projects (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    title           TEXT NOT NULL,
    project_type    TEXT DEFAULT 'filmmaker',  -- filmmaker | actor
    status          TEXT DEFAULT 'draft',       -- draft | scripting | decking | ready | archived
    idea_text       TEXT DEFAULT '',            -- raw logline / pitch from idea page
    synopsis_text   TEXT DEFAULT '',
    characters_json TEXT DEFAULT '[]',          -- Elements panel: [{name, role}, ...]
    world_json      TEXT DEFAULT '{}',          -- Elements panel: {setting, era, tone, themes, notes}
    script_text     TEXT DEFAULT '',            -- raw scene-by-scene script content
    script_path     TEXT DEFAULT '',            -- on-disk path to uploaded screenplay file
    has_script      INTEGER DEFAULT 0,
    has_deck        INTEGER DEFAULT 0,
    has_sizzle      INTEGER DEFAULT 0,
    has_analysis    INTEGER DEFAULT 0,
    brain_path      TEXT DEFAULT '',
    deck_path       TEXT DEFAULT '',
    analysis_path   TEXT DEFAULT '',
    sizzle_path     TEXT DEFAULT '',
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(user_id, status);

-- Per-project file storage (uploaded scripts, posters, images, generated artifacts).
CREATE TABLE IF NOT EXISTS project_assets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL,
    asset_kind    TEXT NOT NULL,    -- script | poster | image | deck | analysis | sizzle | manifest
    asset_name    TEXT NOT NULL,
    asset_path    TEXT NOT NULL,
    size_bytes    INTEGER DEFAULT 0,
    content_type  TEXT DEFAULT '',
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_assets_project ON project_assets(project_id);
CREATE INDEX IF NOT EXISTS idx_assets_kind ON project_assets(project_id, asset_kind);

-- Versioned script saves from the editor.
CREATE TABLE IF NOT EXISTS script_versions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL,
    version_n     INTEGER NOT NULL,
    label         TEXT DEFAULT '',
    script_text   TEXT NOT NULL,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_versions_project ON script_versions(project_id);
