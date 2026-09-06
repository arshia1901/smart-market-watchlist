# Smart Market Watchlist — Design

**Challenge:** Code, by Groww · 72-hour build · solo
**Date:** 2026-09-05
**Status:** design agreed, pending implementation plan

---

## 1. The problem

> Build a smart market watchlist that helps users not just track stocks, but quickly
> understand what has "meaningfully changed" since they last checked, and what
> deserves their attention now.

The brief fixes almost nothing and leaves six things to us: what counts as a meaningful
change, what information to surface, how state persists across sessions and devices, how
to handle stale/delayed/conflicting data, how the system scales, and where to keep things
simple rather than add complexity.

The one term it deliberately leaves undefined — **"meaningfully changed"** — is the
centre of this document. Everything else is downstream of it.

## 2. Thesis

**The system answers "what changed that I should care about?", not "what is the price?"**

Price display is table stakes. The product is the ranking layer that decides what deserves
attention. We would rather ship one idea properly than many partially; the challenge states
outright that feature count is not what is being evaluated.

## 3. Defining "meaningful change"

### 3.1 Why percentage change is the wrong answer

Ranking a watchlist by percentage change surfaces the same volatile small-caps every single
day. A 2% move in a large-cap that rarely moves 2% is a genuinely unusual event. A 2% move
in a stock that routinely swings 5% is an ordinary Tuesday. Sorted by percentage, these are
identical. They are not identical.

**Meaningful is not the same as large.** A change is meaningful when it is unusual
*relative to how that particular stock normally behaves.*

### 3.2 The measure

Significance is the size of the move expressed in units of the stock's own volatility.

**The grain.** One global **1-minute** grid, aligned to a fixed start line, shared by every
stock and every user. Bucket boundaries are absolute; they are not relative to anyone's
login.

**The standard.** For each stock, one number — `sigma`, the standard deviation of that
stock's 1-minute returns over **the last 750 trading buckets (two trading days)**.
Computed on returns rather than prices, because prices are not stationary and returns are.
The window length is a constant, identical for every stock. Maintained asynchronously.

```
NSE session 09:15-15:30 IST  =  22,500s  =  375 buckets per trading day
sigma window                 =  750 buckets  =  2 trading days
```

The window counts **trading** buckets only. Two *calendar* days would be 2,880 buckets, of
which ~74% are the market being shut and every return exactly zero. Padding the sample with
zeros biases `sigma` downward — it comes out near half its true value, every magnitude
doubles, and the bands stop meaning anything.

**The gap.** `N` = the number of 1-minute buckets between the user's previous login and
this one. **One number per user per session**, shared by every stock in their list.

**The expected move.** Over `N` buckets, a stock doing nothing unusual drifts by roughly
`sigma * sqrt(N)`. Volatility compounds with the square root of time.

**The actual move.** `r = (price_now - baseline_value) / baseline_value`

**The magnitude.**

```
magnitude = |r| / (sigma * sqrt(N))
```

Rank descending by magnitude. Display the sign separately.

Mean drift (`mu`) is deliberately dropped: over these horizons it is approximately zero and
carrying it adds a term we would have to defend for no gain in discrimination.

### 3.3 The example that makes the case

Both stocks moved **+2.7%** since the user last looked. They last checked one trading day
ago, so `N = 375` and `sqrt(N) ~ 19.4`.

| Stock | sigma (1m) | Annualised | Expected move | Actual move | Magnitude | Verdict |
|---|---|---|---|---|---|---|
| Large cap | 0.069% | 21% | 1.34% | +2.7% | **2.02** | notable |
| Small cap | 0.207% | 63% | 4.01% | +2.7% | **0.67** | noise |

The magnitudes are quoted to two decimals deliberately. An earlier draft rounded the first
to "2.0", which hid that the true value was 1.99 — and under the half-open bands of 3.4 that
is *mild*, not *notable*. The table contradicted its own verdict column, and only the test
that encodes this table caught it.

The annualised column is a sanity check, not decoration: `sigma_1m * sqrt(375 * 250) =
sigma_1m * 306`. Annualised volatility is grain-invariant, so it is the figure that stays
honest when the grid changes. Any `sigma` we quote has to survive that conversion — 21% and 64% are an
ordinary large cap and an ordinary volatile small cap. Figures that annualise to 150%+ would
mean the example was arithmetic rather than a market.

Identical raw moves. One is news; one is Tuesday. A percentage-sorted watchlist cannot tell
them apart. This table is the argument for the whole design.

### 3.4 Bands

Intervals are half-open, so every boundary value has exactly one band:

