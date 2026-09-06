# Smart Market Watchlist

**Ranked by how *unusual* a move is, not how big it is.**

Built for *Code, by Groww*. Ten real NSE large caps, live prices from BSE, nothing simulated.
A watchlist that tells you what has *meaningfully* changed since you last checked — and
shows you exactly how it knows.

```bash
git clone https://github.com/arshia1901/smart-market-watchlist.git && cd smart-market-watchlist
./run.sh start
```

Open **http://localhost:8080**. Requires **Docker Desktop** and nothing else — no API key,
no account. First start pulls images and builds the frontend (a few minutes); after that
it's seconds. The **Architecture** button opens the full design as a route.

---

## The idea in one table

Two stocks. Both moved **+2.7%** since you last looked, one trading day ago.

| Stock | σ (1-min) | Annualised | Expected move | Actual | Magnitude | |
|---|---|---|---|---|---|---|
| Large cap | 0.069% | 21% | 1.34% | +2.7% | **2.02** | notable |
| Small cap | 0.207% | 63% | 4.01% | +2.7% | **0.67** | noise |

Identical raw moves; one is news, one is Tuesday. A percentage-sorted list cannot tell them
apart. So "meaningful" is defined relative to how *that stock* normally behaves:

```
magnitude = |r| / (σ × √N)

r  = return since the start of your previous session (or since you added the stock)
σ  = that stock's own volatility over 750 one-minute buckets — two trading sessions
N  = trading minutes since you last signed in; closed hours count for nothing
```

Bands are half-open: `< 1` noise · `1–2` mild · `2–3` notable · `≥ 3` extreme. A move of
40% or more is flagged as a corporate action and excluded from ranking. Because √N is a
common factor across every row, N can never change the *order* — only the labels.

---

## Setup

### Prerequisites
- **Docker Desktop** (Docker 24+, Compose v2). Verified on macOS 12 / Intel; images are
  multi-arch and build natively on Apple Silicon and Linux.
- ~2 GB free for images. Ports **8080** (web) and **8000** (API); override with
  `WEB_PORT=9080 API_PORT=9000 ./run.sh start`.

### Commands
| | |
|---|---|
| `./run.sh start` | build and start all six containers, wait until serving, print the URL |
| `./run.sh status` | container health plus a live check of web and API |
| `./run.sh logs [service]` | follow logs (`ingestion`, `statistics`, `api`, `web`, `db`, `cache`) |
| `./run.sh test` | both test suites in containers (backend against its own test database) |
| `./run.sh demo` | the failure demonstrations, with what to watch for |
| `./run.sh stop` | stop containers, keep data |
| `./run.sh reset` | destroy volumes; the next start is a true cold start |

### Sign in
Three hardcoded users — authentication is deliberately not engineered:

| username | password |
|---|---|
| `asha` | `asha` |
| `ravi` | `ravi` |
| `meera` | `meera` |

`http://localhost:8080/?user=ravi` pre-fills the username. **Only the Sign in button
starts a session.** Signing in while already signed in is refused; sign out first.

### First five minutes
1. Sign in. The list is **empty** — nothing is pre-loaded.
2. Search `reliance`, add it. It appears as **NEW**. Within one minute it has a real BSE
   price and a **provisional σ** badge: its volatility was measured from *today's* real
   intraday bars and back-filled so it can be ranked immediately, marked provisional until
   two genuine sessions have replaced the fill.
3. Add two more. Watch the batch strip: **tracked** climbs, and each tick reports
   *new / unchanged / late*.
4. Sign out, sign in. The comparison anchor moves — the chip says when — and the moves
   are measured from your previous session. **Refresh as often as you like; nothing moves
   until you sign in again.**

Outside NSE hours (09:15–15:30 IST, Mon–Fri) prices do not change because nothing is
trading; rows say *last trade · market closed* with the absolute time. During hours the
free feed runs ~15 minutes behind and the chip says *delayed*, because it is.

---

## Test the whole pipeline by hand — the canary

`ARSHIA (test instrument)` is one deliberately non-real stock whose quotes you set yourself.
Everything downstream — ingestion tick, write-if-newer, the stream, the statistics
container, the API, the row — is exactly the path a real stock takes. Its chip reads **TEST**.

