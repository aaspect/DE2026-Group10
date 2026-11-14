---

description: "Task list for the local data pipeline components"
---

# Tasks: Local Data Pipeline Components

**Input**: Design documents from `specs/002-pipeline-components/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: None. The feature is wiring without core logic (constitution III, research R13), so no
pytest tests are added. Validation is the scenario list in [quickstart.md](quickstart.md), plus
`make lint` and `make test` (FR-022).

**Organization**: Tasks are grouped by user story. Phase 2 holds what every service needs before
it can start (the Compose skeleton and the two data stores). US1 makes the four services start and
become healthy, US2 adds the connections between them, US3 adds the weather DAG.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story the task belongs to (US1, US2, US3)

## Path Conventions

- All paths are relative to the repository root. Files go into the existing tool folders
  (`airflow/`, `dbt/`, `superset/`, `infra/`) and the root `compose.yaml`; no new top-level folder.

## Conventions shared by all tasks

- Every credential and host port comes from the root `.env`
  ([contracts/configuration.md](contracts/configuration.md)). Required variables are referenced
  in `compose.yaml` as `${VAR:?set VAR in .env (see .env.example)}`; optional ports as
  `${VAR:-default}`.
- Services reach each other by Compose service name (`postgres`, `clickhouse`). Connection URIs
  are composed once, in `compose.yaml`, and passed to the containers as environment variables.
- Image tags and pip packages are pinned to an exact version from the release line in research R2
  (never `latest`).
- Shell scripts start with `#!/usr/bin/env bash` and `set -euo pipefail`, except init scripts in
  `docker-entrypoint-initdb.d`, which the image may source instead of execute and therefore must
  not change shell options or call `exit`.
- Initialisation is idempotent: a second start must not fail or duplicate anything.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Configuration files every later task relies on

- [X] T001 [P] Create `.env.example` with every variable and example value from
  `contracts/configuration.md`, grouped under the same headings (ports, Postgres, ClickHouse,
  Airflow, Superset), with a header comment saying the values are local-development placeholders
  that must not be reused elsewhere, and a comment on `AIRFLOW_UID` explaining it is only needed
  on Linux (`AIRFLOW_UID=$(id -u)`); leave `AIRFLOW_UID` commented out
- [X] T002 [P] Verify `.gitignore` ignores `.env`, `airflow/logs/`, `ingestion/output/`,
  `dbt/target/`, `dbt/logs/`; create a root `.dockerignore` that excludes everything except the
  files the Airflow image build copies (`ingestion/pyproject.toml`, `ingestion/uv.lock`,
  `airflow/entrypoint.sh`)
- [X] T003 [P] Add `[tool.ruff]` (`target-version = "py312"`, `line-length = 100`) and
  `[tool.ruff.lint]` (`select = ["E", "F", "I", "UP", "B"]`) to the root `pyproject.toml`, the
  same rules as `ingestion/pyproject.toml`, with no `[project]` table

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The Compose file and the two data stores that Airflow and Superset depend on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T004 Write the skeleton of `compose.yaml` (no `version:` key): named volumes
  `postgres-data` and `clickhouse-data`, and the two services below, each with
  `restart: unless-stopped`
- [X] T005 Add service `postgres` to `compose.yaml`: image `postgres:17.x-alpine` (pinned),
  environment `POSTGRES_USER`, `POSTGRES_PASSWORD`, `AIRFLOW_DB_PASSWORD`, `SUPERSET_DB_PASSWORD`
  (all required), volume `postgres-data:/var/lib/postgresql/data`, bind mount
  `./infra/postgres/init:/docker-entrypoint-initdb.d:ro`, no published port, health check
  `pg_isready` over TCP (`-h 127.0.0.1`) so it is not healthy while init scripts still run
- [X] T006 [P] Replace the empty `infra/postgres/init/01_databases.sql` with
  `infra/postgres/init/01_databases.sh`: create role `airflow` (password `AIRFLOW_DB_PASSWORD`)
  owning database `airflow`, and role `superset` (password `SUPERSET_DB_PASSWORD`) owning database
  `superset`; pass passwords as psql variables, not by string concatenation (research R9)
- [X] T007 Add service `clickhouse` to `compose.yaml`: image `clickhouse/clickhouse-server:25.8.x`
  (pinned), environment `CLICKHOUSE_USER`, `CLICKHOUSE_PASSWORD`, `CLICKHOUSE_READER_USER`,
  `CLICKHOUSE_READER_PASSWORD` (all required) and `CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT=1`, volume
  `clickhouse-data:/var/lib/clickhouse`, bind mount
  `./infra/clickhouse/init:/docker-entrypoint-initdb.d:ro`, port
  `${CLICKHOUSE_HTTP_PORT:-8123}:8123` (native port 9000 not published), `nofile` ulimit, health
  check `SELECT 1` via `clickhouse-client` as the pipeline account against the container's network
  address, so it is not healthy while init scripts still run on the localhost-only server