| Magnitude | Band |
|---|---|
| `[3, inf)` | extreme |
| `[2, 3)` | notable |
| `[1, 2)` | mild |
| `[0, 1)` | noise |
| — | **new** — added since the last session, no baseline to compare against |
| — | **unrated** — the stock has under two trading days of history, so no `sigma` |

Bands drive row styling. A highlighted row therefore carries information, not novelty.

### 3.5 The ranking is independent of N

Because `N` is one number shared by every row in a user's payload, `sqrt(N)` is a common
factor. Dividing every row by the same constant cannot change their order:

```
sort order  ==  sort by  |r_i| / sigma_i        N plays no part
band label  ==  needs N
```

**`N` affects interpretation, not ordering.** This materially de-risks the market calendar:
if the holiday list is imperfect, or a half-day session is mishandled, or the overnight gap
is fudged, **the list still ranks correctly**. Only band labels drift, and gently — `N`
wrong by 4x moves `sqrt(N)` by 2x, which might relabel a *notable* as a *mild*. Nothing
inverts; nothing leaps to the top.

The calendar must still be right for **freshness** (section 5.4), which is a different job
with visible consequences. But precise trading-bucket counting is not load-bearing.

### 3.6 The grid matches what feeds actually publish

Free market feeds publish at **1-minute** granularity. The grid is 1 minute *because of that*,
not by coincidence.

Had we picked a finer grid — 5 seconds, say — then 11 of every 12 buckets would carry a zero
return, because no new price arrived in them. `sigma` would collapse by `sqrt(12)` ~ 3.5x,
every magnitude would inflate by the same factor, and **every stock on the board would read
*extreme***. It is the identical failure to the calendar-day window above, arriving through a
different door, and worse — because the product still looks like it is working.

Matching the grid to the feed removes that failure instead of guarding against it, which is the
same move as designing accumulator drift out of reach in section 9: **an edge case designed out
of existence needs no handler, no test, and no explanation.** Worth applying only where the
option genuinely exists — circuit limits looked like another candidate until we found the data,
and the honest answer there was to build the detector.

One consequence worth stating: with the grid aligned to the feed, live data is now a legitimate
source for `sigma`. We still seed the window from the replay fixture, because 750 trading
buckets is 12.5 hours of market time and no amount of polling produces it at boot — but that is
a bootstrapping constraint, not a correctness one.

### 3.7 The measure is a system parameter

`MEASURE = price`, a single system parameter. The arithmetic is written against a measure
abstraction, so pointing it at volume is a configuration change plus a provider field.

We did **not** build a configurable array of measures or a UI to select between them. The
brief asks for judgement about *what* change matters, not for an analytics platform. Volume
anomaly is a genuinely good second signal — a stock up 1% on 10x volume often matters more
than one up 3% on nothing — and it is deliberately out of scope.

## 4. Session and baseline model

### 4.1 The rule

**A symbol's baseline is what it was worth when the user's previous session started.**

That is the entire rule. There is no acknowledge step, no "mark as read" button, and no
endpoint for either. The baseline advances automatically, exactly once, at login.

### 4.2 Why sign-in is the right boundary — and it is explicit

The brief says "since they last checked". A sign-in is the cleanest available definition of
"checked", and it is now the **only** thing that starts a session: `?user=` pre-selects a
user but never signs one in. **Sign out closes the session on the server. Sessions are
sequential: a sign-in while one is open is refused with an error** rather than silently
re-anchoring every baseline — which is exactly what an implicit `?user=` login once did.

Closing the browser without signing out is out of scope by decision. The held token still
reaches the Sign out button; the rule only bites from another browser. What constitutes a
session is a separate debate, and this design takes the narrowest defensible position.

### 4.3 Refresh is not a new session

If the baseline advanced on every page load, F5 would wipe every highlight — the same
failure an acknowledge step exists to prevent. So a session is a token minted at login and
held in **`localStorage`** — not memory, and not `sessionStorage`. In memory, F5 mints a new
session and wipes every highlight, which is the exact failure this section exists to prevent
and which section 4.6 makes unrecoverable. `sessionStorage` dies with the tab, contradicting
4.4's per-user intent. Refreshes reuse the token and re-read state without advancing anything. **The
baseline moves once per login, never per request.** A held token whose session the server has since closed is dead: the page returns to the
sign-in card rather than pretending.

### 4.4 Baselines are per-user, not per-device

If the user saw a move on their phone at 10:00, their laptop should not re-flag it at 11:00.
One baseline per `(user, symbol)`, shared across devices. This directly answers the brief's
question about persistence across sessions and devices.

