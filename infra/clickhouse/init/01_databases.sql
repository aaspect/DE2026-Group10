-- Warehouse layers, one database each. Bronze tables are created by the later init scripts
-- (03_*.sql), silver and gold tables are built by dbt.

-- Raw data as ingested, append-only. Written by the ingestion loaders.
CREATE DATABASE IF NOT EXISTS bronze;

-- Cleaned, typed, deduplicated data. Written by dbt.
CREATE DATABASE IF NOT EXISTS silver;

-- Facts, dimensions and marts. Written by dbt; the only layer Superset reads.
CREATE DATABASE IF NOT EXISTS gold;
