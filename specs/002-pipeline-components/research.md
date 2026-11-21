# Research: Local Data Pipeline Components

Each decision lists what was chosen, why, and what else was considered. Image and package
versions are pinned to exact tags at implementation time; the versions named here are the
release lines to pin from.

## R1. One compose file, one root `.env`

- **Decision**: All services are defined in the existing root `compose.yaml` (Compose v2, no
  `version:` key). Compose reads the root `.env` automatically; a committed root `.env.example`
  holds local placeholder values (see [contracts/configuration.md](contracts/configuration.md)).
  Required variables use `${VAR:?message}` interpolation, so a missing variable stops
  `docker compose up` with a message naming it (spec US1-5).
- **Rationale**: The constitution requires `compose.yaml` and "no manual steps beyond setting
  environment variables". `.env` is already git-ignored.
- **Alternatives**: Per-service `env_file`s (more files, same effect); compose profiles
  (not needed with one environment).

## R2. Image versions

| Component | Image / package | Release line |
|---|---|---|
| Warehouse | `clickhouse/clickhouse-server` | 25.8 (LTS) |
| Metadata DB | `postgres` | 17 (alpine) |
| Orchestrator | `apache/airflow` | 3.1.x, `-python3.12` variant |
| Dashboards | `apache/superset` | 5.0.x |
| Transformation | `dbt-core` + `dbt-clickhouse` (pip) | `dbt-clickhouse~=1.9`, which pins a compatible `dbt-core` |

- **Rationale**: Current stable/LTS lines. Airflow 2.x is end-of-life, so a new project starts on
  3.x. The `python3.12` Airflow variant matches the ingestion job's `requires-python >=3.12`.
- **Alternatives**: `latest` tags (not reproducible; rejected).

## R3. Airflow runs in a single `airflow standalone` container

- **Decision**: One `airflow` service runs `airflow standalone` (API server + scheduler + DAG
  processor + triggerer in one process group) with `LocalExecutor` and its metadata in Postgres.
  `standalone` runs `airflow db migrate` itself, so there is no separate init container.
- **Login**: Airflow 3's default `SimpleAuthManager`. The entrypoint writes the passwords file
  (`{"<user>": "<password>"}`) from `AIRFLOW_ADMIN_USER` / `AIRFLOW_ADMIN_PASSWORD` before
  starting, and `AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_USERS=<user>:admin` makes that user an admin.
  Writing the file every start keeps it idempotent.
- **Health check**: `GET http://localhost:8080/api/v2/monitor/health`.
- **Rationale**: Constitution II (simplicity) and SC-005 (8 GB laptop). The official multi-service
  compose (Celery, Redis, workers, flower) is several times larger and not needed for one DAG.
- **Alternatives**: Split api-server/scheduler/dag-processor services with LocalExecutor (closer to
  production but 3–4 containers and an init job; can be adopted later without changing DAGs);
  CeleryExecutor (needs a broker; rejected); FAB auth manager with `airflow users create` (extra
  provider config for no gain locally).

## R4. How Airflow runs the weather job

- **Decision**: The Airflow image gets a separate virtual environment `/opt/venvs/ingestion`,
  built from `ingestion/pyproject.toml` + `ingestion/uv.lock` with
  `uv sync --locked --no-dev --no-install-project`. The `ingestion/` folder is bind-mounted at
  `/opt/ingestion`, and the DAG runs
  `cd /opt/ingestion && /opt/venvs/ingestion/bin/python -m open_meteo <mode>` with a
  `BashOperator`.
- **Output sharing**: `open_meteo/config.py` resolves relative paths against the folder above the
  package (`PROJECT_DIR`), so in the container the default output is
  `/opt/ingestion/output/open_meteo`, which is the host's `ingestion/output/open_meteo`. No job
  settings change (FR-012), and files from earlier local runs are visible (spec edge case).
- **Exit codes**: exit 1 (run failed) and 2 (refused) both fail the task; Airflow retries per the
  DAG's retry policy (FR-015). Retrying a refusal is harmless and keeps the DAG simple.
- **Rationale**: No change to the job's code; the lock file keeps the container's dependencies
  identical to CI; a separate venv keeps the job's dependencies out of Airflow's own environment.
  Bind-mounting the source means code changes need no image rebuild.
- **Alternatives**: `DockerOperator` with a separate ingestion image (needs the Docker socket
  inside Airflow; rejected for security and simplicity); installing into Airflow's own
  environment (risk of dependency conflicts); `PythonVirtualenvOperator` (rebuilds the venv per
  run).