The alternative — per-device baselines — is more literally accurate per device but replays
changes the user has already seen. Rejected.

### 4.5 The client holds the session and does the arithmetic

Login hands the client its raw materials once: the baseline value per stock, `sigma` per
stock, and the single `N`. The client holds them for the session and computes magnitudes
itself against prices it fetches separately.

An earlier draft used this to justify a **single** baseline column — "the server has
already handed the old value to the client, so it can overwrite immediately." A page refresh
disproved it: refresh re-reads the store, found the freshly advanced values, and every move
read 0.00%. The shift register is back (section 7) and sign-in is the only event that moves
it. The sign-in response is built from stored state *after* the shift, so it and a refresh
can never disagree.

**Values are live; the sort is stable.** Magnitudes recompute as prices arrive, so the
numbers on screen are current. The sort order is fixed at load and re-evaluated only on
refresh, because a list that reorders under the reader's eyes is hostile. Section 3.5 makes
this cheap to justify: order depends only on `|r|/sigma`.

**Cost, stated plainly:** `N` is fixed at login, so a long session under-penalises late
moves — after three hours of watching, the yardstick still assumes the gap you arrived
with.

### 4.6 Advancing the baseline is destructive

With one column, login overwrites the previous value the moment it is read. If the client
crashes and the user never sees the screen, that comparison is gone permanently.

We accept this: **you logged in, so you checked.** It is recorded here rather than
discovered later. The time series would technically permit recovery, but reading history on
the request path is precisely what this design avoids.

### 4.7 Two empty states, both encoded as NULL

| Condition | Meaning | Encoding |
|---|---|---|
| **new** | user added it since their last session | `watchlist_item.baseline_value IS NULL` |
| **unrated** | the stock has under two trading days of history and no fill was possible | `symbol_stats.sigma IS NULL` |
| **provisional** | `sigma` rests on back-filled buckets — see 11 | any `synthetic` row in the last 750 of `quote_snapshot` |

Neither needs a flag column, and neither is a special case in *storage* — same table, same
query, same path. The statistics engine simply does not publish a `sigma` until its window is
full.

The ranking layer is the honest exception: it must branch on both NULLs before dividing. The
claim is about schema design, not about the whole system, and overstating it would invite
exactly the question we could not answer.

## 5. Handling stale, delayed and conflicting data

### 5.1 Last known value

**Nothing on the read path computes, waits, or fails.** It reads what is stored:

```
baseline_value  <- OLTP              frozen at previous login
sigma           <- caching engine    last known
N               <- market calendar   computed once at login
price_now       <- caching engine    last known, fetched separately by the client
```

No blocking call, no error path. The request can only succeed.

One genuine hole, closed explicitly: a symbol added mid-session has no quote until the next
grid cycle, so it can be present in the watchlist and absent from `/api/quotes`. The client
renders it as **new** and does not divide.

### 5.2 Why this is correct, not merely convenient

**Price and volatility decay at completely different rates.** A price is stale within
seconds. Volatility is a slow-moving property of a stock — it clusters rather than jumping
around — so an hour-old `sigma` is very nearly as good as a fresh one.

The expensive quantity to compute is precisely the one that tolerates being old. That
asymmetry is what makes the synchronous/asynchronous split correct rather than a performance
trick.

### 5.3 Last known means last by event time

Market feeds deliver out of order and retry. A delayed packet carrying an older price
arrives *after* a newer one, and under naive last-known-value it rewinds the price — `r`
inverts and the stock leaps to the top of the list for no reason.

**Every write is write-if-newer**, compare-and-set on the quote's own event timestamp. Late
arrivals are dropped, not applied. This one rule is what makes last-known-value robust
rather than sloppy, and it is our direct answer to the word *conflicting*.

### 5.4 Staleness is disclosed, never hidden

Serving an old value silently is lying. Every row carries its as-of timestamp, and freshness
is a visible state — **live / delayed / stale / market closed** — classified against the
market calendar rather than wall clock, so a five-hour-old price on a Saturday reads
correctly as *market closed* rather than *broken*.

This is the part of the calendar that genuinely has to be right (section 3.5).

**Freshness is a ticking clock on the client, not a value recomputed when data arrives.** If it
only updated on new data, then the moment ingestion stopped the label would freeze on *live*
forever — the display would assert the opposite of what was happening, on the one behaviour we
most want to be honest about.

### 5.5 What this buys

The dependency chain inverts. The provider, the ingestion engine and the statistics engine
can all be down and the product still serves, with values that quietly age and say so.
**No component outside the read path can take the product down.**

