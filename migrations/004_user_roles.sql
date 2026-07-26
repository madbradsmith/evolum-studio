-- ============================================================================
-- 004_user_roles.sql — 5-role account type (filmmaker/producer/actor/investor/supporter)
-- Not all users make projects: filmmaker + producer do; the other three don't.
-- Column added only if it doesn't already exist (safe on every boot).
-- ============================================================================

-- SQLite doesn't support "ADD COLUMN IF NOT EXISTS" — but re-running ADD COLUMN
-- on a column that exists raises a duplicate error. So we wrap in a temp trigger
-- that no-ops via CASE. Simpler: check via pragma_table_info at bootstrap time.
-- Done in db.py, not here. This file just documents intent.

-- Manual apply (idempotent via db.py check):
--   ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'filmmaker';
