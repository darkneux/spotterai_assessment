# Fuel Route Optimization API

A Django + DRF service that, given a US start and end location, returns the
driving route, the **cost-optimal fuel stops** chosen from a fuel-price dataset,
and the **total fuel cost** for a vehicle with a **500-mile range** and **10 mpg**.

It is built to the attached design document (`fuel_route_design_revised.docx`)
and is **runnable with zero configuration** — SQLite, an offline routing
provider, and an offline geocoder are the defaults, so `git clone` → install →
seed → run, no API keys or external services required. Postgres, Redis,
OpenRouteService/OSRM, and the US Census / Nominatim geocoders are all opt-in via
environment variables.

---

## Quick start (zero config, ~1 minute)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python manage.py migrate
python manage.py seed_demo          # 10 geocoded stations along SF -> Denver
python manage.py runserver
```

Then:

```bash
curl -s -X POST localhost:8000/api/route-with-fuel/ \
  -H 'Content-Type: application/json' \
  -d '{"start":"San Francisco, CA","end":"Denver, CO"}'
```

Interactive docs (OpenAPI 3): **http://localhost:8000/api/docs/** (Swagger) and
**/api/redoc/**. Health check: **/api/health/**.

### Loading the real dataset

The assessment CSV (`fuel-prices-for-be-assessment.csv`, ~8,151 rows) is **not**
checked in. Drop it in `data/` and run:

```bash
python manage.py import_stations data/fuel-prices-for-be-assessment.csv --truncate
python manage.py geocode_stations --provider census --sleep 0.2   # offline pipeline
```

`import_stations` matches columns case-insensitively (OPIS Truckstop ID,
Truckstop Name, Address, City, State, Rack ID, Retail Price) and upserts by OPIS
ID. `geocode_stations` converts address/city/state to coordinates out-of-band
(never at request time), records a per-row `geocode_status`, retries transient
failures (tracked via `geocode_attempts`), and falls back to a city/state
centroid (flagged `APPROXIMATE`) before giving up (`FAILED`, excluded from
selection). A `data/sample_fuel_prices.csv` is included to exercise this path
offline (its cities are in the built-in gazetteer).

---

## Example response (SF → Denver, greedy)

```jsonc
{
  "route": {
    "distance_miles": 948.78,
    "duration_minutes": 948.8,
    "polyline": "c|peFf`ejV...",       // Google-encoded
    "provider": "offline",
    "points": [ { "lat": 37.77, "lng": -122.42, "distance_from_start_miles": 0.0 }, ... ]
  },
  "fuel_plan": {
    "vehicle": { "max_range_miles": 500.0, "miles_per_gallon": 10.0 },
    "strategy": "greedy",
    "candidate_count": 10,
    "stops": [
      { "station_id": 5, "name": "High Desert Pumps", "distance_along_route_miles": 389.0,
        "price_per_gallon": 3.49, "gallons_purchased": 50.0, "cost": 174.5, ... },
      ...
    ],
    "total_gallons": 94.88,            // == distance / mpg
    "total_cost": 344.53
  },
  "meta": { "cache_hit": false }
}
```

Notice the greedy behaviour: minimal top-ups at the pricier early stations, a
**full 50-gallon tank at the cheapest station** ($3.49), nothing bought at
stations that are dearer than one already within reach.

---

## API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/route-with-fuel/` | Route + fuel plan using the configured strategy |
| POST | `/api/route-with-fuel/greedy/` | Forces the greedy planner |
| POST | `/api/route-with-fuel/dp/` | Forces the reference planner |
| GET | `/api/health/` | Liveness + station counts |
| GET | `/api/docs/`, `/api/redoc/`, `/api/schema/` | OpenAPI 3 docs/schema |

**Request body** (provide each endpoint with text *or* coordinates; coordinates
win when both are given):

```jsonc
{
  "start": "San Francisco, CA",        // or start_lat / start_lng
  "end":   "Denver, CO",               // or end_lat / end_lng
  "strategy": "greedy",                // optional: "greedy" | "dp"
  "max_range_miles": 500,              // optional override
  "initial_fuel_gallons": 0            // optional: fuel already in the tank
}
```

**Error envelope** (uniform across validation and domain errors):

```jsonc
{ "error": { "code": "geocoding_failed", "message": "...", "request_id": "..." } }
```

| Status | `code` | When |
|--------|--------|------|
| 400 | `validation_error` | Missing/!malformed fields |
| 400 | `geocoding_failed` / `outside_usa` / `invalid_strategy` | Bad location or strategy |
| 422 | `infeasible_trip` / `no_stations` | A leg exceeds range / no stations in corridor |
| 502 | `routing_failed` | Routing provider error |
| 503 | `no_dataset` | No geocoded stations loaded |

---

## Architecture

```
Client ─▶ api (DRF views, serializers, error envelope, request-id middleware)
            │
            ├─▶ routing.RoutingService ─▶ provider (offline | ORS | OSRM)   ← 1 call/request
            │        └─ cache (locmem | Redis), keyed by normalized start/end
            │        └─ geocoding (offline | census | nominatim)
            │
            ├─▶ fuelstations.StationRepository ─▶ DB (SQLite | Postgres)     ← 1 query/request
            │        └─ corridor bbox filter + in-memory route projection
            │
            └─▶ planner (Greedy default, DP reference) via get_fuel_planner()
```

Layers are decoupled: `planner/` is pure Python with **no Django imports**, so the
algorithms are unit-testable in isolation; the orchestration in
`api/services.py` is HTTP-free and reusable.