That sentence is only true if we defend it. Putting the last-known quote and `sigma` solely in
the Caching Engine would place the cache *inside* the read path and hand the system exactly the
single point of failure this section claims it does not have. So the Read API **falls back to
`quote_latest` and `symbol_stats` in the OLTP store when the cache is unreachable.** Both tables
already exist in section 7; the fallback is a few lines, and it is what makes the cache an
accelerator rather than a dependency.

Stopping the cache therefore becomes a third demonstration rather than an outage.

## 6. Architecture

### 6.1 Components

Named by role. The implementation behind each is a swap, not a redesign.

| # | Component | Responsibility |
|---|---|---|
| 1 | Instrument Catalogue | Two sets, deliberately distinct. The **catalogue** is the real NSE universe (~2,440 equities from official sources, joined to BSE scripcodes on ISIN) and is what search offers. The **tracked set** is what ingestion actually fetches. Tracking is demand-driven: adding a stock to any watchlist moves it from the first set to the second and collection begins on the next cycle; removing it from the last list that holds it moves it back, and collection stops — the config-driven behaviour described in the brief, with the config being the watchlists themselves. |
| 2 | Provider Adapter | Pluggable quote source, one interface, three legs: **BSE** for real stocks; a **test** leg for the one canary instrument (`ARSHIA`), whose quotes come from a table set by hand so the whole pipeline can be exercised on a day the market is shut; and the **replay** fixture, used by the test suite only. Every row says which leg quoted it. |
| 3 | Ingestion Engine | Walks the catalogue on the grid, writes quotes write-if-newer, emits events. **The grid clock is injected, never global** — replaying two trading days must take seconds, not two trading days. |
| 4 | Subscription Engine | Decouples ingestion from computation. Publishers do not know subscribers. **A persistent, replayable log — not fire-and-forget pub/sub**: stopping the Statistics Engine must not silently punch a hole in `sigma`. |
| 5 | Statistics Engine | Asynchronous. Maintains `sigma` over a 750-bucket rolling window. Allowed to lag. **Cadence: event-driven, not timed.** It tails the stream and recomputes a stock's `sigma` only when a new minute bucket for that stock arrives — once per minute per stock while the market is open, never while it is closed (nothing new to compute from), instantly on add (the warm-up publishes 750 buckets), in full on restart. Each recompute spans the whole window rather than updating an accumulator, so drift cannot occur. Its heartbeat is a separate thing: it reports every ~1s that it is alive and listening, whether or not anything changed — liveness, not recomputation. |
| 6 | Time Series Store | Grid snapshots. Write-heavy, read-rare. Feedstock for `sigma` and the audit trail. Never on the request path. |
| 7 | Caching Engine | Last-known quote and `sigma`. Shared across all users. **An accelerator, never the source of truth** — see 5.5. |
| 8 | OLTP Database | Catalogue, watchlist membership, per-user baselines, login times. |
| 9 | Read API | Serves stored values. No computation of magnitude, no blocking. |
| 10 | Market Calendar | Approximate for `N`; authoritative for freshness. |
| 11 | Session / Identity | Mints a session, advances baselines once. Deliberately trivial. |
| 12 | Web Client | One route. **Computes magnitudes and ranks.** |

### 6.2 Flow

```
Provider Adapter -> Ingestion Engine --+-> Caching Engine       (last known)
                                       +-> Time Series Store    (sigma feedstock)
                                       +-> Subscription Engine -> Statistics Engine -> sigma

  login    ->  Read API  ->  { baseline per stock, sigma per stock, N }   personal, once
  prices   ->  Read API  ->  { price per stock }                          shared, polled
                                        |
                                        v
                                   Web Client:  magnitude = |r| / (sigma * sqrt(N))
```

### 6.3 Three tiers, and what each costs

| Tier | Work | Cost grows with |
|---|---|---|
| **Asynchronous, shared** | ingestion, time series, `sigma` | symbols only |
| **Synchronous, shared** | current prices — identical for every user | nothing; cacheable at the edge |
| **Client, personal** | magnitude and ranking | nothing on our side |

**The server performs no per-user arithmetic.** It hands over raw materials; each user's
device does its own 200-row calculation. Per-user compute cost is not merely small — every
new user brings the CPU that serves them.

## 7. Data model

Seven tables. Users are a hardcoded config array, not a table.

