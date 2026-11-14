# Data Model: Weather POC End-to-End Flow

All timestamps are UTC (`DateTime('UTC')`) unless a column name ends in `_local`. Local time is
Europe/Tallinn and appears only in `dim_interval` and the mart (constitution V).

```text
ingestion job ──INSERT──► bronze.open_meteo_weather            (append-only, native JSON)
                                │ dbt: read paths, cast, clean, dedupe
dbt seed (locations) ──► silver.weather_locations
                         silver.open_meteo_weather              (one row per grain key, latest load)
                                │
             ┌──────────────────┼────────────────────┐
             ▼                  ▼                    ▼
     gold.dim_location   gold.fact_weather    gold.dim_interval
             └─────────┬────────┘────────────────────┘
                       ▼
              gold.mart_past_weather  ──► Superset "Past weather" (reader account, gold only)
```

## Bronze

### `bronze.open_meteo_weather`

Created by the ClickHouse init script `infra/clickhouse/init/03_bronze_open_meteo_weather.sql`
when the stack's volume is first created. The full DDL is in
[contracts/bronze-table.md](contracts/bronze-table.md).

| Column | Type | Description |
|---|---|---|
| `record` | `JSON` | The record with every key and value of one run-file line ([feature 001 output contract](../001-open-meteo-ingestion/contracts/output-file.md)); no type hints, paths read as `record.<key>`. Timestamps stay strings (inference off at insert); `null` values are not stored as paths and read back as `NULL`. |
| `run_id` | `UUID` | Copied from `record.run_id` |
| `source_type` | `LowCardinality(String)` | `forecast` or `archive`, copied from the record |
| `loaded_at` | `DateTime('UTC')` | Copied from `record.loaded_at`; the same for every row of a run |

- **Grain**: one row per location per hour per run. The same hour repeats across runs.
- **Rules**: only `INSERT`; no `UPDATE`, `DELETE` or `TRUNCATE` (FR-004). A run's rows are written
  by one statement, so they all appear or none do (FR-005). A document that is not valid JSON is
  rejected by the insert and fails the run.
- **Freshness**: warn when `max(loaded_at)` is more than 6 h old (FR-008).

## Silver

### `silver.weather_locations` (dbt seed)

A copy of `ingestion/open_meteo/locations.toml`, checked by a pytest. Columns: `location_key`
(`String`, from `id`), `location_name`, `latitude` (`Float64`), `longitude` (`Float64`),
`zone_code` (from `bidding_zone`), `location_role` (from `role`).

### `silver.open_meteo_weather`

Each key is read as `CAST(record.<key>, 'Nullable(String)')` (timestamps then parsed with
`parseDateTimeBestEffortOrNull(..., 'UTC')`) and each value as `CAST(record.<key>,
'Nullable(Float64)')`.

| Column | Type | From the bronze `record` key | Rule |
|---|---|---|---|
| `location_key` | `String` | `location_id` | key; row dropped if missing |
| `interval_start_utc` | `DateTime('UTC')` | `hour_utc` | key; row dropped if missing or unparsable |
| `source_type` | `LowCardinality(String)` | `source_type` | key; row dropped unless `forecast` or `archive` |
| `forecast_issued_utc` | `Nullable(DateTime('UTC'))` | `forecast_version_at` | key; `NULL` for archive; a forecast row without it is dropped |
| `lead_time_h` | `Nullable(Int32)` | derived | `floor((interval_start_utc − forecast_issued_utc) / 1 h)`; `NULL` for archive; can be negative |
| `temperature_c` | `Nullable(Float64)` | `temperature_2m_c` | as delivered |
| `wind_speed_ms` | `Nullable(Float64)` | `wind_speed_10m_ms` | `NULL` if `< 0` |
| `wind_direction_deg` | `Nullable(Float64)` | `wind_direction_10m_deg` | `NULL` if outside `[0, 360]` |
| `shortwave_radiation_wm2` | `Nullable(Float64)` | `shortwave_radiation_wm2` | `NULL` if `< 0` |
| `direct_radiation_wm2` | `Nullable(Float64)` | `direct_radiation_wm2` | `NULL` if `< 0` |
| `cloud_cover_pct` | `Nullable(Float64)` | `cloud_cover_pct` | `NULL` if outside `[0, 100]` |
| `precipitation_mm` | `Nullable(Float64)` | `precipitation_mm` | `NULL` if `< 0` |
| `grid_latitude` | `Nullable(Float64)` | `grid_latitude` | as delivered |
| `grid_longitude` | `Nullable(Float64)` | `grid_longitude` | as delivered |
| `grid_elevation_m` | `Nullable(Float64)` | `grid_elevation_m` | as delivered |
| `run_id` | `UUID` | bronze column | the winning load |
| `loaded_at` | `DateTime('UTC')` | bronze column | the winning load |

- **Grain**: one row per (`location_key`, `interval_start_utc`, `source_type`,
  `forecast_issued_utc`). When the same grain key appears more than once, the row with the
  latest `loaded_at` wins, and the largest `run_id` breaks a tie (FR-010).
- **Excluded rows** stay in bronze: a key path is missing or invalid (FR-011).
- **Tests**: `not_null` on `location_key`, `interval_start_utc`, `source_type`, `run_id`,
  `loaded_at`. `accepted_values` on `source_type`. `unique_combination_of_columns` on the grain.
  `within_range` on the six cleaned values (FR-012).

## Gold

### `gold.dim_location` (SCD type 1)

