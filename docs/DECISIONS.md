# Decisions

Every choice that had a real alternative, what we rejected, and why. The brief said
it would look at *how you got there*, so this is that record.

---

### 1. "Meaningful" means unusual, not large

**Chosen:** `magnitude = |r| / (σ × √N)` — the move in units of that stock's own volatility.

**Rejected:** percentage change. It surfaces the same volatile small-caps every day,
because it cannot distinguish a 2.7% move in a stock that never moves 2.7% from the
same move in one that does it twice a week.

**Cost:** we need σ per stock, which needs a time series, a warm-up window, and an
async engine. Percentage change needs none of that. We think the whole product is on
this side of the trade.

---

### 2. The comparison point is your previous login

**Chosen:** a symbol's baseline is what it was worth when your *previous session*
started. It advances automatically, exactly once, at login.

**Rejected:** an explicit "mark as read" action. It needs an endpoint, a button, and a
new concept for the user — and users don't click it, so highlights go stale.

**Rejected:** fixed windows ("since yesterday's close"). Cacheable and shared, so
genuinely cheaper — but it answers a different question from the one the brief asked.

**Consequence we accepted:** advancing is destructive. Log in, crash before the screen
paints, and that comparison is gone. Our position: *you logged in, so you checked.*

---

### 3. Refresh must not advance anything

The session token lives in `localStorage`. In memory, F5 would mint a new session,
advance every baseline, and wipe every highlight — the exact failure the session model
exists to prevent, made permanent by decision 2. `sessionStorage` dies with the tab,
which contradicts baselines being per-user rather than per-device.

---

### 4. Baselines are per-user, not per-device

If you saw a move on your phone at 10:00, your laptop should not re-flag it at 11:00.
Per-device baselines are more literally accurate per device, and replay changes you
have already seen.

---

### 5. The client computes the magnitude

**Chosen:** the server returns baselines, σ, and one `N`. The browser ranks.

**Why:** it means the server does *no per-user arithmetic at all*. 650,000 users each
do their own 200-row calculation on their own hardware — per-user compute cost doesn't
just stay small, every new user brings the CPU that serves them. It also makes the
shared/personal split structural: `/api/quotes` carries no per-user data, so it caches
once and serves everyone.

**Cost:** the formula exists in two languages. Both are pinned to the same golden value
by tests in each, which is the only thing stopping them drifting.

---

### 6. The grid is 1 minute, because that is what feeds publish

**Rejected:** 5 seconds. On a 1-minute feed, 11 of every 12 buckets carry a zero
return; σ collapses by √12, every magnitude inflates 3.5×, and **every stock reads
*extreme*** — while the product still looks like it is working.

Matching the grid to the feed removes that failure rather than guarding against it.

---

### 7. σ over a fixed 750-bucket window, identical for every stock

**Rejected:** EWMA. It needs a decay factor we would have to justify, and its long
tail means you can never say when an old shock stops mattering. "Two trading days of
1-minute returns" is one sentence with nothing to defend.

**Rejected:** two *calendar* days. 74% of those buckets are the market being shut, with
every return exactly zero, which biases σ down by roughly half.

**Cost:** two days is regime-sensitive. After a big move σ stays elevated and genuinely
suppresses that stock's signals — then drops out cleanly when the window rolls past.
Predictable, which EWMA is not.

---

### 8. σ is winsorised against a robust scale

One fat-fingered print would otherwise raise σ for two full days and silently suppress
real signals. Clipping is done against the median absolute deviation rather than
against σ itself, which would be circular — the outlier is already inside the estimate
you would be clipping with.

---

### 9. Corporate actions are detected on the return, not the magnitude

An earlier draft flagged `magnitude > 10`. **The property test for N-invariance caught
it:** magnitude scales with √N, so a user logging in twice within a few minutes got a
small N, and an ordinary +2.7% move was classified a corporate action. It also made
banding depend on N, contradicting the claim that N cannot affect ranking.

`|r| ≥ 40%` is N-invariant and better grounded: what identifies a split is the size of
the discontinuity, not how unusual it looks relative to volatility.

---

### 10. Circuit limits are read from the official file

