# Data Model: Elering Electricity Prices Pipeline

End-to-end data flow from configuration and Elering API ingestion through the ClickHouse medallion
layers up to the gold star schema.

```text
Elering API (/api/nps/price)
      │  ingestion/elering_prices (single atomic INSERT ... FORMAT JSONEachRow)
      ▼
bronze.elering_prices  (native JSON `record` + run_id, mode, loaded_at; append-only)
      │  dbt: accurateCastOrNull, uppercase zone_code, plausibility filter, LIMIT 1 BY dedup
      ▼
silver.elering_prices                 silver.bidding_zones (dbt seed ◄── bidding_zones.toml)
      │                                     │
      ├───────────────────────┐             │
      │  (union with          ▼             ▼
      │   silver.open_meteo_weather)   gold.dim_bidding_zone (SCD type 2: 60-min + 15-min)
      ▼                       │             │
gold.dim_interval (60-min)    └──────┬──────┘
      │                              │
      └──────────────┬───────────────┘
                     ▼
              gold.fact_price (60-min grain: hourly price / 15-min mean)
```

---

## 1. Configuration Entity: Bidding Zones (`bidding_zones.toml`)

Source of truth for configured bidding zones and their Market Time Unit (MTU) transition metadata.
Stored at `ingestion/elering_prices/bidding_zones.toml`.

| Field | Type | Constraints | Description |
|---|---|---|---|
| `code` | `str` | Required, unique, matches `[A-Z]{2}` | Uppercase bidding zone code (`EE`, `FI`, `LV`, `LT`) |
| `name` | `str` | Required, non-empty string | Human-readable display name (`Estonia`, `Finland`, `Latvia`, `Lithuania`) |
| `historical_mtu_minutes` | `int` | Required, positive divisor of 60 (`60`) | Market interval duration before `mtu_switch_utc` |
| `current_mtu_minutes` | `int` | Required, positive divisor of 60 (`15`) | Market interval duration from `mtu_switch_utc` onward |
| `valid_from` | `str` (ISO-8601 UTC) | Required, valid UTC timestamp (`1970-01-01T00:00:00Z`) | Start of historical regime (`< mtu_switch_utc`) |
| `mtu_switch_utc` | `str` (ISO-8601 UTC) | Required, valid UTC timestamp (`2025-09-30T22:00:00Z`) | Exact UTC instant where MTU changes from historical to current |

**Default entries**:

| `code` | `name` | `historical_mtu_minutes` | `current_mtu_minutes` | `valid_from` | `mtu_switch_utc` |
|---|---|---|---|---|---|
| `EE` | Estonia | 60 | 15 | `1970-01-01T00:00:00Z` | `2025-09-30T22:00:00Z` |
| `FI` | Finland | 60 | 15 | `1970-01-01T00:00:00Z` | `2025-09-30T22:00:00Z` |
| `LV` | Latvia | 60 | 15 | `1970-01-01T00:00:00Z` | `2025-09-30T22:00:00Z` |
| `LT` | Lithuania | 60 | 15 | `1970-01-01T00:00:00Z` | `2025-09-30T22:00:00Z` |

---

## 2. Bronze Layer: `bronze.elering_prices`

Created by `infra/clickhouse/init/04_bronze_elering_prices.sql`. Append-only; written exclusively
by `ingestion/elering_prices`.

- **Engine**: `MergeTree`
- **Partitioning**: `PARTITION BY toYYYYMM(loaded_at)`
- **Sort key**: `ORDER BY (mode, loaded_at, run_id)`
- **Grain**: one row per bidding zone per delivered market interval per ingestion run (same
  interval may repeat across runs).

| Column | ClickHouse Type | Description |
|---|---|---|
| `record` | `JSON` | Native ClickHouse JSON document holding all six raw record keys as delivered |
| `run_id` | `UUID` | Unique UUID4 of the ingestion run; copied from `record.run_id` |
| `mode` | `LowCardinality(String)` | `daily` or `backfill`; copied from `record.mode` |
| `loaded_at` | `DateTime('UTC')` | UTC timestamp when the run built its records; identical across all rows of a run |

**Keys inside `record`**:

| Key | JSON Type | Example | Notes |
|---|---|---|---|
| `zone_code` | `string` | `"ee"` | Lower-case zone code as delivered by Elering |
| `interval_start_utc` | `string` | `"2025-09-30T22:00:00Z"` | UTC interval start timestamp kept as ISO-8601 string |
| `price_eur_mwh` | `number` | `-25.5` / `0` / `98.95` | Raw day-ahead spot price in EUR/MWh; never rounded or filtered |
| `mode` | `string` | `"daily"` / `"backfill"` | Ingestion operating mode |
| `run_id` | `string` | `"3f2c9a8e-..."` | Run UUID4 |
| `loaded_at` | `string` | `"2026-11-22T12:30:05Z"` | UTC load timestamp kept as ISO-8601 string |

