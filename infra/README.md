# Data Dictionary

The warehouse has three layers, each a ClickHouse database:

| Layer | Holds | Created by | Written by |
|---|---|---|---|
| `bronze` | raw data as ingested, append-only | init scripts in [clickhouse/init/](clickhouse/init/) (`03_*.sql`), once, on a fresh data volume | the ingestion jobs |
| `silver` | cleaned, typed, deduplicated data | dbt ([../dbt/](../dbt/)) | dbt |
| `gold` | facts, dimensions and marts | dbt | dbt |

The init scripts also create the read-only account Superset uses. It can read `gold` and nothing
else. All timestamps are UTC (`DateTime('UTC')`); local time (Europe/Tallinn) appears only in
`gold.dim_interval` and `gold.mart_past_weather`.

The weather tables below are described as built. The Elering tables at the end are still planned.

```text
ingestion job ──INSERT──► bronze.open_meteo_weather
                                │ dbt: read JSON paths, cast, clean, deduplicate
dbt seed (locations) ──► silver.weather_locations
                         silver.open_meteo_weather
                                │
             ┌──────────────────┼────────────────────┐
             ▼                  ▼                    ▼
     gold.dim_location   gold.fact_weather    gold.dim_interval
             └─────────┬────────┴────────────────────┘
                       ▼
              gold.mart_past_weather ──► Superset "Past weather" dashboard
```

## bronze.open_meteo_weather

Hourly Open-Meteo weather exactly as the ingestion job produced it. DDL:
[clickhouse/init/03_bronze_open_meteo_weather.sql](clickhouse/init/03_bronze_open_meteo_weather.sql).

| Name | Type | Description |
|---|---|---|
| record | JSON | The whole record as a native JSON document: every key and value of one run-file line ([output contract](../specs/001-open-meteo-ingestion/contracts/output-file.md)) |
| run_id | UUID | The run that loaded the row; copied from `record.run_id` |
| source_type | LowCardinality(String) | `forecast` or `archive`; copied from the record |
| loaded_at | DateTime('UTC') | When the run built its records; the same for every row of a run |

- **Grain**: one row per location per hour per run. The same hour repeats across runs.
- **Reading `record`**: paths are sub-columns, e.g. `record.location_id`. Cast them when reading:
  `CAST(record.hour_utc, 'Nullable(String)')`, `CAST(record.temperature_2m_c, 'Nullable(Float64)')`.
  Timestamps inside the document are strings, numbers are stored as `Int64` or `Float64`, and a
  `null` value or a missing key reads as `NULL`.
- **Keys in `record`**: `location_id`, `hour_utc`, `source_type`, `forecast_version_at`,
  `temperature_2m_c`, `wind_speed_10m_ms`, `wind_direction_10m_deg`, `shortwave_radiation_wm2`,
  `direct_radiation_wm2`, `cloud_cover_pct`, `precipitation_mm`, `grid_latitude`,
  `grid_longitude`, `grid_elevation_m`, `run_id`, `loaded_at`.
- **Append-only**: the job only inserts. One run is one `INSERT`, so its rows all appear or none
  do. Partitioned by month of `loaded_at`, sorted by `(source_type, loaded_at, run_id)`.
- **Freshness**: dbt warns when the newest `loaded_at` is more than 6 hours old
  (`dbt source freshness`, the `check_bronze_freshness` task).
- **Changing the table**: init scripts run only on an empty volume, so a DDL change needs a
  migration or `make reset`.

## silver.weather_locations

The weather locations, a dbt seed ([../dbt/seeds/silver/weather_locations.csv](../dbt/seeds/silver/weather_locations.csv))
copied from `ingestion/open_meteo/locations.toml`. A pytest keeps the two files equal.

| Name | Type | Description |
|---|---|---|
| location_key | String | Location id from the configuration, e.g. `tallinn`. Unique, not null |
| location_name | String | Display name, e.g. `Pärnu` |
| latitude | Float64 | Latitude of the configured point |
| longitude | Float64 | Longitude of the configured point |
| zone_code | LowCardinality(String) | Bidding zone, e.g. `EE` |
| location_role | LowCardinality(String) | `demand`, `solar` or `wind` |

## silver.open_meteo_weather

Bronze weather, typed, renamed, cleaned and deduplicated. Rebuilt in full on every dbt run.

