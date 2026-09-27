"""Stage 6 - Outputs: CSV extracts + the evidence report (the table leadership reads)."""
from __future__ import annotations

import logging

from .config import Config
from .db import now

log = logging.getLogger("pipeline.report")


def _fmt(value, unit):
    if value is None:
        return "n/a"
    if unit == "share":
        return f"{value:.1%}"
    if unit == "trips/day":
        return f"{value:,.0f}"
    return f"{value:.1f}"


def _md_table(headers, rows) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join("" if c is None else str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def export_csvs(con, cfg: Config) -> None:
    out = cfg.paths.output
    exports = {
        "metrics_monthly.csv": "select * exclude (definition) from metrics_monthly "
                               "where status = 'published' order by source_month, metric_id",
        "kpi_breakdown.csv": "select * from kpi_breakdown order by all",
        "reconciliation.csv": "select * from reconciliation order by source_month",
        "validation_results.csv": "select * exclude (rationale) from validation_results order by source_month, rule_id",
        "gate_results.csv": "select * from gate_results order by source_month, gate_id",
    }
    existing = {r[0] for r in con.execute("select table_name from information_schema.tables").fetchall()}
    for name, sql in exports.items():
        if name.removesuffix(".csv") not in existing:
            log.warning("%s not written: table does not exist (no month reached that stage)", name)
            continue
        con.execute(f"copy ({sql}) to '{out / name}' (header, delimiter ',')")


def write_evidence_report(con, cfg: Config, run_id: str, month_status: dict[str, str]) -> None:
    months = sorted(r[0] for r in con.execute("select distinct source_month from metrics_monthly").fetchall())
    status = dict(con.execute("""
        select source_month, arg_max(status, computed_at) from metrics_monthly group by 1""").fetchall())
    status.update(month_status)
    parts = [
        "# Evidence report - NYC Yellow Taxi operational metrics",
        f"_Generated {now():%Y-%m-%d %H:%M} UTC by pipeline run `{run_id}`. "
        "Regenerate with `python -m pipeline run`._",
        "",
        "**Project KPI:** median weekday-daytime (07-19h) trip speed for trips that start and end in the "
        "Manhattan core (TLC 'Yellow Zone'). **Decision it supports:** where/when fleet hours are lost to "
        "slow trips, and whether congestion pricing (started 2025-01-05) changed core speeds.",
        "",
        "## 1. Headline metrics",
        "",
    ]

    metric_rows = con.execute("""
        select metric_id, metric_name, unit, source_month, value, n_basis
        from metrics_monthly order by metric_id, source_month""").fetchall()
    by_metric: dict = {}
    for mid, name, unit, month, value, n in metric_rows:
        by_metric.setdefault((mid, name, unit), {})[month] = (value, n)
    headers = ["id", "metric", "unit"] + [f"{m} ({status.get(m, '?')})" for m in months]
    rows = []
    for (mid, name, unit), vals in by_metric.items():
        cells = []
        for m in months:
            v = vals.get(m)
            cells.append("-" if v is None else f"{_fmt(v[0], unit)} <sub>n={v[1]:,}</sub>")
        rows.append([f"**{mid}**" if mid == "M3" else mid, name, unit, *cells])
    parts += [_md_table(headers, rows), ""]

    # Year-over-year comparison for the KPI where a baseline month exists.
    kpi = {m: v for (mid, _, _), vals in by_metric.items() if mid == "M3" for m, v in vals.items()}
    yoy = []
    for m in months:
        base = f"{int(m[:4]) - 1}{m[4:]}"
        if base in kpi and kpi[m][0] and kpi[base][0]:
            yoy.append([m, base, f"{kpi[base][0]:.2f}", f"{kpi[m][0]:.2f}", f"{kpi[m][0] / kpi[base][0] - 1:+.1%}"])
    if yoy:
        parts += ["### KPI year over year (same month, removes seasonality)", "",
                  _md_table(["month", "baseline", "baseline mph", "month mph", "change"], yoy), ""]

    bd = con.execute("""
        select time_band, source_month, median_speed_mph, trips from kpi_breakdown
        where day_type = 'weekday' and trip_segment = 'manhattan core' order by 1, 2""").fetchall()
    if bd:
        bands = sorted({r[0] for r in bd})
        cell = {(b, m): (s, n) for b, m, s, n in bd}
        rows = [[b[2:]] + [f"{cell[(b, m)][0]:.1f}" if (b, m) in cell else "-" for m in months] for b in bands]
        parts += ["### Manhattan-core weekday median speed (mph) by time band", "",
                  _md_table(["time band"] + months, rows), ""]

    seg = con.execute("""
        select trip_segment, source_month, sum(trips), sum(trips * median_duration_min) / sum(trips)
        from kpi_breakdown group by 1, 2 order by 1, 2""").fetchall()
    if seg:
        segs = sorted({r[0] for r in seg})
        cell = {(s, m): n for s, m, n, _ in seg}
        tot = {m: sum(n for s, mm, n, _ in seg if mm == m) for m in months}
        rows = [[s] + [f"{cell.get((s, m), 0) / tot[m]:.1%}" if tot.get(m) else "-" for m in months] for s in segs]
        parts += ["### Trip mix by segment (share of validated trips)", "",
                  _md_table(["segment"] + months, rows), ""]

    parts += ["## 2. Can these numbers be trusted?", "", "### Reconciliation with TLC's published indicators (API)", ""]
    rec = con.execute("""select source_month, raw_rows, in_month_rows, valid_rows, in_month_trips_per_day,
        tlc_trips_per_day, trips_diff_pct, our_mean_minutes, tlc_avg_minutes_per_trip, minutes_diff_pct
        from reconciliation order by 1""").fetchall()
    rows = [[m, f"{a:,}", f"{b:,}", f"{c:,}", f"{d:,.0f}", "n/a" if e is None else f"{e:,.0f}",
             "n/a" if f is None else f"{f:+.1%}", f"{g:.1f}", "n/a" if h is None else f"{h:.1f}",
             "n/a" if i is None else f"{i:+.1%}"] for m, a, b, c, d, e, f, g, h, i in rec]
    parts += [_md_table(["month", "raw rows", "in-month rows", "valid rows", "our trips/day",
                         "TLC trips/day", "diff", "our mean min", "TLC avg min", "diff"], rows), ""]

    parts += ["### Quality gates", ""]
    gates = con.execute("select source_month, gate_id, gate_name, severity, status, message "
                        "from gate_results order by 1, 2").fetchall()
    parts += [_md_table(["month", "gate", "name", "severity", "status", "evidence"], gates), ""]

    parts += ["### Validation rules - rows excluded per rule (waterfall) and rows flagged", ""]
    vr = con.execute("""select rule_id, rule_name, severity, source_month, failed_pct, attributed_rows
                        from validation_results order by rule_id, source_month""").fetchall()
    by_rule: dict = {}
    for rid, name, sev, m, pct, attr in vr:
        by_rule.setdefault((rid, name, sev), {})[m] = (pct, attr)
    rows = []
    for (rid, name, sev), vals in by_rule.items():
        cells = []
        for m in months:
            pct, attr = vals.get(m, (None, None))
            if pct is None:
                cells.append("-")
            elif sev == "exclude":
                cells.append(f"{pct:.2%} flagged / {attr:,} excluded")
            else:
                cells.append(f"{pct:.2%} flagged (kept)")
        rows.append([rid, name, sev, *cells])
    parts += [_md_table(["rule", "name", "severity"] + months, rows), ""]

    zc = con.execute("select api_crosscheck, count(*) from dim_zone group by 1 order by 2 desc").fetchall()
    parts += ["### Zone reference cross-check (lookup CSV vs Taxi Zones API)", "",
              _md_table(["result", "zones"], zc), ""]

    kual = (cfg.paths.docs / "known_unknowns.md")
    if kual.exists():
        parts += ["## 3. Known / Unknown / Assumptions / Limitations", "",
                  kual.read_text().split("\n", 1)[1].strip(), ""]

    (cfg.paths.output / "evidence_report.md").write_text("\n".join(parts) + "\n")
    log.info("evidence report written to %s", cfg.paths.output / "evidence_report.md")
