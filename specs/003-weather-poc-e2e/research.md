# Research: Weather POC End-to-End Flow

Each decision lists what was chosen, why, and what else was considered. Decisions build on
feature 001 (job, run file contract) and feature 002 (stack, DAG, dbt skeleton).

## R1. The JSON document is stored in a native `JSON` column

- **Decision** (changed by the spec clarification of 2026-11-14): `bronze.open_meteo_weather`
  keeps each record in a `record JSON` column, ClickHouse's native JSON type (production-ready
  since 25.3, so no experimental setting on 25.8). No type hints are declared: every path is stored
  as `Dynamic` with the type ClickHouse infers. Three metadata columns are copied out next to it:
  `run_id UUID`, `source_type LowCardinality(String)` and `loaded_at DateTime('UTC')`. Silver
  reads paths as sub-columns (`record.location_id`) and casts them.
- **Inference**: the insert sends `input_format_try_infer_datetimes=0` (R3), so `hour_utc`,
  `forecast_version_at` and `loaded_at` inside the document stay strings exactly as delivered and
  typing happens only in silver. Numbers arrive as `Int64` (e.g. `"cloud_cover_pct":100`) or
  `Float64` variants; silver casts both to `Float64`. A `null` value is not stored as a path, and
  reading that path returns `NULL`, the same as the delivered value.
- **What is kept**: every key and value of the record (FR-003). Not kept: the original text (key
  order, number formatting). The run file is no longer a byte-for-byte copy of bronze; the
  quickstart compares values per key instead.
- **Rationale**: the documents can be queried by path without parsing functions, paths are stored
  as columns (compact, fast to read), and the layer is still raw: no key is renamed, typed or
  dropped by the loader. New keys from a later job version become new paths without a DDL change
  (`max_dynamic_paths` default 1024, far above the 16 keys).
- **Trade-off accepted**: a document that is not valid JSON cannot be stored; the insert is
  rejected and the run fails (spec edge case). The job always serialises with `json.dumps`, so this
  only happens on a bug, which should fail loudly.
