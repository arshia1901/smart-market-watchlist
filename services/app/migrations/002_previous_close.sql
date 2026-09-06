-- On a first visit there is no "last checked", so the baseline needs a stated
-- fallback the way N already has one. The previous session's close is the honest
-- reference point, and holding it on the instrument keeps the time series off the
-- request path - this is a single column read, not a history scan.
ALTER TABLE instrument ADD COLUMN IF NOT EXISTS previous_close DOUBLE PRECISION;
