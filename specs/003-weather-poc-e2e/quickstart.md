# Quickstart: Validate the Weather POC End to End

These scenarios prove the feature works. Run them from the repository root, with Docker running
and `.env` copied from `.env.example`. The SQL below uses `chq`, a shorthand for a query run as
the pipeline account:

```bash
chq() { docker compose exec -T clickhouse clickhouse-client --user pipeline --password pipeline --query "$1"; }
```

Contracts referenced: [bronze table](contracts/bronze-table.md), [job CLI](contracts/ingestion-cli.md),
[DAG](contracts/weather-dag.md), [mart](contracts/mart-past-weather.md),
[dashboard](contracts/dashboard.md). Column definitions are in [data-model.md](data-model.md).

## 0. Offline checks

```bash
make lint && make test
```

Expected: ruff is clean, and all pytest tests pass offline, including `test_bronze.py` and
`test_locations_seed.py`. In CI, the `dbt` job runs the build against the fixture
`dbt/ci/bronze_open_meteo_weather.jsonl`, and all models and tests pass.

## 1. Fresh stack, one manual run → dashboard (SC-001, US3, US4)

```bash
make reset && make up
```

1. Open Airflow (`http://localhost:8080`, admin/admin). Un-pause `open_meteo_weather` and trigger
   it with `archive = true`. Start a timer.
2. Expected: `ingest_forecast`, `ingest_archive`, `build_silver` and `build_gold` all succeed, in
   that order, and `check_bronze_freshness` succeeds without a warning.
3. Open `http://localhost:8088/superset/dashboard/past-weather/` (admin/admin). Nobody has
   created anything in the UI.
4. Expected: the charts show the last 7 days for all 5 locations, less than 10 minutes after the
   trigger.

## 2. Bronze load (US1, FR-001–FR-007)

Before any run, the table already exists and is empty (created by the init script, FR-006):

```bash
chq "SELECT count() FROM bronze.open_meteo_weather"   # 0 on a fresh stack, before step 1
```

After step 1:

```bash
chq "SELECT source_type, run_id, count() FROM bronze.open_meteo_weather GROUP BY ALL ORDER BY ALL"
```

Expected: one archive run with 840 rows, and two forecast runs with 360 rows each (5 locations
× 72 h): un-pausing the DAG also starts the most recent scheduled run, which ingests a forecast.
`ls ingestion/output/open_meteo/` shows no new file.

Check that each bronze document holds every key and value of its run-file line (FR-003). Run the
job once with both destinations, then compare values per key. The native `JSON` column does not
keep the original text or `null` paths, so `null` values are dropped from the file side before
comparing:

```bash
docker compose exec airflow bash -c 'cd /opt/ingestion && /opt/venvs/ingestion/bin/python -m open_meteo archive --destination both'
# take run_id from the report, then:
chq "SELECT record FROM bronze.open_meteo_weather WHERE run_id = '<run_id>' FORMAT JSONEachRow" > /tmp/bronze.jsonl
python3 - /tmp/bronze.jsonl ingestion/output/open_meteo/open_meteo_archive_*_<run_id>.jsonl <<'PY'
import json, sys
key = lambda r: (r["location_id"], r["hour_utc"])
bronze = {key(r): r for r in (json.loads(line)["record"] for line in open(sys.argv[1]))}
file = [{k: v for k, v in json.loads(line).items() if v is not None} for line in open(sys.argv[2])]
assert len(bronze) == len(file) and all(bronze[key(r)] == r for r in file)
print("identical values")
PY
```

Expected: the job's report shows `destination: both` and a file path, and the comparison prints
`identical values`. The run file itself is unchanged from feature 001 (SC-007).

File mode still works without the stack: `cd ingestion && uv run python -m open_meteo forecast
--destination file` writes a file and needs no ClickHouse credentials.

## 3. Failed insert leaves nothing (FR-005, SC-005)

```bash
docker compose exec -e CLICKHOUSE_PASSWORD=wrong airflow bash -c 'cd /opt/ingestion && /opt/venvs/ingestion/bin/python -m open_meteo forecast; echo exit=$?'
```

Expected: `outcome: failure` with an insert reason that does not show the password, and
`exit=1`. The row count in bronze is unchanged.

## 4. Silver, gold, mart rules (US2, SC-002, SC-004)

Trigger the DAG again with `archive = true` (overlapping window), then check:

```bash
chq "SELECT count(), uniqExact(location_key, interval_start_utc) FROM gold.mart_past_weather"
chq "SELECT count() FROM (SELECT location_key, interval_start_utc, source_type, forecast_issued_utc FROM gold.fact_weather GROUP BY ALL HAVING count() > 1)"
chq "SELECT uniqExact(forecast_issued_utc) FROM silver.open_meteo_weather WHERE source_type = 'forecast'"
```

Expected: the mart has 840 rows, all unique, even though bronze now holds two archive runs. The
duplicate query returns `0`. Silver holds two or more forecast versions. The `build_gold` log
shows `PASS` for every test.

Bad data is not stopped by a failing test. Insert one bronze row with `cloud_cover_pct` 150, one
whose document has no `hour_utc`, and one for location `riga`, then run `build_silver` and
`build_gold` (clear both tasks in Airflow). Expected: both tasks succeed. In silver, the 150 % row
is present with `cloud_cover_pct` `NULL`. The row without `hour_utc` is missing from silver, and
the `riga` row is missing from `fact_weather`. The same scenarios run automatically in the CI
`dbt` job.

## 5. Values match bronze (SC-003)

```bash
chq "SELECT CAST(record.temperature_2m_c, 'Nullable(Float64)') FROM bronze.open_meteo_weather WHERE source_type='archive' AND CAST(record.location_id, 'String')='tartu' AND CAST(record.hour_utc, 'String')='<an hour, e.g. 2026-11-10T12:00:00Z>' ORDER BY loaded_at DESC, run_id DESC LIMIT 1"
chq "SELECT temperature_c FROM gold.mart_past_weather WHERE location_key='tartu' AND interval_start_utc='<same hour>'"
```

Expected: the same value. In the dashboard, with only Tartu selected, the temperature chart
tooltip for that hour shows the same value.

## 6. Rebuild is idempotent (FR-019)

```bash
chq "SELECT sum(cityHash64(toString(tuple(*)))) FROM gold.fact_weather"   # note value
# clear build_silver + build_gold in Airflow (no new ingest), or run `make dbt-build`
chq "SELECT sum(cityHash64(toString(tuple(*)))) FROM gold.fact_weather"   # same value
```

The row is hashed as text because `cityHash64(*)` is `NULL` for any row with a `NULL` column,
which is every archive row (no forecast version). Repeat for `silver.open_meteo_weather` and
`gold.mart_past_weather`. Run it for the dimensions too, with `loaded_at` excluded
(`tuple(* EXCEPT loaded_at)`).

## 7. Failure stops downstream (FR-017, FR-022)

Temporarily break a gold test, for example by setting the grain test of `fact_weather` to
`location_key` only, then trigger the DAG. Expected: `build_gold` fails, the log shows the mart
`SKIP`, and the mart's `max(loaded_at)` is unchanged. Revert the change afterwards.

Stop ClickHouse (`docker compose stop clickhouse`) and trigger the DAG. Expected: the ingest tasks
retry twice and then fail, the build tasks are `upstream_failed`, and `check_bronze_freshness`
still runs (it fails here only because ClickHouse is down). Run `docker compose start clickhouse`
afterwards.

## 8. Dashboard behaviour (US4)

- With the Location filter set to one location, every chart and tile changes.
- With the time range set to an earlier period, charts show "No results" or older data, without
  errors.
- `make down && make up`: the dashboard is still there, only once (Dashboards list), and the data
  is still there.
- Dashboard ⋯ → "Set auto-refresh interval" shows 1 hour.
- In Superset, Settings → Database connections lists `ClickHouse warehouse`. Running
  `SELECT count() FROM silver.open_meteo_weather` in SQL Lab through it fails with an access
  error (the account reads gold only).

## 9. Freshness warning (FR-008)

With bronze older than 6 h (for example, after the pipeline was paused overnight), clear only
`check_bronze_freshness` of the last run. Expected: its log has a `WARN` freshness line for
`source:bronze.open_meteo_weather`, and the task succeeds. The same warning appears in a run whose
ingest tasks fail while bronze is stale, because the check runs with trigger rule `all_done`.

## 10. Filter speed for one year (SC-006)

Backfill one year of observed weather, rebuild, and time a filter change:

```bash
docker compose exec airflow bash -c 'cd /opt/ingestion && /opt/venvs/ingestion/bin/python -m open_meteo archive --start-date <today − 365 d> --end-date <today − 1 d>'
make dbt-build
chq "SELECT count() FROM gold.mart_past_weather"   # about 44 k rows
```

In the dashboard, set the time range to "Last year", then change the Location filter. Expected:
every chart has updated in under 3 seconds (browser network tab, or the chart query times in
Superset's "View query" panel).
