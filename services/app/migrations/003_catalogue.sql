-- The catalogue becomes the real NSE universe (~2,440 equities), which is what the
-- search box should offer. Fetching quotes for all of them is not possible against a
-- free per-symbol API, so tracking is demand-driven: a stock starts being fetched
-- when someone puts it on a watchlist, and not before.
ALTER TABLE instrument ADD COLUMN IF NOT EXISTS isin       TEXT;
ALTER TABLE instrument ADD COLUMN IF NOT EXISTS bse_code   TEXT;
ALTER TABLE instrument ADD COLUMN IF NOT EXISTS is_tracked BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS instrument_tracked ON instrument (is_tracked) WHERE is_tracked;
