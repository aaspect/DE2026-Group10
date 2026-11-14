# Contract: Environment Configuration

All settings come from the root `.env`, which Compose reads automatically (research R1). The root
`.env.example` is committed with the values below; `.env` is git-ignored. Values marked
**required** use `${VAR:?...}` in `compose.yaml`, so a missing value stops startup with a message
naming the variable (spec US1-5).

The placeholder passwords are for local development only and MUST NOT be reused anywhere else.

## Ports (host side)

| Variable | Required | Example value | Used by |
|---|---|---|---|
| `AIRFLOW_PORT` | no | `8080` | Airflow UI |
| `SUPERSET_PORT` | no | `8088` | Superset UI |
| `CLICKHOUSE_HTTP_PORT` | no | `8123` | ClickHouse HTTP interface |

## Metadata database (Postgres)

| Variable | Required | Example value | Meaning |
|---|---|---|---|
| `POSTGRES_USER` | yes | `postgres` | superuser, used only by init and health check |
| `POSTGRES_PASSWORD` | yes | `postgres` | superuser password |
| `AIRFLOW_DB_PASSWORD` | yes | `airflow` | password of role `airflow`, owner of database `airflow` |
| `SUPERSET_DB_PASSWORD` | yes | `superset` | password of role `superset`, owner of database `superset` |

## Warehouse (ClickHouse)

| Variable | Required | Example value | Meaning |
|---|---|---|---|
| `CLICKHOUSE_USER` | yes | `pipeline` | loading/transforming account; owns `bronze`, `silver`, `gold` |
| `CLICKHOUSE_PASSWORD` | yes | `pipeline` | its password |
| `CLICKHOUSE_READER_USER` | yes | `superset_reader` | read-only account used by Superset; `SELECT` on `gold.*` only |
| `CLICKHOUSE_READER_PASSWORD` | yes | `superset_reader` | its password |

## Orchestrator (Airflow)

| Variable | Required | Example value | Meaning |
|---|---|---|---|
| `AIRFLOW_ADMIN_USER` | yes | `admin` | UI login |
| `AIRFLOW_ADMIN_PASSWORD` | yes | `admin` | UI password |
| `AIRFLOW_UID` | no | `50000` | container user; set to `$(id -u)` on Linux so files in `ingestion/output/` and `airflow/logs/` belong to the host user |

Airflow's own settings (`AIRFLOW__DATABASE__SQL_ALCHEMY_CONN`, executor, paused-at-creation,
auth manager) are composed in `compose.yaml` from the variables above and are not part of the
`.env` contract.

## Dashboards (Superset)

| Variable | Required | Example value | Meaning |
|---|---|---|---|
| `SUPERSET_ADMIN_USER` | yes | `admin` | UI login |
| `SUPERSET_ADMIN_PASSWORD` | yes | `admin` | UI password |
| `SUPERSET_SECRET_KEY` | yes | `change-me-local-only` | session signing key; any long random string |

## Transformation (dbt)

`dbt/profiles.yml` reads `CLICKHOUSE_USER` and `CLICKHOUSE_PASSWORD` through `env_var()`, with
host `clickhouse`, port `8123`, and default schema `bronze`. No extra variables.

## Weather job

No `OPEN_METEO_*` variables are set by the stack; the job uses its own defaults and the optional
`ingestion/.env` (feature 001, `specs/001-open-meteo-ingestion/contracts/configuration.md`).
