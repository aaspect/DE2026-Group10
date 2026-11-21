# Quickstart: Open-Meteo Weather Ingestion Job

This guide checks the feature end to end on a team member's machine. Interfaces are defined in
[contracts/](contracts/), and record fields in [data-model.md](data-model.md).

## Prerequisites

- `uv` is installed. It provides Python 3.12 automatically.
- Internet access is needed for every scenario except 6, which runs offline.

```bash
cd ingestion
uv sync                   # installs python-dotenv and the dev tools (pytest, ruff)
cp .env.example .env      # optional: local overrides, git-ignored
```

The defaults work without a `.env` file.

## 1. Forecast snapshot (User Story 1, SC-001)

```bash
time uv run python -m open_meteo forecast; echo "exit=$?"
```

Expected:

- `exit=0` in under 1 minute.
- The report shows `mode: forecast`, `period: <today>..<today+2>`, `locations: 5`,
  `records: 360` and `outcome: success`.
- The default output folder `output/open_meteo/` is created if it does not exist yet.
- There is one new file: `output/open_meteo/open_meteo_forecast_*.jsonl`, with one JSON
  object per line (`head -n 1 <file> | jq .` shows one record).
- Every record has `"source_type": "forecast"`. All records share one `run_id`, one `forecast_version_at`
  and one `loaded_at`.

Run the command again. A second forecast file appears, and the first one is unchanged (compare
`ls -l` before and after).

## 2. Default archive window (User Story 2, SC-002)

```bash
uv run python -m open_meteo archive
```

Expected:

- `period: <today-7>..<today-1>` and `records: 840`.
- `forecast_version_at` is `null` in every record.
- Check for duplicate location-hour pairs. This prints nothing when there are none:

  ```bash
  jq -r '[.location_id, .hour_utc] | @tsv' output/open_meteo/open_meteo_archive_*.jsonl | sort | uniq -d
  ```

## 3. Backfill (User Story 3, SC-003)

```bash
uv run python -m open_meteo archive --start-date 2026-10-01 --end-date 2026-10-31   # 5 × 31 × 24 = 3720
time uv run python -m open_meteo archive --start-date 2025-11-01 --end-date 2026-10-31   # 1 year, under 5 min
```

## 4. Refused inputs (FR-005, FR-007)

Each command below must exit with code `2`. The message explains the problem, and no file is
written:

```bash
uv run python -m open_meteo archive --start-date 2026-11-10 --end-date 2026-11-01
uv run python -m open_meteo archive --start-date 2026-13-01 --end-date 2026-13-02
uv run python -m open_meteo archive --start-date 2026-11-01 --end-date 2099-01-01
OPEN_METEO_LOCATIONS_FILE=/nonexistent.toml uv run python -m open_meteo forecast
```

## 5. All-or-nothing on failure (SC-004)

```bash
OPEN_METEO_ARCHIVE_URL=https://archive-api.open-meteo.com/v1/does-not-exist \
OPEN_METEO_RETRY_BASE_SECONDS=0 uv run python -m open_meteo archive; echo "exit=$?"
ls -a output/open_meteo
```

Expected:

- `exit=1`.
- The report has `outcome: failure` and a `failure:` line naming the first location and the
  HTTP reason.
- `output/open_meteo` has no new `.jsonl` file and no `.tmp` file.

Point the job at a folder that does not exist yet, for example
`OPEN_METEO_OUTPUT_DIR=/tmp/om-test/nested`, and check that it is created and the run succeeds.
Then point it at a location that cannot be created, for example `OPEN_METEO_OUTPUT_DIR=/om-test`.
Expect `exit=1` with a clear message, before any provider request.

## 6. Offline automated checks (FR-022, SC-007)

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest
```

Expected: no lint findings, and all tests pass in under 10 seconds with the network disabled.

## 7. Forecast against observed comparison (SC-006)

After two forecast runs at different times, and one archive run that covers a day both
forecasts included (for example `archive --start-date <today> --end-date <today>`), open the three files (for example in DuckDB or pandas). For one
`location_id` and `hour_utc`, there should be two forecast rows with different
`forecast_version_at` values and one archive row.

## 8. `.env` file and folder-independent paths (FR-008)

```bash
echo 'OPEN_METEO_FORECAST_DAYS=2' > .env
uv run python -m open_meteo forecast                                   # report: records: 240
OPEN_METEO_FORECAST_DAYS=1 uv run python -m open_meteo forecast        # environment wins: records: 120
rm .env

cd ..                                                                  # repo root
uv run --project ingestion python -m open_meteo forecast
ls output 2>/dev/null || echo "no output/ at repo root"                # file is in ingestion/output/open_meteo/
```
