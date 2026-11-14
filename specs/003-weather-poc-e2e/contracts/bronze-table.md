# Contract: `bronze.open_meteo_weather`

The point where the ingestion job (writer) hands data to dbt (reader). Replaces the run file as
the hand-over point. The run file is still available as an option (see
[ingestion-cli.md](ingestion-cli.md)).

## DDL

File: `infra/clickhouse/init/03_bronze_open_meteo_weather.sql`. The ClickHouse container runs it
once, when the data volume is first created, after `01_databases.sql`. CI runs it before the dbt
build. The job never runs DDL.

```sql
CREATE TABLE IF NOT EXISTS bronze.open_meteo_weather
(
    record      JSON,
    run_id      UUID,
    source_type LowCardinality(String),
    loaded_at   DateTime('UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(loaded_at)
ORDER BY (source_type, loaded_at, run_id)
```

`record` is ClickHouse's native `JSON` type (production-ready since 25.3) with no type hints:
each path is stored as `Dynamic` with an inferred type. See
[research R1](../research.md#r1-the-json-document-is-stored-in-a-native-json-column).

A change to this DDL is a contract change. Init scripts do not run again on an existing volume, so
once a stack holds data, a change needs an explicit migration or `make reset`.

## Insert request

```text
POST $CLICKHOUSE_URL/?query=INSERT INTO bronze.open_meteo_weather (record, run_id, source_type, loaded_at) FORMAT JSONEachRow
     &date_time_input_format=best_effort&input_format_try_infer_datetimes=0
     &wait_end_of_query=1&input_format_parallel_parsing=0
X-ClickHouse-User: $CLICKHOUSE_USER
X-ClickHouse-Key:  $CLICKHOUSE_PASSWORD
Content-Type: application/x-ndjson; charset=utf-8
```

The body has one line per record, in the same order as the run file. `record` is the record as a
nested JSON object (not an escaped string):

```json
{"record":{"location_id":"tallinn","hour_utc":"2026-11-14T00:00:00Z",...},"run_id":"3f2c9a8e-5b1d-4c47-9e0a-2d6f8b7c1a90","source_type":"forecast","loaded_at":"2026-11-14T09:30:15Z"}
```

`input_format_try_infer_datetimes=0` keeps the timestamp strings inside `record` as strings;
`date_time_input_format=best_effort` lets the `loaded_at` column accept the `...Z` form.

## Guarantees

| Guarantee | How |
|---|---|
| `record` holds every key and value of the run-file line | the same record dict feeds both destinations; the loader renames, types or drops nothing |
| An invalid document never reaches bronze | the `JSON` column rejects it, the whole insert fails and the run exits 1 |
| A run's rows all appear or none do | one `INSERT`, one block, one partition, no client retry |
| Rows are never changed | the job issues only `INSERT` |
| A missing table fails the run | ClickHouse returns `UNKNOWN_TABLE`; the job reports `bronze insert failed` and exits 1 |
| Metadata equals the document | `run_id`, `source_type` and `loaded_at` are copied from the same record dict |
| A run of `L` locations × `H` hours adds `L × H` rows with one `run_id` | as the run file (feature 001, SC-002) |

## Reader expectations (dbt)

- Rows for the same location and hour repeat across runs. Readers deduplicate them
  (silver: latest `loaded_at`, then largest `run_id`).
- Read paths as sub-columns and cast them: `CAST(record.<key>, 'Nullable(String)')` for keys and
  timestamps, `CAST(record.<key>, 'Nullable(Float64)')` for values (numbers may be stored as
  `Int64` or `Float64`). A missing path or a `null` value reads as `NULL`.
- `record` may in future contain keys this version does not know. They become new paths, and
  readers ignore them.
- Freshness: `max(loaded_at)` is expected to be newer than 6 h while the pipeline is active.
