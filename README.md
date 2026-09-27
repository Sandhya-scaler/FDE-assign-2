# NYC Yellow Taxi – trustworthy monthly operations metrics (Track B)

A small, repeatable pipeline that takes NYC TLC yellow-taxi trip records from raw monthly files to a validated trip workflow model and 5 operational metrics. It reconciles the results against the TLC's own published numbers.

**→ Final output: [output/evidence_report.md](output/evidence_report.md)**

## Problem
A yellow-cab fleet operations lead, and the TLC policy team, want to know **where and when cabs lose time in the Manhattan core**. They also want to know **whether the Congestion Relief Zone toll (started 5 Jan 2025) made trips faster**. The trip data can answer this, but it is messy. Out-of-month timestamps, zero-distance and negative-duration trips, voided fares, unknown zones, a growing block of rows with missing attributes, and vendor-specific fare encoding all distort a naive average.

## Users / stakeholders
| Who | Uses the output to |
|---|---|
| Fleet operations manager | Plan shifts and vehicle hours around the slowest time bands and segments |
| TLC policy analyst | Check the before/after effect of congestion pricing on yellow-cab trip times |
| Data owner (TLC / TPEP vendors) | Get a list of specific data-quality issues to fix at the source |

## Project KPI
**Median weekday-daytime (07:00–19:00) trip speed, in mph, for trips that start and end in the Manhattan core** (TLC `service_zone = 'Yellow Zone'`).
Speed = metered distance ÷ trip time. It is the most direct measure of how fast a cab turns time into completed trips.

| id | Metric | Why it is here |
|---|---|---|
| M1 | Valid trip rate | Can the KPI be trusted this month? |
| M2 | Valid trips per day | Volume behind the KPI; reconciled with TLC |
| **M3** | **Core weekday-daytime median speed (KPI)** | The operational outcome |
| M4 / M4b | Median and p90 trip duration | Rider experience and reliability tail |
| M5 | Manhattan core → JFK median duration | Reliability of the highest-value trip type |
| M6 | Share of trips charged the CBD congestion fee | Exposure to the intervention |

**Result (Jan 2024 vs Jan 2025):** core daytime speed is essentially unchanged (8.0 → 8.0 mph, −0.4%). The long trips improved: p90 duration fell 28.7 → 27.5 min and core→JFK fell 55.8 → 52.6 min. Midday (10–16h) is the slowest band in both years (~7.6 mph). **Decision supported:** do not expect congestion pricing to add yellow-cab trips per hour in the core. Where it helps is long and airport trips, so shift planning should target midday core capacity.

## Sources (details: [docs/source_map.md](docs/source_map.md))
| Source | Mode | Role |
|---|---|---|
| TLC yellow trip records, monthly Parquet (Jan 2024, Jan 2025) | **File** over HTTPS | Workflow events, KPI input |
| TLC taxi zone lookup | **File** (CSV) | Business meaning of zones |
| NYC Open Data – Taxi Zones (`8meu-9t5y`) | **API** (Socrata JSON) | Independent cross-check of zone reference |
| NYC Open Data – TLC Industry Indicators (`v6kb-cqej`) | **API** (Socrata JSON) | Reconcile our trips/day and minutes/trip with TLC's published figures |
| DuckDB warehouse | **SQL** | Validation, modelling, metrics |

Two trip months are used on purpose: January of each year removes seasonality from the before/after comparison.

## How we know retrieval is complete
- Downloaded bytes = HTTP `Content-Length`. The download goes to a `.part` file and is renamed atomically.
- Rows loaded into the warehouse = row count declared in the Parquet footer (fails the load otherwise, and the previous data is kept).
- API pages fetched = server-side `count(*)`.
- Every calendar day of the month has trips (gate G2).
- Our in-month trips/day are within **+0.9% / +1.3%** of TLC's published Yellow trips/day. Mean minutes/trip are within 2–3%.
- Everything is recorded in [data/raw/manifest.json](data/raw/manifest.json): URL, time, bytes, ETag, sha256, rows. Raw files are never modified.