```
instrument      (id, symbol, name, is_tracked, tracked_since)

user_login      (user_id, previous_login_at, last_login_at)  -- user grain; N uses previous

watchlist_item  (user_id, instrument_id, added_at,
                 baseline_value,                          -- price at START of PREVIOUS session
                                                          --   (or at add time); NULL = new
                 session_value)                           -- price at start of THIS session;
                                                          --   promoted to baseline at next sign-in

session         (token, user_id, started_at)

quote_latest    (instrument_id, price, as_of, source, received_at)

quote_snapshot  (instrument_id, bucket_ts, price)         -- the time series

symbol_stats    (instrument_id, sigma, updated_at)        -- NULL sigma = unrated
```

Two things worth noting.

**`user_login` is genuinely user-grain.** One sign-in, therefore one `N` for the whole
payload — it does not belong on the per-stock row. It carries two timestamps for the same
reason `watchlist_item` carries two prices: `N` and the comparison label use the *previous*
session's start; the session chip shows the *current* one.

**The shift, at sign-in and only at sign-in:**

```
previous_login_at <- last_login_at        last_login_at <- now
baseline_value    <- session_value        session_value <- price now      (per stock)
```

A stock added mid-session has `session_value` from its first price, so at the next sign-in
its baseline becomes exactly the price when the user added it — which is when they last
checked it.

**`observations` is not stored.** The window is a constant (750), so the only per-stock
question is whether the stock has been tracked long enough to fill it. That is answered by
`instrument.tracked_since`, and expressed as `symbol_stats.sigma IS NULL`.

**Login writes** one `user_login` row and one `watchlist_item` row per stock — 100-200
writes per login at target watchlist size. This is the design's main write amplification and
is recorded in Appendix A.

## 8. API

```
POST   /api/session          login -> session token, baselines, sigma per stock, N
                                      ADVANCES baselines. The only endpoint that does.
GET    /api/watchlist        current state without advancing (refresh path)
GET    /api/instruments?q=   catalogue search
GET    /api/quotes           current prices - IDENTICAL for every user, cacheable
POST   /api/watchlist        add
DELETE /api/watchlist/{id}   remove
```

Two properties are deliberate. There is **no acknowledge endpoint** (section 4.1). And
`/api/quotes` carries **no per-user data whatsoever**, so it can be cached at the edge and
served once to arbitrarily many users — the shared/personal split is enforced by the API
shape rather than by discipline.

## 9. Edge cases

These are where a naive implementation of section 3 fails loudly.

| Case | Failure if ignored | Handling |
|---|---|---|
| **Corporate action** | A 1:10 split is a -90% return and a magnitude near 50. It tops every watchlist forever, looking like the story of the century. | Flag `|r| >= 40%` as *suspected corporate action* and exclude from ranking. Keyed off the **return**, not the magnitude — see 9.1. A 1:10 split is -90%, a 1:2 split is -50%, and an NSE circuit band caps a genuine session move at 20%. |
| **sigma -> 0** | Illiquid stock, no trades, zero variance, infinite magnitude. | Floor `sigma`. |
| **Outlier inflating sigma** | One bad tick raises `sigma` for two full days and silently suppresses genuine signals. | Winsorise returns before they reach the estimator. |
| **Stale price** | If the last trade was three hours ago, the "change" is fiction. | Freshness gates the magnitude. Section 5.4. |
| **Unrated stock** | A newly tracked stock has under two days of history, so no `sigma`. | `sigma IS NULL`; listed below the ranked rows in an *unrated* group, never faked with a default. |
| **Out-of-order ticks** | A late packet rewinds the price and inverts `r`. | Write-if-newer on event time. Section 5.3. |
| **Market closed in the sample** | Two calendar days is ~74% zero returns; `sigma` halves and every band inflates. | The window counts trading buckets only. Section 3.2. |
| **Container timezone** | Containers default to UTC while the market is IST. A naive timestamp shifts by 5h30m *only inside Docker*: buckets land on the wrong trading day and freshness reads *market closed* through an entire demo — while working perfectly outside Docker. | `TZ=Asia/Kolkata` on every service, every datetime timezone-aware, and a bucket-boundary test that runs in the container as well as on the host. |
| **Cache key expiry** | A TTL on quote or `sigma` keys makes the watchlist go *blank* when ingestion stops, instead of ageing. | No TTL on those keys. Staleness is computed from the stored `as_of`, never from key expiry — section 5.4 restated as a cache rule. |
| **Grid finer than the feed** | A 5s grid on a 1-minute feed is 11-in-12 zero returns; `sigma` collapses by `sqrt(12)` and every stock reads *extreme*. | The grid is 1 minute, matching the feed. Designed out, not handled. Section 3.6. |
| **Weekend gap in N** | Wall-clock `N` from Friday 15:30 to Monday 09:15 is ~3,945 buckets against zero of actual trading, so every stock scores as noise and Monday morning goes blank. | `N` counts trading buckets. Ranking is immune either way (3.5); bands are not. |
| **Circuit limits / halts** | A price pinned at the band is a suppressed move, not a small one. | NSE publishes the official per-stock price band free and unauthenticated. We ship that file as a fixture and read the band per symbol. It reports **No Band** for all ten stocks in our universe — every one is F&O-eligible and so has no fixed circuit, only a flexing dynamic range — so we plant one genuinely banded stock in the catalogue to exercise the detector rather than describe it. A halted stock stops printing event timestamps regardless, so it also degrades into staleness, which already gates magnitude. |
| **Accumulator drift** | Running sum and sum-of-squares over millions of updates accumulate floating-point error. | At prototype scale, recompute `sigma` across the full 750-element ring buffer each cycle — microseconds for 10 stocks, so drift cannot occur. Welford plus periodic reconciliation becomes necessary only at 20,000 symbols (Appendix A). |