| Column | Type | Notes |
|---|---|---|
| `location_key` | `String` | primary key; the configured location id |
| `location_name` | `String` | e.g. `Pärnu` |
| `latitude` | `Float64` | configured point, not the provider grid point |
| `longitude` | `Float64` | |
| `zone_code` | `LowCardinality(String)` | bidding zone, `EE` |
| `location_role` | `LowCardinality(String)` | `demand`, `solar` or `wind` |
| `loaded_at` | `DateTime('UTC')` | dbt build time |

Rebuilt from the seed on every run, so a change to the configuration overwrites the old values.
Tests: `unique` and `not_null` on `location_key`.

### `gold.dim_interval` (static, 60-minute grain)

| Column | Type | Derivation from `interval_start_utc` (`t`) |
|---|---|---|
| `interval_key` | `UInt64` | `toUInt64(formatDateTime(t, '%Y%m%d%H%i'))`, e.g. `202611140000` |
| `interval_start_utc` | `DateTime('UTC')` | every whole hour in the covered range |
| `interval_start_local` | `DateTime('Europe/Tallinn')` | `toTimeZone(t, 'Europe/Tallinn')` |
| `local_date` | `Date` | `toDate(interval_start_local)` |
| `local_hour` | `UInt8` | `toHour(interval_start_local)`, 0–23 |
| `day_of_week` | `UInt8` | `toDayOfWeek(interval_start_local)`, 1 = Monday |
| `is_weekend` | `Bool` | `day_of_week >= 6` |
| `month` | `UInt8` | local month |
| `year` | `UInt16` | local year |
| `iso_week` | `UInt8` | `toISOWeek(interval_start_local)` |
| `season` | `LowCardinality(String)` | local month: Dec–Feb `winter`, Mar–May `spring`, Jun–Aug `summer`, Sep–Nov `autumn` |
| `is_dst` | `Bool` | Tallinn's UTC offset at `t` is +3 h (summer time) |
| `loaded_at` | `DateTime('UTC')` | dbt build time |

- **Range**: 1 January of the earliest silver year to 31 December of the latest silver year, in UTC.
  Empty silver gives an empty table.
- **DST**: every UTC hour appears once. On the autumn change, local hour 3 appears twice on one
  local date, and on the spring change local hour 3 does not appear.
- **Deferred**: `is_ee_holiday`, `tariff_period`, `quarter_of_hour`.
- **Tests**: `unique` and `not_null` on `interval_key` and `interval_start_utc`.

### `gold.fact_weather`

| Column | Type | Notes |
|---|---|---|
| `interval_key` | `UInt64` | FK → `dim_interval` |
| `location_key` | `String` | FK → `dim_location` |
| `interval_start_utc` | `DateTime('UTC')` | kept for range filters without a join |
| `source_type` | `LowCardinality(String)` | `forecast` or `archive` |
| `forecast_issued_utc` | `Nullable(DateTime('UTC'))` | forecast version; `NULL` for archive |
| `lead_time_h` | `Nullable(Int32)` | |
| `temperature_c` … `precipitation_mm` | `Nullable(Float64)` | the seven silver values, unchanged |
| `loaded_at` | `DateTime('UTC')` | silver `loaded_at` (bronze load time) |

- **Grain**: one row per location per hour per source type per forecast version (FR-016). Archive
  rows have `forecast_issued_utc = NULL`.
- **Built as**: silver rows inner-joined to `dim_location`, so rows for unknown locations are
  dropped (edge case), with `interval_key` computed from `interval_start_utc`.
- **Tests**: `unique_combination_of_columns` (`location_key`, `interval_start_utc`, `source_type`,
  `forecast_issued_utc`). `not_null` on `interval_key`, `location_key`, `interval_start_utc`,
  `source_type`. `relationships` from `interval_key` to `dim_interval` and from `location_key` to
  `dim_location` (FR-017).

## Marts (in the `gold` database)

### `gold.mart_past_weather`

The interface Superset depends on, specified in
[contracts/mart-past-weather.md](contracts/mart-past-weather.md).

- **Grain**: one row per location per observed hour (`source_type = 'archive'` only).
- **Columns**: `location_key`, `location_name`, `location_role`, `zone_code`, `interval_start_utc`,
  `interval_start_local`, `local_date`, `local_hour`, `day_of_week`, `is_weekend`, the seven
  weather values, `loaded_at`.
- **Tests**: `unique_combination_of_columns` (`location_key`, `interval_start_utc`). `not_null` on
  both key columns.

## Superset objects

| Object | Identity | Source |
|---|---|---|
| Database `ClickHouse warehouse` | fixed UUID in the bundle | `SUPERSET_WAREHOUSE_URI` (reader account, `gold`) |
| Dataset `mart_past_weather` | fixed UUID | physical table `gold.mart_past_weather` |
| Charts (see [contracts/dashboard.md](contracts/dashboard.md)) | fixed UUIDs | the dataset above |
| Dashboard `Past weather` | fixed UUID, slug `past-weather` | the charts above, two native filters |

## Lifecycle and state

- **Bronze row**: inserted → never changed.
- **Built tables**: replaced as a whole by each successful dbt model run (build a new table, then
  swap it in). If a model or its upstream tests fail, the model is not rebuilt and keeps its last
  good contents.
- **Pipeline run**: `ingest_*` (fetch + insert) → `build_silver` (seed, silver, silver tests) →
  `build_gold` (dimensions, fact, mart, their tests). Any failure stops the steps after it. Beside
  them, `check_bronze_freshness` runs after the ingest tasks whatever their outcome and only warns.