**Rejected:** writing the edge case off as "no data source exists" — which is what we
believed until we looked. NSE publishes the per-stock price band free and
unauthenticated.

It reports **No Band** for all ten large caps, because every one is F&O-eligible and
has no fixed circuit. So we plant one genuinely banded stock to exercise the detector.
*"We read the official file, and here is what it says"* is a much better sentence than
*"no source exists"*.

---

### 11. The bus is a replayable stream, not pub/sub

Pub/sub is fire-and-forget. Stop the statistics engine, restart it, and every message
published in between is gone — σ silently develops a hole, during the exact demo we
most want to run. The engine also rebuilds every window from the time series on boot,
so the durable record is the time series and not the backlog.

---

### 12. The cache is an accelerator, never the source of truth

Putting σ and quotes *only* in the cache would place it inside the read path and create
exactly the single point of failure we claim not to have. The API falls back to
Postgres. That turns stopping the cache from an outage into a demonstration.

---

### 13. Authentication is deliberately not engineered

Hardcoded users, a `?user=` bypass, no hashing. Its only job is showing that two people
see different things from one shared price stream. Half-built auth would be worse than
none, and saying so is better than implying otherwise.

---

### 14. Tracking is demand-driven, and the catalogue is the whole market

**Chosen:** the search box offers the real NSE universe — 2,442 equities from official
sources. Only what someone has put on a watchlist is actually fetched. Adding a stock starts
collection for it on the next cycle.

**Rejected:** fetching the whole universe. A free per-symbol API cannot serve 2,442 quotes a
minute, and 95% of them nobody is watching. The brief's own words were "as we keep adding
stocks it will start fetching for that stock going forward" — that is demand-driven tracking.

**Rejected:** a hardcoded list of ten. It capped the product at ten and made the "searchable
list" a menu.

**Consequence accepted:** a newly added stock is `NEW` with no price for up to one cycle, then
`UNRATED` until it has two days of history. Both states are honest and both are visible.
Removal by the **last** list holding a stock stops collection — there is no one left to
collect for. One user's removal never blanks another's list. (This reverses an earlier
"keep collecting regardless" rule; the user's instinct — don't fetch what nobody watches —
was the better one. History already gathered is kept, so re-adding does not re-fetch bars.)

### 15. No numpy

σ over 12 × 750 floats is a median and a mean. numpy would be the largest wheel in the
tree, for arithmetic we can write in ten lines — and every dependency is cold-start
time on the judge's machine.

---

### 16. A newly tracked stock is rankable now, not in two days

**Chosen:** on tracking, pull today's real 1-minute bars for the stock, compute its real σ,
and back-fill a full window by resampling those returns, anchored to the live price.
Marked synthetic; shown as *provisional σ* until genuine history replaces it.

**Rejected:** waiting two sessions. The stock a user just added would be *unrated* for
exactly the two days they most want to watch it.

**Rejected:** back-filling with a fixed small deviation. It would give every new stock the
same σ and reduce the ranking to a percentage sort — the failure this whole product argues
against. The fill has to carry the stock's *own* spread, which is why it is built from that
stock's real bars and not from a constant.

### 17. The running system is live and starts empty — the fixture is test-only

**Chosen:** ten real instruments, nothing tracked at boot, every quote a real BSE quote
on a one-minute cadence. The replay fixture survives only as a test harness.

**Reversed:** an earlier design ran twelve seeded stocks from a deterministic fixture so
that σ existed on first paint and edge cases could be shown on demand. That was a real
trade-off *then* — σ needed two days of history nobody could supply on a cold start. The
live warm-up (decision 16) removed the constraint, and once it had, showing a judge
simulated prices next to real symbols served nothing. As the user put it: if every
container is live, why simulate.

**Given up, knowingly:** the planted demonstrations — a split, a stalled feed, late ticks
— no longer happen on screen; they live in the test suite. And on a weekend nothing moves,
because nothing is trading. Both are the truth, and the truth is the better demo.

### 18. Adding a stock is checking it

**Chosen:** a newly added stock's baseline is the first price it receives, so the very
next login shows a delta.