### 9.1 Why the corporate-action threshold is not a magnitude

An earlier draft flagged `magnitude > 10`. That was wrong in a way worth recording, because
the property test for 3.5 is what found it.

Magnitude scales with `sqrt(N)`. A user who logs in twice within a few minutes has a small
`N`, so their magnitudes inflate — and an ordinary +2.7% move was classified a **corporate
action** at `N = 7`. Worse, it made *banding* depend on `N`, which directly contradicts 3.5's
claim that `N` cannot affect the ranking.

The return does not move with `N`. Keying the threshold to `|r|` restores the invariant and is
better grounded anyway: the thing that identifies a split is the size of the price
discontinuity, not how unusual it looks relative to volatility.

**Known simplifications, recorded rather than hidden.** The overnight and weekend gap is a
real price move that occurred during no trading bucket, and is therefore slightly
under-penalised. `N` is fixed at login, so long sessions under-penalise late moves. Neither
affects ranking.

## 10. Scale

### 10.1 The load-bearing insight

**Ingestion cost is O(symbols), not O(users x symbols).**

The naive design fetches each user's watchlist: 650,000 users x 150 symbols = 97.5M fetches
per cycle. Dead on arrival.

Price data is shared. One fetch of a symbol serves every user watching it. So ingestion is
bounded by the universe — 20,000 — and **the 650,000th user adds exactly zero ingestion
cost.**

```
write path (ingest)   O(20,000)   flat in user count
read  path (serve)    O(users)    horizontally scaled, and cheap per user
```

The number this produces is *flat*: 20,000 symbols on a 1-minute grid is **333 quote updates
per second**, whether the system has ten users or 650,000. Flatness is the property that
matters — that figure does not move when users do.

### 10.2 The two axes are independent

Growing 10 -> 20,000 stocks pushes on ingestion, statistics and the time series.
Growing 0 -> 650,000 users pushes on the Read API and the per-user store.
**Neither pushes on the other.** That is why the design survives.

### 10.3 The read path splits by cacheability

| | `/api/quotes` | `/api/session` |
|---|---|---|
| Content | last-known prices | baselines, `sigma`, `N` |
| Identical across users | **yes** | no |
| Changes | each grid cycle | on login |
| Fetched | polled | **once per session** |
| Served from | edge cache | Read API |

Locally, "edge cache" is a two-second micro-cache in the web tier, which makes the claim
checkable rather than asserted: the response carries a cache-status header, so a judge can watch
one origin request serve many clients.

Because baselines freeze at login and the client keeps them, the personal payload is fetched
**once per session**, not per poll. At ten-minute sessions, 650,000 concurrent users generate
roughly **1,100 personal requests per second** — ordinary — while the polled traffic collapses
onto a single cacheable response.

Section 4 chose the session-scoped baseline as a *product* decision. It turns out to be what
makes the read path cacheable. When the product model and the scaling model agree, that is
usually a sign the model is right.

## 11. Prototype scope

| | Prototype | Target |
|---|---|---|
| Instruments | 10 real large caps + 1 labelled test instrument · **0 tracked at boot**, growing with demand | 20,000 tracked |
| Concurrent users | a handful | 650,000 |
| Grid | 1 minute | 1 minute |
| `sigma` window | 750 buckets | 750 buckets |
| Cadence | 1-minute batches, real grid, both legs | 1 minute |
| Deployment | six containers, one command | see Appendix A |

