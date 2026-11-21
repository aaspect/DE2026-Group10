# Contract: Run Output File

This file is the hand-over point to the later warehouse-loading integration (FR-021). It is
written once and never changed afterwards (FR-018).

## Location and name

```text
$OPEN_METEO_OUTPUT_DIR/open_meteo_<mode>_<YYYYMMDDTHHMMSSZ>_<run_id>.jsonl
```

- If `$OPEN_METEO_OUTPUT_DIR` is missing, the job creates it, including any missing parent
  folders, before contacting the provider.
- `<mode>` is `forecast` or `archive`.
- The timestamp is the run's `retrieved_at` in UTC.
- `<run_id>` is the full UUID4.
- Files whose names start with `.` and end in `.tmp` are in-progress or abandoned writes, and
  loaders MUST ignore them.

## Format

- JSON Lines: UTF-8 without BOM. Each line is one JSON object, which is one record, and ends with
  `\n`. There is no surrounding array and no header line.
- Every object has all 16 keys below, in this order. A missing value is JSON `null`, never an
  omitted key.
- Timestamps are JSON strings in ISO 8601 UTC with a `Z` suffix, for example
  `"2026-11-14T00:00:00Z"`.
- Numbers are JSON numbers, written as the provider delivered them with no rounding. The
  provider's integers, such as `cloud_cover: 97`, stay integers.
- Non-ASCII characters are written as-is (`ensure_ascii=False`). Objects are written compactly,
  with no indentation.
- There is one line per location per hour. Lines are sorted by `location_id` in configuration
  order, then by `hour_utc`.

## Fields

| # | Key | JSON type | `null` allowed | ClickHouse type (suggested) |
|---|---|---|---|---|
| 1 | `location_id` | string | no | `String` |
| 2 | `hour_utc` | string (timestamp) | no | `DateTime('UTC')` |
| 3 | `source_type` | string: `forecast` \| `archive` | no | `LowCardinality(String)` |
| 4 | `forecast_version_at` | string (timestamp) | yes (always for archive) | `Nullable(DateTime('UTC'))` |
| 5 | `temperature_2m_c` | number | yes | `Nullable(Float64)` |
| 6 | `wind_speed_10m_ms` | number | yes | `Nullable(Float64)` |
| 7 | `wind_direction_10m_deg` | number | yes | `Nullable(Float64)` |
| 8 | `shortwave_radiation_wm2` | number | yes | `Nullable(Float64)` |
| 9 | `direct_radiation_wm2` | number | yes | `Nullable(Float64)` |
| 10 | `cloud_cover_pct` | number | yes | `Nullable(Float64)` |
| 11 | `precipitation_mm` | number | yes | `Nullable(Float64)` |
| 12 | `grid_latitude` | number | no | `Float64` |
| 13 | `grid_longitude` | number | no | `Float64` |
| 14 | `grid_elevation_m` | number | no | `Float64` |
| 15 | `run_id` | string (UUID) | no | `UUID` |
| 16 | `loaded_at` | string (timestamp) | no | `DateTime('UTC')` |

The ClickHouse types are only a guide for the warehouse-loading integration, which can load the
file with `FORMAT JSONEachRow`. This feature does not change any DDL.

For radiation and precipitation, `hour_utc` refers to the *preceding* hour, which is the
provider's convention. Alignment to market intervals happens in the silver layer.

## Example (one line, wrapped here for readability)

```json
{"location_id":"tallinn","hour_utc":"2026-11-14T00:00:00Z","source_type":"forecast",
 "forecast_version_at":"2026-11-14T09:30:12Z","temperature_2m_c":2.8,"wind_speed_10m_ms":3.0,
 "wind_direction_10m_deg":238,"shortwave_radiation_wm2":0.0,"direct_radiation_wm2":0.0,
 "cloud_cover_pct":97,"precipitation_mm":2.3,"grid_latitude":59.439518,"grid_longitude":24.75708,
 "grid_elevation_m":10.0,"run_id":"3f2c9a8e-5b1d-4c47-9e0a-2d6f8b7c1a90",
 "loaded_at":"2026-11-14T09:30:15Z"}
```

## Guarantees

- Each file contains exactly `locations × expected_hours` lines (SC-002), with no duplicate
  (`location_id`, `hour_utc`) pair.
- Every line in a file has the same `run_id`, `source_type` and `loaded_at`. Forecast files also
  share one `forecast_version_at`.
- A file exists only if the run succeeded (SC-004).