- **Alternatives**: `String` column with the run-file line (byte-identical to the file, but every
  read needs `JSONExtract*` and invalid text could be stored; the team chose the native type
  instead). `JSON` with type hints for the value paths (a hint mismatch would reject the whole run
  at insert time and move typing into bronze; rejected). One typed column per record key (that is
  silver's job and would make bronze change whenever the record changes; rejected).

## R2. The stack's ClickHouse init script creates the bronze table

- **Decision**: The table definition is a new init script,
  `infra/clickhouse/init/03_bronze_open_meteo_weather.sql`. It runs after `01_databases.sql`
  when the ClickHouse volume is first created. Engine `MergeTree`,
  `PARTITION BY toYYYYMM(loaded_at)`, `ORDER BY (source_type, loaded_at, run_id)`. The job only
  inserts and never runs DDL. If the table is missing, the insert fails with ClickHouse's
  `UNKNOWN_TABLE` error and the run fails (exit 1). CI applies the same file before its dbt build
  (R12). See [contracts/bronze-table.md](contracts/bronze-table.md).
- **Rationale**: FR-006 is met "by the stack". It follows the existing pattern: `infra/` owns the
  warehouse layout, and the data dictionary said bronze DDL comes with the loading feature. No
  stack is deployed yet, so creating the table on a fresh volume is enough. The table exists before
  any job or dbt run, so dbt on empty bronze builds empty tables (edge case "empty bronze") instead
  of failing on a missing source. The job needs no DDL permissions. The sort key keeps rows of one
  run together, which is how bronze is traced.
- **Later schema changes**: init scripts run only on an empty volume. A change to this table after
  the stack is in use needs a migration or `make reset`. That is acceptable while everything is in
  implementation.
- **Alternatives**: The job runs `CREATE TABLE IF NOT EXISTS` before each insert (mixes DDL into
  the loader and splits warehouse layout between `infra/` and `ingestion/`; rejected). A dbt
  `on-run-start` hook (dbt must not write bronze, constitution V; rejected).

## R3. Inserts use ClickHouse's HTTP interface through the standard library

- **Decision**: A new `open_meteo/bronze.py` sends one `POST` per run to
  `$CLICKHOUSE_URL/?query=INSERT INTO bronze.open_meteo_weather (...) FORMAT JSONEachRow` with
  `urllib.request`. The body is one JSON line per bronze row, with the record as a nested object
  in `record`. Credentials go in the `X-ClickHouse-User` / `X-ClickHouse-Key` headers. Query
  settings sent with the request: `date_time_input_format=best_effort` (accepts the `...Z`
  timestamps of `loaded_at`), `input_format_try_infer_datetimes=0` (timestamps inside `record`
  stay strings, R1), `wait_end_of_query=1` (the HTTP status reflects the final outcome) and
  `input_format_parallel_parsing=0` (see R4).
- **Rationale**: Constitution II prefers the standard library. The client already uses `urllib`
  for Open-Meteo. A whole run is 360 to 840 rows, well below 1 MB, so batching or compression
  is not needed.
- **Alternatives**: `clickhouse-connect` (adds a dependency to the job and its lock file for one
  insert; rejected). Native-protocol `clickhouse-driver` (same objection, plus a second port).
  Loading run files afterwards from a separate task (a second moving part and a shared folder
  between tasks; the spec makes the job do the insert).

## R4. All-or-nothing insert

- **Decision**: One run is one `INSERT` statement, and the job does not retry it. ClickHouse
  inserts a `MergeTree` block atomically when the rows fit in one block
  (`max_insert_block_size`, default about 1 M rows) and fall into one partition. All rows of a run
  share `loaded_at`, so they always fall into one partition. Turning off parallel parsing makes
  sure the body is never split into several blocks. If the connection drops, the server
  discards the half-received block. Any non-200 response or connection error raises
  `BronzeLoadError`. The run then reports `outcome: failure` and exits with code 1.
- **Ambiguous outcome**: if the server commits but the response is lost, the run reports failure
  and Airflow retries it with a new `run_id`. Bronze then holds the same hours twice. Silver
  deduplicates them, so this is harmless and keeps bronze append-only.
- **Rationale**: Meets FR-005, SC-005 and the "partial insert" edge case without staging tables or
  delete-on-failure logic. That logic would also break the append-only rule (FR-004).
- **Alternatives**: Insert into a staging table, then `INSERT SELECT` (more DDL, same guarantee).
  `insert_deduplication_token` (only on replicated or non-replicated tables with dedup windows
  enabled; not needed).

## R5. Choosing the destination

- **Decision**: New setting `OPEN_METEO_DESTINATION` = `warehouse` (default) | `file` | `both`,
  overridable per run with `--destination`. Warehouse settings: `CLICKHOUSE_URL` (default
  `http://localhost:8123`), `CLICKHOUSE_USER`, `CLICKHOUSE_PASSWORD`. The user and password are
  required only when the destination includes the warehouse. If they are missing, the job
  refuses to start (exit 2). The output directory is prepared only when the destination includes
  the file. With `both`, the job inserts first and then writes the file. So a file exists only for
  runs whose insert succeeded. A file-write error after a successful insert fails the run but
  leaves the complete run in bronze (documented in the CLI contract).
- **Rationale**: FR-002 and FR-007. The variable names match what `compose.yaml` already passes to
  the Airflow container (`CLICKHOUSE_USER` and `CLICKHOUSE_PASSWORD` for the pipeline account), so
  only `CLICKHOUSE_URL=http://clickhouse:8123` is added there. Local runs outside Docker reach
  the published port by default.
- **Alternatives**: CLI flag only (cannot be set once in `ingestion/.env` for local file-mode work).
  Separate `--no-file` / `--no-warehouse` flags (two booleans with an invalid "neither" state).

## R6. Bronze rows carry the record dict itself

- **Decision**: The bronze row builder puts the record dict unchanged into `record`, and the
  insert body is serialised once with `json.dumps(row, ensure_ascii=False)`. The run file keeps its
  own serialisation in `write_records_atomically`, untouched. No shared serialiser is needed,
  because bronze no longer stores the file line as text (R1).
- **Rationale**: The same dict feeds both destinations, so bronze and the file hold the same keys
  and values (FR-003, SC-003). The file format stays exactly as in feature 001 (SC-007) because its
  code does not change.

## R7. Silver: parse, clean, deduplicate with full rebuilds

- **Decision**: `silver.open_meteo_weather` is a dbt `table` model, rebuilt in full on every run.
  - Keys are read as sub-columns cast to strings (`CAST(record.location_id, 'Nullable(String)')`),
    and timestamps with `parseDateTimeBestEffortOrNull(CAST(record.hour_utc,
    'Nullable(String)'), 'UTC')`. Rows with a missing or unparsable key (`location_id`,
    `hour_utc`, `source_type` not in `forecast`/`archive`) are excluded (FR-011). Invalid JSON
    cannot reach bronze (R1).
  - Values come from `CAST(record.<key>, 'Nullable(Float64)')`, which accepts both the `Int64` and
    `Float64` variants. The provider contract (feature 001) delivers only numbers or `null`, so a
    non-numeric value would fail the silver build rather than be silently dropped. Impossible
    values become `NULL` with `if(x < 0, NULL, x)` or a range check (FR-012). The limits are listed
    in [data-model.md](data-model.md#silver).
  - Deduplication: `ORDER BY loaded_at DESC, run_id DESC LIMIT 1 BY location_key,
    interval_start_utc, source_type, forecast_issued_utc` (FR-010). `run_id` breaks ties between
    two loads with the same second, so rebuilds are deterministic (FR-019).
  - `lead_time_h = toInt32(floor(dateDiff('second', forecast_issued_utc, interval_start_utc) /
    3600))`, that is, whole hours rounded down, so hours before the issue time are negative. It is
    `NULL` for archive rows (FR-013).
- **Rationale**: Data volume is tiny (about 530 k forecast rows and 44 k archive rows a year).
  dbt-clickhouse's `table` materialisation builds into a new table and swaps it in with
  `EXCHANGE TABLES`, so readers never see a half-built table. Full rebuilds avoid incremental-model
  edge cases and are trivially idempotent.
- **Alternatives**: `incremental` models with `ReplacingMergeTree` (the plan's demo query uses
  `FINAL`, which hints at this; more moving parts and `FINAL` on every read; deferred until volume
  needs it). `row_number()` window (same result, longer than `LIMIT BY`).

## R8. Gold keys and dimensions

- **`location_key`**: the configured location id (`tallinn`, ...). It is the natural key of an
  SCD1 dimension. Silver already renames `location_id` to it (FR-009).
- **`interval_key`**: `UInt64` built as `YYYYMMDDhhmm` of the UTC start (`202611140000`). It is
  readable, sorts in time order, and the same scheme can hold the 15-minute price intervals later
  without changing type.
- **`dim_location`**: from a dbt seed `dbt/seeds/silver/weather_locations.csv`, a copy of
  `ingestion/open_meteo/locations.toml` (dbt cannot read TOML). It is kept in sync by one pytest
  that compares the two files. The config is the source of truth, and a silent mismatch would
  drop a location's data from gold (edge case "unknown location"). The seed is built into
  `silver`, because bronze is written only by ingestion.
- **`dim_interval`**: generated with `numbers()` from 1 January of the year of the earliest silver
  hour to 31 December of the year of the latest silver hour. Built from silver: it always covers
  every fact hour (FR-015), backfills before any fixed start date included. For empty silver it is
  empty. Local attributes use `toTimeZone(..., 'Europe/Tallinn')`. Seasons are meteorological:
  winter = Dec–Feb, spring = Mar–May, summer = Jun–Aug, autumn = Sep–Nov.
- **`loaded_at` in gold**: `fact_weather.loaded_at` is the silver (bronze) load time, which is
  deterministic. In the dimensions, `loaded_at` is the dbt build time (`now()`). The plan defines
  it as "when the row was loaded". This is the one column excluded from the "identical results"
  check (FR-019), and the quickstart compares everything else.
- **Alternatives**: hashed surrogate keys (unreadable, and no join benefit at this size). A fixed
  `dim_interval` range such as 2020–2030 (a backfill before 2020 would fail the relationship
  test). A Python step that writes locations to bronze (the spec says the dimension comes from
  configuration, not bronze).

## R9. Data tests without extra packages

- **Decision**: Two small generic tests in `dbt/tests/generic/`. `unique_combination_of_columns`
  (`GROUP BY` the columns, `HAVING count() > 1`; ClickHouse groups `NULL` with `NULL`, so archive
  rows with no forecast version are handled). `within_range(min, max)` (non-null values outside
  the limits). Built-in tests cover the rest: `not_null`, `unique`, `accepted_values`,
  `relationships`.
- **Freshness**: `sources.yml` gives the bronze table `loaded_at_field: loaded_at` and
  `freshness: warn_after: {count: 6, period: hour}` with no `error_after`. `dbt source freshness`
  then exits 0 with a warning (FR-008). It runs as its own DAG task, `check_bronze_freshness`
  (R10), because `dbt build` does not check freshness and because a check inside `build_silver`
  would run only after a successful ingest, when bronze is fresh by definition.
- **Rationale**: `dbt_utils` would need `dbt deps` (network access at image build or run time and
  a `packages.yml`) for two macros of about 10 lines each. Constitution II.
- **Alternatives**: `dbt_utils` (rejected as above). Singular tests per model (repeats the same SQL
  for each grain; the generic tests are reused 4+ times, above the rule-of-three threshold).

## R10. DAG: the fetch tasks now load, and the build tasks run dbt

- **Decision**: The `load_bronze` placeholder is removed, because the job itself now loads
  bronze. The two fetch tasks are renamed `ingest_forecast` and `ingest_archive`, and they run
  the same commands (destination defaults to warehouse). `build_silver` becomes a `BashOperator`
  running `dbt build --select silver`. It has trigger rule `none_failed_min_one_success`, so it
  runs when the archive was skipped but not when an ingest failed. `build_gold` runs
  `dbt build --select gold marts`. A separate `check_bronze_freshness` task runs
  `dbt source freshness --select source:bronze.open_meteo_weather` after both ingest tasks with
  trigger rule `all_done`, so it also runs when an ingest failed (FR-008). It is a leaf: nothing
  depends on it, so it never blocks the builds, and a warning still exits 0. All dbt tasks use
  `--project-dir /opt/dbt` with the dbt venv. Schedule, params, `max_active_runs=1` and paused
  start are unchanged (FR-021). dbt tasks get `retries=0`. A failed test is not temporary, and a
  retry would only rebuild the same failing models. See
  [contracts/weather-dag.md](contracts/weather-dag.md).
- **Why the stopping works (FR-017, FR-022)**: inside one `dbt build`, a model's tests run before
  its children, and a failing test skips those children. Across tasks, a non-zero dbt exit fails
  the task, and Airflow marks the following tasks `upstream_failed`. The `table` swap (R7) means
  models that were not rebuilt keep their last good contents.
- **Selection**: `silver` matches the `silver` folder of both models and seeds (dbt FQN), so the
  location seed is rebuilt with silver. `gold marts` picks up the two other folders.
- **Alternatives**: Keep `load_bronze` as a no-op (a placeholder left in place violates FR-020).
  A separate dbt DAG triggered by datasets (deferred by the clarification). Astronomer Cosmos
  (new dependency; rejected in feature 002).

## R11. Superset dashboard as code: an import bundle applied on every start

- **Decision**: The dashboard is committed as a Superset export bundle (YAML) under
  `superset/dashboards/past_weather/`: `metadata.yaml`, `databases/`, `datasets/`, `charts/`,
  `dashboards/`. It is created once in the UI, exported with `superset export-dashboards`, and
  cleaned of instance-specific ids. The database YAML is a template whose `sqlalchemy_uri` is
  `${SUPERSET_WAREHOUSE_URI}`, and its UUID is fixed. `bootstrap.sh` replaces the
  `set-database-uri` step with a short stdlib script (`superset/render_bundle.py`) that fills the
  template and zips the bundle. `superset import-dashboards --path <zip> --username
  $SUPERSET_ADMIN_USER` then imports it. The import matches objects by UUID, so restarts never
  duplicate anything (FR-023). Found during implementation: in Superset 5.0 this command
  overwrites only the dashboard; an existing database, dataset or chart is left as it is and only
  created when missing. A changed chart therefore reaches an existing stack only after the old
  chart is deleted or the stack is reset. The database keeps the name
  `ClickHouse warehouse` and stays on the read-only reader account (FR-026).
- **Hourly refresh**: the dashboard's `json_metadata.refresh_frequency = 3600` (FR-025). Superset's
  data cache is not configured (null cache), so each refresh queries the mart.
- **Time axis**: charts use `interval_start_utc`, labelled "UTC". Superset turns timezone-aware
  values into naive UTC, so a `DateTime('Europe/Tallinn')` axis would not show local time
  reliably. Local date and hour are still in the mart (FR-018) for tables and later filters.
- **Fresh metadata assumed**: no stack is deployed yet, so the bundle's database (fixed UUID) is
  the only `ClickHouse warehouse` connection that ever exists. Re-imports update it by UUID.
- **Alternatives**: A Python script that calls the Superset REST API to create the dataset,
  charts and dashboard (much more code, and chart `form_data` still has to come from an export).
  Keep `set-database-uri` and import only the dashboard (the bundle must reference the database by
  UUID, which `set-database-uri` assigns at random).

## R12. CI runs the dbt build against a throwaway ClickHouse

- **Decision**: A new CI job `dbt` starts `clickhouse/clickhouse-server:25.8.33` as a service,
  applies the init SQL files (`01_databases.sql`, `03_bronze_open_meteo_weather.sql`) in
  file-name order with `docker exec <service> clickhouse-client --multiquery` (service containers
  start before checkout, so the init folder cannot be mounted, and the HTTP interface takes only
  one statement per request while `01_databases.sql` has three), then inserts the fixture
  `dbt/ci/bronze_open_meteo_weather.jsonl` the same way, with the same input settings as the job
  (R3). It runs `dbt build` (seeds included) and `dbt source freshness` with the same
  `dbt-clickhouse` pin as the Airflow image. The fixture holds about 30 rows that cover the US2
  scenarios: two overlapping archive runs, two forecast versions, one null value, one impossible
  value per limit, one document without `hour_utc`, one unknown location.
- **Rationale**: Constitution workflow: CI runs "dbt tests where applicable", and the models are
  now applicable. The fixture turns US2's independent test into an automatic check, with no
  Python tests for SQL behaviour (constitution III: warehouse quality is checked with dbt tests).
  The CI profile uses `CLICKHOUSE_HOST` (new env var in `profiles.yml`, default `clickhouse`) to
  reach `localhost`.
- **Alternatives**: `dbt parse` only (catches syntax errors, not wrong results). Running the whole
  Compose stack in CI (slow, and not needed to test SQL).

## R13. Mart shape

- **Decision**: `gold.mart_past_weather` is a `table` model: archive rows of `fact_weather` joined
  to both dimensions, one row per `location_key` and `interval_start_utc`. It has the location
  name, role and zone, the UTC start, the local date, hour, day of week and weekend flag, and the
  seven values. It is ordered by `(location_key, interval_start_utc)`.
- **Rationale**: FR-018 (hourly, denormalised). At about 44 k rows a year, the mart's queries
  take 10–60 ms, with no pre-aggregation needed.
- **Measured (SC-006)**: with the default "Last week" range, a filter change updates every chart
  well under 3 s. With one year selected it takes about 3 s for one location and about 9 s for
  all five. The time is spent in Superset, not ClickHouse: it reshapes each time-series chart's
  rows in Python (about 1.5 s per chart for 43 800 rows) and its one web worker does the five
  charts one after another. Accepted as it is for the POC; more web workers
  (`SERVER_WORKER_AMOUNT`) roughly halve it at the cost of memory.

## R14. Python tests changed or added (constitution III, IV)

| Test file | Change | Behaviour covered |
|---|---|---|
| `tests/open_meteo/test_bronze.py` | **new** | bronze rows are built from records: `record` is the record dict itself, and the metadata columns are copied out. The insert request is one POST with one line per record (stub opener). A non-200 response or connection error raises `BronzeLoadError`. |
| `tests/open_meteo/test_job.py` | **updated** | default destination inserts all records in one call and writes no file. A failed insert gives outcome failure and no file. `both` writes the file only after the insert. The existing file-mode tests now pass `destination=file`. |
| `tests/open_meteo/test_config.py` | **updated** | the destination is parsed and validated, and the warehouse credentials are required only for warehouse destinations |
| `tests/open_meteo/test_locations_seed.py` | **new** | the dbt location seed matches `locations.toml` |

No regression-only tests are added. SQL behaviour is covered by dbt tests and the CI fixture (R12).
