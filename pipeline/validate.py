"""Stage 3 - Validation.

Rules are business rules, not generic null checks: each one answers "can this row be
trusted as a real, completed passenger trip for the metrics we publish?"

Nothing is silently fixed. Every raw row is kept in stg_trips with one boolean flag per
rule, so any exclusion can be traced back to the rule (and threshold) that caused it.
  * severity "exclude": row is not used for metrics
  * severity "warn":    row is used, but the issue is counted and reported
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import Config

log = logging.getLogger("pipeline.validate")


@dataclass(frozen=True)
class Rule:
    id: str
    name: str
    severity: str        # exclude | warn
    fails_when: str      # SQL predicate over staging columns; true = row violates the rule
    rationale: str


def rules(cfg: Config) -> list[Rule]:
    v = cfg.validation
    return [
        Rule("R01", "pickup_outside_file_month", "exclude",
             "tpep_pickup_datetime < month_start or tpep_pickup_datetime >= month_end",
             "Monthly files contain stray timestamps (e.g. 2002, 2009) from bad device clocks; "
             "counting them would leak trips into the wrong month."),
        Rule("R02", "non_positive_duration", "exclude",
             "duration_s is null or duration_s <= 0",
             "Drop-off at or before pick-up is physically impossible."),
        Rule("R03", "implausible_duration", "exclude",
             f"duration_s > 0 and (duration_s < {v['min_duration_s']} or duration_s > {v['max_duration_s']})",
             f"< {v['min_duration_s']}s is a meter test/cancel; > {v['max_duration_s'] // 3600}h is a meter "
             "left running. Both distort duration and speed."),
        Rule("R04", "zero_distance", "exclude",
             "trip_distance is null or trip_distance <= 0",
             "No distance recorded means no journey to measure speed on."),
        Rule("R05", "implausible_distance", "exclude",
             f"trip_distance > {v['max_distance_mi']}",
             "Odometer glitches (values of 100k+ miles occur)."),
        Rule("R06", "implausible_speed", "exclude",
             f"speed_mph > {v['max_speed_mph']}",
             "Distance and duration are individually plausible but inconsistent with each other."),
        Rule("R07", "unknown_location", "exclude",
             "pulocationid in (264, 265) or dolocationid in (264, 265)",
             "264/265 = 'Unknown' / 'Outside of NYC': the trip cannot be placed in the zone workflow."),
        Rule("R08", "location_not_in_lookup", "exclude",
             "pulocationid not in (select location_id from ref_zone_lookup) or "
             "dolocationid not in (select location_id from ref_zone_lookup) or "
             "pulocationid is null or dolocationid is null",
             "Referential integrity against the TLC zone lookup."),
        Rule("R09", "negative_amount", "exclude",
             "fare_amount < 0 or total_amount < 0",
             "Negative amounts are voids/refund adjustments, not trips."),
        Rule("R10", "duplicate_record", "exclude",
             "dup_rank > 1",
             "Exact duplicate on vendor, timestamps, locations, distance and amount."),
        Rule("W01", "missing_trip_attributes", "warn",
             "passenger_count is null or ratecodeid is null",
             "A block of rows (payment_type 0) has no passenger/rate data. Distance, time and "
             "location are populated and plausible, so the trip is real; kept for time/speed metrics."),
        Rule("W02", "unknown_ratecode", "warn", "ratecodeid = 99",
             "Rate code not recorded by the vendor."),
        Rule("W03", "zero_passengers", "warn", "passenger_count = 0",
             "Driver-entered field; 0 is common and not evidence of a non-trip."),
        Rule("W04", "total_not_equal_components", "warn",
             f"abs(total_amount - component_sum) > {v['amount_tolerance']}",
             "Concentrated in VendorID 1, which appears to fold surcharges into 'extra'. This is a "
             "vendor encoding difference, so fare-component metrics are avoided and trips are kept."),
        Rule("W05", "unknown_vendor", "warn",
             "vendorid is null or vendorid not in (select vendor_id from dim_vendor)",
             "Vendor code not in the TLC data dictionary."),
    ]


def _staging_select(cfg: Config) -> str:
    rs = rules(cfg)
    flags = ",\n            ".join(f"coalesce({r.fails_when}, false) as {r.id.lower()}_{r.name}" for r in rs)
    exclude = [r for r in rs if r.severity == "exclude"]
    reason = " ".join(f"when {r.id.lower()}_{r.name} then '{r.id}'" for r in exclude)
    not_excluded = " and ".join(f"not {r.id.lower()}_{r.name}" for r in exclude)
    return f"""
    with base as (
        select t.*,
            strptime(t.source_month || '-01', '%Y-%m-%d') as month_start,
            strptime(t.source_month || '-01', '%Y-%m-%d') + interval 1 month as month_end,
            date_diff('second', tpep_pickup_datetime, tpep_dropoff_datetime) as duration_s,
            fare_amount + extra + mta_tax + tip_amount + tolls_amount + improvement_surcharge
              + coalesce(congestion_surcharge, 0) + coalesce(airport_fee, 0)
              + coalesce(cbd_congestion_fee, 0) as component_sum,
            row_number() over (
                partition by vendorid, tpep_pickup_datetime, tpep_dropoff_datetime,
                             pulocationid, dolocationid, trip_distance, total_amount
                order by source_row) as dup_rank
        from raw_yellow_trips t
        where source_month = ?
    ), derived as (
        select *,
            case when duration_s > 0 then trip_distance / (duration_s / 3600.0) end as speed_mph
        from base
    ), flagged as (
        select *,
            {flags}
        from derived
    )
    select * exclude (month_start, month_end),
        case {reason} end as exclusion_rule,
        ({not_excluded}) as is_valid
    from flagged
    """


def validate_month(con, cfg: Config, month: str) -> dict:
    select = _staging_select(cfg)
    con.execute("begin transaction")
    try:
        exists = con.execute("select count(*) from information_schema.tables "
                             "where table_name = 'stg_trips'").fetchone()[0]
        if not exists:
            con.execute(f"create table stg_trips as {select} limit 0", [month])
        con.execute("delete from stg_trips where source_month = ?", [month])
        con.execute(f"insert into stg_trips {select}", [month])
        _write_results(con, cfg, month)
        con.execute("commit")
    except Exception:
        con.execute("rollback")
        raise
    total, valid = con.execute(
        "select count(*), count(*) filter (where is_valid) from stg_trips where source_month = ?",
        [month]).fetchone()
    log.info("%s: %d/%d rows valid (%.2f%%)", month, valid, total, 100 * valid / max(total, 1))
    return {"total": total, "valid": valid, "valid_rate": valid / max(total, 1)}


def _write_results(con, cfg: Config, month: str) -> None:
    con.execute("""create table if not exists validation_results (
        source_month varchar, rule_id varchar, rule_name varchar, severity varchar,
        failed_rows bigint, attributed_rows bigint, total_rows bigint, failed_pct double,
        rationale varchar)""")
    con.execute("delete from validation_results where source_month = ?", [month])
    for r in rules(cfg):
        col = f"{r.id.lower()}_{r.name}"
        # failed_rows: every row violating the rule. attributed_rows: rows *excluded* because this was
        # the first failing exclude-rule (a waterfall, so exclusions sum to the total dropped).
        con.execute(f"""
            insert into validation_results
            select ?, ?, ?, ?,
                count(*) filter (where {col}),
                count(*) filter (where exclusion_rule = ?),
                count(*),
                count(*) filter (where {col}) / count(*),
                ?
            from stg_trips where source_month = ?
        """, [month, r.id, r.name, r.severity, r.id, r.rationale, month])
