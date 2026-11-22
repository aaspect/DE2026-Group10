# Quickstart Validation: Elering Electricity Prices Pipeline

Runnable end-to-end checks proving all four user stories and success criteria work after
implementation. Refer to [data-model.md](data-model.md) and the contracts under
[contracts/](contracts/) for full schemas and rules.

## Prerequisites

- Docker (or Podman) with Compose, `make`, and `uv` installed.
- `.env` created from `.env.example`.
- Note: if you already have a ClickHouse volume from feature 003, run `make reset` before `make up`
  so `infra/clickhouse/init/04_bronze_elering_prices.sql` executes on a fresh volume.

---

## 1. Offline Quality & Unit Tests (SC-007)

Verify linting, formatting, and all offline ingestion tests (including `bidding_zones.toml` ↔
`bidding_zones.csv` parity):

```bash
make lint
make test
```

**Expected**: ruff reports zero errors; pytest passes offline in under 10 seconds.

---

## 2. Fresh Stack Start & Initialisation (FR-016, FR-031)

```bash
make reset
make up
```

Verify `bronze.elering_prices` exists and the `dbt_build` Airflow pool has 1 slot:

```bash
docker compose exec -T clickhouse clickhouse-client --user pipeline --password pipeline \
    --query "SHOW CREATE TABLE bronze.elering_prices"
docker compose exec -T airflow airflow pools get dbt_build
```

**Expected**: `bronze.elering_prices` exists with `record JSON`, `run_id UUID`,
`mode LowCardinality(String)`, `loaded_at DateTime('UTC')`; `dbt_build` pool shows `slots = 1`.

---

## 3. Standalone CLI Validation — File Mode & Invalid Range Refusal (US1, US2)

Run local file-only mode without requiring ClickHouse credentials, and verify pre-flight refusal on
an invalid backfill range (see [contracts/ingestion-cli.md](contracts/ingestion-cli.md)):

```bash
# Refuses before contacting Elering (exit 2)
cd ingestion && uv run python -m elering_prices backfill --start-date 2025-10-05 --end-date 2025-10-01
echo "Exit code: $?"

# Backfill across the October 2025 MTU switch to a local JSONL file
uv run python -m elering_prices backfill --start-date 2025-09-29 --end-date 2025-10-02 --destination file
```

**Expected**:
- First command prints `outcome: failure`, exits `2`, writes no file.
- Second command prints `outcome: success`, `zones: 4`, `records: 984` (4 zones × (46 pre-switch
  hourly + 200 post-switch 15-min intervals)), exits `0`, writes one `.jsonl` file under
  `ingestion/output/elering_prices/`.

---

## 4. Historical Backfill & Star Schema with Empty Weather Bronze (US2, US3, SC-002, SC-005)

Load a backfill crossing the October 2025 MTU transition into `bronze.elering_prices` (while
`bronze.open_meteo_weather` is still empty) and build dbt:

```bash
docker compose exec -T airflow bash -c \
    'cd /opt/ingestion && env -u PYTHONPATH /opt/venvs/ingestion/bin/python -m elering_prices backfill --start-date 2025-09-29 --end-date 2025-10-02'

make dbt-build
```

Inspect silver and gold results:

```bash
docker compose exec -T clickhouse clickhouse-client --user pipeline --password pipeline --multiquery <<'SQL'
SELECT count() AS bronze_rows FROM bronze.elering_prices;
SELECT count() AS silver_rows, uniqExact(zone_code) AS zones FROM silver.elering_prices;
SELECT zone_code, mtu_minutes, valid_from, valid_to, is_current FROM gold.dim_bidding_zone ORDER BY zone_key;
SELECT min(interval_start_utc), max(interval_start_utc), count() FROM gold.dim_interval;
SELECT z.zone_code, z.mtu_minutes, count() AS hours
FROM gold.fact_price f
JOIN gold.dim_bidding_zone z ON f.zone_key = z.zone_key
GROUP BY z.zone_code, z.mtu_minutes
ORDER BY z.zone_code, z.mtu_minutes;
SQL
```

**Expected**:
- `make dbt-build` succeeds with 100 % passing tests even with `bronze.open_meteo_weather` empty.
- `bronze_rows = 984`, `silver_rows = 984`, `zones = 4`.
- `gold.dim_bidding_zone` has 8 rows (2 SCD-2 versions per zone split at `2025-09-30 22:00:00`).
- `gold.dim_interval` spans `2025-01-01 00:00:00` through `2025-12-31 23:00:00` (8760 hours).
- `gold.fact_price` has 46 rows per zone under `mtu_minutes = 60` and 50 rows per zone under
  `mtu_minutes = 15` (96 UTC hours × 4 zones = 384 rows total).

### One-Year Backfill Check (SC-002)

```bash
time docker compose exec -T airflow bash -c \
    'cd /opt/ingestion && env -u PYTHONPATH /opt/venvs/ingestion/bin/python -m elering_prices backfill --start-date 2025-01-01 --end-date 2025-12-31'
make dbt-build
```

**Expected**: completes in under 5 minutes in a single run with all dbt tests (including
`fact_price_complete_interior_days`) passing and zero missing UTC hours across `2025-09-30`.

---

## 5. Idempotency & Append-Only Bronze (US1, US3, SC-003)

Re-run the same backfill window and rebuild dbt:

```bash
docker compose exec -T airflow bash -c \
    'cd /opt/ingestion && env -u PYTHONPATH /opt/venvs/ingestion/bin/python -m elering_prices backfill --start-date 2025-09-29 --end-date 2025-10-02'
make dbt-build
```

**Expected**: `bronze.elering_prices` gains 984 appended rows under a new `run_id` (existing rows
unchanged); `silver.elering_prices` and `gold.fact_price` row counts and prices remain identical.

---

## 6. Orchestrated Daily Run & Concurrency Serialisation (US4, SC-001)

After daily Nord Pool publication (~14:30 Europe/Tallinn), unpause and trigger both DAGs together
(see [contracts/elering-dag.md](contracts/elering-dag.md)):

```bash
docker compose exec -T airflow airflow dags unpause elering_prices
docker compose exec -T airflow airflow dags unpause open_meteo_weather
docker compose exec -T airflow airflow dags trigger elering_prices
docker compose exec -T airflow airflow dags trigger open_meteo_weather --conf '{"archive": true}'
```

**Expected**:
- Both DAGs appear paused before unpausing and run cleanly without overlapping `build_silver` /
  `build_gold` conflicts (serialised via `dbt_build` pool).
- `elering_prices` tasks (`ingest_prices`, `build_silver`, `build_gold`, `check_bronze_freshness`)
  all succeed in under 5 minutes.
- `gold.dim_interval` spans the union of both weather and price years.
- Restarting the stack (`make down && make up`) preserves all bronze, silver, gold, and Airflow
  state.
