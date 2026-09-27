"""Profiling of the preserved raw files (before any validation), written to docs/profiling_report.md."""
from __future__ import annotations

import logging

import duckdb

from .config import Config
from .db import now

log = logging.getLogger("pipeline.profile")

ISSUE_PROBES = [
    ("pickup outside file month", "tpep_pickup_datetime < ms or tpep_pickup_datetime >= ms + interval 1 month"),
    ("dropoff <= pickup", "tpep_dropoff_datetime <= tpep_pickup_datetime"),
    ("duration > 3h", "date_diff('second', tpep_pickup_datetime, tpep_dropoff_datetime) > 10800"),
    ("trip_distance <= 0", "trip_distance <= 0"),
    ("trip_distance > 100 mi", "trip_distance > 100"),
    ("passenger_count null", "passenger_count is null"),
    ("passenger_count = 0", "passenger_count = 0"),
    ("RatecodeID = 99", "RatecodeID = 99"),
    ("payment_type = 0", "payment_type = 0"),
    ("fare_amount < 0", "fare_amount < 0"),
    ("PU/DO location 264/265 (unknown)", "PULocationID in (264, 265) or DOLocationID in (264, 265)"),
    ("total != sum of components", "abs(total_amount - (fare_amount + extra + mta_tax + tip_amount + "
     "tolls_amount + improvement_surcharge + coalesce(congestion_surcharge, 0) + coalesce(Airport_fee, 0) "
     "+ {cbd})) > 0.01"),
]


def profile(cfg: Config, months: list[str]) -> None:
    con = duckdb.connect()
    lines = ["# Profiling report (raw files, before validation)", "",
             f"_Generated {now():%Y-%m-%d %H:%M} UTC with `python -m pipeline profile`._", ""]
    probe_rows = []
    for month in months:
        path = cfg.paths.raw_trips / f"yellow_tripdata_{month}.parquet"
        if not path.exists():
            log.warning("%s: raw file not present, skipping profile", month)
            continue
        cols = {r[0].lower() for r in con.execute(f"describe select * from '{path}'").fetchall()}
        cbd = "coalesce(cbd_congestion_fee, 0)" if "cbd_congestion_fee" in cols else "0"
        n = con.execute(f"select count(*) from '{path}'").fetchone()[0]
        lines += [f"## {month} - {n:,} rows", "", "| column | type | min | max | null % | approx distinct |",
                  "|---|---|---|---|---|---|"]
        for r in con.execute(f"summarize select * from '{path}'").fetchall():
            name, typ, mn, mx, approx, *_rest = r
            null_pct = r[-1]
            lines.append(f"| {name} | {typ} | {mn} | {mx} | {float(null_pct):.2f} | {approx:,} |")
        lines.append("")
        for label, pred in ISSUE_PROBES:
            pred = pred.format(cbd=cbd)
            k = con.execute(f"select count(*) from (select *, strptime('{month}-01', '%Y-%m-%d') ms "
                            f"from '{path}') where {pred}").fetchone()[0]
            probe_rows.append((label, month, k, k / n))
        vend = con.execute(f"select VendorID, count(*) from '{path}' group by 1 order by 1").fetchall()
        lines += ["Vendor mix: " + ", ".join(f"{v}: {c:,}" for v, c in vend), ""]
        mism = con.execute(f"""select VendorID, count(*) from '{path}' where {ISSUE_PROBES[-1][1].format(cbd=cbd)}
                               group by 1 order by 1""").fetchall()
        lines += ["Total-vs-components mismatches by vendor: " + ", ".join(f"{v}: {c:,}" for v, c in mism), ""]

    by_label: dict = {}
    for label, month, k, share in probe_rows:
        by_label.setdefault(label, {})[month] = f"{k:,} ({share:.2%})"
    ms = sorted({m for _, m, _, _ in probe_rows})
    issue = ["## Issue probes (drove the validation rules)", "", "| probe | " + " | ".join(ms) + " |",
             "|---|" + "---|" * len(ms)]
    issue += [f"| {lab} | " + " | ".join(v.get(m, "-") for m in ms) + " |" for lab, v in by_label.items()]
    out = lines[:4] + issue + [""] + lines[4:]
    (cfg.paths.docs / "profiling_report.md").write_text("\n".join(out) + "\n")
    log.info("profiling report written to docs/profiling_report.md")
