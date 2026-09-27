"""Stage 5 - Metrics.

Project KPI: median weekday-daytime trip speed inside the Manhattan core (mph).
Speed = distance / time is the most direct measure of how fast a cab converts time
into completed trips. It is sensitive to congestion and to the congestion-pricing intervention.
The other metrics say whether the KPI can be trusted (M1), how much volume sits behind it (M2),
what riders experience (M4, M5) and how exposed trips are to the intervention (M6).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import Config

log = logging.getLogger("pipeline.metrics")


@dataclass(frozen=True)
class Metric:
    id: str
    name: str
    unit: str
    definition: str
    sql: str   # returns (value, n_basis) for the month; params: month


def catalogue(cfg: Config) -> list[Metric]:
    m = cfg.metrics
    day = f"is_weekday and pickup_hour >= {m['daytime_start_hour']} and pickup_hour < {m['daytime_end_hour']}"
    days = "(select date_diff('day', strptime(? || '-01', '%Y-%m-%d'), " \
           "strptime(? || '-01', '%Y-%m-%d') + interval 1 month))"
    return [
        Metric("M1", "valid_trip_rate", "share",
               "Rows passing all exclude-rules / all rows in the monthly file",
               "select avg(is_valid::int), count(*) from stg_trips where source_month = ?"),
        Metric("M2", "valid_trips_per_day", "trips/day",
               "Validated trips / calendar days in month",
               f"select count(*) / {days}, count(*) from fct_trip where source_month = ?"),
        Metric("M3", "core_weekday_daytime_median_speed", "mph",
               f"KPI. Median speed of trips with pickup AND dropoff in the Manhattan core "
               f"('{m['core_service_zone']}'), weekdays {m['daytime_start_hour']}:00-{m['daytime_end_hour']}:00",
               f"select median(speed_mph), count(*) from fct_trip where source_month = ? "
               f"and is_core_trip and {day}"),
        Metric("M4", "median_trip_duration", "minutes",
               "Median pickup-to-dropoff time, all validated trips",
               "select median(duration_min), count(*) from fct_trip where source_month = ?"),
        Metric("M4b", "p90_trip_duration", "minutes",
               "90th percentile pickup-to-dropoff time (reliability tail), all validated trips",
               "select quantile_cont(duration_min, 0.9), count(*) from fct_trip where source_month = ?"),
        Metric("M5", "core_to_jfk_median_duration", "minutes",
               f"Median duration, Manhattan core -> JFK (zone {m['jfk_zone_id']}), weekdays "
               f"{m['daytime_start_hour']}:00-{m['daytime_end_hour']}:00",
               f"select median(f.duration_min), count(*) from fct_trip f "
               f"join dim_zone pz on pz.location_id = f.pu_zone_id "
               f"where f.source_month = ? and pz.is_manhattan_core and f.do_zone_id = {m['jfk_zone_id']} "
               f"and {day}"),
        Metric("M6", "cbd_fee_trip_share", "share",
               "Share of validated trips charged the congestion-relief-zone fee (null before 2025: "
               "column did not exist)",
               "select avg(cbd_fee_charged::int), count(cbd_fee_charged) from fct_trip where source_month = ?"),
    ]


def compute_month(con, cfg: Config, month: str, run_id: str, publishable: bool) -> list[tuple]:
    con.execute("""create table if not exists metrics_monthly (
        source_month varchar, metric_id varchar, metric_name varchar, value double, unit varchar,
        n_basis bigint, status varchar, definition varchar, run_id varchar, computed_at timestamp)""")
    status = "published" if publishable else "blocked"
    rows = []
    for mt in catalogue(cfg):
        params = [month] * mt.sql.count("?")
        value, n = con.execute(mt.sql, params).fetchone()
        rows.append((month, mt.id, mt.name, value, mt.unit, n, status, mt.definition, run_id))
    con.execute("begin transaction")
    try:
        con.execute("delete from metrics_monthly where source_month = ?", [month])
        con.executemany("insert into metrics_monthly values (?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)",
                        rows)
        _breakdowns(con, cfg, month)
        _reconciliation(con, month)
        con.execute("commit")
    except Exception:
        con.execute("rollback")
        raise
    log.info("%s: %d metrics computed (status=%s)", month, len(rows), status)
    return rows


def _breakdowns(con, cfg: Config, month: str) -> None:
    """KPI by time band and trip segment: where and when speed is lost (supports deployment decisions)."""
    con.execute("""create table if not exists kpi_breakdown (
        source_month varchar, day_type varchar, time_band varchar, trip_segment varchar,
        trips bigint, median_speed_mph double, median_duration_min double, p90_duration_min double)""")
    con.execute("delete from kpi_breakdown where source_month = ?", [month])
    con.execute("""
        insert into kpi_breakdown
        select source_month, case when is_weekday then 'weekday' else 'weekend' end, time_band,
               trip_segment, count(*), median(speed_mph), median(duration_min),
               quantile_cont(duration_min, 0.9)
        from fct_trip where source_month = ?
        group by all
    """, [month])


def _reconciliation(con, month: str) -> None:
    con.execute("""create table if not exists reconciliation (
        source_month varchar, days int, raw_rows bigint, in_month_rows bigint, valid_rows bigint,
        in_month_trips_per_day double, valid_trips_per_day double, tlc_trips_per_day double,
        trips_diff_pct double, our_mean_minutes double, tlc_avg_minutes_per_trip double,
        minutes_diff_pct double)""")
    con.execute("delete from reconciliation where source_month = ?", [month])
    con.execute("""
        insert into reconciliation
        with d as (
            select date_diff('day', strptime(? || '-01', '%Y-%m-%d'),
                             strptime(? || '-01', '%Y-%m-%d') + interval 1 month) as days
        ), s as (
            select count(*) as raw_rows, count(*) filter (where not r01_pickup_outside_file_month) as in_month,
                   count(*) filter (where is_valid) as valid_n
            from stg_trips where source_month = ?
        ), f as (select avg(duration_min) mean_min from fct_trip where source_month = ?),
        t as (select trips_per_day, avg_minutes_per_trip from ref_industry_indicators
              where license_class = 'Yellow' and month_year = ?)
        select ?, d.days, s.raw_rows, s.in_month, s.valid_n,
               s.in_month / d.days, s.valid_n / d.days, t.trips_per_day,
               (s.in_month / d.days) / t.trips_per_day - 1,
               f.mean_min, t.avg_minutes_per_trip, f.mean_min / t.avg_minutes_per_trip - 1
        from d cross join s cross join f left join t on true
    """, [month, month, month, month, month, month])
