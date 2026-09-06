# Reiseplan

A door-to-door journey comparator for Germany. Trains, coaches and domestic
flights, ranked by what a trip actually costs you in money *and* hours from
your own front door.

Every booking site quotes you the gate-to-gate number. A Dortmund → München
flight is 1h05 in the air and about 5h05 once you count getting to Düsseldorf,
sitting in security, waiting for bags and riding into the city. The ICE is
5h30 and €46 cheaper. This service surfaces that comparison instead of hiding
it, and it is the only reason to build the thing.

## Running it

```bash
make up                       # db-vendo-client + redis + api on :8000
open http://localhost:8000
```

Or without Docker:

```bash
cd backend
pip install -e ".[dev]"
make test                     # 24 tests, no network needed
make dev                      # falls back to v6.db.transport.rest
```

The API is one endpoint:

```
GET /api/plan
    ?origin=Dortmund&destination=München
    &depart=2026-10-14T08:00:00
    &preset=balanced|cheapest|fastest|laptop|low_carbon
    &vot_cents=1600
    &checked_bag=false&deutschlandticket=false&bahncard=0
```

## What is real and what is modelled

Every option carries a `confidence` field, and the UI shows it. No number
gets presented as fact when it is an estimate.

| Feed | Status | Notes |
|---|---|---|
| Rail schedules | **live** | DB via db-vendo-client |
| Rail fares | **live** | DB quotes, incl. BahnCard, when it returns one |
| Airport access and egress | **live** | Same DB API, routed to the airport station |
| Deutschlandticket routing | **live** | Long-distance products filtered out |
| Coach | modelled | FlixBus has no open API — see below |
| Flight schedules and fares | modelled | See below |

**Flights.** Amadeus shut its Self-Service tier on 17 July 2026 and Kiwi's
Tequila closed to new developers, so there is no free real-fare feed left.
Duffel's test mode returns invented prices from a fictional airline, which is
worse than a model for ranking. The fare here is therefore modelled from a
distance curve and an advance-purchase curve, and every flight is tagged
`modelled`. Drop in a `DuffelProvider` behind the same `Provider` protocol
when you have live-mode credentials; nothing else changes.

The German domestic route table in `providers/air.py` is explicit rather than
distance-derived, because domestic aviation has shrunk a lot. Returning "no
flight exists" for Dortmund → Essen is a correct and useful answer.

**Coach.** FlixBus is effectively the entire German intercity coach market and
has no public API. The legitimate paths to live data are their distribution
partner programme or a reseller like Distribusion. Until then it is modelled
from road distance. Do not point the `ENABLE_FLIX` flag at their internal
search endpoint on a real deployment.

## Architecture

```
main.py        HTTP surface, serialisation
  └ planner    fan-out across providers, dedupe, trim
      ├ providers/db_rail   real DB journeys → Itinerary
      ├ providers/air       real access legs + modelled flight
      └ providers/coach     modelled
  └ scoring    PURE. no I/O, no clock. the actual product.
  └ cache      redis or in-process, with single-flight dedup
```

`scoring.py` is deliberately pure so the whole ranking model is testable
without a single mock. If you port this to Go, port that file first and keep
its behaviour identical.

### The ranking model

Generalised cost, which is standard transport economics:

```
  fare
+ time × value-of-time × discomfort(mode)
- workable time × value-of-time × productivity-weight × 0.6
+ carbon × carbon-price
+ hassle-points × €3.50
```

Discomfort is why an hour in an airport queue costs more than an hour in an
ICE seat, and why a sleeper berth is nearly free. The productivity credit is
capped at the time cost so an option can never score below its own fare.
Coach time is explicitly *not* productive — a tray table and patchy wifi for
ten hours is not a working environment, and pretending otherwise let the coach
win every laptop-weighted search during development.

Change the preset and the winner genuinely changes. That is the test in
`test_scoring.py` that matters most.

## Rate limiting, which is the real operational risk

DB's vendo/movas endpoints block aggressively. The shared instance at
`v6.db.transport.rest` allows 100 requests/minute *for the whole internet*,
and one `/api/plan` call can spend four of them (rail, regional, and both
airport access legs). So:

