# Quickstart: Validate the Local Pipeline Stack

Each scenario maps to a user story or requirement in [spec.md](spec.md). Commands run from the
repository root.

## Prerequisites

- Docker Desktop (or Docker Engine) with Compose v2, at least 8 GB memory for containers.
- Ports 8080, 8088 and 8123 free, or other ports set in `.env`
  ([contracts/configuration.md](contracts/configuration.md)).
- Linux only: `AIRFLOW_UID=$(id -u)` in `.env`.

## 1. Start the stack (US1, FR-001, SC-001/SC-002)

```bash
cp .env.example .env
make up
make ps
```

Expected: `make up` returns successfully; `make ps` shows `postgres`, `clickhouse`, `airflow`,
`superset` all `healthy`.

## 2. Web UIs and logins (US1-2)

- `http://localhost:8080` → Airflow login with `AIRFLOW_ADMIN_USER`/`AIRFLOW_ADMIN_PASSWORD`.
- `http://localhost:8088` → Superset login with `SUPERSET_ADMIN_USER`/`SUPERSET_ADMIN_PASSWORD`.

## 3. Warehouse layers and accounts (US2-1, US2-5, FR-007/FR-008)

```bash
docker compose exec clickhouse clickhouse-client --user pipeline --password pipeline \
  --query "SHOW DATABASES"
docker compose exec clickhouse clickhouse-client --user superset_reader --password superset_reader \
  --query "CREATE TABLE gold.t (x UInt8) ENGINE = Memory"
docker compose exec clickhouse clickhouse-client --user superset_reader --password superset_reader \
  --query "SHOW TABLES FROM bronze"
```

Expected: the list contains `bronze`, `silver`, `gold` and no `staging`; the reader's `CREATE TABLE`
fails with an access-denied error; `SHOW TABLES FROM bronze` as the reader returns nothing (ClickHouse
hides what an account may not see instead of raising an error, and a `SELECT` from a bronze or silver
table is refused); `SHOW TABLES FROM gold` as the reader succeeds (empty).

## 4. dbt connection (US2-2, FR-016/FR-017)

```bash
make dbt-debug
```

Expected: `All checks passed!`.

## 5. Superset data source (US2-3, FR-019)

In Superset: *Settings → Database Connections*. Expected: `ClickHouse warehouse` is listed; *Edit →
Test connection* succeeds. In *SQL Lab*, the `gold` database is selectable.

## 6. Metadata databases (US2-4, FR-010)

```bash
docker compose exec postgres psql -U postgres -c '\l'
```

Expected: databases `airflow` and `superset` exist, owned by roles `airflow` and `superset`.

## 7. Weather pipeline (US3, SC-004)

1. In Airflow, `open_meteo_weather` is listed and paused, showing
   `fetch_forecast`, `fetch_archive` → `load_bronze` → `build_silver` → `build_gold`.
2. Trigger it with default params (▶). Expected: `fetch_forecast` success, `fetch_archive`
   skipped, the three placeholders success.
3. `ls ingestion/output/open_meteo/` shows exactly one new `open_meteo_forecast_*.jsonl`.
4. Failure path (optional): `docker compose exec airflow` cannot reach the provider when the
   machine is offline; trigger again and expect `fetch_forecast` to retry twice, then fail, and
   the placeholders to be `upstream_failed`.

## 8. Persistence and reset (US1-3/US1-4, FR-005, SC-006)

```bash
make down && make up
```

Expected: the previous DAG run is still in Airflow history; the Superset data source still
exists; ClickHouse still lists the three layers. Then `make reset` removes containers and volumes;
the next `make up` starts from empty state without errors (idempotent init).

## 9. Missing variable (US1-5)

Remove `CLICKHOUSE_READER_PASSWORD` from `.env` and run `make up`. Expected: Compose stops with an
error naming `CLICKHOUSE_READER_PASSWORD`. Restore it afterwards.

## 10. Code quality (FR-022)

```bash
make lint && make test
```

Expected: both pass.