## Validation (rules in [pipeline/validate.py](pipeline/validate.py), thresholds in [config/pipeline.toml](config/pipeline.toml))
Profiling ([docs/profiling_report.md](docs/profiling_report.md)) drove 10 **exclude** rules: out-of-month pickup, non-positive / implausible duration, zero / implausible distance, impossible speed, unknown zone, zone not in lookup, negative amount, duplicate. It also drove 5 **warn** rules. Every raw row stays in `stg_trips` with one flag per rule and the first exclusion reason, so nothing is fixed silently. Months pass through **quality gates**. `fail` gates (valid rate ≥ 85%, daily coverage) block publishing. `warn` gates reconcile with TLC.

### The FDE judgement call (demo)
About 15.5% of Jan 2025 rows (4.7% in Jan 2024) have **null passenger count and rate code** (`payment_type = 0`). A generic "drop incomplete rows" step would remove them. We **kept** them as warn-only (W01) because:
1. their time, distance and zones are populated and plausible (median 1.8 mi, 13.7 min in the core);
2. TLC counts them. Dropping them would cut Jan 2025 volume by about 13% and break reconciliation with TLC's published trips/day (+1.3% → −14.4%);
3. the KPI barely moves either way (7.94 vs 7.98 mph), so keeping them costs nothing in accuracy and avoids under-reporting demand.

The same reasoning applies to the ~26–32% of rows whose total ≠ sum of components. These are concentrated in VendorID 1, a vendor encoding difference. We avoid fare-component metrics instead of deleting a third of the trips.

## Pipeline
```
ingest (files + APIs, manifest)  →  load (raw, lineage)  →  validate (rule flags)  →  gates G1–G2
   →  model (dim_zone, fct_trip, fct_trip_event)  →  metrics  →  reconcile gates G3–G4  →  report
```
- **Reruns are idempotent.** Each month is replaced in a transaction. Unchanged raw files (same ETag + sha256) are not downloaded again. If TLC re-publishes a month, the change is detected and the file is re-downloaded.
- **Failure handling.** HTTP calls retry with backoff. A month not yet published → `source_unavailable`, and the other months continue. An exception in a month → rollback and `failed`, and the other months continue. A lock file prevents concurrent runs. Missing required columns (schema drift) fail fast. New columns are logged.
- **Logging / audit.** Logs go to the console and `logs/run_<id>.log`. `pipeline_runs` and `pipeline_stage_log` tables record each stage's status, rows and seconds. Every metric row carries its `run_id` and a `published`/`blocked` status.
- **Exit code** is 0 only if every month was published. This makes it safe to schedule (e.g. monthly cron).

Model diagrams: [docs/data_model.md](docs/data_model.md).

## Setup and run
Requires Python 3.11+.
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python -m pipeline run                          # default months from config (2024-01, 2025-01); ~110 MB download
python -m pipeline run --months 2025-03         # any other month
python -m pipeline run --offline                # rebuild everything from preserved raw files, no network
python -m pipeline profile                      # regenerate docs/profiling_report.md
python -m pipeline status                       # recent runs and published months
pytest -q                                       # rule, idempotency, gate and rollback tests
```

## Repository layout
```
config/pipeline.toml      every threshold and judgement parameter
pipeline/                 ingest, load, validate, gates, model, metrics, report, profile, CLI
seeds/                    code tables from the TLC data dictionary
docs/                     source map, data model, profiling report, known/unknowns
data/raw/manifest.json    retrieval evidence (raw files themselves are git-ignored, re-downloadable)
output/                   evidence_report.md + CSV extracts (metrics, breakdown, reconciliation, rules, gates)
tests/                    synthetic-data tests
```

## Known / Unknown / Assumptions / Limitations
See [docs/known_unknowns.md](docs/known_unknowns.md). The same text is included at the end of the evidence report.
