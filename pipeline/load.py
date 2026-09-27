"""Stage 2 - Load raw inputs into the warehouse, unchanged, with lineage columns.

Every load is idempotent: a month is replaced inside one transaction (delete + insert),
so re-running never duplicates rows and a failure leaves the previous version intact.
"""
from __future__ import annotations

import json
import logging

from .config import Config
from .ingest import RetrievalIncomplete, latest_api_snapshot, load_manifest, parquet_columns

log = logging.getLogger("pipeline.load")

RAW_TRIPS_DDL = """
create table if not exists raw_yellow_trips (
    trip_id varchar,               -- <source_month>-<row number in source file>: stable across reruns
    source_month varchar,
    source_file varchar,
    source_row bigint,
    vendorid integer,
    tpep_pickup_datetime timestamp,
    tpep_dropoff_datetime timestamp,
    passenger_count bigint,
    trip_distance double,
    ratecodeid bigint,
    store_and_fwd_flag varchar,
    pulocationid integer,
    dolocationid integer,
    payment_type bigint,
    fare_amount double,
    extra double,
    mta_tax double,
    tip_amount double,
    tolls_amount double,
    improvement_surcharge double,
    total_amount double,
    congestion_surcharge double,
    airport_fee double,
    cbd_congestion_fee double,
    loaded_at timestamp
)
"""


def load_trip_month(con, cfg: Config, month: str) -> int:
    path = cfg.paths.raw_trips / f"yellow_tripdata_{month}.parquet"
    entry = load_manifest(cfg)["files"][str(path.relative_to(cfg.paths.root))]
    has_cbd = "cbd_congestion_fee" in parquet_columns(path)
    cbd = "cbd_congestion_fee" if has_cbd else "null::double"

    con.execute(RAW_TRIPS_DDL)
    con.execute("begin transaction")
    try:
        con.execute("delete from raw_yellow_trips where source_month = ?", [month])
        con.execute(f"""
            insert into raw_yellow_trips
            select
                ? || '-' || file_row_number as trip_id,
                ? as source_month,
                ? as source_file,
                file_row_number as source_row,
                VendorID, tpep_pickup_datetime, tpep_dropoff_datetime, passenger_count,
                trip_distance, RatecodeID, store_and_fwd_flag, PULocationID, DOLocationID,
                payment_type, fare_amount, extra, mta_tax, tip_amount, tolls_amount,
                improvement_surcharge, total_amount, congestion_surcharge, Airport_fee,
                {cbd} as cbd_congestion_fee,
                current_timestamp
            from read_parquet('{path}', file_row_number = true)
        """, [month, month, path.name])
        loaded = con.execute("select count(*) from raw_yellow_trips where source_month = ?",
                             [month]).fetchone()[0]
        # Completeness: every row the producer declared in the Parquet footer is in the warehouse.
        if loaded != entry["parquet_rows"]:
            raise RetrievalIncomplete(f"{month}: loaded {loaded} rows, parquet footer declares "
                                      f"{entry['parquet_rows']}")
        con.execute("commit")
    except Exception:
        con.execute("rollback")
        raise
    log.info("%s: loaded %d raw rows (matches parquet footer)", month, loaded)
    return loaded


def load_reference(con, cfg: Config) -> None:
    """(Re)build reference tables from the preserved raw files and seeds."""
    lookup = cfg.paths.raw_reference / "taxi_zone_lookup.csv"
    con.execute(f"""
        create or replace table ref_zone_lookup as
        select LocationID::integer as location_id, Borough as borough, Zone as zone,
               service_zone
        from read_csv('{lookup}', header = true)
    """)

    zones = json.loads(latest_api_snapshot(cfg, "taxi_zones").read_text())["rows"]
    con.execute("create or replace table ref_zones_api (location_id integer, borough varchar, "
                "zone varchar, shape_area double)")
    con.executemany("insert into ref_zones_api values (?, ?, ?, ?)",
                    [[int(float(r["locationid"])), r.get("borough"), r.get("zone"),
                      float(r["shape_area"]) if r.get("shape_area") else None] for r in zones])

    ind = json.loads(latest_api_snapshot(cfg, "industry_indicators").read_text())["rows"]
    con.execute("""create or replace table ref_industry_indicators (
        month_year varchar, license_class varchar, trips_per_day double, farebox_per_day double,
        unique_vehicles double, vehicles_per_day double, avg_minutes_per_trip double)""")
    num = lambda v: float(v) if v not in (None, "") else None  # noqa: E731
    con.executemany("insert into ref_industry_indicators values (?, ?, ?, ?, ?, ?, ?)",
                    [[r["month_year"], r["license_class"], num(r.get("trips_per_day")),
                      num(r.get("farebox_per_day")), num(r.get("unique_vehicles")),
                      num(r.get("vehicles_per_day")), num(r.get("avg_minutes_per_trip"))]
                     for r in ind])

    for seed in ("dim_vendor", "dim_ratecode", "dim_payment_type"):
        con.execute(f"create or replace table {seed} as "
                    f"select * from read_csv('{cfg.paths.seeds / (seed + '.csv')}', header = true)")
    log.info("reference tables loaded: %d lookup zones, %d API zones, %d indicator months",
             con.execute("select count(*) from ref_zone_lookup").fetchone()[0], len(zones), len(ind))
