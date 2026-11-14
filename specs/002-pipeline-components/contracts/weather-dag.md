# Contract: `open_meteo_weather` DAG

File: `airflow/dags/open_meteo_weather.py`. See research R8 for the reasoning.

## DAG properties

| Property | Value |
|---|---|
| `dag_id` | `open_meteo_weather` |
| Schedule | `0 */6 * * *` (UTC) |
| `catchup` | `False` |
| Paused at creation | yes |
| `max_active_runs` | 1 |
| Params | `archive` (bool, default `false`): also fetch observed weather on a manual run |
| `default_args` | `retries=2`, `retry_delay=5 min` |
| Tags | `open_meteo`, `weather` |

## Tasks

```text
fetch_forecast ─┐
                ├─► load_bronze ─► build_silver ─► build_gold
fetch_archive  ─┘
```

| Task | Operator | Real work? | Behaviour |
|---|---|---|---|
| `fetch_forecast` | `BashOperator` | yes | `cd /opt/ingestion && /opt/venvs/ingestion/bin/python -m open_meteo forecast`; every run |
| `fetch_archive` | `BashOperator` | yes | same with `archive` (rolling window); runs on the scheduled 00:00 UTC run or when `params.archive` is true, otherwise skipped |
| `load_bronze` | `EmptyOperator` | **placeholder** | trigger rule `none_failed_min_one_success`; later loads run files into `bronze.open_meteo_weather` |
| `build_silver` | `EmptyOperator` | **placeholder** | later `dbt build --select silver` |
| `build_gold` | `EmptyOperator` | **placeholder** | later `dbt build --select gold marts` |

Each placeholder carries a `doc_md` stating it is a placeholder and which feature replaces it.

## Outcomes

| Situation | Result |
|---|---|
| Manual trigger, default params | `fetch_forecast` succeeds, `fetch_archive` skipped, placeholders succeed; exactly one new forecast file |
| Manual trigger with `archive=true` | both fetch tasks run; two new files |
| Job exits non-zero | task retried twice, then failed; `load_bronze` and later tasks are `upstream_failed` |
