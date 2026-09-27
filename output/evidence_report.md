# Evidence report - NYC Yellow Taxi operational metrics
_Generated 2026-09-27 15:05 UTC by pipeline run `20260927T150509-cfc40b`. Regenerate with `python -m pipeline run`._

**Project KPI:** median weekday-daytime (07-19h) trip speed for trips that start and end in the Manhattan core (TLC 'Yellow Zone'). **Decision it supports:** where/when fleet hours are lost to slow trips, and whether congestion pricing (started 2025-01-05) changed core speeds.

## 1. Headline metrics

| id | metric | unit | 2024-01 (published) | 2025-01 (published) |
|---|---|---|---|---|
| M1 | valid_trip_rate | share | 95.5% <sub>n=2,964,624</sub> | 92.6% <sub>n=3,475,226</sub> |
| M2 | valid_trips_per_day | trips/day | 91,340 <sub>n=2,831,534</sub> | 103,764 <sub>n=3,216,692</sub> |
| **M3** | core_weekday_daytime_median_speed | mph | 8.0 <sub>n=1,163,962</sub> | 8.0 <sub>n=1,291,965</sub> |
| M4 | median_trip_duration | minutes | 11.7 <sub>n=2,831,534</sub> | 11.7 <sub>n=3,216,692</sub> |
| M4b | p90_trip_duration | minutes | 28.7 <sub>n=2,831,534</sub> | 27.5 <sub>n=3,216,692</sub> |
| M5 | core_to_jfk_median_duration | minutes | 55.8 <sub>n=13,044</sub> | 52.6 <sub>n=11,784</sub> |
| M6 | cbd_fee_trip_share | share | n/a <sub>n=0</sub> | 66.0% <sub>n=3,216,692</sub> |

### KPI year over year (same month, removes seasonality)

| month | baseline | baseline mph | month mph | change |
|---|---|---|---|---|
| 2025-01 | 2024-01 | 8.01 | 7.98 | -0.4% |

### Manhattan-core weekday median speed (mph) by time band

| time band | 2024-01 | 2025-01 |
|---|---|---|
| overnight 00-07 | 12.2 | 12.0 |
| am peak 07-10 | 8.7 | 8.7 |
| midday 10-16 | 7.7 | 7.6 |
| pm peak 16-19 | 8.2 | 8.2 |
| evening 19-24 | 10.1 | 9.9 |

### Trip mix by segment (share of validated trips)

| segment | 2024-01 | 2025-01 |
|---|---|---|
| airport | 9.6% | 8.3% |
| cross-borough | 4.2% | 4.4% |
| intra-borough (non-core) | 5.9% | 7.1% |
| manhattan core | 80.3% | 80.2% |

## 2. Can these numbers be trusted?

### Reconciliation with TLC's published indicators (API)

| month | raw rows | in-month rows | valid rows | our trips/day | TLC trips/day | diff | our mean min | TLC avg min | diff |
|---|---|---|---|---|---|---|---|---|---|
| 2024-01 | 2,964,624 | 2,964,606 | 2,831,534 | 95,632 | 94,742 | +0.9% | 14.9 | 14.6 | +2.2% |
| 2025-01 | 3,475,226 | 3,475,204 | 3,216,692 | 112,103 | 110,654 | +1.3% | 14.6 | 14.2 | +3.1% |

### Quality gates

| month | gate | name | severity | status | evidence |
|---|---|---|---|---|---|
| 2024-01 | G1 | valid_rate | fail | pass | 2,831,534 of 2,964,624 rows pass all exclude-rules |
| 2024-01 | G2 | daily_coverage | fail | pass | 31/31 days have trips; quietest day = 69% of median day |
| 2024-01 | G3 | trips_reconcile_tlc | warn | pass | in-month records/day 95,632 vs TLC 94,742 (+0.9%) |
| 2024-01 | G4 | duration_reconcile_tlc | warn | pass | valid-trip mean 14.9 min vs TLC 14.6 (+2.2%) |
| 2025-01 | G1 | valid_rate | fail | pass | 3,216,692 of 3,475,226 rows pass all exclude-rules |
| 2025-01 | G2 | daily_coverage | fail | pass | 31/31 days have trips; quietest day = 69% of median day |
| 2025-01 | G3 | trips_reconcile_tlc | warn | pass | in-month records/day 112,103 vs TLC 110,654 (+1.3%) |
| 2025-01 | G4 | duration_reconcile_tlc | warn | pass | valid-trip mean 14.6 min vs TLC 14.2 (+3.1%) |

### Validation rules - rows excluded per rule (waterfall) and rows flagged