| Name | Type | From `record` key | Description |
|---|---|---|---|
| location_key | String | location_id | Configured location id |
| interval_start_utc | DateTime('UTC') | hour_utc | Start of the hour |
| source_type | LowCardinality(String) | source_type | `forecast` or `archive` |
| forecast_issued_utc | Nullable(DateTime('UTC')) | forecast_version_at | Forecast version (when it was retrieved); `NULL` for archive |
| lead_time_h | Nullable(Int32) | derived | Whole hours from `forecast_issued_utc` to `interval_start_utc`, rounded down; can be negative; `NULL` for archive |
| temperature_c | Nullable(Float64) | temperature_2m_c | Air temperature at 2 m, °C; as delivered |
| wind_speed_ms | Nullable(Float64) | wind_speed_10m_ms | Wind speed at 10 m, m/s; `NULL` if delivered `< 0` |
| wind_direction_deg | Nullable(Float64) | wind_direction_10m_deg | Wind direction at 10 m; `NULL` if delivered outside 0–360 |
| shortwave_radiation_wm2 | Nullable(Float64) | shortwave_radiation_wm2 | Global horizontal radiation, W/m², mean over the preceding hour; `NULL` if delivered `< 0` |
| direct_radiation_wm2 | Nullable(Float64) | direct_radiation_wm2 | Direct radiation, W/m², mean over the preceding hour; `NULL` if delivered `< 0` |
| cloud_cover_pct | Nullable(Float64) | cloud_cover_pct | Total cloud cover, %; `NULL` if delivered outside 0–100 |
| precipitation_mm | Nullable(Float64) | precipitation_mm | Precipitation, mm, sum over the preceding hour; `NULL` if delivered `< 0` |
| grid_latitude | Nullable(Float64) | grid_latitude | Latitude of the provider's grid point |
| grid_longitude | Nullable(Float64) | grid_longitude | Longitude of the provider's grid point |
| grid_elevation_m | Nullable(Float64) | grid_elevation_m | Elevation of the provider's grid point, m |
| run_id | UUID | bronze column | The run whose load supplied the row |
| loaded_at | DateTime('UTC') | bronze column | When that load was made |

- **Grain**: one row per (`location_key`, `interval_start_utc`, `source_type`,
  `forecast_issued_utc`). When bronze holds a grain key more than once, the row with the latest
  `loaded_at` wins, and the largest `run_id` breaks a tie.
- **Cleaning**: a physically impossible value becomes `NULL` and the rest of the row is kept, so
  one bad provider value cannot fail the build.
- **Left out** (they stay in bronze): rows whose location, hour or source type is missing or
  unparsable, and forecast rows without a forecast version.
- **Tests**: the grain is unique; keys, `run_id` and `loaded_at` are not null; `source_type` is
  `forecast` or `archive`; the six cleaned values are within their limits.

## gold.dim_location

One row per configured weather location. SCD type 1: rebuilt from `silver.weather_locations` on
every dbt run, so a configuration change overwrites the old values.

| Name | Type | Description |
|---|---|---|
| location_key | String | Primary key; the configured location id. Unique, not null (tested) |
| location_name | String | Display name |
| latitude | Float64 | Configured point, not the provider's grid point |
| longitude | Float64 | |
| zone_code | LowCardinality(String) | Bidding zone |
| location_role | LowCardinality(String) | `demand`, `solar` or `wind` |
| loaded_at | DateTime('UTC') | When dbt built the row |

## gold.dim_interval

Time dimension at 60-minute grain: one row per UTC hour, from 1 January of the earliest year in
silver weather to 31 December of the latest. Local attributes are Europe/Tallinn.

| Name | Type | Description |
|---|---|---|
| interval_key | UInt64 | Primary key; the UTC start as `YYYYMMDDhhmm`, e.g. `202611140000`. Unique, not null (tested) |
| interval_start_utc | DateTime('UTC') | Start of the hour. Unique, not null (tested) |
| interval_start_local | DateTime('Europe/Tallinn') | The same moment in Tallinn time |
| local_date | Date | Tallinn date |
| local_hour | UInt8 | Tallinn hour, 0–23 |
| day_of_week | UInt8 | 1 = Monday … 7 = Sunday |
| is_weekend | Bool | Saturday or Sunday |
| month | UInt8 | Tallinn month |
| year | UInt16 | Tallinn year |
| iso_week | UInt8 | ISO week number |
| season | LowCardinality(String) | `winter` (Dec–Feb), `spring` (Mar–May), `summer` (Jun–Aug), `autumn` (Sep–Nov) |
| is_dst | Bool | Tallinn is on summer time (UTC+3) |
| loaded_at | DateTime('UTC') | When dbt built the row |

Every UTC hour appears once. On the autumn clock change local hour 3 appears twice on one local
date; on the spring change local hour 3 does not appear. Not built yet: `is_ee_holiday`,
`tariff_period`, `quarter_of_hour`.

## gold.fact_weather

Hourly weather values, forecast and observed, for the locations in `dim_location`.

