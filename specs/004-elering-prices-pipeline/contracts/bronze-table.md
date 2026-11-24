# Contract: `bronze.elering_prices`

Hand-over interface between `ingestion/elering_prices` (writer) and `dbt` (reader). Mirrors
`bronze.open_meteo_weather` from feature 003.

## DDL

File: `infra/clickhouse/init/04_bronze_elering_prices.sql`. Applied automatically by the ClickHouse
container on a fresh data volume (after `01_databases.sql`) and by CI before `dbt build`. The
ingestion job NEVER runs DDL.

```sql
CREATE TABLE IF NOT EXISTS bronze.elering_prices
(
    record    JSON,
    run_id    UUID,
    mode      LowCardinality(String),
    loaded_at DateTime('UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(loaded_at)
ORDER BY (mode, loaded_at, run_id);
```

## Insert Request

```text
POST $CLICKHOUSE_URL/?query=INSERT INTO bronze.elering_prices (record, run_id, mode, loaded_at) FORMAT JSONEachRow
     &date_time_input_format=best_effort&input_format_try_infer_datetimes=0
     &wait_end_of_query=1&input_format_parallel_parsing=0
X-ClickHouse-User: $CLICKHOUSE_USER
X-ClickHouse-Key:  $CLICKHOUSE_PASSWORD
Content-Type: application/x-ndjson; charset=utf-8
```

One NDJSON line per price record, with `record` as a nested JSON object:

```json
{"record":{"zone_code":"ee","interval_start_utc":"2025-09-30T22:00:00Z","price_eur_mwh":98.95,"mode":"backfill","run_id":"3f2c9a8e-5b1d-4c47-9e0a-2d6f8b7c1a90","loaded_at":"2026-11-22T12:30:05Z"},"run_id":"3f2c9a8e-5b1d-4c47-9e0a-2d6f8b7c1a90","mode":"backfill","loaded_at":"2026-11-22T12:30:05Z"}
```

## Guarantees

| Guarantee | Mechanism |
|---|---|
| Raw preservation | `record` stores every key/value unchanged; `input_format_try_infer_datetimes=0` keeps timestamps as strings |
| Native JSON integrity | ClickHouse's `JSON` column rejects syntactically invalid JSON atomically |
| Atomicity | One `INSERT` statement, one MergeTree block (`input_format_parallel_parsing=0`), one partition (shared `loaded_at`), no client retry |
| Append-only | The job only executes `INSERT`; existing rows are never updated or deleted |
| Missing table fails loudly | ClickHouse returns `UNKNOWN_TABLE`; job raises `BronzeLoadError` and exits `1` |
| Credential scoping | Uses loading account (`CLICKHOUSE_USER` / `CLICKHOUSE_PASSWORD`), never the read-only reporting account |

## Reader Expectations (`dbt`)

- Same `(zone_code, interval_start_utc)` may repeat across runs; silver deduplicates by
  `ORDER BY loaded_at DESC, run_id DESC LIMIT 1 BY zone_code, interval_start_utc`.
- Silver reads JSON paths safely with `accurateCastOrNull(...)` so valid JSON documents carrying
  missing or unparsable fields evaluate to `NULL` and are excluded without failing the build.
- Freshness: `dbt source freshness` checks `max(loaded_at)` with `warn_after: 26 hours` (warn
  only, never error).
