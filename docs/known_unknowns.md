# Known / Unknown / Assumptions / Limitations

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