### Performance design (meets "1 routing call, 1–2 DB queries")

* **One** routing-provider call per request (cached for repeats).
* **One** indexed bounding-box DB query per request; projection and planning run
  in memory on the small corridor subset (typically tens–low hundreds of
  stations).
* Greedy planner is `O(M log M)`-class on `M` candidates; the dominant latency is
  the routing call, not CPU.

### Why no PostGIS (and how to add it)

The design allows "PostGIS **or numeric fields**." To keep the project runnable
on plain SQLite/Postgres with no GIS stack, stations store numeric `latitude`/
`longitude` with B-tree indexes; the repository does a padded **bounding-box**
query, then projects each candidate onto the route polyline in Python
(`planner/geo.py`, nearest-segment in local equirectangular coordinates) and
keeps those within the corridor half-width.

To scale further, swap to GeoDjango: a `PointField` + GiST index, an
`ST_DWithin(route_buffer, point, width)` corridor filter, and
`ST_LineLocatePoint` for projection — a drop-in replacement for
`StationRepository.candidates_for_route` with no change to the planner or API.

---

## Fuel model & optimality (important)

Assumptions (per design §10): the vehicle **starts empty** and pays for every
gallon, fuel is fractional, prices are fixed during a trip, tank capacity =
range = 50 gallons, and the route is fixed. Therefore
`total_gallons == total_distance / mpg` exactly.

**The origin leg.** The miles from the origin to the first candidate station can
only be powered by fuel bought at that first station's price (nothing is
"behind" them). We charge that leg as a fixed pre-cost attributed to the first
station and then solve the classic fixed-route refueling problem over the real
station nodes starting with an empty tank at the first station. This avoids
inventing an artificial "origin price" while keeping the gallons identity exact.

**Greedy planner (default, `planner/greedy.py`).** At the current station, look
ahead within range: if a strictly cheaper station is reachable, buy only enough
to reach it; otherwise fill up at the current (locally cheapest) station —
capped by the fuel still needed to finish, so we never overbuy near the
destination — and advance. This is the classic optimal rule; an exchange
argument shows each mile ends up powered by the cheapest station that can reach
it, which is the minimum possible cost.

**Reference planner (`planner/dp.py`) — and a deliberate correction.** The design
proposes a station-graph DP with the state "min cost to arrive at station *i*
with an empty tank." **That formulation is actually suboptimal for this model**:
when a station lies within range but the next *cheaper* station is beyond range,
the trip is forced to stop at the intermediate station, and an arrive-empty
state cannot carry cheap fuel *through* that forced stop — although the vehicle
physically can. On randomized routes the arrive-empty DP returns a strictly
higher cost than greedy. I therefore implemented the reference as the **true
optimum the design's own exchange argument implies**: sweep the route, split it
where the in-range station set changes, and charge each segment to its cheapest
in-range supplier. It is a completely different computation from the greedy heap,
so their agreement is a meaningful cross-check. The test suite asserts
greedy == reference on 300 randomized routes (`planner/tests/test_planners.py`).

---

## Configuration (env-driven, `.env` optional)

See `.env.example`. Highlights:

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | (SQLite) | `postgres://…` to use Postgres |
| `REDIS_URL` | (locmem) | `redis://…` to cache routes in Redis |
| `ROUTING_PROVIDER` | `offline` | `offline` \| `ors` \| `osrm` |
| `ORS_API_KEY` | — | required for `ors` |
| `GEOCODING_PROVIDER` | `offline` | `offline` \| `census` \| `nominatim` |
| `FUEL_MAX_RANGE_MILES` | `500` | Vehicle range |
| `FUEL_MILES_PER_GALLON` | `10` | Efficiency |
| `ROUTE_CORRIDOR_WIDTH_KM` | `30` | Corridor half-width for candidate selection |
| `FUEL_PLANNER_STRATEGY` | `greedy` | Default strategy |
| `ROUTING_CACHE_TTL_SECONDS` | `86400` | Route cache TTL |

---

## Testing

```bash
python manage.py test
```

24 tests covering: haversine/projection geometry; every design §16 planner
scenario (short trip, exact-range, multi-stop, infeasible, identical prices,
no-backtrack); the greedy-vs-reference equivalence sweep; and API integration
(happy path, text & coordinate input, the single-routing-call + cache guarantee,
strategy parity, and the 400/422/503 error paths).

---

## Observability & security

* **Request IDs**: `RequestIDMiddleware` assigns/propagates an `X-Request-ID`
  echoed in the response header and included in error bodies and logs, so a
  single request can be traced across routing → repository → planner.
* **Structured logs**: each stage logs provider/latency-relevant facts (route
  distance, corridor candidate count `M`, chosen strategy, feasibility, cache
  hit/miss).
* **Security**: all DB access goes through the ORM (no raw SQL); inputs are
  validated and USA-bounded; secrets/credentials come from the environment. The
  service runs unauthenticated in a trusted environment by design (§26); add API
  keys/OAuth2 at the DRF layer + HTTPS-only at the proxy when exposing it
  externally.

## Project layout

```
config/        Django project (settings, urls, wsgi/asgi)
api/           DRF views, serializers, orchestration service, error envelope, middleware
routing/       RoutingService, providers (offline/ors/osrm), geocoding, polyline codec, cache
fuelstations/  FuelStation model, StationRepository, import/geocode/seed_demo commands
planner/       Pure-Python domain objects, geo utils, Greedy + reference planners, factory
data/          sample_fuel_prices.csv (real CSV goes here)
```
