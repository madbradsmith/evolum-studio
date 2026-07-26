CREATE TABLE IF NOT EXISTS users (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    email                  TEXT NOT NULL UNIQUE,
    password_hash          TEXT NOT NULL,
    name                   TEXT DEFAULT '',
    created_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    stripe_customer_id     TEXT DEFAULT '',
    stripe_subscription_id TEXT DEFAULT '',
    plan                   TEXT DEFAULT 'trial',
    subscription_active    INTEGER DEFAULT 0,
    trial_ends_at          TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_email             ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_stripe_customer   ON users(stripe_customer_id);
