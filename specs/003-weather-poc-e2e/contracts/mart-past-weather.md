# Contract: `gold.mart_past_weather`

The only table the dashboard reads (FR-026). Changing or removing a column here is a breaking
change for the Superset dataset in `superset/dashboards/past_weather/`.

## Grain

One row per `location_key` per observed hour (`interval_start_utc`). Only archive data appears;
forecasts never do.

## Columns

| Column | Type | Nullable | Meaning |
|---|---|---|---|
| `location_key` | `String` | no | configured location id |
| `location_name` | `String` | no | display name (filter and series label) |
| `location_role` | `LowCardinality(String)` | no | `demand` / `solar` / `wind` |
| `zone_code` | `LowCardinality(String)` | no | bidding zone |
| `interval_start_utc` | `DateTime('UTC')` | no | start of the hour; the dashboard's time column |
| `interval_start_local` | `DateTime('Europe/Tallinn')` | no | the same moment in Tallinn time |
| `local_date` | `Date` | no | Tallinn date |
| `local_hour` | `UInt8` | no | Tallinn hour 0–23 |
| `day_of_week` | `UInt8` | no | 1 = Monday |
| `is_weekend` | `Bool` | no | |
| `temperature_c` | `Float64` | yes | air temperature at 2 m, °C |
| `wind_speed_ms` | `Float64` | yes | wind speed at 10 m, m/s |
| `wind_direction_deg` | `Float64` | yes | 0–360° |
| `shortwave_radiation_wm2` | `Float64` | yes | global horizontal radiation, W/m², mean over the preceding hour |
| `direct_radiation_wm2` | `Float64` | yes | direct radiation, W/m², mean over the preceding hour |
| `cloud_cover_pct` | `Float64` | yes | 0–100 % |
| `precipitation_mm` | `Float64` | yes | sum over the preceding hour, mm |
| `loaded_at` | `DateTime('UTC')` | no | when the shown value was loaded into bronze |

`NULL` means that the provider gave no value or that silver removed an impossible value.

## Guarantees

- The grain is unique, and both key columns are not null (dbt tests).
- Each value equals the latest loaded archive value in bronze for that location and hour, except
  values silver removed (SC-003).
- The table is replaced whole on each successful build and never shows a half-built state.
- Sort key `(location_key, interval_start_utc)`.
