# Contract: `elering_prices` DAG & Multi-DAG Build Serialisation

Orchestration contract for `airflow/dags/elering_prices.py`, plus the shared concurrency update to
`airflow/dags/open_meteo_weather.py` and `airflow/entrypoint.sh`.

## `elering_prices` DAG Properties

| Property | Value |
|---|---|
| `dag_id` | `elering_prices` |
| `schedule` | `CronTriggerTimetable("30 14 * * *", timezone="Europe/Tallinn")` (daily 14:30 Tallinn time, DST-aware) |
| `start_date` | `datetime(2026, 11, 1, tzinfo=UTC)` |
| `catchup` | `False` |
| `is_paused_upon_creation` | `True` |
| `max_active_runs` | `1` |
| `params` | `start_date` (nullable string, `YYYY-MM-DD`, default `None`), `end_date` (nullable string, `YYYY-MM-DD`, default `None`) |
| `tags` | `["elering", "prices"]` |

## Task Graph

```text
ingest_prices ─┬─► build_silver ─► build_gold
               └─► check_bronze_freshness   (all_done; leaf, never blocks builds)
```

`DBT = "env -u PYTHONPATH /opt/venvs/dbt/bin/dbt"`, `PROJECT = "--project-dir /opt/dbt"`

| Task | Command / Behaviour | Trigger Rule | Retries | Retry Delay | Pool |
|---|---|---|---|---|---|
| `ingest_prices` | Passes `params.start_date` and `params.end_date` via env vars (`append_env=True`). Runs `python -m elering_prices daily` when both are empty, or `python -m elering_prices backfill --start-date ... --end-date ...` when either is set. | default | `6` | `1 hour` | default |
| `build_silver` | `$DBT build $PROJECT --select silver` | default | `0` | — | `dbt_build` |
| `build_gold` | `$DBT build $PROJECT --select gold` | default | `0` | — | `dbt_build` |
| `check_bronze_freshness` | `$DBT source freshness $PROJECT --target-path /tmp/dbt-freshness-elering --select source:bronze.elering_prices` | `all_done` | `0` | — | default |

## Concurrency Serialisation Across Pipelines (FR-031)

1. **`airflow/entrypoint.sh`** runs idempotently on every container start before `exec airflow standalone`:
   ```bash
   airflow db migrate
   airflow pools set dbt_build 1 "Serialises dbt builds across pipelines so shared tables do not clash."
   ```
2. **Both DAGs** (`open_meteo_weather` and `elering_prices`) assign `pool="dbt_build"` to their
   `build_silver` and `build_gold` tasks so at most one `dbt build` runs at any moment across the
   entire stack — protecting both ClickHouse table swaps (e.g. shared `gold.dim_interval`) and
   `/opt/dbt/target/` artifacts.
3. **Both DAGs** pass distinct `--target-path` values (`/tmp/dbt-freshness-open-meteo` and
   `/tmp/dbt-freshness-elering`) to `check_bronze_freshness`, keeping freshness completely
   non-blocking and free of `/opt/dbt/target/` contention.

## Outcomes

| Situation | Result |
|---|---|
| Manual trigger, default params (after D+1 publication) | `ingest_prices` ✔ (D+1), `build_silver` ✔, `build_gold` ✔, `check_bronze_freshness` ✔ |
| Manual trigger with `{"start_date": "2025-09-29", "end_date": "2025-10-02"}` | `ingest_prices` ✔ (backfill across Oct 2025 MTU switch), `build_silver` ✔, `build_gold` ✔, `check_bronze_freshness` ✔ |
| Scheduled run before D+1 prices are published | `ingest_prices` fails (incomplete slots), retries hourly up to 6 times; `build_silver` & `build_gold` wait; if all retries fail, downstream builds are `upstream_failed` while `check_bronze_freshness` still runs |
| Bronze prices older than 26 hours | `check_bronze_freshness` logs `WARN` and exits `0` (task succeeds) |
| Silver or gold dbt test fails | Failing build task is not retried (`retries=0`); downstream models/tasks do not run and retain last good data |
| Concurrent triggers of `open_meteo_weather` and `elering_prices` | Both ingests run concurrently; their `build_silver`/`build_gold` tasks queue cleanly through `pool="dbt_build"` with zero conflicts |
