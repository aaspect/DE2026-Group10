# Contract: Services, Endpoints and Commands

## Services (`compose.yaml`)

| Service | Image | Depends on (healthy) | Host endpoint | Health check | Persistent data |
|---|---|---|---|---|---|
| `postgres` | `postgres:17-alpine` | — | none (internal `postgres:5432`) | `pg_isready` | volume `postgres-data` |
| `clickhouse` | `clickhouse/clickhouse-server:25.8` | — | `http://localhost:${CLICKHOUSE_HTTP_PORT}` | `SELECT 1` via client | volume `clickhouse-data` |
| `airflow` | built from `airflow/Dockerfile` (base `apache/airflow:3.1.x-python3.12`) | `postgres`, `clickhouse` | `http://localhost:${AIRFLOW_PORT}` | `GET /api/v2/monitor/health` | in Postgres; logs in `airflow/logs/` |
| `superset` | built from `superset/Dockerfile` (base `apache/superset:5.0.x`) | `postgres`, `clickhouse` | `http://localhost:${SUPERSET_PORT}` | `GET /health` | in Postgres |

All services use `restart: unless-stopped` and share the default Compose network; they reach each
other by service name.

## Bind mounts

| Host path | Container path | Service | Purpose |
|---|---|---|---|
| `infra/postgres/init/` | `/docker-entrypoint-initdb.d` | postgres | create `airflow`, `superset` databases |
| `infra/clickhouse/init/` | `/docker-entrypoint-initdb.d` | clickhouse | create layers and reader user |
| `airflow/dags/` | `/opt/airflow/dags` | airflow | DAG files |
| `airflow/logs/` | `/opt/airflow/logs` | airflow | task logs (git-ignored) |
| `ingestion/` | `/opt/ingestion` | airflow | weather job code, locations, output folder |
| `dbt/` | `/opt/dbt` | airflow | dbt project and `profiles.yml` |

## Inside the Airflow image

| Path | Content |
|---|---|
| `/opt/venvs/ingestion` | Python 3.12 venv with the weather job's locked runtime dependencies |
| `/opt/venvs/dbt` | venv with `dbt-clickhouse` |

## Make targets (repository root)

| Command | Effect |
|---|---|
| `make up` | build images and start the stack; returns when every service is healthy (`--wait`) or fails |
| `make down` | stop and remove containers; volumes are kept |
| `make reset` | `down` plus delete volumes (all warehouse and metadata data) |
| `make ps` | show service status and health |
| `make logs` | follow logs of all services |
| `make dbt-debug` | run `dbt debug` inside the Airflow container against ClickHouse |
| `make lint` / `make format` | as before, plus `airflow/` and `superset/` Python files |