| rule | name | severity | 2024-01 | 2025-01 |
|---|---|---|---|---|
| R01 | pickup_outside_file_month | exclude | 0.00% flagged / 18 excluded | 0.00% flagged / 22 excluded |
| R02 | non_positive_duration | exclude | 0.03% flagged / 870 excluded | 0.06% flagged / 2,051 excluded |
| R03 | implausible_duration | exclude | 1.22% flagged / 36,234 excluded | 1.13% flagged / 39,437 excluded |
| R04 | zero_distance | exclude | 2.04% flagged / 36,215 excluded | 2.62% flagged / 64,352 excluded |
| R05 | implausible_distance | exclude | 0.00% flagged / 54 excluded | 0.00% flagged / 155 excluded |
| R06 | implausible_speed | exclude | 0.04% flagged / 139 excluded | 0.03% flagged / 251 excluded |
| R07 | unknown_location | exclude | 1.06% flagged / 27,882 excluded | 0.82% flagged / 25,839 excluded |
| R08 | location_not_in_lookup | exclude | 0.00% flagged / 0 excluded | 0.00% flagged / 0 excluded |
| R09 | negative_amount | exclude | 1.27% flagged / 31,678 excluded | 4.16% flagged / 126,427 excluded |
| R10 | duplicate_record | exclude | 0.00% flagged / 0 excluded | 0.00% flagged / 0 excluded |
| W01 | missing_trip_attributes | warn | 4.73% flagged (kept) | 15.54% flagged (kept) |
| W02 | unknown_ratecode | warn | 0.97% flagged (kept) | 1.21% flagged (kept) |
| W03 | zero_passengers | warn | 1.06% flagged (kept) | 0.71% flagged (kept) |
| W04 | total_not_equal_components | warn | 25.70% flagged (kept) | 31.99% flagged (kept) |
| W05 | unknown_vendor | warn | 0.00% flagged (kept) | 0.00% flagged (kept) |

### Zone reference cross-check (lookup CSV vs Taxi Zones API)

| result | zones |
|---|---|
| match | 260 |
| missing from API (API reuses id 56/103) | 3 |
| n/a (unknown zone) | 2 |

## 3. Known / Unknown / Assumptions / Limitations

**Known**
- Monthly files are complete as published: every row in the Parquet footer is loaded (checked on every run), and every calendar day has trips (gate G2).
- Record volume matches TLC's own published Yellow trips/day to within a few percent (gate G3). Our trip counts line up with the regulator's.
- Stray timestamps (e.g. 2002, 2009 pickups), zero/negative durations, zero distances, odometer glitches and negative (void/refund) amounts are present each month. They are excluded by named rules and counted, not dropped silently.
- The zone lookup CSV and the Taxi Zones API agree on borough and name for all 260 zones they share. The API repeats IDs 56 (Corona) and 103 (Governor's/Ellis/Liberty Island) for several shapes and has no rows for 57, 104 and 105. The lookup CSV is therefore the source of truth for zone IDs, and the API is used only as a cross-check.

**Unknown**
- Why a block of rows has `payment_type = 0` with null passenger count and rate code. The 2025 data dictionary calls it "Flex Fare". The volume grew about 4× from Jan 2024 to Jan 2025. We cannot tell whether these are one trip type or a vendor reporting gap.
- The exact method behind TLC's `avg_minutes_per_trip` and `trips_per_day` (filters, outlier handling). The reconciliation gates therefore only warn.
- Whether VendorID 1 puts surcharges inside `extra`. The pattern fits that explanation but is not confirmed by the vendor.

**Assumptions**
- "Manhattan core" = TLC `service_zone = 'Yellow Zone'`. This is close to, but not the same as, the Congestion Relief Zone (south of 60th St).
- A trip under 1 minute, over 3 hours, over 100 miles or faster than 65 mph end-to-end is not a real passenger trip. All thresholds are in `config/pipeline.toml`.
- `trip_distance` is the metered distance and is right for speed. Straight-line zone distance is not used.
- Pickup time decides which month, day and time band a trip belongs to.

**Limitations**
- Yellow taxis only. Uber/Lyft (FHVHV) trips share the same streets but are not in this data, so core speed shows street conditions only as seen by yellow cabs.
- Jan 2024 vs Jan 2025 is a before/after comparison, not a controlled experiment. Weather, events, fare changes and the growth in Flex Fare trips also differ between the years.
- Zone-level locations (263 zones) only. There is no GPS, so within-zone trips have no route detail.
- TLC can re-publish a month (the ETag changes). The pipeline detects this and re-downloads, so metrics from an earlier run can change. `run_id` on every metric row gives traceability.