**Freshness**: `dbt source freshness` checks `max(loaded_at)` with `warn_after: 26 hours` (no
`error_after`).

---

## 3. Silver Reference Seed: `silver.bidding_zones`

dbt seed at `dbt/seeds/silver/bidding_zones.csv` (schema tests in `bidding_zones.yml`). Derived
from `ingestion/elering_prices/bidding_zones.toml` and kept in sync by
`ingestion/tests/elering_prices/test_bidding_zones_seed.py`.

| Column | ClickHouse Type | Tests | Description |
|---|---|---|---|
| `zone_key` | `UInt32` | `unique`, `not_null` | Deterministic surrogate key per zone version (`1`–`8`) |
| `zone_code` | `LowCardinality(String)` | `not_null`, `accepted_values: [EE, FI, LV, LT]` | Uppercase bidding zone code |
| `zone_name` | `String` | `not_null` | Display name |
| `mtu_minutes` | `UInt8` | `not_null`, `accepted_values: [60, 15]` | Market time unit in minutes (`60` or `15`) |
| `valid_from` | `String` | `not_null` | ISO-8601 UTC start of regime (`1970-01-01T00:00:00Z` or `2025-09-30T22:00:00Z`) |
| `valid_to` | `Nullable(String)` | — | ISO-8601 UTC exclusive end (`2025-09-30T22:00:00Z`) or empty (`NULL`) for current |
| `is_current` | `Bool` | `not_null` | `false` for historical 60-min version, `true` for current 15-min version |

**Seed rows**:

| `zone_key` | `zone_code` | `zone_name` | `mtu_minutes` | `valid_from` | `valid_to` | `is_current` |
|---|---|---|---|---|---|---|
| 1 | `EE` | Estonia | 60 | `1970-01-01T00:00:00Z` | `2025-09-30T22:00:00Z` | `false` |
| 2 | `EE` | Estonia | 15 | `2025-09-30T22:00:00Z` | *(empty / NULL)* | `true` |
| 3 | `FI` | Finland | 60 | `1970-01-01T00:00:00Z` | `2025-09-30T22:00:00Z` | `false` |
| 4 | `FI` | Finland | 15 | `2025-09-30T22:00:00Z` | *(empty / NULL)* | `true` |
| 5 | `LV` | Latvia | 60 | `1970-01-01T00:00:00Z` | `2025-09-30T22:00:00Z` | `false` |
| 6 | `LV` | Latvia | 15 | `2025-09-30T22:00:00Z` | *(empty / NULL)* | `true` |
| 7 | `LT` | Lithuania | 60 | `1970-01-01T00:00:00Z` | `2025-09-30T22:00:00Z` | `false` |
| 8 | `LT` | Lithuania | 15 | `2025-09-30T22:00:00Z` | *(empty / NULL)* | `true` |

---

## 4. Silver Layer: `silver.elering_prices`

dbt `table` model (`dbt/models/silver/elering_prices.sql`), full rebuild on every dbt run.

- **Engine**: `MergeTree()`
- **Sort key**: `ORDER BY (zone_code, interval_start_utc)`
- **Grain**: one row per `(zone_code, interval_start_utc)` at delivered market resolution
  (60-minute pre-switch, 15-minute post-switch).

| Column | ClickHouse Type | Source | Tests | Description |
|---|---|---|---|---|
| `zone_code` | `LowCardinality(String)` | `upper(trim(accurateCastOrNull(record.zone_code, 'String')))` | `not_null`, `accepted_values: [EE, FI, LV, LT]` | Standardized uppercase bidding zone code |
| `interval_start_utc` | `DateTime('UTC')` | `parseDateTimeBestEffortOrNull(accurateCastOrNull(record.interval_start_utc, 'String'), 'UTC')` | `not_null` | Start of the delivered market interval (UTC) |
| `price_eur_mwh` | `Float64` | `accurateCastOrNull(record.price_eur_mwh, 'Float64')` | `not_null`, `within_range(-500, 5000)` | Day-ahead price in EUR/MWh; negative and zero values preserved |
| `run_id` | `UUID` | `bronze.run_id` | `not_null` | Run identifier of the winning load |
| `loaded_at` | `DateTime('UTC')` | `bronze.loaded_at` | `not_null` | UTC load timestamp of the winning load |

**Model-level tests**:
- `unique_combination_of_columns: [zone_code, interval_start_utc]`

**Cleaning & deduplication rules**:
- Exclude rows where `zone_code` is null/empty or not present in `silver.bidding_zones`,
  `interval_start_utc` is null/unparsable, or `price_eur_mwh` is null/unparsable/non-finite or
  outside `[-500, 5000]`. Excluded rows remain untouched in bronze and do not fail the build.
- Deduplicate with `ORDER BY loaded_at DESC, run_id DESC LIMIT 1 BY zone_code, interval_start_utc`.

---

## 5. Gold Layer: Star Schema