**Checkpoint**: `docker compose up -d --wait postgres clickhouse` reports both healthy

---

## Phase 3: User Story 1 - Start the whole stack with one command (Priority: P1) 🎯 MVP

**Goal**: `cp .env.example .env && make up` starts all four services healthy; both web UIs accept
the documented login; data survives `make down`; `make reset` clears it.

**Independent Test**: quickstart scenarios 1, 2, 8 and 9.

- [X] T008 [P] [US1] Write `airflow/Dockerfile`: `FROM apache/airflow:3.1.x-python3.12` (pinned),
  copy `airflow/entrypoint.sh` into the image and make it the default command, keeping the base
  image's own entrypoint (build context is the repository root)
- [X] T009 [P] [US1] Write `airflow/entrypoint.sh`: write the SimpleAuthManager passwords file
  (JSON `{"<AIRFLOW_ADMIN_USER>": "<AIRFLOW_ADMIN_PASSWORD>"}`, produced with a JSON encoder so
  any password is escaped correctly) to the path in
  `AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_PASSWORDS_FILE` on every start, then
  `exec airflow standalone` (research R3)
- [X] T010 [US1] Add service `airflow` to `compose.yaml`: build `airflow/Dockerfile` with context
  `.`, `user: "${AIRFLOW_UID:-50000}:0"`, `depends_on` `postgres` and `clickhouse` with
  `condition: service_healthy`, port `${AIRFLOW_PORT:-8080}:8080`, environment: LocalExecutor,
  `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN` for role/database `airflow` on `postgres:5432`,
  `AIRFLOW__CORE__LOAD_EXAMPLES=false`, `AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION=true`,
  `AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_USERS=<AIRFLOW_ADMIN_USER>:admin`, the passwords file path,
  `AIRFLOW_ADMIN_USER`, `AIRFLOW_ADMIN_PASSWORD` (both required); bind mounts
  `./airflow/dags:/opt/airflow/dags` and `./airflow/logs:/opt/airflow/logs`; health check
  `GET http://localhost:8080/api/v2/monitor/health` with a `start_period` long enough for the
  first database migration
- [X] T011 [P] [US1] Write `superset/Dockerfile`: `FROM apache/superset:5.0.x` (pinned), install
  pinned `psycopg2-binary` and `clickhouse-connect` into `/app/.venv`, copy
  `superset_config.py` onto the image's Python path and `bootstrap.sh` as the default command
  (research R10)
- [X] T012 [P] [US1] Write `superset/superset_config.py`: `SECRET_KEY` from `SUPERSET_SECRET_KEY`
  and `SQLALCHEMY_DATABASE_URI` from the metadata database URI variable set in `compose.yaml`;
  nothing else
- [X] T013 [P] [US1] Write `superset/bootstrap.sh`: `superset db upgrade`,
  `superset fab create-admin` from `SUPERSET_ADMIN_USER` / `SUPERSET_ADMIN_PASSWORD`,
  `superset init`, then `exec` the base image's server start script; must succeed on a second
  start when the admin already exists
- [X] T014 [US1] Add service `superset` to `compose.yaml`: build `./superset`, `depends_on`
  `postgres` and `clickhouse` with `condition: service_healthy`, port
  `${SUPERSET_PORT:-8088}:8088`, environment `SUPERSET_SECRET_KEY`, `SUPERSET_ADMIN_USER`,
  `SUPERSET_ADMIN_PASSWORD` (all required) and the metadata database URI for role/database
  `superset` on `postgres:5432`; health check `GET http://localhost:8088/health` with a
  `start_period` long enough for the first migration
- [X] T015 [US1] Add targets `up` (create `airflow/logs` and `ingestion/output/open_meteo` if
  missing, then `docker compose up -d --build --wait`), `down` (`docker compose down`), `reset`
  (`docker compose down -v`), `ps` and `logs` to `Makefile` and to its `.PHONY` list
  (contracts/services.md)
- [X] T016 [US1] Validate quickstart scenarios 1, 2, 8 (stop/start part) and 9 against the running
  stack and fix whatever fails

**Checkpoint**: all four services healthy after `make up`; both logins work

---