```bash
# in the app: search "arshia", add it. Then:
curl -X POST 'localhost:8000/api/test/warmup?symbol=ARSHIA&price=100&sigma=0.0007'
curl -X POST 'localhost:8000/api/test/quote?symbol=ARSHIA&price=100.15'   # next tick: +0.15%, notable
curl -X POST 'localhost:8000/api/test/quote?symbol=ARSHIA&price=100.30'   # extreme
curl -X POST 'localhost:8000/api/test/quote?symbol=ARSHIA&price=55'       # corporate action
```

The endpoints refuse every other symbol; a real stock cannot be poisoned. Add `&now=1` to
inject immediately instead of waiting for the tick.

---

## How it works

Six containers: `web` (nginx + Angular) · `api` (FastAPI) · `ingestion` · `statistics` ·
`db` (Postgres 16) · `cache` (Redis 7). One shared Python image, four entrypoints.

- **Ingestion** runs once a minute, fans out to BSE, and applies a quote only if its
  **event time is newer** than what is stored — an atomic compare-and-set in Redis. Equal
  time is *unchanged* (normal every minute on a closed market); older is a late packet and
  is dropped. This is the answer to the brief's word *conflicting*.
- **Statistics** tails a Redis Stream (persistent, replayable — not pub/sub) and recomputes
  σ over the whole 750-bucket window whenever a new bucket arrives, winsorising against the
  median absolute deviation so one bad tick cannot inflate σ for two days. On restart it
  rebuilds every window from the time series.
- **Sessions** are explicit and sequential. Sign in performs one transaction — the *shift
  register*: `previous_login ← last_login`, `last_login ← now`; per stock,
  `baseline ← session_price`, `session_price ← price now`. Refresh reads. Nothing else
  writes either column.
- **The read path is split by cacheability.** `/api/quotes` is identical for every user
  and micro-cached 2 s at the edge; `/api/watchlist` is personal and fetched once per
  session. **The server never does per-user arithmetic** — your browser computes the
  magnitude and ranks. Each user brings the CPU that serves them.
- **Failure is visible.** Stop the API and a red banner appears after 12 s without a fresh
  answer; stop the cache and the header flips to *served by store* (Postgres fallback);
  stop ingestion and prices visibly age. A failed click names the stock. *Stale is allowed,
  silent is not.*

The full design — wiring diagrams, data flow per component, and the GCP scaling plan for
200,000 concurrent users across 20,000 stocks — is in the app at **/arch** and in
[`docs/DESIGN.md`](docs/DESIGN.md).

---

## How to test it

### 1. The automated suites — one command

```bash
./run.sh test
```

Runs the backend suite inside the built image (64 tests) and the frontend suite in a node
container (22 tests). The backend's lifecycle tests create and use a **separate database**
(`watchlist_test`), so they never touch the data the app is serving.

Run them individually while developing:

```bash
cd services && python3 -m pytest -q          # pure tests need nothing running; lifecycle tests skip without a DB
cd web && npm test                            # Vitest, node environment, sub-second
```

With the stack up, the lifecycle tests run too (they reach the database through Docker):

```bash
docker compose run --rm --no-deps -T -v "$PWD/services/tests:/srv/tests:ro" api python -m pytest -q
```

| Suite | What it proves |
|---|---|
| `test_magnitude.py` | the worked example gives **2.02 → notable**; bands are half-open; a 1:10 split is flagged, not ranked; **N cannot reorder the list** (property test over 500 random lists) |
| `test_statistics.py` | σ recovers a planted σ within 5%; one 500-σ tick moves the winsorised σ under 10% while wrecking the naive one; a flatline is floored, never zero |
| `test_calendar.py` | a weekend contributes zero trading minutes; Saturday reads *market closed*, not *stale*; the container-timezone trap |
| `test_backfill.py` | the warm-up fill keeps the stock's own volatility and ends exactly at the live price |
| `test_fixture.py` | on the replay fixture the thesis holds end to end: the bigger raw move ranks lower |
| `test_lifecycle.py` | add → tracked → collecting → rated → removed; **three sign-ins compare against 100, 100, 110 with refreshes changing nothing**; sequential sessions (409); the canary provider cannot touch a real stock |
| `magnitude.spec.ts` | the **same golden value, 2.020687**, in TypeScript — the browser's formula cannot drift from the server's; the sort holds still while values update |

### 2. Test the application by hand — a ten-minute script

Start clean so nothing is inherited: `./run.sh reset && ./run.sh start`.

