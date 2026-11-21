# Implementation Plan: Local Data Pipeline Components

**Branch**: `pipeline_components` (spec directory `002-pipeline-components`) | **Date**: 2026-11-14 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/002-pipeline-components/spec.md`

## Summary

This plan stands up the whole pipeline from the project plan as a local Docker Compose stack of
four services: Postgres (metadata for Airflow and Superset), ClickHouse (warehouse with empty
`bronze`, `silver`, `gold` databases, a pipeline account and a read-only reader account), Airflow
(single `airflow standalone` container with LocalExecutor) and Superset (with the ClickHouse
`gold` database registered automatically through the reader account). The Airflow image carries
two isolated virtual environments: one with the existing Open-Meteo job's locked dependencies and
one with `dbt-clickhouse`. One DAG, `open_meteo_weather`, runs the real job (forecast every 6 h,
archive daily) followed by three clearly marked placeholder steps (load bronze → build silver →
build gold). The dbt project gets its profile, layer folders, a bronze source declaration and a
schema-naming macro, but no models. `make up/down/reset` manage the stack.

## Technical Context

**Language/Version**: Python 3.12 (Airflow DAG, Superset config); SQL and shell for init scripts;
YAML for Compose and dbt

**Primary Dependencies**: Docker Compose v2; images `postgres:17-alpine`,
`clickhouse/clickhouse-server:25.8`, `apache/airflow:3.1.x-python3.12`, `apache/superset:5.0.x`;
pip packages `dbt-clickhouse~=1.9`, `clickhouse-connect`, `psycopg2-binary`
([research R2](research.md#r2-image-versions))

**Storage**: ClickHouse (warehouse, volume `clickhouse-data`); Postgres (metadata, volume
`postgres-data`); weather run files on the host in `ingestion/output/open_meteo/` (bind mount)

**Testing**: No new pytest tests (wiring only, constitution III). Validation by the scenarios in
[quickstart.md](quickstart.md); `ruff` on new Python; existing `ingestion` tests keep passing

**Target Platform**: Developer laptops (macOS, Linux, Windows/WSL2) with Docker Desktop or Docker
Engine

**Project Type**: Local infrastructure / data platform configuration

**Performance Goals**: all services healthy within 3 min on a warm start (SC-002) and 10 min from a
fresh clone excluding downloads (SC-001)

**Constraints**: ≤ 8 GB memory for containers (SC-005, about 3.5 GB estimated in research R14);
no secrets committed; idempotent initialisation; local-only (no TLS, no external exposure)

**Scale/Scope**: 4 services, 1 DAG with 5 tasks, 3 warehouse databases, 2 warehouse accounts,
2 metadata databases, 1 Superset data source

All Technical Context items are resolved; no NEEDS CLARIFICATION remains (see
[research.md](research.md)).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|---|---|---|
| I. Clean, readable Python | The DAG and `superset_config.py` are short, typed where functions exist, and pass ruff (root `pyproject.toml` ruff config, research R13). Credentials, hosts and ports come from `.env`; only `.env.example` with local placeholders is committed. | ✅ Pass |
| II. Simplicity first | One Airflow container (`standalone`, LocalExecutor) instead of the Celery stack; no Redis; no DockerOperator; no Cosmos. New dependencies (`dbt-clickhouse`, `clickhouse-connect`, `psycopg2-binary`) are the minimum drivers the constitution's stack needs, each justified in research R5/R10. | ✅ Pass |
| III. Minimal tests for core functionality | No core logic is added, so no new tests. Warehouse data-quality tests belong to the modelling features (dbt tests). | ✅ Pass |
| IV. Update tests, no regression accumulation | Existing tests are untouched and keep passing. | ✅ Pass |
| V. Layered, documented data model | Creates the `bronze` → `silver` → `gold` layers (marts inside gold) as separate databases; the reader account sees only gold; no layer is skipped; no tables yet, so no grains to state. | ✅ Pass |
| Stack and layout | Uses exactly the constitution's stack (ClickHouse, Postgres, dbt, Airflow, Superset, Docker Compose). Files go into existing `airflow/`, `dbt/`, `superset/`, `infra/` folders and root `compose.yaml`; no new top-level folders. CI extended with ruff on the new Python (research R13). | ✅ Pass |

**Post-design re-check (after Phase 1)**: ✅ Pass. The design adds no abstractions, keeps every
setting in `.env`, and the placeholders write no data.

## Project Structure

### Documentation (this feature)

```text
specs/002-pipeline-components/
├── plan.md              # this file
├── research.md          # Phase 0: decisions R1–R15
├── data-model.md        # Phase 1: layers, accounts, metadata DBs, data source, DAG, dbt project
├── quickstart.md        # Phase 1: validation scenarios
├── contracts/
│   ├── configuration.md # .env variables
│   ├── services.md      # services, ports, mounts, health checks, make targets
│   └── weather-dag.md   # open_meteo_weather DAG properties and tasks
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks; not created here)
```

### Source Code (repository root)

```text
compose.yaml                      # 4 services, volumes, health checks, depends_on: service_healthy
.env.example                      # NEW: all variables from contracts/configuration.md
Makefile                          # + up, down, reset, ps, logs, dbt-debug; lint/format also cover airflow/, superset/
pyproject.toml                    # root ruff config for airflow/ and superset/ (no [project])
README.md                         # + "Running the stack" section: commands, URLs, logins, memory, placeholders
.github/workflows/ci.yml          # + ruff check/format on airflow/ and superset/

infra/
├── README.md                     # note that bronze tables are defined by the loading feature
├── postgres/init/
│   └── 01_databases.sh           # replaces empty 01_databases.sql: airflow + superset roles/DBs
└── clickhouse/init/
    ├── 01_databases.sql          # bronze, silver, gold (replaces staging content)
    └── 02_users.sh               # replaces 02_bronze_tables.sql: reader user, SELECT ON gold.*

airflow/
├── Dockerfile                    # FROM apache/airflow:3.1.x-python3.12; /opt/venvs/ingestion (uv sync --locked), /opt/venvs/dbt
├── entrypoint.sh                 # writes SimpleAuthManager passwords file, exec airflow standalone
├── dags/
│   └── open_meteo_weather.py     # contracts/weather-dag.md
└── logs/                         # git-ignored, bind mount

dbt/
├── dbt_project.yml               # energy_analytics; silver → silver, gold/marts → gold
├── profiles.yml                  # env_var() based, host clickhouse
├── macros/
│   └── generate_schema_name.sql
└── models/
    ├── sources.yml               # source bronze.open_meteo_weather
    ├── silver/.gitkeep
    ├── gold/.gitkeep
    └── marts/.gitkeep

superset/
├── Dockerfile                    # FROM apache/superset:5.0.x + psycopg2-binary, clickhouse-connect
├── superset_config.py            # SECRET_KEY, SQLALCHEMY_DATABASE_URI from env
└── bootstrap.sh                  # db upgrade, create-admin, init, set-database-uri, run-server

ingestion/                        # unchanged; mounted at /opt/ingestion
```

**Structure Decision**: Organised by tool, as the constitution requires. The Airflow image is
built with the repository root as build context so it can copy `ingestion/pyproject.toml` and
`ingestion/uv.lock`; the source code itself is bind-mounted, not copied.

## Complexity Tracking

No constitution violations to justify.
