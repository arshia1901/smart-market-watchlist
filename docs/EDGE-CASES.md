# Edge cases

How each one fails, how it is handled, and — where possible — the command that makes
it visible. Every case below is planted in the committed replay fixture, so none of
this is theoretical.

---

## The ones that would corrupt the ranking silently

### One bad tick inflating σ
A single fat-fingered print raises σ for two full trading days and quietly suppresses
that stock's genuine signals for the whole window. Nothing looks broken.

**Handled:** returns are winsorised against the median absolute deviation before they
reach the estimator — a *robust* scale, not σ itself, which would be circular because
the outlier is already inside the estimate you would clip with.

**See it:** `BHARTIARTL` carries a +9% print in the fixture.
`test_one_bad_tick_does_not_inflate_sigma` asserts the naive estimator is wrecked
(>5×) and ours moves under 10%.

### A late packet rewinding the price
Feeds retry and deliver out of order. An older price arriving *after* a newer one
inverts `r` under naive last-known-value, and the stock leaps to the top for no reason.

**Handled:** every write is compare-and-set on the quote's own **event time**, applied
atomically. Late arrivals are dropped, not applied.

**See it:** `./run.sh logs ingestion` — `SBIN` emits genuinely out-of-order rows and
you watch `dropped late tick` appear.

### The σ window including a shut market
Two *calendar* days is ~74% zero returns. σ comes out near half its true value, every
magnitude doubles, and **every stock reads *extreme*** — while looking like it works.

**Handled:** the window counts trading buckets only.

### A grid finer than the feed
Same failure through a different door: a 5-second grid on a 1-minute feed is 11-in-12
zero returns, σ collapses by √12.

**Designed out:** the grid *is* 1 minute. The failure has nowhere to occur.

### A corporate action topping the list forever
A 1:10 split is −90%, a magnitude near 50, and looks like the story of the century.

**Handled:** `|r| ≥ 40%` is flagged and excluded from ranking. Keyed off the **return**,
not the magnitude — magnitude scales with √N, so a magnitude threshold made an ordinary
+2.7% move read as a corporate action whenever someone logged in twice in a few
minutes. The N-invariance property test found that.

**See it:** `LT` splits at midday in the fixture.

---

## The ones that would divide by zero or render NaN

### σ → 0 on an untraded stock
Zero variance, infinite magnitude, `Infinity` on screen while you explain that ranking
is the entire product.

**Handled:** σ is floored. **See it:** `ITC` is flat all demo day.

### No baseline, no σ, or no quote yet
Three different absences, none of which may be faked with a default.

**Handled:** each returns `None`/`null` and is classified rather than scored — `NEW`
when you added it since your last session, `UNRATED` when the stock itself lacks two
days of history. Both are `NULL`s in storage; the ranking layer is the honest exception
that must branch before dividing.

**See it (test fixture):** `NEWLIST` is tracked only from the demo day and renders `UNRATED`.
In the running system a freshly added stock is *provisional σ* instead, because its
window is warmed from real intraday bars — `UNRATED` now only appears when that warm-up
found no price at all. Add any
stock through search and it renders `NEW`.

---

## The ones about time

### Wall-clock N over a weekend
Friday 15:30 to Monday 09:15 is ~3,945 wall-clock buckets against **zero** of actual
trading. The expected move becomes enormous, every stock scores as noise, and Monday
morning — the view that matters most — goes blank.

**Handled:** N counts trading buckets. Note the ranking is immune either way, because
√N is a common factor; it is the *band labels* that would be wrong.

### Container timezone
Containers default to UTC; the market is IST. A naive timestamp shifts 5h30m **only
inside Docker** — buckets land on the wrong trading day and freshness reads *market
closed* through an entire demo, while working perfectly outside Docker. The worst
possible failure shape.

**Handled:** `TZ=Asia/Kolkata` on every service, every datetime timezone-aware, and
`test_container_timezone_trap` asserts the same instant classifies identically in UTC
and IST.

### A stale price presented as current
If the last trade was three hours ago, the "change" is fiction.

**Handled:** every row carries its as-of and a freshness state — **live / delayed /
stale / market closed** — classified against the market calendar rather than wall
clock, so a five-hour-old price on a Saturday reads *market closed*, not *broken*.

**Two implementation rules this depends on**, either of which would invert the meaning:
freshness is a **ticking client-side clock** (otherwise stopping ingestion freezes
every label on *live* forever), and there is **no TTL on cache keys** (otherwise the
watchlist goes *blank* rather than ageing).

