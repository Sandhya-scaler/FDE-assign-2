# Profiling report (raw files, before validation)

_Generated 2026-09-27 15:03 UTC with `python -m pipeline profile`._

## Issue probes (drove the validation rules)

| probe | 2024-01 | 2025-01 |
|---|---|---|
| pickup outside file month | 18 (0.00%) | 22 (0.00%) |
| dropoff <= pickup | 870 (0.03%) | 2,051 (0.06%) |
| duration > 3h | 1,983 (0.07%) | 1,377 (0.04%) |
| trip_distance <= 0 | 60,371 (2.04%) | 90,893 (2.62%) |
| trip_distance > 100 mi | 59 (0.00%) | 162 (0.00%) |
| passenger_count null | 140,162 (4.73%) | 540,149 (15.54%) |
| passenger_count = 0 | 31,465 (1.06%) | 24,656 (0.71%) |
| RatecodeID = 99 | 28,663 (0.97%) | 41,963 (1.21%) |
| payment_type = 0 | 140,162 (4.73%) | 540,149 (15.54%) |
| fare_amount < 0 | 37,448 (1.26%) | 144,118 (4.15%) |
| PU/DO location 264/265 (unknown) | 31,527 (1.06%) | 28,357 (0.82%) |
| total != sum of components | 761,838 (25.70%) | 1,111,807 (31.99%) |

## 2024-01 - 2,964,624 rows

| column | type | min | max | null % | approx distinct |
|---|---|---|---|---|---|
| VendorID | INTEGER | 1 | 6 | 0.00 | 3 |
| tpep_pickup_datetime | TIMESTAMP | 2002-12-31 22:59:39 | 2024-02-01 00:01:15 | 0.00 | 1,407,614 |
| tpep_dropoff_datetime | TIMESTAMP | 2002-12-31 23:05:41 | 2024-02-02 13:56:52 | 0.00 | 1,394,941 |
| passenger_count | BIGINT | 0 | 9 | 4.73 | 11 |
| trip_distance | DOUBLE | 0.0 | 312722.3 | 0.00 | 3,376 |
| RatecodeID | BIGINT | 1 | 99 | 4.73 | 7 |
| store_and_fwd_flag | VARCHAR | N | Y | 4.73 | 2 |
| PULocationID | INTEGER | 1 | 265 | 0.00 | 290 |
| DOLocationID | INTEGER | 1 | 265 | 0.00 | 290 |
| payment_type | BIGINT | 0 | 4 | 0.00 | 5 |
| fare_amount | DOUBLE | -899.0 | 5000.0 | 0.00 | 7,091 |
| extra | DOUBLE | -7.5 | 14.25 | 0.00 | 50 |
| mta_tax | DOUBLE | -0.5 | 4.0 | 0.00 | 7 |
| tip_amount | DOUBLE | -80.0 | 428.0 | 0.00 | 3,551 |
| tolls_amount | DOUBLE | -80.0 | 115.92 | 0.00 | 977 |
| improvement_surcharge | DOUBLE | -1.0 | 1.0 | 0.00 | 5 |
| total_amount | DOUBLE | -900.0 | 5000.0 | 0.00 | 19,162 |
| congestion_surcharge | DOUBLE | -2.5 | 2.5 | 4.73 | 6 |
| Airport_fee | DOUBLE | -1.75 | 1.75 | 4.73 | 3 |

Vendor mix: 1: 729,732, 2: 2,234,632, 6: 260

Total-vs-components mismatches by vendor: 1: 675,956, 2: 85,882

## 2025-01 - 3,475,226 rows

| column | type | min | max | null % | approx distinct |
|---|---|---|---|---|---|
| VendorID | INTEGER | 1 | 7 | 0.00 | 4 |
| tpep_pickup_datetime | TIMESTAMP | 2024-12-31 20:47:55 | 2025-02-01 00:00:44 | 0.00 | 1,967,401 |
| tpep_dropoff_datetime | TIMESTAMP | 2024-12-18 07:52:40 | 2025-02-01 23:44:11 | 0.00 | 1,773,673 |
| passenger_count | BIGINT | 0 | 9 | 15.54 | 11 |
| trip_distance | DOUBLE | 0.0 | 276423.57 | 0.00 | 3,330 |
| RatecodeID | BIGINT | 1 | 99 | 15.54 | 7 |
| store_and_fwd_flag | VARCHAR | N | Y | 15.54 | 2 |
| PULocationID | INTEGER | 1 | 265 | 0.00 | 266 |
| DOLocationID | INTEGER | 1 | 265 | 0.00 | 290 |
| payment_type | BIGINT | 0 | 5 | 0.00 | 6 |
| fare_amount | DOUBLE | -900.0 | 863372.12 | 0.00 | 10,304 |
| extra | DOUBLE | -7.5 | 15.0 | 0.00 | 73 |
| mta_tax | DOUBLE | -0.5 | 10.5 | 0.00 | 10 |
| tip_amount | DOUBLE | -86.0 | 400.0 | 0.00 | 3,209 |
| tolls_amount | DOUBLE | -126.94 | 170.94 | 0.00 | 1,127 |
| improvement_surcharge | DOUBLE | -1.0 | 1.0 | 0.00 | 4 |
| total_amount | DOUBLE | -901.0 | 863380.37 | 0.00 | 20,482 |
| congestion_surcharge | DOUBLE | -2.5 | 2.5 | 15.54 | 3 |
| Airport_fee | DOUBLE | -1.75 | 6.75 | 15.54 | 7 |
| cbd_congestion_fee | DOUBLE | -0.75 | 0.75 | 0.00 | 3 |

Vendor mix: 1: 753,671, 2: 2,719,860, 6: 489, 7: 1,206

Total-vs-components mismatches by vendor: 1: 683,316, 2: 427,442, 6: 489, 7: 560

