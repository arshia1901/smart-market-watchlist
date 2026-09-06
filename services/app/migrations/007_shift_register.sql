-- The shift register, reinstated.
--
-- baseline_value  what this session compares against: the price at the START of the
--                 PREVIOUS session (or the price when the stock was added mid-session)
-- session_value   the price at the start of THIS session; promoted to baseline_value
--                 at the next sign-in
--
-- An earlier design dropped session_value on the argument that the client holds the
-- old baseline for the session. A page refresh is exactly the case where it does not:
-- the API returned the freshly-advanced baselines and every move read 0.00%.
-- Sign-in is now the only event that moves either column; refresh only reads.
ALTER TABLE watchlist_item ADD COLUMN IF NOT EXISTS session_value DOUBLE PRECISION;
ALTER TABLE user_login     ADD COLUMN IF NOT EXISTS previous_login_at TIMESTAMPTZ;
-- Backfill: the current anchor is the only anchor known. Nothing to promote yet.
UPDATE watchlist_item SET session_value = baseline_value WHERE session_value IS NULL;