## Phase 4: User Story 2 - Components are wired together (Priority: P1)

**Goal**: the warehouse holds the empty `bronze`, `silver`, `gold` databases and a read-only
reader account; `dbt debug` succeeds from inside the stack; Superset has the warehouse registered
through the reader account.

**Independent Test**: quickstart scenarios 3, 4, 5 and 6.

- [X] T017 [P] [US2] Write `infra/clickhouse/init/01_databases.sql` with
  `CREATE DATABASE IF NOT EXISTS` for `bronze`, `silver` and `gold`, each with a one-line comment
  naming who writes it (data-model.md), and delete `infra/clickhouse/init/02_bronze_tables.sql`
  (FR-009)
- [X] T018 [P] [US2] Write `infra/clickhouse/init/02_users.sh`:
  `CREATE USER IF NOT EXISTS <CLICKHOUSE_READER_USER>` identified by `CLICKHOUSE_READER_PASSWORD`
  and `GRANT SELECT ON gold.*` to it, run as the pipeline account; no other grant (research R7)
- [X] T019 [P] [US2] Write `dbt/dbt_project.yml`: name and profile `energy_analytics`, model path
  `models`, macro path `macros`, `+schema: silver` for `models/silver`, `+schema: gold` for
  `models/gold` and `models/marts` (data-model.md)
- [X] T020 [P] [US2] Write `dbt/profiles.yml`: profile `energy_analytics`, target `local`,
  `type: clickhouse`, host `clickhouse`, port `8123`, schema `bronze`, user and password from
  `env_var('CLICKHOUSE_USER')` / `env_var('CLICKHOUSE_PASSWORD')`
- [X] T021 [P] [US2] Write `dbt/macros/generate_schema_name.sql` so a folder's `+schema` is used
  as the ClickHouse database name verbatim, and the target schema when none is set (research R6)
- [X] T022 [P] [US2] Write `dbt/models/sources.yml` declaring source `bronze` (schema `bronze`)
  with table `open_meteo_weather` and a description saying its columns arrive with the loading
  feature; add `.gitkeep` to `dbt/models/silver/`, `dbt/models/gold/` and `dbt/models/marts/`; no
  models (FR-017)
- [X] T023 [US2] Add the dbt virtual environment `/opt/venvs/dbt` with pinned `dbt-clickhouse`
  (1.9 line) to `airflow/Dockerfile`, plus whatever `dbt debug` needs to pass in the image
  (research R5)
- [X] T024 [US2] Extend service `airflow` in `compose.yaml`: bind mount `./dbt:/opt/dbt`,
  environment `DBT_PROFILES_DIR=/opt/dbt`, `CLICKHOUSE_USER` and `CLICKHOUSE_PASSWORD`
- [X] T025 [US2] Add target `dbt-debug`
  (`docker compose exec airflow /opt/venvs/dbt/bin/dbt debug --project-dir /opt/dbt`) to `Makefile`
- [X] T026 [US2] Register the warehouse in `superset/bootstrap.sh` after `superset init`:
  `superset set-database-uri --database_name "ClickHouse warehouse"` with the reader-account URI
  `clickhousedb://<reader>:<password>@clickhouse:8123/gold`, passed from `compose.yaml` as an
  environment variable built from `CLICKHOUSE_READER_USER` / `CLICKHOUSE_READER_PASSWORD`
  (both required); create-or-update on every start (FR-019)
- [X] T027 [US2] Validate quickstart scenarios 3, 4, 5 and 6 against a freshly reset stack and fix
  whatever fails

**Checkpoint**: layers exist, reader is read-only on gold only, `make dbt-debug` passes, Superset
lists `ClickHouse warehouse`

---

## Phase 5: User Story 3 - Weather job is runnable from the orchestrator (Priority: P2)

**Goal**: Airflow lists one paused DAG `open_meteo_weather` whose fetch tasks run the existing
job unchanged and whose remaining tasks are marked placeholders.

**Independent Test**: quickstart scenario 7.

- [X] T028 [US3] Add the ingestion virtual environment `/opt/venvs/ingestion` to
  `airflow/Dockerfile`, built from `ingestion/pyproject.toml` and `ingestion/uv.lock` with
  `uv sync --locked --no-dev --no-install-project` (research R4)
- [X] T029 [US3] Extend service `airflow` in `compose.yaml` with bind mount
  `./ingestion:/opt/ingestion`; set no `OPEN_METEO_*` variable (contracts/configuration.md)
