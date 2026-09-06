# Assumptions and non-goals

The brief left six things undefined and said it would judge *problem interpretation*.
The only way to get credit for what we deliberately did not build is to write it down.

---

## What we assumed

### The market
- **NSE equities, INR, IST.** Market state is first-class: pre-open, open, closed,
  holiday. "What changed since Friday" is a different question at 11:00 Tuesday than at
  21:00 Saturday.
- **Delayed, imperfect data is a domain fact, not a bug.** No number renders without
  its as-of, its source, and a freshness state.
- **The instrument catalogue is seeded and static.** No live corporate-action feed, no
  listings or delistings.
- **Single currency, no FX.**

### The user
- Tens to a couple of hundred symbols, checked a few times a day, from one or two
  devices.
- "Last checked" means last checked by *you*, anywhere — not per device.
- A login is the cleanest available definition of "checked": no user action, nothing to
  forget, no new concept.

### The data
- **No free source for Indian equities is licence-clean.** Yahoo has had no official API
  since 2017; NSE and BSE both restrict redistribution. Local prototype use is the
  ordinary grey area. Live mode is opt-in and off by default for that reason as much as
  any technical one.
- **Free feeds publish at 1-minute granularity**, which is why the grid is one minute.
- σ is seeded from the fixture at boot because 750 buckets is 12.5 hours of market time
  — a bootstrapping constraint, not a correctness one.

### Scale
- 20,000 instruments and 650,000 concurrent users as the target the *design* answers,
  with ten real instruments in the catalogue and nothing tracked until a user adds it.
- Judges will not load-test. So scale is argued structurally and made checkable —
  `/api/quotes` provably carries no per-user data — rather than benchmarked.

### The exercise itself
- **The binding constraint is defensibility.** AI tools are explicitly permitted; the
  funnel ends with engineers asking *why*. Anything that cannot be explained in two
  minutes from memory is a liability even when it works.
- **Feature count is explicitly not scored**, which is the permission slip for
  everything below.

---

## What we deliberately did not build

### Authentication
Hardcoded users, a `?user=` bypass, no hashing, no real tokens. Its only job is
demonstrating that two people see different things from one shared price stream.
Half-built auth is worse than none, and saying so is better than implying otherwise.

### A configurable measure
`MEASURE = price` is one system parameter. Pointing it at volume is a config change
plus a provider field — but there is no array of measures and no UI to choose between
them. The brief asked for judgement about *what* change matters, not for an analytics
platform.

Volume anomaly is a genuinely good second signal — a stock up 1% on 10× volume often
matters more than one up 3% on nothing — and it is out of scope on purpose.

### Alerts and notifications
A different product. "What deserves attention now" is answered inside the app.

### Orders, money, portfolio, P&L
Not this problem.

### Sub-minute data
Requires a paid websocket feed. Nothing in the design changes if one is supplied.

### A cloud deployment
The full topology runs locally in six containers. What we have not done is *host* it —
a hosting exercise, not a design one, and pretending otherwise would be the single
dishonest note in a project about handling data honestly.

### Historical charting, native mobile, multi-region, multi-currency
Each would be real work that answers a question nobody asked.

---

## Three things designed out rather than handled

An edge case designed out of existence needs no handler, no test, and no explanation.

| | |
|---|---|
| **Accumulator drift** | Nothing accumulates. σ is recomputed across the whole window each time — microseconds at 750 floats. |
| **Grain mismatch** | The grid matches what feeds publish, so a σ-collapsing mismatch has nowhere to occur. |
| **Trading halts** | A halted stock stops printing timestamps and degrades into staleness, which already gates the magnitude. |

We applied this only where the option genuinely existed. Circuit limits looked like a
fourth candidate until we found that NSE publishes the price bands — and there the
honest answer was to build the detector.
