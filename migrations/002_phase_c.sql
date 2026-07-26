-- Phase C — actor profile, notifications, submissions, reel-cut log.
-- All tables idempotent.
--
-- Note: the `notify_new_roles` column on users was added MANUALLY via a
-- one-shot script (SQLite doesn't support ALTER TABLE ... ADD COLUMN IF NOT
-- EXISTS, so re-running this migration would crash the boot). New deployments
-- that need to re-create the schema from scratch should add the column via
-- the one-shot at the top of 001_initial.sql or via a deploy script.

CREATE TABLE IF NOT EXISTS actor_profiles (
    user_id        INTEGER PRIMARY KEY,
    stage_name     TEXT DEFAULT '',
    union_status   TEXT DEFAULT 'non-union',
    headshot_url   TEXT DEFAULT '',
    reel_url       TEXT DEFAULT '',
    agent_contact  TEXT DEFAULT '',
    bio            TEXT DEFAULT '',
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS actor_submissions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL,
    role           TEXT DEFAULT '',
    project        TEXT DEFAULT '',
    favored        INTEGER DEFAULT 0,
    submitted_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reel_cut_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL,
    source         TEXT DEFAULT '',
    requested_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
