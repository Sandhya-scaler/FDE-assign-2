# Workflow and data model

## Trip workflow (one yellow-cab trip)

```mermaid
flowchart LR
    A[Street hail / dispatch] --> P((Pickup<br/>time + zone))
    P --> R[In-trip<br/>metered distance]
    R --> D((Dropoff<br/>time + zone))
    D --> $((Payment<br/>fare, tip, fees))
    I[/"Intervention: congestion relief zone fee<br/>(from 2025-01-05)"/] -. charged on .-> $
    I -. expected effect on .-> R
    D --> O[["Outcome: duration, speed,<br/>fare per trip"]]
```

Entities: **zone** (where), **vendor / TPEP provider** (who recorded it), **rate code** and **payment type** (how it was charged).
Events: pickup → dropoff → payment (`fct_trip_event`). Outcome: duration, distance, speed (`fct_trip`).
Intervention: `cbd_congestion_fee > 0` marks trips charged the congestion toll. The column is absent before 2025, so it is `null`, not `0`.

## Pipeline

```mermaid
flowchart LR
    subgraph Sources
      S1[(TLC trip Parquet<br/>HTTPS file)]
      S2[(Zone lookup CSV<br/>HTTPS file)]
      S3[(Taxi Zones<br/>Socrata API)]
      S4[(Industry Indicators<br/>Socrata API)]
    end
    subgraph Ingest
      RAW[data/raw/ + manifest.json<br/>checksums, row counts]
    end
    S1 & S2 & S3 & S4 --> RAW
    RAW --> L[raw_yellow_trips<br/>ref_* tables]
    L --> V[stg_trips<br/>one flag per rule]
    V --> G{Gates G1-G2<br/>fail = block month}
    G --> M[dim_zone, fct_trip,<br/>fct_trip_event]
    M --> K[metrics_monthly<br/>kpi_breakdown]
    K --> RC{Gates G3-G4<br/>reconcile vs TLC API}
    RC --> OUT[output/*.csv<br/>evidence_report.md]
```

## Relational model (DuckDB, `warehouse/tlc.duckdb`)

```mermaid
erDiagram
    raw_yellow_trips ||--|| stg_trips : "trip_id (all rows kept + rule flags)"
    stg_trips ||--o| fct_trip : "is_valid only"
    fct_trip ||--|{ fct_trip_event : "pickup, dropoff, payment"
    dim_zone ||--o{ fct_trip : "pu_zone_id / do_zone_id"
    dim_vendor ||--o{ fct_trip : vendor_id
    dim_ratecode ||--o{ fct_trip : ratecodeid
    dim_payment_type ||--o{ fct_trip : payment_type
    fct_trip }o--|| metrics_monthly : "aggregated by source_month"
    ref_industry_indicators ||--o| reconciliation : month_year
    fct_trip {
        varchar trip_id PK
        varchar source_month
        timestamp pickup_ts
        timestamp dropoff_ts
        int pu_zone_id FK
        int do_zone_id FK
        varchar time_band
        varchar trip_segment
        double duration_min
        double distance_mi
        double speed_mph
        boolean cbd_fee_charged
    }
    dim_zone {
        int location_id PK
        varchar borough
        varchar zone
        varchar service_zone
        boolean is_manhattan_core
        boolean is_airport
        varchar api_crosscheck
    }
    metrics_monthly {
        varchar source_month
        varchar metric_id
        double value
        bigint n_basis
        varchar status
        varchar run_id
    }
```

| Table | Grain | Built by | Rerun behaviour |
|---|---|---|---|
| `raw_yellow_trips` | raw row | `load.py` | month replaced in one transaction |
| `stg_trips` | raw row + 15 rule flags, `is_valid`, `exclusion_rule` | `validate.py` | month replaced |
| `validation_results` | month × rule | `validate.py` | month replaced |
| `gate_results` | month × gate | `gates.py` | month replaced |
| `dim_zone` | LocationID | `model.py` | rebuilt each run |
| `fct_trip` | validated trip | `model.py` | month replaced |
| `fct_trip_event` (view) | trip × event | `model.py` | view |
| `metrics_monthly`, `kpi_breakdown`, `reconciliation` | month × metric / band / segment | `metrics.py` | month replaced |
| `pipeline_runs`, `pipeline_stage_log` | run / run × month × stage | `__main__.py` | append-only audit log |
