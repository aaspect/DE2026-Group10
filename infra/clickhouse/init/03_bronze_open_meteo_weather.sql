-- Raw Open-Meteo weather, one row per location per hour per run.
--
-- Created once, on a fresh data volume, after 01_databases.sql. Append-only, and written only by
-- the ingestion job (ingestion/open_meteo/bronze.py), which never runs DDL. Init scripts do not run
-- again on an existing volume, so a change here needs a migration or `make reset`.
--
-- `record` is ClickHouse's native JSON type without type hints: it holds every key and value of
-- one record, read as `record.<key>`. Timestamps inside it stay strings, because the job inserts
-- with input_format_try_infer_datetimes=0; typing happens in silver.
CREATE TABLE IF NOT EXISTS bronze.open_meteo_weather
(
    record      JSON,
    run_id      UUID,
    source_type LowCardinality(String),
    loaded_at   DateTime('UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(loaded_at)
ORDER BY (source_type, loaded_at, run_id);
