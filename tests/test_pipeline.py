"""Tests on a tiny synthetic month: rules fire on the rows they should, reruns are idempotent,
gates block bad months, and a failed load rolls back without touching previous data."""
import json
import shutil

import duckdb
import pytest

from pipeline import gates, load, metrics, model, validate
from pipeline.config import ROOT, Config
from pipeline.db import connect
from pipeline.ingest import RetrievalIncomplete

MONTH = "2025-01"

# (label, pickup, dropoff, distance, PU, DO, fare, total, expected exclusion rule)
ROWS = [
    ("good_core", "2025-01-06 08:00:00", "2025-01-06 08:12:00", 1.6, 161, 236, 12.0, 12.0, None),
    ("good_jfk", "2025-01-06 09:00:00", "2025-01-06 09:50:00", 17.0, 161, 132, 70.0, 70.0, None),
    ("stray_2009", "2009-01-01 00:10:00", "2009-01-01 00:20:00", 2.0, 161, 236, 10.0, 10.0, "R01"),
    ("negative_duration", "2025-01-07 10:00:00", "2025-01-07 09:59:00", 1.0, 161, 236, 8.0, 8.0, "R02"),
    ("too_short", "2025-01-07 10:00:00", "2025-01-07 10:00:30", 0.1, 161, 236, 3.0, 3.0, "R03"),
    ("zero_distance", "2025-01-07 11:00:00", "2025-01-07 11:10:00", 0.0, 161, 236, 8.0, 8.0, "R04"),
    ("odometer", "2025-01-07 12:00:00", "2025-01-07 14:00:00", 5000.0, 161, 236, 20.0, 20.0, "R05"),
    ("too_fast", "2025-01-07 13:00:00", "2025-01-07 13:05:00", 20.0, 161, 236, 20.0, 20.0, "R06"),
    ("unknown_zone", "2025-01-07 14:00:00", "2025-01-07 14:10:00", 2.0, 264, 236, 10.0, 10.0, "R07"),
    ("bad_zone", "2025-01-07 15:00:00", "2025-01-07 15:10:00", 2.0, 999, 236, 10.0, 10.0, "R08"),
    ("refund", "2025-01-07 16:00:00", "2025-01-07 16:10:00", 2.0, 161, 236, -10.0, -10.0, "R09"),
    ("good_core", "2025-01-06 08:00:00", "2025-01-06 08:12:00", 1.6, 161, 236, 12.0, 12.0, "R10"),  # duplicate
]


def _make_parquet(path, rows, pad_days=True):
    con = duckdb.connect()
    con.execute("""create table t (VendorID int, tpep_pickup_datetime timestamp, tpep_dropoff_datetime timestamp,
        passenger_count bigint, trip_distance double, RatecodeID bigint, store_and_fwd_flag varchar,
        PULocationID int, DOLocationID int, payment_type bigint, fare_amount double, extra double,
        mta_tax double, tip_amount double, tolls_amount double, improvement_surcharge double,
        total_amount double, congestion_surcharge double, Airport_fee double, cbd_congestion_fee double)""")
    data = [(2, pu, do, 1, dist, 1, "N", pul, dol, 1, fare, 0, 0, 0, 0, 0, tot, 0, 0, 0)
            for _, pu, do, dist, pul, dol, fare, tot, _ in rows]
    if pad_days:  # one good trip per day so the daily-coverage gate has something to measure
        data += [(2, f"2025-01-{d:02d} 12:00:00", f"2025-01-{d:02d} 12:15:00", 1, 2.0, 1, "N", 161, 236, 1,
                  12.0, 0, 0, 0, 0, 0, 12.0, 0, 0, 0.75) for d in range(1, 32)]
    con.executemany("insert into t values (" + ",".join("?" * 20) + ")", data)
    con.execute(f"copy t to '{path}' (format parquet)")
    return len(data)