| Name | Type | Description |
|---|---|---|
| interval_key | UInt64 | Foreign key to `dim_interval` |
| location_key | String | Foreign key to `dim_location` |
| interval_start_utc | DateTime('UTC') | Start of the hour; kept for range filters without a join |
| source_type | LowCardinality(String) | `forecast` or `archive` |
| forecast_issued_utc | Nullable(DateTime('UTC')) | Forecast version; `NULL` for archive |
| lead_time_h | Nullable(Int32) | Hours from the forecast issue time to the hour; `NULL` for archive |
| temperature_c | Nullable(Float64) | Air temperature at 2 m, °C |
| wind_speed_ms | Nullable(Float64) | Wind speed at 10 m, m/s |
| wind_direction_deg | Nullable(Float64) | Wind direction at 10 m, 0–360° |
| shortwave_radiation_wm2 | Nullable(Float64) | Global horizontal radiation, W/m², mean over the preceding hour |
| direct_radiation_wm2 | Nullable(Float64) | Direct radiation, W/m², mean over the preceding hour |
| cloud_cover_pct | Nullable(Float64) | Total cloud cover, 0–100 % |
| precipitation_mm | Nullable(Float64) | Precipitation, mm, sum over the preceding hour |
| loaded_at | DateTime('UTC') | When the values were loaded into bronze |

- **Grain**: one row per location per hour per source type per forecast version. Archive rows
  have no forecast version.
- Silver rows for a location that is not in `dim_location` are left out.
- **Tests**: the grain is unique; `interval_key`, `location_key`, `interval_start_utc` and
  `source_type` are not null; every `interval_key` exists in `dim_interval` and every
  `location_key` in `dim_location`.

## gold.mart_past_weather

Observed (archive) weather, hourly, with location and local-time attributes joined in. The only
table the Superset "Past weather" dashboard reads, so changing or removing a column breaks the
dashboard's dataset.

| Name | Type | Description |
|---|---|---|
| location_key | String | Configured location id |
| location_name | String | Display name; the dashboard's filter and series label |
| location_role | LowCardinality(String) | `demand`, `solar` or `wind` |
| zone_code | LowCardinality(String) | Bidding zone |
| interval_start_utc | DateTime('UTC') | Start of the hour; the dashboard's time column |
| interval_start_local | DateTime('Europe/Tallinn') | The same moment in Tallinn time |
| local_date | Date | Tallinn date |
| local_hour | UInt8 | Tallinn hour, 0–23 |
| day_of_week | UInt8 | 1 = Monday |
| is_weekend | Bool | |
| temperature_c | Nullable(Float64) | Air temperature at 2 m, °C |
| wind_speed_ms | Nullable(Float64) | Wind speed at 10 m, m/s |
| wind_direction_deg | Nullable(Float64) | Wind direction at 10 m, 0–360° |
| shortwave_radiation_wm2 | Nullable(Float64) | Global horizontal radiation, W/m², mean over the preceding hour |
| direct_radiation_wm2 | Nullable(Float64) | Direct radiation, W/m², mean over the preceding hour |
| cloud_cover_pct | Nullable(Float64) | Total cloud cover, 0–100 % |
| precipitation_mm | Nullable(Float64) | Precipitation, mm, sum over the preceding hour |
| loaded_at | DateTime('UTC') | When the shown value was loaded into bronze |

- **Grain**: one row per location per observed hour; forecasts never appear. Not pre-aggregated:
  the dashboard aggregates as needed.
- `NULL` in a value column means the provider gave no value or silver removed an impossible one.
- **Tests**: the grain is unique; `location_key` and `interval_start_utc` are not null.

## Planned: Elering tables

The bronze tables below are **planned**, not created yet. Each gets its DDL in the feature that
loads it, and the definitions here will be updated to match then.

## bronze.elering_prices

| Name | Type | Description |
|---|---|---|
| id | serial int | |
| zone_code | char(2) | Bidding zone (EE, FI, LV, LT) |
| interval_start_utc | timestamptz | Start of the market interval |
| price_eur_mwh | numeric | Electricity price EUR/MWh |
| loaded_at | timestampz | When the row was loaded |

## bronze.elering_system

| Name | Type | Description |
|---|---|---|
| id | serial int | |
| interval_start_utc | timestamptz | Start of the market interval |
| consumption_mw | numeric | Estonian electricity consumption |
| production_mw | numeric | Total Estonian production |
| renewable_production_mw | numeric | Production from renewable sources |
| solar_production_mw | numeric | Solar production |
| losses_mw | numeric | Grid losses |
| system_balance_mw | numeric | Production minus consumption |
| ac_balance_mw | numeric | Balance on the AC cross-border connections |
| frequency_hz | numeric | Grid frequency |
| renewable_share_pct | numeric | Portion of renewable energy being consumed |
| loaded_at | timestampz | When the row was loaded |

## bronze.elering_system_plan

| Name | Type | Description |
|---|---|---|
| id | serial int | |
| interval_start_utc | timestamptz | Start of the market interval |
| series_type | varschar | Real or plan |
| consumption_mw | numeric | Actual or planned electricity consumption |
| production_mw | numeric | Actual or planned production |
| loaded_at | timestampz | When the row was loaded |