- **Linux file ownership**: Airflow runs as `AIRFLOW_UID` (default 50000). On Linux hosts this
  must be set to the host user's UID so files written to the bind mount are owned by the user;
  documented in `.env.example` and the README. Not needed on macOS/Windows.

## R5. dbt runs inside the Airflow image

- **Decision**: A second venv `/opt/venvs/dbt` in the Airflow image with `dbt-clickhouse`.
  `dbt/` is bind-mounted at `/opt/dbt`; `DBT_PROFILES_DIR=/opt/dbt` points to a committed
  `dbt/profiles.yml` that reads everything from `env_var()`. The connection check is
  `docker compose exec airflow /opt/venvs/dbt/bin/dbt debug --project-dir /opt/dbt` (wrapped as
  `make dbt-debug`).
- **Rationale**: Airflow must be able to run dbt (FR-013), and a `BashOperator` calling the venv's
  `dbt` is the simplest way. A separate venv avoids the well-known dbt/Airflow dependency
  conflicts. No extra container to keep running.
- **Alternatives**: Separate `dbt` service (Airflow could not run it without the Docker socket);
  Astronomer Cosmos (an extra dependency; worth revisiting once models exist).

## R6. dbt project layout and schema naming

- **Decision**: Project name `energy_analytics`, with `models/silver/`, `models/gold/`,
  `models/marts/` (each holding only `.gitkeep`) and `models/sources.yml` declaring source
  `bronze` (database `bronze`) with table `open_meteo_weather` and no columns yet. A
  `macros/generate_schema_name.sql` override makes a folder's `+schema` the ClickHouse database
  name exactly (`silver`, `gold`), instead of dbt's default `<target>_<custom>` prefixing. `marts`
  are built into `gold`, as the project plan places marts inside gold.
- **Rationale**: FR-017. In ClickHouse a dbt "schema" is a database; without the override, models
  would land in `default_silver` etc., breaking the layer layout from FR-007. Adding the macro now
  avoids a confusing first model later.
- **Placeholder behaviour**: With no models, `dbt parse`/`dbt debug` succeed; `dbt build` reports
  "nothing to do". The DAG does not call dbt yet (R8).
- **Alternatives**: No override (wrong databases); declaring no source (spec requires it).

## R7. ClickHouse layers and accounts

- **Decision**: Init scripts in `infra/clickhouse/init/` (mounted at
  `/docker-entrypoint-initdb.d`):
  - `01_databases.sql`: `CREATE DATABASE IF NOT EXISTS bronze|silver|gold`.
  - `02_users.sh`: creates role-less user `CLICKHOUSE_READER_USER` with
    `CLICKHOUSE_READER_PASSWORD` and `GRANT SELECT ON gold.*`; `IF NOT EXISTS` everywhere.
  - The existing `02_bronze_tables.sql` (`staging.raw_*`) is deleted (FR-009).
  The pipeline account is the image's built-in `CLICKHOUSE_USER`/`CLICKHOUSE_PASSWORD` with
  `CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT=1`, so it can create the reader user and own all layers.
- **Rationale**: FR-007/FR-008. The image runs init scripts only on an empty data volume, and the
  `IF NOT EXISTS` clauses make re-runs safe anyway (edge case "initialisation runs twice"). A
  `SELECT`-only grant makes the reader unable to write anywhere and unable to read bronze/silver.
- **Ports**: HTTP 8123 published to the host (`CLICKHOUSE_HTTP_PORT`) for ad-hoc queries; the
  native port 9000 stays internal.
- **Health check**: `clickhouse-client --query "SELECT 1"`.
- **Alternatives**: `readonly=1` user setting (breaks drivers that set session settings);
  XML user config files (harder to read than SQL, passwords would be in files).

## R8. The weather DAG

- **Decision**: `airflow/dags/open_meteo_weather.py`, DAG id `open_meteo_weather`:
  - Schedule `0 */6 * * *` (UTC), `catchup=False`, `is_paused_upon_creation=True`
    (the env `AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION=True` too), `max_active_runs=1`.
  - Tasks: `fetch_forecast` and `fetch_archive` (`BashOperator`, R4) in parallel →
    `load_bronze` → `build_silver` → `build_gold`, the last three `EmptyOperator`s whose docs say
    "placeholder" (FR-014).
  - `fetch_archive` runs only on the scheduled run at 00:00 UTC, or on a manual run with param
    `archive=true` (default `false`); otherwise it is skipped. This gives "forecast every 6 h,
    archive daily" from one DAG (spec US3-4) and a manual run in forecast mode produces exactly
    one file (SC-004).
  - `load_bronze` uses trigger rule `none_failed_min_one_success`, so a skipped archive task does
    not skip the rest, but any failed fetch stops everything after it (FR-015).
  - `default_args`: `retries=2`, `retry_delay=5 min`.
