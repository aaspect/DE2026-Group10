-- Warehouse layers, one database each. No tables are created here: bronze tables come with the
-- loading features, silver and gold are built by dbt.

-- Raw data as ingested, append-only. Written by the ingestion loaders.
CREATE DATABASE IF NOT EXISTS bronze;

-- Cleaned, typed, deduplicated data. Written by dbt.
CREATE DATABASE IF NOT EXISTS silver;

-- Facts, dimensions and marts. Written by dbt; the only layer Superset reads.
CREATE DATABASE IF NOT EXISTS gold;
