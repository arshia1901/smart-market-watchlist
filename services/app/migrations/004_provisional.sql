-- Back-filled history is real in shape (the stock's own intraday volatility, resampled)
-- but not real in fact. It is marked so, and a sigma resting on any of it is shown as
-- provisional until 750 genuine buckets have displaced it.
ALTER TABLE quote_snapshot ADD COLUMN IF NOT EXISTS synthetic BOOLEAN NOT NULL DEFAULT FALSE;