- **Rationale**: The project plan says "one DAG per source on its own schedule"; Open-Meteo is one
  source with two cadences. Empty placeholders make the final shape visible without writing data.
- **Alternatives**: Two DAGs (forecast, archive) — simpler scheduling but contradicts the "one
  pipeline" in the spec and plan; Datasets/asset-triggered dbt DAG (premature until models exist).

## R9. Postgres metadata databases

- **Decision**: `postgres` service with superuser from `POSTGRES_USER`/`POSTGRES_PASSWORD`. The
  empty `infra/postgres/init/01_databases.sql` is replaced by `01_databases.sh`, which creates
  roles and databases `airflow` and `superset`, each owned by its own role, with passwords from
  `AIRFLOW_DB_PASSWORD` and `SUPERSET_DB_PASSWORD`. Not published to the host.
- **Health check**: `pg_isready -U $POSTGRES_USER`.
- **Rationale**: FR-010; a shell script is needed because SQL init files cannot read environment
  variables. Not publishing the port avoids a host conflict with any local Postgres.

## R10. Superset

- **Decision**: `superset/Dockerfile` extends `apache/superset:5.0.x` and installs
  `psycopg2-binary` (metadata DB) and `clickhouse-connect` (warehouse driver, SQLAlchemy dialect
  `clickhousedb://`) into the image's `/app/.venv`. Superset 4.1+ images ship without database
  drivers. `superset/superset_config.py` reads `SUPERSET_SECRET_KEY` and builds
  `SQLALCHEMY_DATABASE_URI` from environment variables. `superset/bootstrap.sh` runs on every
  start:
  1. `superset db upgrade`
  2. `superset fab create-admin ...` (prints "already exists" on later starts)
  3. `superset init`
  4. `superset set-database-uri --database_name "ClickHouse warehouse" --uri clickhousedb://<reader>:<pw>@clickhouse:8123/gold`
     (creates or updates; idempotent; FR-019)
  5. `exec /usr/bin/run-server.sh`
- **Health check**: `GET http://localhost:8088/health`.
- **Rationale**: Automatic data source registration with the read-only account and no UI steps
  (SC-003). No Redis: the query cache in the architecture diagram is an optimisation for later.
- **Alternatives**: Importing a datasource YAML (`superset import-datasources`) — more files for
  one connection; Redis + Celery workers for async queries (not needed locally).

## R11. Persistence and reset

- **Decision**: Named volumes `clickhouse-data` and `postgres-data`. Airflow run history and
  Superset settings live in Postgres, so they persist through `postgres-data`. Airflow task logs go
  to the git-ignored `airflow/logs/` bind mount. `make reset` runs `docker compose down -v`.
- **Rationale**: FR-005, SC-006.

## R12. Commands

- **Decision**: Extend the root `Makefile`: `up` (`docker compose up -d --build --wait`),
  `down`, `reset`, `ps`, `logs`, `dbt-debug`. `--wait` blocks until all health checks pass, which
  gives a clear "healthy" signal for SC-001/SC-002.
- **Rationale**: FR-001/FR-002; the README already uses `make` for lint/test.

## R13. Linting new Python

- **Decision**: The new Python files (`airflow/dags/*.py`, `superset/superset_config.py`) are
  linted by adding `[tool.ruff]` to the (currently empty) root `pyproject.toml` with the same
  rules as `ingestion/`, and extending `make lint`/`make format` and CI with
  `uvx ruff check airflow superset` / `uvx ruff format --check airflow superset`. No pytest tests
  are added: the DAG and config are wiring without core logic (constitution III).
- **Rationale**: FR-022. `ruff` checks files statically, so Airflow does not need to be installed
  in CI.
- **Alternatives**: A DAG import test in CI (needs Airflow installed in CI; deferred until the DAG
  has real logic).

## R14. Resource budget

Approximate idle memory: ClickHouse ~0.8 GB, Airflow standalone ~1.5 GB, Superset ~0.8 GB,
Postgres ~0.1 GB — about 3.5 GB, within the 8 GB target (SC-005). ClickHouse's
`max_server_memory_usage_to_ram_ratio` is left at its default.

## R15. Demo queries are outdated

The demo queries in `docs/examples.sql` and the project plan are outdated (they use a `core.`
database) and are not a source of truth for names. The layers follow the constitution:
`bronze`, `silver`, `gold`, with facts, dimensions and marts in `gold`.
