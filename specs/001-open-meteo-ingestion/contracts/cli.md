# Contract: Command-Line Interface

The job is a Python module in the `ingestion/` project (FR-001):

```text
uv run python -m open_meteo forecast
uv run python -m open_meteo archive [--start-date YYYY-MM-DD --end-date YYYY-MM-DD]
```

These commands are shown as run from `ingestion/`. From another folder, add
`--project <path-to-ingestion>` after `uv run`. The files the job reads and writes are the same
either way, because paths are resolved against `ingestion/` ([configuration.md](configuration.md)).

## Arguments

| Argument | Modes | Required | Meaning |
|---|---|---|---|
| `forecast` \| `archive` | — | yes | positional; the run mode |
| `--start-date` | archive | together with `--end-date` | first UTC day of a backfill (inclusive) |
| `--end-date` | archive | together with `--start-date` | last UTC day of a backfill (inclusive); must not be after today (UTC) |

Without dates, archive mode captures the rolling window (`OPEN_METEO_ARCHIVE_DAYS` full days
before today). All other settings come from the environment ([configuration.md](configuration.md)).

## Exit codes (FR-017)

| Code | Meaning | Output file |
|---|---|---|
| `0` | success: all records stored | exactly one new file |
| `1` | run failure: provider, validation or file-writing error | none |
| `2` | refused to start: invalid arguments, dates, settings or locations | none; no provider contact |

## Run report (FR-019)

Logs go to stderr. A single report block is printed to stdout at the end of every run that got
past argument parsing, as `key: value` lines:

```text
run_id: 3f2c9a8e-5b1d-4c47-9e0a-2d6f8b7c1a90
mode: forecast
period: 2026-11-14..2026-11-16
locations: 5
records: 360
output_file: output/open_meteo/open_meteo_forecast_20261114T093012Z_3f2c9a8e-5b1d-4c47-9e0a-2d6f8b7c1a90.jsonl
outcome: success
```

On failure:

```text
run_id: 7a1d...
mode: archive
period: 2026-11-07..2026-11-13
locations: 5
records: 0
output_file: none
outcome: failure
failure: location=narva reason=HTTP 503 after 3 attempts
```

Rules:

- `failure` is present only when `outcome` is `failure`.
- `location=` is omitted when the failure has no specific location, for example a file-writing
  error or a configuration error.
- For exit code `2`, `run_id` is still generated and reported. `period` may be `none` if the
  dates could not be parsed.
