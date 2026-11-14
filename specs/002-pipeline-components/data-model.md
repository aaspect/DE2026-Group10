# Data Model: Local Data Pipeline Components

This feature creates no tables. Its "data model" is the set of stores, accounts and layers the
stack provisions, and the pipeline definition. Table schemas arrive with the loading and
modelling features.

## Warehouse layers (ClickHouse databases)

| Database | Written by | Read by | Created content in this feature |
|---|---|---|---|
| `bronze` | ingestion loaders (pipeline account) | dbt | empty |
| `silver` | dbt (pipeline account) | dbt | empty |
| `gold` | dbt (pipeline account); holds facts, dimensions and marts | dbt, Superset (reader account) | empty |

Rules (constitution V): layers are not skipped; bronze is append-only; all timestamps in UTC.

Planned bronze table name declared as a dbt source: `bronze.open_meteo_weather` (one row per
location per hour per run, columns from `specs/001-open-meteo-ingestion/contracts/output-file.md`).
Its DDL is part of the loading feature, not this one.

Removed: database `staging` and tables `raw_weather`, `raw_prices`, `raw_consumption`,
`raw_production` from `infra/clickhouse/init/02_bronze_tables.sql` (FR-009).

## Warehouse accounts

| Account | Source of credentials | Privileges | Validation |
|---|---|---|---|
| pipeline (`CLICKHOUSE_USER`) | `.env` | all on `bronze`, `silver`, `gold`; access management | dbt debug succeeds |
| reader (`CLICKHOUSE_READER_USER`) | `.env` | `SELECT ON gold.*` only | `INSERT`/`CREATE` anywhere and `SELECT` on `bronze`/`silver` are refused |

## Metadata databases (Postgres)

| Database | Owner role | Used by |
|---|---|---|
| `airflow` | `airflow` | Airflow metadata (DAG runs, task instances, connections) |
| `superset` | `superset` | Superset metadata (users, data sources, later charts) |

## Superset data source

| Field | Value |
|---|---|
| Name | `ClickHouse warehouse` |
| URI | `clickhousedb://<reader>:<password>@clickhouse:8123/gold` |
| Created by | `superset/bootstrap.sh` on every start (create or update) |

## Pipeline: `open_meteo_weather`

Defined in [contracts/weather-dag.md](contracts/weather-dag.md). State transitions per run follow
Airflow's standard task states; the ones that matter here:

```text
fetch_*      : queued → running → success | up_for_retry → … → failed
fetch_archive: skipped (when not the 00:00 UTC scheduled run and params.archive is false)
placeholders : success (all fetches succeeded or skipped) | upstream_failed (any fetch failed)
```

## dbt project: `energy_analytics`

| Item | Value |
|---|---|
| Profile | `energy_analytics`, target `local`, `type: clickhouse`, host `clickhouse`, port 8123, schema `bronze` |
| Model folders | `models/silver/` → database `silver`; `models/gold/` and `models/marts/` → database `gold` |
| Sources | `bronze.open_meteo_weather` (no columns yet) |
| Macros | `generate_schema_name` override (use `+schema` as database name verbatim) |