@pytest.fixture
def env(tmp_path):
    cfg = Config.load(root=tmp_path)
    cfg.paths.ensure()
    shutil.copytree(ROOT / "seeds", tmp_path / "seeds")
    zones = [(1, "EWR", "Newark Airport", "EWR"), (132, "Queens", "JFK Airport", "Airports"),
             (161, "Manhattan", "Midtown Center", "Yellow Zone"), (236, "Manhattan", "Upper East Side North",
                                                                    "Yellow Zone"),
             (264, "Unknown", "N/A", "N/A")]
    (cfg.paths.raw_reference / "taxi_zone_lookup.csv").write_text(
        '"LocationID","Borough","Zone","service_zone"\n' + "\n".join(f'{a},"{b}","{c}","{d}"' for a, b, c, d in zones))
    api = {"taxi_zones": {"rows": [{"locationid": str(z[0]), "borough": z[1], "zone": z[2]} for z in zones[:4]]},
           "industry_indicators": {"rows": [{"month_year": MONTH, "license_class": "Yellow",
                                             "trips_per_day": "1.3", "avg_minutes_per_trip": "15"}]}}
    manifest = {"files": {}, "latest": {}}
    for name, payload in api.items():
        p = cfg.paths.raw_api / f"{name}.json"
        p.write_text(json.dumps(payload))
        manifest["latest"][name] = str(p.relative_to(tmp_path))
    trip = cfg.paths.raw_trips / f"yellow_tripdata_{MONTH}.parquet"
    n = _make_parquet(trip, ROWS)
    manifest["files"][str(trip.relative_to(tmp_path))] = {"parquet_rows": n}
    cfg.paths.manifest.write_text(json.dumps(manifest))
    con = connect(cfg)
    load.load_reference(con, cfg)
    model.build_dimensions(con, cfg)
    return cfg, con, n


def _run_month(cfg, con):
    load.load_trip_month(con, cfg, MONTH)
    validate.validate_month(con, cfg, MONTH)
    ok = gates.run_blocking_gates(con, cfg, MONTH)
    model.build_month(con, cfg, MONTH)
    metrics.compute_month(con, cfg, MONTH, "test", ok)
    return ok


def test_each_rule_catches_its_row(env):
    cfg, con, _ = env
    _run_month(cfg, con)
    got = con.execute("select source_row, exclusion_rule from stg_trips order by source_row").fetchall()
    for (row, rule), (label, *_, expected) in zip(got, ROWS):
        assert rule == expected, f"{label}: expected {expected}, got {rule}"


def test_rerun_is_idempotent(env):
    cfg, con, n = env
    _run_month(cfg, con)
    first = con.execute("select metric_id, value from metrics_monthly order by 1").fetchall()
    _run_month(cfg, con)
    assert con.execute("select count(*) from raw_yellow_trips").fetchone()[0] == n
    assert con.execute("select count(*) from stg_trips").fetchone()[0] == n
    assert con.execute("select metric_id, value from metrics_monthly order by 1").fetchall() == first


def test_warn_rules_keep_rows(env):
    cfg, con, _ = env
    _run_month(cfg, con)
    assert con.execute("select count(*) from stg_trips where exclusion_rule like 'W%'").fetchone()[0] == 0


def test_gate_blocks_mostly_invalid_month(env, tmp_path):
    cfg, con, _ = env
    trip = cfg.paths.raw_trips / f"yellow_tripdata_{MONTH}.parquet"
    n = _make_parquet(trip, [r for r in ROWS if r[-1]], pad_days=False)  # only bad rows
    m = json.loads(cfg.paths.manifest.read_text())
    m["files"][str(trip.relative_to(tmp_path))]["parquet_rows"] = n
    cfg.paths.manifest.write_text(json.dumps(m))
    assert _run_month(cfg, con) is False
    assert {r[0] for r in con.execute("select status from metrics_monthly").fetchall()} == {"blocked"}


def test_incomplete_load_rolls_back(env, tmp_path):
    cfg, con, n = env
    load.load_trip_month(con, cfg, MONTH)
    trip = cfg.paths.raw_trips / f"yellow_tripdata_{MONTH}.parquet"
    m = json.loads(cfg.paths.manifest.read_text())
    m["files"][str(trip.relative_to(tmp_path))]["parquet_rows"] = n + 5  # producer claims more rows
    cfg.paths.manifest.write_text(json.dumps(m))
    with pytest.raises(RetrievalIncomplete):
        load.load_trip_month(con, cfg, MONTH)
    assert con.execute("select count(*) from raw_yellow_trips").fetchone()[0] == n  # previous load intact
