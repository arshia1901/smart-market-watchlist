-- The canary. A test instrument's quotes come from here instead of an exchange, so the
-- whole pipeline - ingestion, write-if-newer, the stream, the statistics engine, the
-- API, the UI - can be exercised on a Sunday with a value set by hand. Rows here are
-- only ever read for symbols in config.TEST_SYMBOLS; a real stock cannot be poisoned.
CREATE TABLE IF NOT EXISTS test_quote (
    symbol  TEXT PRIMARY KEY,
    price   DOUBLE PRECISION NOT NULL,
    as_of   TIMESTAMPTZ NOT NULL
);
