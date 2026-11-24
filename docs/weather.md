# Weather Pipeline (Open-Meteo)

End-to-end Open-Meteo weather ingestion, transformation, and dashboard flow. For local stack setup, see [README.md](../README.md).

```text
Open-Meteo ─► ingestion job ─► bronze ─► silver ─► gold (star schema + mart) ─► "Past weather" dashboard
              (Airflow: ingest_*)        (Airflow: build_silver, build_gold, run by dbt)   (Superset)
```

## Components

- **Warehouse**: `bronze.open_meteo_weather` (written by `pipeline`; `superset_reader` can only read `gold`).
- **Airflow**: DAG `open_meteo_weather` (paused by default), scheduled every 6 hours (UTC).
- **dbt**: project `energy_analytics` in [dbt/](../dbt/) with `silver.weather_locations`, `silver.open_meteo_weather`, `gold.dim_location`, `gold.dim_interval`, `gold.fact_weather`, `gold.mart_past_weather`, and their tests.
- **Superset**: `ClickHouse warehouse` connection (read-only) and the "Past weather" dashboard, imported on every start.

All layer tables are described in the [data dictionary](../infra/README.md).

## Running the End-to-End Flow

1. Start the stack: `make up`.
2. Open Airflow (<http://localhost:8080>), switch on `open_meteo_weather` and trigger it with the `archive` option enabled. Or from a terminal (Podman users can substitute `podman-compose` or `podman compose` for `docker compose`):

   ```bash
   docker compose exec airflow airflow dags unpause open_meteo_weather
   docker compose exec airflow airflow dags trigger open_meteo_weather --conf '{"archive": true}'
   ```

3. Open the dashboard: <http://localhost:8088/superset/dashboard/past-weather/> (login from `.env`, `admin` / `admin`). It shows the last 7 days of observed weather for the 5 locations. Before the first run the charts show a query error, because dbt creates the mart table on the first build.

### DAG Tasks

| Task | What it does |
|---|---|
| `ingest_forecast` | Fetches the 3-day forecast and inserts the run into `bronze.open_meteo_weather`. |
| `ingest_archive` | Fetches the last 7 days of observed weather. Runs on the 00:00 UTC run, or on a manual run with `archive` enabled; otherwise skipped. |
| `build_silver` | `dbt build --select silver`: location seed, `silver.open_meteo_weather`, and tests. |
| `build_gold` | `dbt build --select gold marts`: dimensions, `fact_weather`, `mart_past_weather`, and tests. |
| `check_bronze_freshness` | Warns in its log when the newest load is older than 6 hours. Runs even when an ingest failed, and never fails because of stale data. |

A failed ingest stops the builds, and a failed dbt test stops the models after it, so the dashboard keeps showing the last good data. Switching the DAG on starts the most recent scheduled run right away, so a first manual trigger shows two runs.

To rebuild the models by hand, run `make dbt-build`. To inspect bronze data:

```bash
docker compose exec clickhouse clickhouse-client --user pipeline --password pipeline \
    --query "SELECT source_type, run_id, count() FROM bronze.open_meteo_weather GROUP BY ALL"
```

## Storage Destinations (`--destination`)

By default the job inserts each run into bronze. It can also write the run as a JSON Lines file to `ingestion/output/open_meteo/`, instead of or in addition to the insert:

| `--destination` | Bronze insert | Run file |
|---|---|---|
| `warehouse` (default) | yes | no |
| `file` | no | yes |
| `both` | yes, first | yes, only after the insert succeeded |

Set it for one run with `--destination`, or for every run with `OPEN_METEO_DESTINATION`. The warehouse destinations need `CLICKHOUSE_USER` and `CLICKHOUSE_PASSWORD` (the `pipeline` account, never the reader account) and use `CLICKHOUSE_URL` (default `http://localhost:8123`). Inside the stack these are already set. Outside it, put them in `ingestion/.env` (see [ingestion/.env.example](../ingestion/.env.example)).

```bash
# Inside the stack: fetch observed weather and store it in bronze and in a file.
docker compose exec airflow bash -c \
    'cd /opt/ingestion && /opt/venvs/ingestion/bin/python -m open_meteo archive --destination both'

# Without the stack: file mode needs no ClickHouse.
cd ingestion && uv run python -m open_meteo forecast --destination file
```

## Changing the Dashboard

The dashboard is kept in the repository as a Superset export in [superset/dashboards/past_weather/](../superset/dashboards/past_weather/). To change it:

1. Edit the dashboard or its charts in the Superset UI and save.
2. Export it and unpack the export:

   ```bash
   docker compose exec superset superset export-dashboards -f /tmp/export.zip
   docker compose exec -T superset cat /tmp/export.zip > export.zip && unzip export.zip
   ```

3. Replace `metadata.yaml`, `databases/`, `datasets/`, `charts/` and `dashboards/` in `superset/dashboards/past_weather/` with the exported ones.
4. In `databases/ClickHouse_warehouse.yaml`, set the connection back to the placeholder: `sqlalchemy_uri: ${SUPERSET_WAREHOUSE_URI}`. The start script fills it in from `.env`, so no credentials are committed.
5. Keep every `uuid` as it is. Superset finds the existing objects by UUID on the next start, so nothing is created twice.

On every start Superset imports the bundle: the dashboard itself (layout, filters, refresh interval) is overwritten, while the warehouse connection, the dataset and the charts are only created when they are missing. A stack that already has the dashboard therefore gets a changed chart only after you delete the old chart in the UI and restart, or after `make reset`.
