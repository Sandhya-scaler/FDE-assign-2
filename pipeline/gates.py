"""Quality gates: decide whether a month's metrics are trustworthy enough to publish.

fail gates  -> the month is 'blocked': metrics are computed for diagnosis but not published.
warn gates  -> reported in the evidence report; publishing continues.
Reconciliation against the TLC's own published indicators is 'unverified' (not failed)
when TLC has not yet published that month.
"""
from __future__ import annotations

import logging

from .config import Config

log = logging.getLogger("pipeline.gates")

DDL = """create table if not exists gate_results (
    source_month varchar, gate_id varchar, gate_name varchar, severity varchar,
    status varchar, observed double, threshold double, message varchar)"""


def _record(con, month, gid, name, severity, ok, observed, threshold, message):
    status = "unverified" if ok is None else ("pass" if ok else "fail")
    con.execute("insert into gate_results values (?, ?, ?, ?, ?, ?, ?, ?)",
                [month, gid, name, severity, status, observed, threshold, message])
    level = logging.INFO if status == "pass" else logging.WARNING
    log.log(level, "%s gate %s %s: %s (%s)", month, gid, name, status, message)
    return status


def run_blocking_gates(con, cfg: Config, month: str) -> bool:
    """Gates on the validated staging data. Returns True if the month may be published."""
    g = cfg.gates
    con.execute(DDL)
    con.execute("delete from gate_results where source_month = ?", [month])

    total, valid = con.execute("select count(*), count(*) filter (where is_valid) from stg_trips "
                               "where source_month = ?", [month]).fetchone()
    rate = valid / max(total, 1)
    s1 = _record(con, month, "G1", "valid_rate", "fail", rate >= g["min_valid_rate"], rate,
                 g["min_valid_rate"], f"{valid:,} of {total:,} rows pass all exclude-rules")

    days_in_month, days_present, min_day, med_day = con.execute("""
        with days as (
            select unnest(generate_series(strptime(? || '-01', '%Y-%m-%d'),
                          strptime(? || '-01', '%Y-%m-%d') + interval 1 month - interval 1 day,
                          interval 1 day))::date as d
        ), counts as (
            select d, count(s.trip_id) as n
            from days left join stg_trips s
              on s.source_month = ? and s.is_valid and cast(s.tpep_pickup_datetime as date) = d
            group by d
        )
        select count(*), count(*) filter (where n > 0), min(n), median(n) from counts
    """, [month, month, month]).fetchone()
    share = (min_day / med_day) if med_day else 0.0
    s2 = _record(con, month, "G2", "daily_coverage", "fail",
                 share >= g["min_day_share_of_median"], share, g["min_day_share_of_median"],
                 f"{days_present}/{days_in_month} days have trips; quietest day = {share:.0%} of median day")
    return s1 == "pass" and s2 == "pass"


def run_reconciliation_gates(con, cfg: Config, month: str) -> None:
    """Compare our numbers with TLC's independently published monthly indicators (API source)."""
    g = cfg.gates
    ours = con.execute("select * from reconciliation where source_month = ?", [month]).fetchone()
    cols = [d[0] for d in con.description]
    r = dict(zip(cols, ours))
    if r["tlc_trips_per_day"] is None:
        _record(con, month, "G3", "trips_reconcile_tlc", "warn", None, None,
                g["max_reconciliation_diff"], "TLC has not published indicators for this month yet")
        _record(con, month, "G4", "duration_reconcile_tlc", "warn", None, None,
                g["max_duration_reconciliation_diff"], "TLC has not published indicators for this month yet")
        return
    d = r["trips_diff_pct"]
    _record(con, month, "G3", "trips_reconcile_tlc", "warn", abs(d) <= g["max_reconciliation_diff"], d,
            g["max_reconciliation_diff"],
            f"in-month records/day {r['in_month_trips_per_day']:,.0f} vs TLC {r['tlc_trips_per_day']:,.0f} "
            f"({d:+.1%})")
    d2 = r["minutes_diff_pct"]
    _record(con, month, "G4", "duration_reconcile_tlc", "warn",
            abs(d2) <= g["max_duration_reconciliation_diff"], d2, g["max_duration_reconciliation_diff"],
            f"valid-trip mean {r['our_mean_minutes']:.1f} min vs TLC {r['tlc_avg_minutes_per_trip']:.1f} "
            f"({d2:+.1%})")
