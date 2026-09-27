"""Stage 4 - Workflow model.

Entities : zone (dim_zone), vendor/TPEP provider (dim_vendor), rate code, payment type
Events   : pickup -> dropoff -> payment, one trip = one instance of the workflow (fct_trip_event)
Outcome  : duration, distance, speed, fare of each completed, validated trip (fct_trip)
Intervention: Manhattan Congestion Relief Zone toll from 2025-01-05, visible per trip
              as cbd_congestion_fee > 0 (column absent before 2025 -> null, not 0).
"""
from __future__ import annotations

import logging

from .config import Config

log = logging.getLogger("pipeline.model")


def build_dimensions(con, cfg: Config) -> dict:
    m = cfg.metrics
    airports = ", ".join(str(z) for z in m["airport_zone_ids"])
    con.execute(f"""
        create or replace table dim_zone as
        select l.location_id, l.borough, l.zone, l.service_zone,
            l.service_zone = '{m["core_service_zone"]}' as is_manhattan_core,
            l.location_id in ({airports}) as is_airport,
            l.location_id in (264, 265) as is_unknown,
            a.location_id is not null as in_zones_api,
            case
                when l.location_id in (264, 265) then 'n/a (unknown zone)'
                when a.location_id is null then 'missing from API (API reuses id 56/103)'
                when lower(trim(a.borough)) = lower(trim(l.borough))
                     and lower(trim(a.zone)) = lower(trim(l.zone)) then 'match'
                when lower(trim(a.borough)) = lower(trim(l.borough)) then 'zone name differs'
                else 'borough differs'
            end as api_crosscheck
        from ref_zone_lookup l
        left join (select distinct location_id, borough, zone from ref_zones_api) a using (location_id)
    """)
    summary = dict(con.execute("select api_crosscheck, count(*) from dim_zone group by 1").fetchall())
    log.info("dim_zone built; lookup vs Taxi Zones API cross-check: %s", summary)
    return summary


FCT_TRIP_SELECT = """
    select
        s.trip_id, s.source_month, s.vendorid as vendor_id,
        s.tpep_pickup_datetime as pickup_ts, s.tpep_dropoff_datetime as dropoff_ts,
        cast(s.tpep_pickup_datetime as date) as pickup_date,
        hour(s.tpep_pickup_datetime) as pickup_hour,
        isodow(s.tpep_pickup_datetime) as pickup_isodow,
        isodow(s.tpep_pickup_datetime) <= 5 as is_weekday,
        case
            when hour(s.tpep_pickup_datetime) between 0 and 6 then '1 overnight 00-07'
            when hour(s.tpep_pickup_datetime) between 7 and 9 then '2 am peak 07-10'
            when hour(s.tpep_pickup_datetime) between 10 and 15 then '3 midday 10-16'
            when hour(s.tpep_pickup_datetime) between 16 and 18 then '4 pm peak 16-19'
            else '5 evening 19-24'
        end as time_band,
        s.pulocationid as pu_zone_id, s.dolocationid as do_zone_id,
        pu.borough as pu_borough, dz.borough as do_borough,
        pu.is_manhattan_core and dz.is_manhattan_core as is_core_trip,
        pu.is_airport or dz.is_airport as touches_airport,
        case
            when pu.is_manhattan_core and dz.is_manhattan_core then 'manhattan core'
            when pu.is_airport or dz.is_airport then 'airport'
            when pu.borough = dz.borough then 'intra-borough (non-core)'
            else 'cross-borough'
        end as trip_segment,
        s.duration_s / 60.0 as duration_min,
        s.trip_distance as distance_mi,
        s.speed_mph,
        s.passenger_count, s.ratecodeid, s.payment_type,
        s.fare_amount, s.tip_amount, s.total_amount,
        s.cbd_congestion_fee,
        case when s.cbd_congestion_fee is null then null else s.cbd_congestion_fee > 0 end as cbd_fee_charged,
        s.w01_missing_trip_attributes as has_missing_attributes
    from stg_trips s
    join dim_zone pu on pu.location_id = s.pulocationid
    join dim_zone dz on dz.location_id = s.dolocationid
    where s.source_month = ? and s.is_valid
"""


def build_month(con, cfg: Config, month: str) -> int:
    con.execute("begin transaction")
    try:
        exists = con.execute("select count(*) from information_schema.tables "
                             "where table_name = 'fct_trip'").fetchone()[0]
        if not exists:
            con.execute(f"create table fct_trip as {FCT_TRIP_SELECT} limit 0", [month])
        con.execute("delete from fct_trip where source_month = ?", [month])
        con.execute(f"insert into fct_trip {FCT_TRIP_SELECT}", [month])
        con.execute("commit")
    except Exception:
        con.execute("rollback")
        raise
    # Event view: each trip expanded into its workflow events (pickup -> dropoff -> payment).
    con.execute("""
        create or replace view fct_trip_event as
        select trip_id, source_month, 1 as event_seq, 'pickup' as event_type, pickup_ts as event_ts,
               pu_zone_id as zone_id, null::double as amount from fct_trip
        union all
        select trip_id, source_month, 2, 'dropoff', dropoff_ts, do_zone_id, null from fct_trip
        union all
        select trip_id, source_month, 3, 'payment', dropoff_ts, do_zone_id, total_amount from fct_trip
    """)
    n = con.execute("select count(*) from fct_trip where source_month = ?", [month]).fetchone()[0]
    log.info("%s: fct_trip has %d validated trips", month, n)
    return n
