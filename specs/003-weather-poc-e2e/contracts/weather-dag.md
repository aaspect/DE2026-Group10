# Contract: `open_meteo_weather` DAG (all steps real)

This contract supersedes [feature 002's DAG contract](../../002-pipeline-components/contracts/weather-dag.md).
File: `airflow/dags/open_meteo_weather.py`.

## DAG properties (unchanged)

| Property | Value |
|---|---|
| `dag_id` | `open_meteo_weather` |
| Schedule | `0 */6 * * *` (UTC) |
| `catchup` | `False` |
| Paused at creation | yes |
| `max_active_runs` | 1 (a second trigger waits, it does not overlap) |
| Params | `archive` (bool, default `false`) |
| `default_args` | `retries=2`, `retry_delay=5 min` |
| Tags | `open_meteo`, `weather` |

## Tasks

```text
ingest_forecast ─┐
                 ├─► build_silver ─► build_gold
ingest_archive  ─┤
                 └─► check_bronze_freshness      (all_done; a leaf, nothing waits for it)
```

`DBT = /opt/venvs/dbt/bin/dbt`, `PROJECT = --project-dir /opt/dbt`

| Task | Command | Trigger rule | Retries |
|---|---|---|---|
| `ingest_forecast` | `cd /opt/ingestion && /opt/venvs/ingestion/bin/python -m open_meteo forecast` | default | 2 |
| `ingest_archive` | same with `archive`. It runs on the scheduled 00:00 UTC run or when `params.archive` is true; otherwise it exits 99 and is skipped. | default | 2 |
| `build_silver` | `$DBT build $PROJECT --select silver` | `none_failed_min_one_success` | 0 |
| `build_gold` | `$DBT build $PROJECT --select gold marts` | default | 0 |
| `check_bronze_freshness` | `$DBT source freshness $PROJECT --select source:bronze.open_meteo_weather` | `all_done` | 0 |

The ingest tasks use the job's default destination (`warehouse`). The Airflow service gets
`CLICKHOUSE_URL=http://clickhouse:8123`. It already has `CLICKHOUSE_USER` and
`CLICKHOUSE_PASSWORD` (the pipeline account). The `load_bronze` placeholder is removed.

## Outcomes

| Situation | Result |
|---|---|
| Manual trigger, default params | `ingest_forecast` ✔, `ingest_archive` skipped, `build_silver` ✔, `build_gold` ✔, `check_bronze_freshness` ✔ |
| Manual trigger, `archive=true`, empty bronze | all five ✔; the mart has 840 rows |
| An ingest task fails after its retries | it is marked failed; `build_silver` and `build_gold` are `upstream_failed`; `check_bronze_freshness` still runs and warns if the newest load is older than 6 h; the DAG run is failed |
| A silver model or test fails | `build_silver` failed, `build_gold` `upstream_failed`; gold and the mart keep their last good data |
| A gold test fails | `build_gold` failed; dbt skips the models downstream of the failing test (e.g. the mart) |
| Bronze older than 6 h at `check_bronze_freshness` | the `WARN` freshness line is in the task log; the task still succeeds |