**See it:** `ICICIBANK` stops printing at midday. `docker compose stop ingestion` does
it to everything at once.

---

## The API itself is unreachable

The design lets last-known values stay on screen when the backend is down — that is the
point of last-known-value. What it must never do is let that be **invisible**. A
validation run against the live system caught exactly that: during a 13-second `api`
outage a real browser clicked × on two stocks, both requests got 502, and the page said
nothing. One stock silently stayed on the list.

**Handled, layer by layer:**

| Layer | What happens | What the user sees |
|---|---|---|
| nginx | keeps serving its last good `/api/quotes` (`X-Cache-Status: STALE`/`UPDATING`) — by design | — |
| client feed | reads that header, and judges it **over time**: one STALE response is nginx refreshing its 2-second cache (measured: 2 of every 15 polls on a healthy API answering in 3ms). Twelve seconds without a *fresh* answer — six consecutive polls — is an outage. | red **Feed problem** banner after 12s: *"The API has not answered a fresh request for 17s (last fresh answer 23:41 IST). The web tier is serving its last good copy; prices below are not being refreshed."* An earlier build flagged every STALE response and flickered twice a minute. |
| ages | tick against the wall clock, not the frozen feed timestamp | "45s ago" keeps growing instead of freezing |
| `/api/status` | fails → strip does **not** keep repeating a stale "cache up" | *"status endpoint unreachable for Ns — the API is not answering"* |
| add / remove | 5xx → thrown, caught, shown | dismissible notice: *"Could not remove TCS — it is still on your list. server unavailable (502)"* |
| sign-in | 5xx → distinguished from a bad password | *"sign in: server unavailable (502)"*, not *"login failed"* |
| a symbol with no quote | labelled as a feed gap, not a data property | **NO QUOTE**, listed under "Not ranked" — never *UNRATED* or *STALE* |

**See it:** `docker compose stop api`, watch the page for ten seconds, `docker compose
start api`. The banner clears itself when the feed recovers.

**The rule that came out of it:** a `catch {}` that swallows a backend failure is a defect,
whatever the comment inside it says. Stale is allowed. Silent is not.

## The one we could not implement, and then could

### Circuit limits and halts
A price pinned at its band is a *suppressed* move, not a small one. We wrote this off
as unimplementable — no data source. That was wrong: **NSE publishes the per-stock
price band free and unauthenticated.**

It reports **No Band** for all ten large caps, because every one is F&O-eligible and
has no fixed circuit — only a flexing dynamic range. So one genuinely banded stock is
planted to exercise the detector rather than describe it.

**See it (test fixture):** `SMALLCAP` pins at its +20% upper band from midday and reads `AT CIRCUIT`,
listed rather than ranked.

A halted stock also stops printing timestamps and degrades into staleness, which
already gates the magnitude — so that half needs no separate detector.

---

## Deliberately not handled, and why

**Accumulator drift.** Designed out: nothing accumulates. σ is recomputed across the
whole window each time, which at 750 floats is microseconds. Welford plus periodic
reconciliation only becomes necessary at 20,000 symbols.

**The overnight gap being under-penalised.** A price move across a session boundary
occurred during no trading bucket. Real, small, and the alternative breaks Monday
morning entirely.

**N fixed at login.** A long session under-penalises late moves — after three hours the
yardstick still assumes the gap you arrived with. The honest cost of "between two
logins".

**Sub-minute ticks.** They need a paid feed. Nothing in the design changes if one is
supplied: same formula, different constant.

---

## What is deliberately not tested

Asked *"why didn't you test X"*, these are the answers:

| Not tested | Why |
|---|---|
| Angular components and templates | The logic behind the rendering is unit tested as pure functions. A component test here asserts that a `<div>` exists. |
| Browser E2E | One route, one developer. The cost is an hour of setup plus ongoing flake, to catch what the fixture tests and one look at the screen catch in seconds. |
| Watchlist add/remove | One insert, one delete, against a schema-constrained table. A test here asserts that the database works. |
| The live provider | Network I/O behind an interface whose contract the replay implementation already exercises. Testing it means mocking the network and asserting your own mock — and the offline path is the one that has to be right. |
| The subscription mechanism | We test the seam (a quote in produces one σ update out), not the message broker. |
| Scale claims | They are claims about the shape of the code, not about behaviour. What *is* asserted is the structural property they rest on: `/api/quotes` carries no per-user data. |
| Coverage percentage | We don't have one and didn't want one. This table is the answer instead. |
