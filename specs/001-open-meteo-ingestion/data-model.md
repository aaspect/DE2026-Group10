# Data Model: Open-Meteo Weather Ingestion Job

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-11-14

All entities are in-memory Python types (frozen dataclasses). Only `RawWeatherRecord` is
persisted, as lines (JSON objects) of the run output file ([contracts/output-file.md](contracts/output-file.md)).
All times are timezone-aware UTC `datetime` objects. All dates are UTC calendar dates.

## Location

Loaded from the locations file ([contracts/configuration.md](contracts/configuration.md)).

| Field | Type | Rules |
|---|---|---|
| `location_id` | str | required; non-empty; `[a-z0-9_]+`; unique across the file |
| `name` | str | required; non-empty |
| `latitude` | float | required; −90 ≤ value ≤ 90 |
| `longitude` | float | required; −180 ≤ value ≤ 180 |
| `bidding_zone` | str | required; non-empty (for example `EE`) |
| `role` | str | required; non-empty (for example `demand`, `wind`, `solar`) |

Validation (FR-007):

- An empty list is an error.
- Every error message names the entry, using its `id` or, if the `id` is missing, its 1-based
  position.
- Configuration errors stop the job before any provider call.

Downstream, this entity becomes `dim_location`.

## Settings

Read once at start-up from the process environment, then from the optional `ingestion/.env`,
then from defaults, in that order of priority. Relative paths are resolved against the
`ingestion/` project directory. Names and defaults are in
[contracts/configuration.md](contracts/configuration.md).

| Field | Type | Rules |
|---|---|---|
| `forecast_url` | str | non-empty URL |
| `archive_url` | str | non-empty URL |
| `forecast_days` | int | 1 ≤ value ≤ 16 (provider maximum) |
| `archive_days` | int | ≥ 1 |
| `max_attempts` | int | ≥ 1 |
| `retry_base_seconds` | float | ≥ 0 |
| `timeout_seconds` | float | > 0 |
| `output_dir` | Path | created with parents if missing, then must be writable; both are checked before any provider call |
| `locations_file` | Path | must exist and be readable |

## Period

The UTC date range one run captures. It is derived from mode, today's date (UTC) and optional
CLI dates.

| Field | Type | Rules |
|---|---|---|
| `start_date` | date | ≤ `end_date` |
| `end_date` | date | inclusive |
| `expected_hours` | int (derived) | `(end_date − start_date + 1 day) × 24` |

How the period is resolved (FR-003 to FR-005):

| Mode | Input | start_date | end_date |
|---|---|---|---|
| forecast | none | today | today + `forecast_days` − 1 |
| archive | none | today − `archive_days` | today − 1 |
| archive | `--start-date S --end-date E` | S | E |

Rejected inputs (FR-005). All are checked before any provider call:

- a malformed date
- only one of the two dates given
- `S > E`
- `E > today`
- dates given in forecast mode

## IngestionRun

One execution of the job. It is not persisted. Its fields appear in the run report
([contracts/cli.md](contracts/cli.md)).

| Field | Type | Notes |
|---|---|---|
| `run_id` | str | UUID4, generated when the run starts |
| `mode` | `"forecast"` \| `"archive"` | |
| `period` | Period | |
| `retrieved_at` | datetime | UTC time the run starts, truncated to seconds |
| `location_count` | int | |
| `record_count` | int | 0 until the file is written |
| `output_file` | Path \| None | set only on success |
| `outcome` | `"success"` \| `"failure"` | |
| `failure` | str \| None | on failure: the location (if any) and the reason |

State transitions:

```text
started ──config/period invalid──▶ failure (exit 2, nothing fetched)
   │
   ▼
preparing output dir (mkdir -p) ──cannot create / not writable──▶ failure (exit 1, nothing fetched)
   │
   ▼
fetching (per location) ──fetch/validation error──▶ failure (exit 1, no file)
   │
   ▼
writing (temp file) ──OS error──▶ failure (exit 1, temp file removed)
   │
   ▼
success (exit 0, final file exists)
```

## RawWeatherRecord

One location-hour from one run. Each one is one JSON line of the output file.

| Field | Type | Nullable | Source |
|---|---|---|---|
| `location_id` | str | no | Location |
| `hour_utc` | datetime | no | `hourly.time[i]`, interpreted as UTC |
| `source_type` | `"forecast"` \| `"archive"` | no | mode |
| `forecast_version_at` | datetime | yes (always null for archive) | run `retrieved_at` |
| `temperature_2m_c` | float | yes | `hourly.temperature_2m[i]` |
| `wind_speed_10m_ms` | float | yes | `hourly.wind_speed_10m[i]` |
| `wind_direction_10m_deg` | float | yes | `hourly.wind_direction_10m[i]` |
| `shortwave_radiation_wm2` | float | yes | `hourly.shortwave_radiation[i]` |
| `direct_radiation_wm2` | float | yes | `hourly.direct_radiation[i]` |
| `cloud_cover_pct` | float | yes | `hourly.cloud_cover[i]` |
| `precipitation_mm` | float | yes | `hourly.precipitation[i]` |
| `grid_latitude` | float | no | response `latitude` |
| `grid_longitude` | float | no | response `longitude` |
| `grid_elevation_m` | float | no | response `elevation` |
| `run_id` | str | no | IngestionRun |
| `loaded_at` | datetime | no | one UTC timestamp per run, taken when records are built |

Rules:

- Values are copied exactly as delivered (FR-013). The job does no rounding, filling,
  filtering or range checks. JSON `null` stays null.
- Natural key: (`location_id`, `hour_utc`, `source_type`, `forecast_version_at`). It is unique
  within a run. Across runs, duplicates are expected and told apart by `run_id` and `loaded_at`
  (FR-018).
- Lead time is `hour_utc − forecast_version_at`. It is derived downstream and can be negative
  for hours earlier in the current day.

Relationships:

```text
Location 1 ──< RawWeatherRecord >── 1 IngestionRun
```

## Validation of a provider response (FR-014)

These checks run on each per-location response before any records are built. A failure raises
`InvalidResponseError`, which is not retried:

1. The response is a JSON object, and `error` is not `true`.
2. `latitude`, `longitude` and `elevation` are present.
3. `hourly` is an object containing `time` and all 7 variables.
4. Every `hourly` series has a length equal to `Period.expected_hours`.
5. `hourly.time[0]` equals `start_date` at 00:00.