**The grain is a parameter, set to 1 minute to match the feed** (section 3.6). Polling faster
than the publisher just returns the same event timestamp repeatedly, which write-if-newer
correctly discards — motion without information. Sub-minute ticks would require a paid websocket
feed, and nothing in the design changes if one is ever supplied: the formula is identical and
only the constant moves.

**Provider: BSE's quote endpoint, primary.** No key, no account, no token — it needs two request
headers, which is shaping rather than authentication. Ten symbols fan out in parallel in ~1.7s;
serially it is ~11s, so the adapter must not loop. It carries a genuine event timestamp, which is
what write-if-newer (5.3) needs, plus volume, which makes 3.7's "point it at volume" a
configuration change rather than a claim.

**Yahoo `spark` is the secondary adapter**, same interface, different vendor. Two implementations
from two vendors is a materially better demonstration of the seam than one vendor twice.

**In practice the default is a composite:** the replay fixture speaks for the twelve seeded
instruments (deterministic, warm `sigma`, planted edge cases, no network needed) and the live
adapter quotes anything a user adds from the catalogue. That is what makes the add-a-stock
lifecycle real rather than staged — a symbol nobody was tracking gets a genuine quote within one
cycle of being added. **The two legs run on independent cadences.** An earlier build let a replay
speed multiplier drive the live leg too: a real API polled every two seconds, returning the same
event timestamp thirty times — the failure this very section warns against, and the one that
cost us Yahoo. Live is never polled faster than the feed publishes.

`PROVIDER=live` is the **default**. The running system carries no simulated data: the replay
adapter and its fixture remain as a test harness only, so the edge-case tests can plant a split
or an out-of-order tick on demand. The provider is called only
from the ingestion loop, never from a request handler, so a hung provider cannot hang a page by
construction rather than by timeout tuning. One attempt, 4-second timeout, no in-tick retry: the
next grid tick is the retry, and retrying immediately turns a throttle into a ban. Three
consecutive failures open a circuit breaker and set `provider: degraded`.

In live mode the freshness chip reads **delayed** all session, because the feed genuinely is.
That is section 5.4 working, and we say so in the README rather than loosening the threshold to
get a green light that lies.

**No free source for Indian equities is licence-clean.** Yahoo has had no official API since
2017; NSE and BSE both restrict redistribution. Local prototype use is the ordinary grey area,
redistribution plainly is not. In a design whose entire thesis is handling data honestly, the
right move is to state that in the README rather than imply a permission we do not have — which
is also why live mode is opt-in and off by default.

**The fixture is seeded from NSE's official end-of-day file**, which is free, unauthenticated,
and real market data rather than something we invented.

**Why build live mode at all**, given replay is what ships: Appendix A rests its entire
adapter-swap argument on the Provider Adapter having two implementations. With one, that
sentence describes code that does not exist.

**A newly tracked stock is rankable now, not in two days.** Without intervention a stock
added from the search box would sit *unrated* for two sessions — the product's thesis
invisible for exactly the stock the user just asked about. So on tracking, the system pulls
the stock's **real intraday 1-minute bars for today** (one genuine session, ~375 points),
computes its real `sigma` from them, and back-fills a 750-bucket window by **resampling
those real returns**, anchored to end exactly at the current price so the live stream
continues from it seamlessly.

The constraint that makes this sound rather than a cheat: the fill must carry **the stock's
own volatility**. A fixed "small deviation" would give every new stock the same `sigma` and
collapse the ranking to a percentage sort — the one thing this product exists to avoid.
Resampling preserves the spread; measured against the real bars, the back-filled `sigma`
lands within ~10%.

Back-filled rows are marked `synthetic` in storage, and any `sigma` resting on one is shown
as **provisional** in the UI until 750 genuine buckets have displaced the fill. Shown, never
hidden — it is also the visible countdown to the stock becoming fully organic.

**The fixture seeds the warm-up and replays only the demo day.** 750 buckets at 1 minute is
12.5 hours of market time, so days 1-2 are bulk-loaded at boot and `sigma` is computed there; the
replay clock starts on day 3. The judge sees a fully rated list on first paint, with the only
*unrated* row being one we planted deliberately. The generated dataset is committed alongside
its SHA-256 — the file is the fixture of record, the generator is documentation.

**Cold start is non-negotiable.** `git clone` -> `./run.sh start` -> working app, with **no API
key and no market-data network access**, in under five minutes. Precisely: installing
dependencies needs the network once, like any project; *running* the system needs no external
service at all. Overstating this would be the wrong kind of claim to make in a document about
handling data honestly. The most likely way to lose this challenge is a judge
hitting a rate limit and seeing a stack trace. The replay fixture that makes offline mode work
is the same harness that lets us *demonstrate* stale-data handling rather than claim it.

