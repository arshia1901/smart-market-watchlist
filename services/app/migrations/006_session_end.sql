-- Sessions are explicit and sequential: opened by Sign in, closed by Sign out, and a
-- second Sign in while one is open is refused. ended_at IS NULL means open.
ALTER TABLE session ADD COLUMN IF NOT EXISTS ended_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS session_open ON session (user_id) WHERE ended_at IS NULL;
