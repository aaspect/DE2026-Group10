# DE2026-Group10
The project of Group 10 for the Data Engineering course in Fall 2026.

The objective of the project is to provide analytics related to electricity prices, combined with the weather data and historical consumption.

## Architecture

![Architecture diagram](docs/architecture.png)

## Running the stack

The whole pipeline runs locally with Docker Compose or Podman Compose: Postgres (metadata),
ClickHouse (warehouse), Airflow (orchestrator, which also runs dbt) and Superset (dashboards).

**You need**: Docker (Docker Desktop or Docker Engine with Compose v2) or Podman (with
`podman-compose` or `podman compose`), and `make`. The stack uses about 2–4 GB of memory; give
Docker or Podman at least 4 GB, 8 GB is comfortable. Ports 8080, 8088 and 8123 must be free, or
set other ports in `.env`.

```bash
cp .env.example .env   # local placeholder settings; on Linux Docker also set AIRFLOW_UID=$(id -u)
make up                # build, start, and wait until every service is healthy
```

`Makefile` auto-detects `docker compose`, `podman-compose`, or `podman compose` (override with
`COMPOSE=...`, e.g. `make up COMPOSE="podman compose"`). On rootless Podman, `make up` sets
`AIRFLOW_UID=0` automatically unless it is already set in `.env`, so files written to bind mounts
belong to your host user. In the manual `docker compose` examples below, Podman users can substitute
`podman-compose` (or `podman compose`).

| Command | What it does |
|---|---|
| `make up` | Build the images and start the stack. Returns when all services are healthy. |
| `make down` | Stop the stack. Data is kept. |
| `make reset` | Stop the stack and delete all warehouse and metadata data. |
| `make ps` | Show the services and their health. |
| `make logs` | Follow the logs of all services. |
| `make dbt-debug` | Check that dbt can connect to the warehouse. |
| `make dbt-build` | Build and test all dbt models (seed, silver, gold, mart). |
| `make lint` / `make format` / `make test` | Lint, format and test the Python code. |

| Service | URL | Login (from `.env`) |
|---|---|---|
| Airflow | <http://localhost:8080> | `AIRFLOW_ADMIN_USER` / `AIRFLOW_ADMIN_PASSWORD` (`admin` / `admin`) |
| Superset | <http://localhost:8088> | `SUPERSET_ADMIN_USER` / `SUPERSET_ADMIN_PASSWORD` (`admin` / `admin`) |
| ClickHouse (HTTP) | <http://localhost:8123> | `CLICKHOUSE_USER` / `CLICKHOUSE_PASSWORD` (`pipeline` / `pipeline`) |

Postgres is only reachable from inside the stack. The values in `.env.example` are for a local
machine only; never reuse them elsewhere. `.env` is git-ignored.

### What is in place

- **Warehouse**: databases `bronze`, `silver` and `gold`, and the table
  `bronze.open_meteo_weather`. The `pipeline` account writes to all three layers;
  `superset_reader` can only read `gold`.
- **Airflow**: one DAG, `open_meteo_weather`, paused until you switch it on. It runs the whole
  weather flow every 6 hours (UTC), see below.
- **dbt**: project `energy_analytics` in `dbt/`, with the weather models
  `silver.open_meteo_weather`, `gold.dim_location`, `gold.dim_interval`, `gold.fact_weather` and
  `gold.mart_past_weather`, and their tests.
- **Superset**: the warehouse is registered as `ClickHouse warehouse`, through the read-only
  account, and the "Past weather" dashboard is imported on every start.

## End-to-end weather flow

```text
Open-Meteo ─► ingestion job ─► bronze ─► silver ─► gold (star schema + mart) ─► "Past weather" dashboard
              (Airflow: ingest_*)        (Airflow: build_silver, build_gold, run by dbt)   (Superset)
```

1. Start the stack: `make up`.
2. Open Airflow (<http://localhost:8080>), switch on `open_meteo_weather` and trigger it with the
   `archive` option on. Or from a terminal:

   ```bash
   docker compose exec airflow airflow dags unpause open_meteo_weather
   docker compose exec airflow airflow dags trigger open_meteo_weather --conf '{"archive": true}'
   ```

3. Open the dashboard: <http://localhost:8088/superset/dashboard/past-weather/> (login from
   `.env`, `admin` / `admin`). It shows the last 7 days of observed weather for the 5 locations.
   Before the first run the charts show a query error, because dbt creates the mart table on
   the first build.

What the DAG does on each run:

