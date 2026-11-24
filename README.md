# DE2026-Group10

Group 10 project for the Data Engineering course (Fall 2026): analytics combining electricity prices, weather data, and historical consumption.

## Architecture

![Architecture diagram](docs/architecture.png)

Data flows through ClickHouse layers (`bronze` → `silver` → `gold`), orchestrated by Airflow, transformed with dbt ([dbt/](dbt/)), and visualised in Superset (read-only access to `gold`).

## Spec-Driven Development

Features are developed with [Spec Kit](https://github.com/github/spec-kit).

- Project principles: [.specify/memory/constitution.md](.specify/memory/constitution.md)
- Feature specs, plans and tasks: [specs/](specs/)

Workflow: `/speckit-specify` → `/speckit-clarify` → `/speckit-plan` → `/speckit-tasks` → `/speckit-analyze` → `/speckit-implement`.

Other commands: `/speckit-constitution` (update principles), `/speckit-checklist` (generate a quality checklist), `/speckit-converge` (add tasks for unbuilt work).

No separate LLM disclosure file is provided, as the specs already cover LLM usage.

## Running the Stack

The stack runs locally with Docker Compose or Podman Compose (Postgres, ClickHouse, Airflow + dbt, Superset).

**Prerequisites**: Docker (Compose v2) or Podman (`podman-compose` / `podman compose`), `make`, at least 4 GB RAM (8 GB comfortable), and free ports `8080`, `8088`, `8123`, `5432` (configurable in `.env`).

```bash
cp .env.example .env   # local placeholders only (git-ignored); on Linux Docker also set AIRFLOW_UID=$(id -u)
make up                # build, start, and wait until all services are healthy
```

`Makefile` auto-detects `docker compose`, `podman-compose`, or `podman compose` (override via `COMPOSE=...`). On rootless Podman, `AIRFLOW_UID=0` is set automatically unless defined in `.env`.

| Command | What it does |
|---|---|
| `make up` / `make down` | Start (and wait until healthy) or stop the stack (data is kept). |
| `make reset` | Stop the stack and delete all warehouse and metadata volumes. |
| `make ps` / `make logs` | Show service health or follow all service logs. |
| `make dbt-debug` / `make dbt-build` | Verify dbt connection or build and test all dbt models. |
| `make lint` / `make format` / `make test` | Lint, format, and test Python code. |

| Service | URL | Default login (`.env`) |
|---|---|---|
| Airflow | <http://localhost:8080> | `AIRFLOW_ADMIN_USER` / `AIRFLOW_ADMIN_PASSWORD` (`admin` / `admin`) |
| Superset | <http://localhost:8088> | `SUPERSET_ADMIN_USER` / `SUPERSET_ADMIN_PASSWORD` (`admin` / `admin`) |
| ClickHouse (HTTP) | <http://localhost:8123> | `CLICKHOUSE_USER` / `CLICKHOUSE_PASSWORD` (`pipeline` / `pipeline`) |
| Postgres | `localhost:5432` | `POSTGRES_USER` / `POSTGRES_PASSWORD` (`postgres` / `postgres`) |

## Pipelines & Documentation

- **Weather pipeline (Open-Meteo)**: end-to-end flow, ingestion options, and Superset dashboard — [docs/weather.md](docs/weather.md)
- **Data dictionary**: bronze, silver, gold, and mart schemas — [infra/README.md](infra/README.md)
- **Warehouse DDL & models**: ClickHouse init scripts in [infra/clickhouse/init/](infra/clickhouse/init/) and dbt models in [dbt/models/](dbt/models/)
- **Example queries**: [docs/examples.sql](docs/examples.sql)
