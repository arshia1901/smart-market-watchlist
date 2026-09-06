-- Smart Market Watchlist. Spec section 7.
--
-- Seven tables. Users are a hardcoded config array, not a table (spec 12).
-- Two NULLs carry the two empty states: no baseline is *new*, no sigma is
-- *unrated*. Neither needs a flag column.

CREATE TABLE IF NOT EXISTS instrument (
    id             SERIAL PRIMARY KEY,
    symbol         TEXT NOT NULL UNIQUE,
    name           TEXT NOT NULL,
    band_limit     TEXT NOT NULL DEFAULT 'No Band',  -- official NSE price band
    tracked_since  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS instrument_symbol_trgm ON instrument (lower(symbol) text_pattern_ops);
CREATE INDEX IF NOT EXISTS instrument_name_lower  ON instrument (lower(name)   text_pattern_ops);

-- User grain: one login, one timestamp, therefore ONE N for the whole payload.
CREATE TABLE IF NOT EXISTS user_login (
    user_id        TEXT PRIMARY KEY,
    last_login_at  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS watchlist_item (
    user_id        TEXT NOT NULL,
    instrument_id  INT  NOT NULL REFERENCES instrument(id) ON DELETE CASCADE,
    added_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    baseline_value DOUBLE PRECISION,          -- NULL = new (spec 4.7)
    PRIMARY KEY (user_id, instrument_id)
);

CREATE TABLE IF NOT EXISTS session (
    token       TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Last known value. `as_of` is the quote's own event time, and is what
-- write-if-newer compares - never arrival time (spec 5.3).
CREATE TABLE IF NOT EXISTS quote_latest (
    instrument_id  INT PRIMARY KEY REFERENCES instrument(id) ON DELETE CASCADE,
    price          DOUBLE PRECISION NOT NULL,
    as_of          TIMESTAMPTZ NOT NULL,
    source         TEXT NOT NULL,
    received_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The time series. Feedstock for sigma and the audit trail; never read by the API.
CREATE TABLE IF NOT EXISTS quote_snapshot (
    instrument_id  INT NOT NULL REFERENCES instrument(id) ON DELETE CASCADE,
    bucket_ts      TIMESTAMPTZ NOT NULL,
    price          DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (instrument_id, bucket_ts)
);

CREATE TABLE IF NOT EXISTS symbol_stats (
    instrument_id  INT PRIMARY KEY REFERENCES instrument(id) ON DELETE CASCADE,
    sigma          DOUBLE PRECISION,          -- NULL = unrated (spec 4.7)
    observations   INT NOT NULL DEFAULT 0,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