| Task | What it does |
|---|---|
| `ingest_forecast` | Fetches the 3-day forecast and inserts the run into `bronze.open_meteo_weather`. |
| `ingest_archive` | The same for the last 7 days of observed weather. Runs on the 00:00 UTC run, or on a manual run with the `archive` option on; otherwise it is skipped. |
| `build_silver` | `dbt build --select silver`: the location seed, `silver.open_meteo_weather` and their tests. |
| `build_gold` | `dbt build --select gold marts`: dimensions, `fact_weather`, `mart_past_weather` and their tests. |
| `check_bronze_freshness` | Warns in its log when the newest load is older than 6 hours. Runs even when an ingest failed, and never fails because of stale data. |

A failed ingest stops the builds, and a failed dbt test stops the models after it, so the
dashboard keeps showing the last good data. Switching the DAG on starts the most recent scheduled
run right away, so a first manual trigger shows two runs.

To rebuild the models by hand, run `make dbt-build`. To look at the data:

```bash
docker compose exec clickhouse clickhouse-client --user pipeline --password pipeline \
    --query "SELECT source_type, run_id, count() FROM bronze.open_meteo_weather GROUP BY ALL"
```

The tables of every layer are described in the [data dictionary](infra/README.md).

### Where the weather job stores a run

By default the job inserts each run into bronze. It can also write the run as a JSON Lines file
to `ingestion/output/open_meteo/`, instead of or in addition to the insert:

| `--destination` | Bronze insert | Run file |
|---|---|---|
| `warehouse` (default) | yes | no |
| `file` | no | yes |
| `both` | yes, first | yes, only after the insert succeeded |

Set it for one run with `--destination`, or for every run with `OPEN_METEO_DESTINATION`. The
warehouse destinations need `CLICKHOUSE_USER` and `CLICKHOUSE_PASSWORD` (the `pipeline` account,
never the reader account) and use `CLICKHOUSE_URL` (default `http://localhost:8123`). Inside the
stack these are already set. Outside it, put them in `ingestion/.env`
(see `ingestion/.env.example`).

```bash
# Inside the stack: fetch observed weather and store it in bronze and in a file.
docker compose exec airflow bash -c \
    'cd /opt/ingestion && /opt/venvs/ingestion/bin/python -m open_meteo archive --destination both'

# Without the stack: file mode needs no ClickHouse.
cd ingestion && uv run python -m open_meteo forecast --destination file
```

### Changing the dashboard

The dashboard is kept in the repository as a Superset export in
[superset/dashboards/past_weather/](superset/dashboards/past_weather/). To change it:

1. Edit the dashboard or its charts in the Superset UI and save.
2. Export it and unpack the export:

   ```bash
   docker compose exec superset superset export-dashboards -f /tmp/export.zip
   docker compose exec -T superset cat /tmp/export.zip > export.zip && unzip export.zip
   ```

3. Replace `metadata.yaml`, `databases/`, `datasets/`, `charts/` and `dashboards/` in
   `superset/dashboards/past_weather/` with the exported ones.
4. In `databases/ClickHouse_warehouse.yaml`, set the connection back to the placeholder:
   `sqlalchemy_uri: ${SUPERSET_WAREHOUSE_URI}`. The start script fills it in from `.env`, so no
   credentials are committed.
5. Keep every `uuid` as it is. Superset finds the existing objects by UUID on the next start, so
   nothing is created twice.

On every start Superset imports the bundle: the dashboard itself (layout, filters, refresh
interval) is overwritten, while the warehouse connection, the dataset and the charts are only
created when they are missing. A stack that already has the dashboard therefore gets a changed
chart only after you delete the old chart in the UI and restart, or after `make reset`.

## Data Dictionary

See [infra/README.md](infra/README.md).

## Example Queries and DDL

See [docs/examples.sql](docs/examples.sql) for example queries.

See [infra/clickhouse/init/](infra/clickhouse/init/) for the warehouse initialisation: the layer databases, the
read-only account and the bronze table DDL. Silver and gold tables are defined by the dbt models in
[dbt/models/](dbt/models/).

## Spec-Driven Development

Features are developed with [Spec Kit](https://github.com/github/spec-kit).

- Project principles: [.specify/memory/constitution.md](.specify/memory/constitution.md)
- Feature specs, plans and tasks: [specs/](specs/)

Workflow: `/speckit-specify` → `/speckit-clarify` → `/speckit-plan` → `/speckit-tasks` → `/speckit-analyze` → `/speckit-implement`.

Other commands: `/speckit-constitution` (update principles), `/speckit-checklist` (generate a quality checklist), `/speckit-converge` (add tasks for unbuilt work).

No separate LLM disclosure file is provided, as the specs already cover LLM usage.