**Rejected:** the strict reading — baseline is only ever set at login. It is internally
consistent and produced a stock that stayed `NEW` through the next visit and showed a
delta only on the one after. Two logins to see what changed since you added something
is a rule serving itself, not the reader.

**Also removed:** the first-visit fallback to the previous close. It was written for
seeded watchlists, where stocks appeared without the user adding them. Kept alongside
"adding is checking", it produced **+0.74% on ITC added on a Saturday** — Friday's session
move against Thursday's close, which the user never watched. Every stock now arrives by
the user's action, so there is always a real "when you checked": the add. The row reads
+0.00% until something changes, and `baseline_source` says `added` or `previous_session`.

### 19. Every backend failure reaches the screen

**Chosen:** last-known values may stay on screen when the API is down — but a red banner
says so, ages keep ticking, a failed click names the stock it failed on, a dead status
endpoint is reported as dead rather than as "cache up", and a symbol the feed never
delivered is labelled *NO QUOTE* rather than *UNRATED*.

**Why it needed deciding:** an earlier build had `catch { /* last known values stay - that
is the point */ }`. The comment was half right. A validation agent stopped the API for 13
seconds while a real browser was in use; two × clicks got 502s and nothing on the page
changed. Stale is a feature. Silent is a defect.

**Rejected:** dropping nginx's stale-serving. It is what keeps prices visible through an
outage, which the design wants — the fix is to *read* the `X-Cache-Status` header the web
tier already sends, not to stop sending it.

### 20. One deliberately fake instrument, after removing all the others

**Chosen:** `ARSHIA (test instrument)` in the catalogue, quoted from a table set by hand,
venue chip **TEST**, endpoints under `/api/test/*` that refuse any other symbol.

**Why, having just removed every simulated stock:** the objection to the fixture was that
plausible prices sat next to real symbols with nothing on screen to tell them apart. The
canary is the opposite case — named as a test instrument, labelled on every row, opt-in via
search, and it exists so the *real* pipeline can be exercised on a Sunday. Removing the
fixture made the system honest; the canary makes it testable without making it dishonest.

**Rejected:** a scripted provider in a separate compose project. Correct but heavy, and it
tests a copy of the stack rather than the one that is running.

### 21. Sessions are explicit and sequential

**Chosen:** Sign in opens a session and anchors baselines. Sign out closes it on the
server. A sign-in while one is open is **refused** (409, with the time the open session
started). `?user=` only pre-selects the user. The password is required. A held token
stops working once its session is closed.

**Why:** a second session opened by accident — `?user=ravi` from a tab holding another
user's token — silently re-anchored every baseline to that instant, and the user could not
tell it had happened. An error is louder than a wrong number.

**Out of scope, deliberately:** closing the browser without signing out. The held token
still reaches the Sign out button; the rule only bites from a different browser. What a
session *is* — tab, device, person, timeout — is a separate debate; this takes the
narrowest defensible position and says so.

### 22. The shift register, reinstated — a refresh must not move the anchor

**Chosen:** two prices per watchlist row (`baseline_value`, `session_value`) and two
timestamps per user. Sign-in promotes session → baseline and records now. Nothing else
writes either column. The sign-in response is built from stored state *after* the shift.

**Reversed:** decision 5's claim that a single column suffices "because the client holds
the previous baseline for the session." The user refreshed the page. The client held
nothing; the store held the just-advanced values; every move read 0.00%. A model whose
correctness depends on the browser not being reloaded is not a model.

**Verified:** three sign-ins at 100 → 110 → 120 compare against 100, 100, 110, with reads
between each changing nothing; and on the live system the sign-in response and an
immediate refresh are byte-identical in baselines and previous-visit time.

### 23. Three edge cases are designed out rather than handled

*Accumulator drift* cannot occur because nothing accumulates — σ is recomputed across
the whole window each time, which at 750 floats is microseconds. *Grain mismatch*
cannot occur because the grid matches the feed. *Halts* need no detector because a
halted stock stops printing timestamps and degrades into staleness, which already gates
the magnitude.

An edge case designed out of existence needs no handler, no test, and no explanation.