- Run your own `db-vendo-client` container. The compose file does this.
- Caching is a correctness requirement, not an optimisation. `cache.py` does
  single-flight dedup so concurrent identical searches make one upstream call.
- `DB_MAX_CONCURRENCY` bounds in-flight requests per process.
- Providers never raise. A dead provider degrades the result set; it does not
  fail the request.

## Known gaps

- Regional-only routing approximates Deutschlandticket eligibility by
  filtering long-distance products. It does not model the IC exceptions
  (e.g. some Bremen–Norddeich services) that the ticket does cover.
- Airport station IDs are resolved by name through `/locations` and cached.
  A DB rename would silently reroute; pin the EVA numbers before production.
- Delay risk is not priced. DB long-distance punctuality belongs in the
  discomfort term as an expected-delay penalty — that is the next real
  improvement, and the data is in the API already.
- Single traveller only. Group fares change the rail/coach balance a lot.
- Germany only. The catalogue and route table are the only things that are
  country-specific; the scorer is not.

---

# Shipping a UAT round

## 1. Push and set secrets

```bash
git remote add origin git@github.com:<you>/reiseplan.git
git push -u origin main
```

GitHub → Settings → Secrets and variables → Actions:

| Secret | Example | Why |
|---|---|---|
| `FLY_API_TOKEN` | `flyctl auth token` | deploy |
| `UAT_CODES` | `rishabh:r1-plum,anna:r1-oak,ci:round1-ci` | one code per tester |
| `SESSION_SECRET` | `openssl rand -hex 32` | rotating it ends the round |
| `BROWSERSTACK_USERNAME` | | |
| `BROWSERSTACK_ACCESS_KEY` | | |
| `UAT_TEST_CODE` | `round1-ci` | must match the `ci:` entry above |

Repository **variable** `FLY_APP_NAME` = your Fly app name.

## 2. First deploy

```bash
fly launch --no-deploy --name reiseplan-uat --region fra
fly volumes create reiseplan_data --size 1 --region fra
fly secrets set UAT_CODES="..." SESSION_SECRET="$(openssl rand -hex 32)"
fly deploy
```

After that, every push to `main` deploys and runs the browser matrix.

## 3. Hand out codes

Each tester gets the URL and their own code. Codes are per-person so feedback
is attributed — the summary tells you who tested and who went quiet. Revoke
someone by removing their entry from `UAT_CODES` and redeploying; end the
whole round by rotating `SESSION_SECRET`.

## 4. Read the results

```
GET /api/feedback/summary      counts, who is active, last 50 verdicts
GET /api/feedback/export.csv   the whole round
```

Every row stores the query and the ranking the tester was looking at, so you
can replay any complaint exactly.

# Testing

```bash
cd backend && python -m pytest -q      # 63 tests, no network
cd e2e && npx playwright test          # 46 browser tests against localhost
cd e2e && npm run test:bs              # the same 46 on BrowserStack
```

Backend coverage: the scoring engine, the DB parser, the API contract, the
invite gate, feedback capture, and a scenario matrix over eight real German
city pairs (`test_scenarios.py`). Scenario tests assert *properties* of a
route shape rather than frozen numbers — fares and timetables move, but
"Berlin–Hamburg has no flight" and "checking a bag makes flying slower and
dearer" do not.

The browser suite covers the gate, the search matrix, ranking behaviour under
each preset, the breakdown panel, feedback submission, keyboard reachability,
and a 375px viewport. It runs on a local Chromium in CI before it is allowed
to spend BrowserStack minutes.

## Known issue to settle before you send invites

The `fastest` preset is labelled "Getting there soonest" in the UI, but it
ranks by generalised cost at a high value of time — not by clock time. On
München–Hamburg it picks the 6h05 train over the 4h02 flight, because the
flight costs €40 more, carries five hassle points and gives back no working
time. The ranking is defensible; the label is not, and a tester will file it
as a bug on day one. Either rename it to something like "Time matters most",
or make that one preset sort on `door_to_door_minutes` and accept that it
stops being a generalised-cost preset. This is a product call, so it is
flagged rather than fixed.