| Step | Do | Expect |
|---|---|---|
| Cold start | sign in as `ravi` / `ravi` | empty list; *"this is your first visit — no market time yet"*; strip shows 0 tracked |
| Add | search `reliance`, add | row appears **NEW**, no price; strip → **1 tracked** |
| Warm-up | wait for the next tick (≤ 60 s) | real BSE price; badge **provisional σ**; chip **BSE** |
| Anchor | sign out, sign in | chip *session started HH:MM UTC* moves; moves measured from the previous session |
| Refresh | press F5 five times | **nothing changes** — same baselines, same session time |
| Sequential | press Sign in again without signing out | refused: *"already signed in since … sign out first"* |
| Two users | open `?user=asha` in another browser, sign in, add the same stock | same price, **different move** — each measured from their own sign-in |
| Remove | remove the stock from the last list holding it | strip's tracked count drops; ingestion log: *no longer tracking* |

### 3. Drive a change through the whole pipeline — the canary

The market is closed two days in seven. `ARSHIA (test instrument)` lets you inject a price
and watch it travel ingestion → write-if-newer → stream → statistics → API → screen:

```bash
# add ARSHIA to a list in the app, then
curl -X POST 'localhost:8000/api/test/warmup?symbol=ARSHIA&price=100&sigma=0.0007'   # σ appears in seconds
curl -X POST 'localhost:8000/api/test/quote?symbol=ARSHIA&price=100.15'               # next tick: +0.15%, notable
curl -X POST 'localhost:8000/api/test/quote?symbol=ARSHIA&price=100.30'               # extreme
curl -X POST 'localhost:8000/api/test/quote?symbol=ARSHIA&price=55'                   # CORP ACTION, unranked
curl -X POST 'localhost:8000/api/test/quote?symbol=RELIANCE&price=1'                  # 400 — real stocks are protected
```

### 4. Check the arithmetic yourself

Everything on screen is computable from two endpoints:

```bash
curl -s 'localhost:8000/api/watchlist?user=ravi' | python3 -m json.tool   # baseline, sigma, n per row
curl -s 'localhost:8000/api/quotes' | python3 -m json.tool                 # price, as_of, source per stock
```

For any row: `r = (price − baseline) / baseline`, `magnitude = |r| / (sigma × √n)`. The
number in the Magnitude column is that, to two decimals. `sigma_provisional` says whether σ
still rests on back-filled buckets; `baseline_source` says whether the anchor is `added` or
`previous_session`; `trading_minutes_elapsed` is the truth behind `n` (0 on a weekend).

### 5. Failure demonstrations

```bash
./run.sh demo                        # the list, with what to watch for
docker compose stop ingestion        # prices age visibly; strip dot turns red after two missed cadences
docker compose stop cache            # header flips "served by store"; API falls back to Postgres
docker compose stop api              # after 12 s: red "Feed problem" banner; a failed click names the stock
docker compose start api ingestion cache
```

What is deliberately *not* tested, and the one-sentence defence for each omission, is in
[`docs/EDGE-CASES.md`](docs/EDGE-CASES.md).

---

## Data, honestly

- **Live, from BSE**, one call per tracked stock per minute. No key, no account.
- The catalogue is ten real NSE large caps (names, ISINs, circuit bands from official NSE
  files; BSE scripcodes joined on ISIN). Prices are BSE last trades; NSE/Yahoo figures for
  the same stock differ by a normal ~0.1% inter-exchange spread — the row says **BSE**.
- **No free source for Indian equities is licence-clean.** NSE and BSE restrict
  redistribution; local prototype use is the ordinary grey area. At any real scale this
  needs a data contract.
- A deterministic replay fixture exists **for the test suite only**, so edge cases (a 1:10
  split, a stalled feed, out-of-order ticks) can be planted on demand. It is never seeded
  into the running system.

---

## Documents

| | |
|---|---|
| [`PITCH.md`](PITCH.md) | the 100-word pitch |
| [`docs/DESIGN.md`](docs/DESIGN.md) | the design, with every argument |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | 22 decisions: the alternative, and why — including the reversals |
| [`docs/ASSUMPTIONS.md`](docs/ASSUMPTIONS.md) | what was assumed and what was deliberately not built |
| [`docs/EDGE-CASES.md`](docs/EDGE-CASES.md) | how each one fails, how it's handled, how to see it |

## Layout

```
run.sh · docker-compose.yml
services/app/        Python: domain/ (calendar, sigma, magnitude, backfill) · adapters/ · engines/ · api/
services/tests/      pytest — pure tests need no database; lifecycle tests create their own
web/src/app/         Angular: domain/ (magnitude, rank — pure, tested) · watchlist/ · arch/ · stock-search/
docs/                design, decisions, assumptions, edge cases
```