### 5.1 `gold.dim_bidding_zone` (SCD Type 2)

dbt `table` model (`dbt/models/gold/dim_bidding_zone.sql`), rebuilt from `silver.bidding_zones`.

- **Engine**: `MergeTree()`
- **Sort key**: `ORDER BY (zone_code, valid_from)`
- **Grain**: one row per bidding zone per historical market regime version.

| Column | ClickHouse Type | Tests | Description |
|---|---|---|---|
| `zone_key` | `UInt32` | `unique`, `not_null` | Primary key; surrogate key per zone version |
| `zone_code` | `LowCardinality(String)` | `not_null`, `accepted_values: [EE, FI, LV, LT]` | Natural key (`EE`, `FI`, `LV`, `LT`) |
| `zone_name` | `String` | `not_null` | Display name |
| `mtu_minutes` | `UInt8` | `not_null`, `accepted_values: [60, 15]` | Market time unit in minutes |
| `valid_from` | `DateTime('UTC')` | `not_null` | Inclusive UTC start of version validity |
| `valid_to` | `Nullable(DateTime('UTC'))` | — | Exclusive UTC end of version validity; `NULL` for current version |
| `is_current` | `Bool` | `not_null` | `true` for the active version, `false` for historical |
| `loaded_at` | `DateTime('UTC')` | `not_null` | UTC timestamp when dbt built the dimension |

**SCD Type 2 integrity tests** (singular dbt tests):
- `dim_bidding_zone_no_overlapping_windows`: no two rows for the same `zone_code` have overlapping
  `[valid_from, coalesce(valid_to, max_dt))` ranges.
- `dim_bidding_zone_one_current_per_zone`: every `zone_code` has exactly one row with
  `is_current = true`.

### 5.2 `gold.dim_interval` (Static, Shared — Updated)

Existing dbt `table` model (`dbt/models/gold/dim_interval.sql`), 60-minute UTC grain with
Europe/Tallinn calendar attributes.

- **Change**: The year range (`1 January` of earliest year through `31 December` of latest year) is
  computed over the union of `interval_start_utc` from `silver.open_meteo_weather` **and**
  `silver.elering_prices`. Produces an empty table only when both silver tables are empty.
- **Columns & tests**: Unchanged from feature 003 (`interval_key UInt64`, `interval_start_utc`,
  `interval_start_local`, `local_date`, `local_hour`, `day_of_week`, `is_weekend`, `month`, `year`,
  `iso_week`, `season`, `is_dst`, `loaded_at`). Deferred columns remain `is_ee_holiday`,
  `tariff_period`, `quarter_of_hour`.

### 5.3 `gold.fact_price`

dbt `table` model (`dbt/models/gold/fact_price.sql`), full rebuild on every dbt run.

- **Engine**: `MergeTree()`
- **Sort key**: `ORDER BY (zone_key, interval_start_utc)`
- **Grain**: **one row per bidding zone per 60-minute UTC interval**.

| Column | ClickHouse Type | Tests | Description |
|---|---|---|---|
| `interval_key` | `UInt64` | `not_null`, `relationships` → `dim_interval.interval_key` | Foreign key to `dim_interval` (`YYYYMMDDhhmm` UTC) |
| `zone_key` | `UInt32` | `not_null`, `relationships` → `dim_bidding_zone.zone_key` | Foreign key to historically valid `dim_bidding_zone` version |
| `interval_start_utc` | `DateTime('UTC')` | `not_null` | Start of the 60-minute UTC interval (`toStartOfHour`) |
| `price_eur_mwh` | `Float64` | `not_null`, `within_range(-500, 5000)` | Hourly price (pre-switch) or arithmetic mean of available valid 15-min prices in that hour (post-switch) |
| `loaded_at` | `DateTime('UTC')` | `not_null` | Latest silver `loaded_at` among the intervals contributing to that hour |

**Model-level & singular tests**:
- `unique_combination_of_columns: [zone_key, interval_key]`
- `unique_combination_of_columns: [zone_key, interval_start_utc]`
- `fact_price_complete_interior_days`: every UTC date strictly between `min(toDate(interval_start_utc))`
  and `max(toDate(interval_start_utc))` has exactly 24 hourly rows per bidding zone (`zone_code`
  via `dim_bidding_zone`, seamlessly summing pre- and post-switch versions on `2025-09-30`). Passes
  with zero interior days when `fact_price` is empty or holds only a single daily `D+1` run.

**SCD Type 2 join rule**:
```sql
hourly.zone_code = dim_zone.zone_code
and hourly.interval_start_utc >= dim_zone.valid_from
and (dim_zone.valid_to is null or hourly.interval_start_utc < dim_zone.valid_to)
```
Hours before `2025-09-30 22:00:00 UTC` link to the 60-minute `zone_key` (`1, 3, 5, 7`); hours at
or after `2025-09-30 22:00:00 UTC` link to the 15-minute `zone_key` (`2, 4, 6, 8`).
