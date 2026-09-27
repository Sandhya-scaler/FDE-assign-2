# Source map

## Business questions → information → source

| # | Business question (fleet operations / TLC policy) | Information required | Source system | Retrieval mode |
|---|---|---|---|---|
| Q1 | How fast do cabs move through the Manhattan core, and when is it slowest? | pickup/dropoff time, metered distance, pickup/dropoff zone | TLC Trip Record Data (TPEP) | File: monthly Parquet over HTTPS |
| Q2 | Did congestion pricing (2025-01-05) change core speed or trip times? | same as Q1, plus `cbd_congestion_fee` per trip; same-month baseline year | TLC Trip Record Data | File: Parquet |
| Q3 | Which zones are "Manhattan core", airports, or unknown? | LocationID → borough, zone, service_zone | TLC Taxi Zone Lookup | File: CSV over HTTPS |
| Q4 | Is the zone reference itself trustworthy? | independent zone list | NYC Open Data – NYC Taxi Zones (`8meu-9t5y`) | API: Socrata SODA JSON |
| Q5 | Do our trip counts and durations agree with the regulator's own numbers? | monthly Yellow trips/day, avg minutes/trip | NYC Open Data – TLC Industry Indicators (`v6kb-cqej`) | API: Socrata SODA JSON |
| – | Model, validate and aggregate all of the above | – | Local DuckDB warehouse | SQL |

## Source details: owner, grain, gaps

| Source | Owner | Grain | Refresh | Completeness evidence | Known gaps |
|---|---|---|---|---|---|
| Yellow trip Parquet `yellow_tripdata_YYYY-MM.parquet` | NYC TLC, from TPEP vendors (Creative Mobile, Curb, Myle, Helix) | one row per metered trip | monthly, ~2 month lag; can be re-published | bytes = Content-Length; loaded rows = Parquet footer `num_rows`; ETag + sha256 in manifest; every day of month present | no driver/vehicle ID; zone-level locations only; vendor-entered fields (passenger count) unreliable; stray timestamps outside the month; null block with `payment_type = 0` |
| `taxi_zone_lookup.csv` | NYC TLC | one row per LocationID (265) | rarely | row count recorded; cross-checked against API | 264/265 are "Unknown"/"Outside NYC", not real zones |
| NYC Taxi Zones API | TLC via NYC Open Data (DoITT) | one row per zone *shape* (not per ID) | rarely | paged rows = server `count(*)` | repeats IDs 56 and 103; missing 57, 104, 105 |
| TLC Industry Indicators API | NYC TLC | one row per month × license class | monthly | paged rows = server `count(*)` | aggregate only; method not documented; latest months may lag trip files |

## Why these sources
- Trip records are the only place the workflow events (pickup, dropoff, payment) exist.
- The zone lookup gives the business meaning (core / airport / borough) that the KPI definition needs.
- The two APIs are **independent checks**, not inputs to the KPI. They are how we know the retrieval is complete and the reference data is right, without trusting a single system.
- Deliberately *not* used: FHV/Uber/Lyft trip files. They would answer a different question (all street traffic) and would roughly 6× the data volume. This is listed under Limitations.

## Raw preservation
All inputs land unmodified under `data/raw/` and are recorded in [`data/raw/manifest.json`](../data/raw/manifest.json) (URL, retrieval time, bytes, ETag, sha256, row counts, completeness evidence). API responses are kept as dated JSON snapshots. Everything downstream can be rebuilt from `data/raw/` with `python -m pipeline run --offline`.