- [X] T030 [US3] Write `airflow/dags/open_meteo_weather.py` per
  [contracts/weather-dag.md](contracts/weather-dag.md): `dag_id` `open_meteo_weather`, schedule
  `0 */6 * * *` UTC, `catchup=False`, `is_paused_upon_creation=True`, `max_active_runs=1`, param
  `archive` (bool, default `false`), `default_args` `retries=2` and `retry_delay` 5 minutes, tags
  `open_meteo`, `weather`; `fetch_forecast` and `fetch_archive` (`BashOperator`,
  `cd /opt/ingestion && /opt/venvs/ingestion/bin/python -m open_meteo <mode>`), where
  `fetch_archive` is skipped unless the run is the scheduled 00:00 UTC run or `params.archive` is
  true; then `load_bronze` (`EmptyOperator`, trigger rule `none_failed_min_one_success`) →
  `build_silver` → `build_gold` (`EmptyOperator`), each with a `doc_md` that says it is a
  placeholder and what will replace it
- [X] T031 [US3] Validate quickstart scenario 7 (steps 1–3) against the running stack: DAG listed
  and paused, manual run gives `fetch_forecast` success, `fetch_archive` skipped, placeholders
  success, exactly one new forecast file in `ingestion/output/open_meteo/`

**Checkpoint**: the weather pipeline runs end to end from the Airflow UI

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, linting and the final end-to-end check

- [X] T032 [P] Extend `lint` and `format` in `Makefile` with `uvx ruff check airflow superset` /
  `uvx ruff format --check airflow superset` (and the fixing variants in `format`) (research R13)
- [X] T033 [P] Add a job to `.github/workflows/ci.yml` that runs `uvx ruff check airflow superset`
  and `uvx ruff format --check airflow superset` from the repository root
- [X] T034 [P] Add a "Running the stack" section to `README.md`: prerequisites and minimum memory
  (8 GB for containers), `cp .env.example .env`, `make up` / `down` / `reset` / `ps` / `logs` /
  `dbt-debug`, the URL and login variables of each web UI, the Linux `AIRFLOW_UID` note, and a
  list of what is a placeholder (load and build tasks, empty dbt project, no Superset
  datasets/charts); fix the "DDL" link text so it no longer promises table DDL (FR-021)
- [X] T035 [P] Update `infra/README.md`: state that the init scripts create only the `bronze`,
  `silver`, `gold` databases and the reader account, and that the bronze tables listed there are
  planned and get their DDL in the loading features
- [X] T036 Run `make lint` and `make test`; fix findings (FR-022, quickstart scenario 10)
- [X] T037 Run the remaining quickstart scenarios on a freshly reset stack (`make reset`,
  `make up`), including the persistence and reset checks in scenario 8, and record deviations

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies
- **Foundational (Phase 2)**: needs T001 (`.env.example`); blocks all user stories
- **US1 (Phase 3)**: needs Phase 2
- **US2 (Phase 4)**: needs US1 (it extends the `airflow` and `superset` services and their images)
- **US3 (Phase 5)**: needs US1 (the `airflow` service); independent of US2
- **Polish (Phase 6)**: needs all stories

### Same-file sequences

- `compose.yaml`: T004 → T005 → T007 → T010 → T014 → T024 → T029
- `airflow/Dockerfile`: T008 → T023 → T028
- `superset/bootstrap.sh`: T013 → T026
- `Makefile`: T015 → T025 → T032

### Parallel Opportunities

- Phase 1: T001, T002, T003
- Phase 3: T008, T009, T011, T012, T013 (different files), then the `compose.yaml` tasks
- Phase 4: T017–T022 (different files)
- Phase 6: T032–T035

## Parallel Example: User Story 2

```text
Task: "Write infra/clickhouse/init/01_databases.sql and delete 02_bronze_tables.sql"
Task: "Write infra/clickhouse/init/02_users.sh"
Task: "Write dbt/dbt_project.yml"
Task: "Write dbt/profiles.yml"
Task: "Write dbt/macros/generate_schema_name.sql"
Task: "Write dbt/models/sources.yml and the .gitkeep files"
```

## Implementation Strategy

1. Phases 1–2, then US1: a stack that starts and stops with one command (MVP).
2. US2: the connections (layers, accounts, dbt, Superset data source). ClickHouse init scripts
   only run on an empty volume, so validate with `make reset` first.
3. US3: the weather DAG.
4. Polish: lint, CI, README, full quickstart run.

## Notes

- No task writes data into the warehouse, creates a table, a dbt model, or a Superset dataset,
  chart or dashboard (FR-020, spec Assumptions).
- The weather job's code under `ingestion/open_meteo/` is not changed (FR-012).