## 11.1 The architecture ships as a route

The **Architecture** button in the app opens `/arch`: this document's wiring as inline SVG (exact boxes and
arrows), a drill-down into each component with how data moves, and the horizontal-scaling plan on Google Cloud
for 200,000 concurrent users across 20,000 stocks. One generated illustration is used where it passed
inspection; the wiring diagrams are hand-authored because generative images could not spell `nginx` in two
attempts and invented topology — a picture that misstates the system is worse than none.

## 12. Non-goals

Stated so that restraint reads as a decision rather than an omission.

- **Authentication.** Hardcoded users and a `?user=x` bypass. Its only job is demonstrating
  multi-user behaviour. We are not engineering auth and say so.
- Configurable measure arrays or a measure-selection UI (section 3.6).
- Orders, money movement, portfolio or P&L.
- Alerts and notifications — a different product; "what deserves attention now" is answered
  inside the app.
- Native mobile, historical charting, multi-currency, live corporate-action ingestion.
- Real-time tick data.
- Multi-region deployment.

---

## Appendix A — Prototype vs target, and what moves us

An earlier draft of this appendix argued that we had deliberately *not* built the distributed
topology, because a broker, a distributed cache and an analytical store all cost money to idle.
Containers removed that argument: running the real topology locally is free. So we built it, and
this table records what actually runs against what a cloud deployment would use.

Every component below is a real boundary in the code and now also a process boundary. The
right-hand column is a hosting decision, not a redesign — and the Provider Adapter proves the
seam works, because it ships with three implementations across two vendors and a fixture.

| Component | Runs locally as | Cloud target | Status / remaining trigger |
|---|---|---|---|
| Ingestion Engine | its own container, one grid loop | sharded workers scaled on queue depth | one grid cycle stops fitting the interval: `symbols x fetch latency > grid` |
| Subscription Engine | a persistent, replayable stream | managed broker | **already past in-process.** Remaining trigger: throughput beyond a single node |
| Statistics Engine | its own container | independently scaled workers | **already process-isolated.** Remaining trigger: `sigma` lags the grid |
| Time Series Store | a relational table — 3,750 rows/day | columnar / analytical store — 7.5M rows/day | write volume or retention outgrows the instance |
| Caching Engine | shared cache container | managed distributed cache | **the trigger already fired** — see below |
| OLTP Database | one relational instance | relational + per-user store keyed by user | login write amplification (100-200 rows per login) exceeds one instance |
| Read API | its own container | horizontally scaled, `/api/quotes` at the edge | concurrency beyond one instance. The local web tier's micro-cache is that edge cache in miniature |
| `sigma` window state | 10 x 750 floats — negligible | 20,000 x 750 floats — ~120 MB | ring buffers stop fitting in worker memory; shard by symbol |

**The Caching Engine row is still the one to point at, but the story changed.** Its trigger was
"the moment there is a second Read API process", and containerising fired it — so we moved,
rather than documenting a limit we were living with. The remaining trigger is replica count, not
process count. A trigger that fired and was acted on is better evidence than one still pending.

**What we have genuinely not done is deploy this.** That is a hosting exercise, not a design
one, and pretending otherwise would be the one dishonest note in a document about handling data
honestly.

## Appendix B — Assumptions

**Context.** Submission closes **Monday 7 Sep, 11:00 IST**. Code freeze **Sunday 6 Sep, 22:00 IST**, leaving the evening for documentation and Monday morning as buffer. AI tools are
explicitly permitted by the rules; the binding constraint is the **defensibility gate** —
anything that cannot be explained in two minutes from memory does not ship. Feature count is
explicitly not scored.

**Domain.** NSE equities, INR, IST. Market state is first-class: pre-open, open, closed,
holiday. Delayed and imperfect data is a domain fact, not a bug. The instrument catalogue is
seeded and static.

**Platform.** Python backend, Angular frontend, GCP target. Scalability is bought, not built:
managed services, and for anything not shipped, a written trigger.

**Product.** Change is measured against a per-user baseline advancing once per login. Refresh
reuses the session. Baselines are per-user, not per-device. No baseline means *new*; no
`sigma` means *unrated*.

## Appendix C — Open items

1. **Provider selection** — a timeboxed spike, not a discussion. The replay fixture makes the
   outcome non-blocking.
2. **What the row surfaces** beyond magnitude, direction, price and freshness. Additive and
   cosmetic; touches no maths, no data model, no architecture.
