# Research: Elering Electricity Prices Pipeline

Each decision records what was chosen, why, and what alternatives were considered. Where earlier
project documentation (`docs/project_plan.pdf`, `docs/examples.sql`, `infra/README.md`) conflicts
with decisions established in the weather pipeline (`specs/003-weather-poc-e2e`), the weather
pipeline takes precedence.

## R1. Elering API request boundaries, chunking, and response contract

- **Decision**: The ingestion job queries `GET https://dashboard.elering.ee/api/nps/price` with
  ISO-8601 UTC query parameters `start` and `end` (`YYYY-MM-DDTHH:MM:SSZ`), URL-encoded via
  `urllib.parse.urlencode`.
  - **Inclusive boundaries**: Live verification against `dashboard.elering.ee/api/nps/price`
    confirms that both `start` and `end` are **inclusive** on interval start timestamps (e.g.
    `start=2025-09-30T21:00:00Z&end=2025-09-30T23:00:00Z` returns `21:00`, `22:00`, `22:15`,
    `22:30`, `22:45`, **and** `23:00`, whereas `end=2025-09-30T22:59:59Z` stops at `22:45`). To
    request any half-open UTC window `[start_utc, end_utc)` without overlapping adjacent windows or
    chunks, the client sends `start = start_utc` and `end = end_utc - 1 second`.
  - **Chunking**: Elering enforces a hard maximum span of **1 year** per request (returning HTTP
    400 `{"status":"BAD_REQUEST","messages":["Maximum period is 1 year"]}`). Backfill ranges are
    split into contiguous half-open chunks of `ELERING_CHUNK_DAYS` days (default **31**, valid
    `1..365`). A 1-year backfill takes 12 small requests (~400 KB max each at 15-min resolution)
    and completes in seconds.
  - **Response format**: `{"success": true, "data": {"ee": [{"timestamp": 1759269600, "price": 98.95}, ...], "fi": [...], "lv": [...], "lt": [...]}}`.
    `timestamp` is Unix epoch seconds in UTC; `price` is a finite JSON number in EUR/MWh (may be
    negative or zero); zone keys are lower-case.
- **Rationale**: Matches empirically verified provider behaviour, avoids off-by-one duplicate
  boundary intervals between chunks or consecutive daily runs, and satisfies FR-003 (1-year+
  backfills in a single run) and SC-002 (< 5 minutes).
- **Alternatives**: Requesting 365 days in a single HTTP call (larger payloads, higher timeout
  risk, still fails on > 1-year backfills; rejected). Using `fields` query parameter per zone (4×
  as many HTTP requests when a single request already returns all 4 zones; rejected). Using the
  `/api/nps/price/csv` endpoint (non-JSON format, breaks native JSON bronze pattern; rejected).

## R2. Daily mode window (`D+1` in Europe/Tallinn) and DST / MTU boundary math

- **Decision**: Daily mode targets only the next Europe/Tallinn calendar day (`D+1`), derived using
  Python 3.12's stdlib `zoneinfo.ZoneInfo("Europe/Tallinn")`:
  - `local_today = now.astimezone(TALLINN_TZ).date()`
  - `target_date = local_today + timedelta(days=1)`
  - `start_utc = datetime(target_date.year, target_date.month, target_date.day, tzinfo=TALLINN_TZ).astimezone(UTC)`
  - `end_utc = datetime(next_day.year, next_day.month, next_day.day, tzinfo=TALLINN_TZ).astimezone(UTC)`
  - On standard days this spans 24 UTC hours (96 post-switch slots/zone); on spring DST it spans
    23 UTC hours (92 slots/zone); on autumn DST it spans 25 UTC hours (100 slots/zone). Consecutive
    daily runs tile seamlessly with zero UTC gaps or duplicates.
  - **Backfill mode** takes inclusive UTC dates `--start-date` and `--end-date`, producing
    `[start_date 00:00:00Z, (end_date + 1 day) 00:00:00Z)`, and rejects `end_date > local_tomorrow`
    before contacting the provider (FR-004).
  - **Expected interval count**: For any half-open UTC window `[start_utc, end_utc)` and a zone's
    configured `mtu_switch_utc` (`2025-09-30T22:00:00Z`), expected slots equal
    `pre_switch_hours * (60 // historical_mtu_minutes) + post_switch_hours * (60 // current_mtu_minutes)`.
    This handles pre-switch hourly periods, post-switch 15-minute periods, windows straddling
    `2025-09-30T22:00:00Z` (e.g. `2025-09-30` UTC = 22 + 8 = 30 slots), and 23/24/25-hour DST days
    with one formula.
- **Rationale**: Uses stdlib `zoneinfo` (no new dependencies, Constitution II), directly implements
  the 2026-11-22 clarification (`D+1` only; missed days recovered via backfill), and eliminates
  hard-coded slot counts (96) that would fail on DST days or pre-switch backfills.
- **Alternatives**: Hard-coding 96 slots/day (breaks on spring/autumn DST days and pre-October 2025
  backfills; rejected). Fetching a rolling 48-hour lookback in daily mode (rejected during spec
  clarification in favour of `D+1` only + explicit backfill).

## R3. Self-contained ingestion package (`ingestion/elering_prices/`)

- **Decision**: Implement Elering prices ingestion as a standalone package
  `ingestion/elering_prices/` mirroring `ingestion/open_meteo/` (`__main__.py`, `config.py`,
  `periods.py`, `client.py`, `records.py`, `bronze.py`, `output.py`, `job.py`,
  `bidding_zones.toml`), added to `[tool.hatch.build.targets.wheel] packages` in
  `ingestion/pyproject.toml`. No shared abstraction package is extracted yet.
- **Rationale**: Constitution Principle II states *"Each data source is handled by its own small,
  self-contained ingestion module"*, and Constitution Principle I establishes the Rule of Three
  (*"Duplicate logic MUST be extracted once it appears in a third place"*). `elering_prices` is the
  second source; extracting a shared framework now would violate both principles. When the third
  source (`elering_system`) arrives, common ClickHouse/output helpers can be extracted once.
- **Alternatives**: Creating `ingestion/common/` now for HTTP retries, ClickHouse insert, and
  atomic file writes (premature abstraction on the 2nd source, violates Rule of Three; rejected).

## R4. Native `JSON` bronze table created by ClickHouse init script

- **Decision**: Create `bronze.elering_prices` via a new init script
  `infra/clickhouse/init/04_bronze_elering_prices.sql`:
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
  - Matches `bronze.open_meteo_weather` (`record JSON`, metadata columns copied out, append-only,
    never altered by the job).
  - The job inserts all records of a run in a single HTTP `POST` to ClickHouse (`FORMAT
    JSONEachRow`) with `date_time_input_format=best_effort`, `input_format_try_infer_datetimes=0`,
    `wait_end_of_query=1`, and `input_format_parallel_parsing=0`.
  - A 1-year post-switch backfill for 4 zones is ~140 160 rows (~25 MB NDJSON), well below
    ClickHouse's `max_insert_block_size` (~1 M rows), so all rows of a run still land in a single
    atomic MergeTree block in one partition (since all rows share `loaded_at`).
  - Destination support (`warehouse` default | `file` | `both`) mirrors `open_meteo` via
    `ELERING_DESTINATION` / `--destination`; in `both` mode the warehouse insert succeeds before
    the local JSONL file is written atomically via `os.link`.
- **Rationale**: Aligns 100 % with the weather pipeline (taking precedence over the stale typed
  `bronze.elering_prices` sketch in `infra/README.md`), satisfies FR-011–FR-017 and SC-006, and
  requires zero extra Python dependencies (stdlib `urllib.request`).
- **Alternatives**: Typed bronze columns from `infra/README.md` (conflicts with weather pipeline
  precedence; rejected). `clickhouse-connect` library (adds a dependency for one HTTP POST;
  rejected).

## R5. Raw record schema and validation rules

- **Decision**: Each flattened record dict (feeding both `record` in bronze and lines in local
  `.jsonl` files) contains exactly six keys:
  - `zone_code`: lower-case zone code as delivered by Elering (`"ee"`, `"fi"`, `"lv"`, `"lt"`)
  - `interval_start_utc`: ISO-8601 UTC string (`"2025-09-30T22:00:00Z"`) converted from epoch seconds
  - `price_eur_mwh`: numeric EUR/MWh price as delivered (float/int, preserving negative and zero
    values without rounding or filtering)
  - `mode`: `"daily"` or `"backfill"`
  - `run_id`: UUID4 string
  - `loaded_at`: ISO-8601 UTC string (`YYYY-MM-DDTHH:MM:SSZ`)
- **Validation before storage (FR-008)**:
  - Each chunk response must be a JSON object with `success is True` and a `data` dict.
  - Every configured zone's lower-case code must exist in `data` as a non-empty list.
  - Every item must be a dict with an integer `timestamp` (not `bool`) whose UTC instant falls
    within `[chunk_start, chunk_end)` and a finite numeric `price` (`int | float`, not `bool`,
    `math.isfinite`).
  - No duplicate `(zone_code, interval_start_utc)` pairs may occur within a chunk or across chunks.
  - For each zone, the delivered item count in each chunk must equal the exact expected interval
    count for that chunk's UTC span (accounting for `mtu_switch_utc`).
  - Any violation raises `InvalidResponseError` (no internal job retries; fails immediately with
    exit 1 and zero rows written).
- **Rationale**: Ensures incomplete day-ahead publications (e.g. only 2 of 4 zones published, or
  fewer than 96/92/100 slots) fail fast so Airflow's hourly retry can pick up the complete day
  later, while never polluting bronze with partial runs.
- **Alternatives**: Uppercasing `zone_code` in ingestion (spec FR-007 & FR-019 explicitly state
  bronze keeps the provider's lower-case code and silver standardizes to uppercase; rejected).
  Validating only total row count across all zones (could mask one zone having duplicates while
  another is missing slots; rejected).

## R6. Silver parsing, safe casting, cleaning, and deduplication

- **Decision**: `silver.elering_prices` is a dbt full-rebuild `table` model (`MergeTree`,
  `ORDER BY (zone_code, interval_start_utc)`):
  - **Safe casting from native `JSON`**:
    - `upper(trim(accurateCastOrNull(record.zone_code, 'String'))) as zone_code`
    - `parseDateTimeBestEffortOrNull(accurateCastOrNull(record.interval_start_utc, 'String'), 'UTC') as interval_start_utc`
    - `accurateCastOrNull(record.price_eur_mwh, 'Float64') as price_eur_mwh`
  - **Why `accurateCastOrNull` instead of `CAST`**: ClickHouse `JSON` sub-columns have type
    `Dynamic`. Plain `CAST(record.price_eur_mwh, 'Nullable(Float64)')` throws `CANNOT_PARSE_TEXT`
    when a malformed bronze document contains a string like `"bad"` or a non-convertible JSON
    array. `accurateCastOrNull` safely converts `Int64`, `Float64`, and numeric `String` variants
    to `Float64` and returns `NULL` for unparsable strings or incompatible types without failing
    the build.
  - **Non-blocking filtering (FR-021)**: Keep only rows where:
    - `zone_code in (select distinct zone_code from {{ ref('bidding_zones') }})` (matches the
      configured bidding zones `EE`, `FI`, `LV`, `LT` without hard-coding the list in SQL)
    - `interval_start_utc is not null`
    - `price_eur_mwh is not null and isFinite(price_eur_mwh)`
    - `price_eur_mwh >= -500 and price_eur_mwh <= 5000`
    Negative prices down to `-500` and zero prices are kept unchanged; malformed or out-of-bounds
    rows stay untouched in bronze and are excluded from silver without failing the build.
  - **Deduplication (FR-020)**: `ORDER BY loaded_at DESC, run_id DESC LIMIT 1 BY zone_code,
    interval_start_utc`. Preserves delivered market intervals (60-minute pre-switch, 15-minute
    post-switch).
  - **Numeric type `Float64`**: Matches `silver.open_meteo_weather` and `gold.fact_weather` (which
    use `Float64` rather than the ERD's `Decimal`), preserves exact EUR/MWh values without
    premature rounding, and ensures `avg()` in `fact_price` yields exact arithmetic means of four
    15-minute slots (e.g. `.xx25`, `.xx5`, `.xx75`, satisfying SC-003).
- **Rationale**: Satisfies FR-019–FR-022 and the 2026-11-22 clarification cleanly, handles
  heterogeneous ClickHouse `Dynamic` sub-columns without runtime cast failures, and keeps
  rebuilds trivially idempotent.
- **Alternatives**: `Decimal(10, 2)` (rounds 4-slot hourly means like `10.0225` to `10.02`,
  violating SC-003 "exact arithmetic mean", and diverges from `fact_weather`'s `Float64`; rejected).
  `toFloat64OrNull(record.price_eur_mwh)` (throws `ILLEGAL_TYPE_OF_ARGUMENT` on ClickHouse
  `Dynamic` sub-columns containing `Int64`/`Float64`; rejected).

## R7. Bidding-zone reference config, dbt seed, and `dim_bidding_zone` (SCD Type 2)

- **Decision**:
  - Ingestion reads `ingestion/elering_prices/bidding_zones.toml` (4 `[[zones]]` entries for `EE`,
    `FI`, `LV`, `LT`, each with `code`, `name`, `historical_mtu_minutes = 60`,
    `current_mtu_minutes = 15`, `valid_from = "1970-01-01T00:00:00Z"`, and
    `mtu_switch_utc = "2025-09-30T22:00:00Z"`).
  - dbt maintains a matching seed `dbt/seeds/silver/bidding_zones.csv` (8 rows: 2 SCD-2 versions
    per zone, `zone_key` 1–8) with string ISO-8601 timestamps (`valid_from`, `valid_to` empty for
    current) so `dbt seed` / `agate` never suffers locale/timezone inference issues.
  - A pytest (`ingestion/tests/elering_prices/test_bidding_zones_seed.py`) derives the expected
    8 SCD-2 rows from `bidding_zones.toml` and asserts exact parity with `bidding_zones.csv`
    (mirroring `test_locations_seed.py`).
  - `gold.dim_bidding_zone` (`dbt/models/gold/dim_bidding_zone.sql`) reads `{{ ref('bidding_zones') }}`,
    casts `valid_from` to `DateTime('UTC')` and empty/null `valid_to` to `Nullable(DateTime('UTC'))`,
    and adds `toDateTime(now(), 'UTC') as loaded_at`.
  - Why `1970-01-01T00:00:00Z` for `valid_from`: ClickHouse `DateTime('UTC')` is unsigned 32-bit
    epoch seconds starting at `1970-01-01 00:00:00`, so `1970-01-01T00:00:00Z` covers every
    historical pre-switch timestamp representable in ClickHouse.
- **Rationale**: Matches `weather_locations.csv` / `dim_location.sql`, supports adding future
  SCD-2 market regime versions cleanly, and prevents silent config-vs-seed drift via CI pytest.
- **Alternatives**: Hard-coding the 8 rows inside `dim_bidding_zone.sql` (duplicates config into
  SQL and skips the seed pattern; rejected). Storing `DateTime('UTC')` directly in the seed CSV
  (fragile with agate timestamp inference and nullable empty cells; rejected).

## R8. Shared `dim_interval` spanning both weather and prices

- **Decision**: Update `dbt/models/gold/dim_interval.sql` so its `bounds` CTE unions
  `interval_start_utc` from both `{{ ref('open_meteo_weather') }}` and `{{ ref('elering_prices') }}`.
  All columns, types (`UInt64` `interval_key`, `Europe/Tallinn` local attributes), deferred columns
  (`is_ee_holiday`, `tariff_period`, `quarter_of_hour`), and empty-silver behaviour (empty table
  only when *both* silver sources are empty) remain unchanged.
- **Rationale**: Directly satisfies FR-024 and SC-005 (passes even when weather bronze is empty
  and only prices exist, or vice versa) with a 4-line diff to `dim_interval.sql`.
- **Alternatives**: Separate `dim_interval_price` table (breaks the star schema's conformed time
  dimension; rejected). Fixed year range 2020–2030 (breaks on backfills outside the range and
  diverges from the weather pipeline's data-driven range; rejected).

## R9. `fact_price` aggregation, SCD-2 join, and interior-day completeness test

- **Decision**: `gold.fact_price` (`dbt/models/gold/fact_price.sql`) is a full-rebuild `table`
  model (`MergeTree`, `ORDER BY (zone_key, interval_start_utc)`):
  - Aggregates `silver.elering_prices` by `(zone_code, toStartOfHour(interval_start_utc))`:
    - `avg(price_eur_mwh) as price_eur_mwh` (exact delivered price for 60-min pre-switch rows;
      exact arithmetic mean of available valid 15-min slots for post-switch rows)
    - `max(loaded_at) as loaded_at`
  - Inner-joins `{{ ref('dim_bidding_zone') }}` on:
    `hourly.zone_code = dim_zone.zone_code AND hourly.interval_start_utc >= dim_zone.valid_from AND (dim_zone.valid_to IS NULL OR hourly.interval_start_utc < dim_zone.valid_to)`.
  - Derives `interval_key` with `toUInt64(formatDateTime(interval_start_utc, '%Y%m%d%H%i', 'UTC'))`.
  - **Tests**:
    - Built-in/generic tests in `gold.yml`: `unique_combination_of_columns` on `[zone_key,
      interval_key]` and `[zone_key, interval_start_utc]`; `not_null` on all 5 columns;
      `relationships` to `dim_interval` and `dim_bidding_zone`; `within_range(-500, 5000)` on
      `price_eur_mwh`.
    - Singular tests in `dbt/tests/`:
      1. `dim_bidding_zone_no_overlapping_windows.sql`: fails if any two versions of the same
         `zone_code` have overlapping `[valid_from, valid_to)` intervals.
      2. `dim_bidding_zone_one_current_per_zone.sql`: fails if any `zone_code` does not have
         exactly one `is_current = true` row.
      3. `fact_price_complete_interior_days.sql`: computes `min_date` and `max_date` across
         `fact_price`, generates every interior UTC date `d` with `min_date < d < max_date` crossed
         with every `zone_code` present in `fact_price` (joined via `dim_bidding_zone`), and fails
         if any `(zone_code, d)` pair does not have exactly 24 hourly rows.
- **Why group completeness by `zone_code` instead of `zone_key`**: On `2025-09-30` (UTC), hours
  `00:00Z..21:00Z` link to the 60-minute `zone_key` (22 rows) and hours `22:00Z..23:00Z` link to
  the 15-minute `zone_key` (2 rows). Grouping by `zone_code` correctly counts `22 + 2 = 24` rows
  for the MTU transition day, and crossing interior dates with active zones also catches completely
  missing interior days (0 rows). When `fact_price` is empty or contains only a single daily `D+1`
  run (spanning 2 partial UTC dates), there are zero interior days and the test passes cleanly.
- **Rationale**: Satisfies FR-025, FR-026, SC-003, SC-005 without external dbt packages.
- **Alternatives**: Checking 96 intervals per UTC day (only applies to post-switch silver, not
  60-minute gold, and fails on pre-switch days; rejected). Grouping completeness by `zone_key`
  (falsely fails on `2025-09-30`; rejected).

## R10. Airflow DAG schedule, retries, params, and concurrency serialisation

- **Decision**:
  - New DAG `airflow/dags/elering_prices.py`:
    - `dag_id="elering_prices"`, `is_paused_upon_creation=True`, `max_active_runs=1`,
      `catchup=False`.
    - `schedule=CronTriggerTimetable("30 14 * * *", timezone="Europe/Tallinn")` (Airflow 3.1.8
      native timezone-aware cron timetable; tracks EET/EEST DST automatically so daily runs always
      fire at 14:30 Tallinn time after Nord Pool's ~13:45 Tallinn publication).
    - Manual trigger `params`: optional `start_date` and `end_date` (nullable strings, `YYYY-MM-DD`).
      Passed into `ingest_prices` via `BashOperator(env=..., append_env=True)` to avoid shell
      quoting bugs; when empty, runs `daily` mode; when either is set, runs `backfill --start-date
      ... --end-date ...` (letting the Python job validate that both are provided and valid).
    - `ingest_prices`: `retries=6`, `retry_delay=timedelta(hours=1)` (FR-029).
    - `build_silver`: `dbt build --project-dir /opt/dbt --select silver`, `retries=0`,
      `pool="dbt_build"`.
    - `build_gold`: `dbt build --project-dir /opt/dbt --select gold`, `retries=0`,
      `pool="dbt_build"`.
    - `check_bronze_freshness`: `dbt source freshness --project-dir /opt/dbt --target-path
      /tmp/dbt-freshness-elering --select source:bronze.elering_prices`, `trigger_rule="all_done"`,
      `retries=0` (leaf task, never blocks builds, warns when `max(loaded_at)` > 26 hours).
  - **Concurrency serialisation (FR-031)**:
    - `airflow/entrypoint.sh` runs `airflow db migrate` followed by
      `airflow pools set dbt_build 1 "Serialises dbt builds across pipelines so shared tables do not clash."`
      before `exec airflow standalone` (idempotent on every start and after `make reset`).
    - Both `open_meteo_weather.py` and `elering_prices.py` assign `pool="dbt_build"` to their
      `build_silver` and `build_gold` tasks, and isolate their `check_bronze_freshness` tasks'
      `--target-path` to `/tmp/dbt-freshness-<source>`.
    - Why `build_silver` uses `--select silver` in both DAGs: `dim_interval` reads both
      `silver.open_meteo_weather` and `silver.elering_prices`. Running `--select silver` guarantees
      both silver tables exist (even when one bronze table is empty) regardless of which DAG runs
      first on a fresh stack.
- **Rationale**: Native Airflow 3.1 pool serialisation requires zero new dependencies, prevents
  both ClickHouse `EXCHANGE TABLES` collisions on `dim_interval` and concurrent writes to
  `/opt/dbt/target/`, visibly queues overlapping tasks in the Airflow UI, and aligns with the
  2026-11-22 clarification.
- **Alternatives**: Using `flock` inside bash commands (hides queuing inside a running task slot
  and isn't visible in Airflow UI; rejected). Fixed UTC cron `30 12 * * *` (shifts between 14:30
  winter and 15:30 summer; rejected in favour of `CronTriggerTimetable(..., timezone="Europe/Tallinn")`).
  Separate shared dbt DAG triggered by Airflow Assets (rejected during spec clarification).

## R11. Bronze freshness threshold (26 hours)

- **Decision**: In `dbt/models/sources.yml`, register `bronze.elering_prices` with
  `loaded_at_field: loaded_at` and `freshness: warn_after: {count: 26, period: hour}` (no
  `error_after`).
- **Rationale**: Matches FR-018 (24-hour daily cycle + 2-hour publication grace window), warns
  without failing the task, and mirrors `bronze.open_meteo_weather`'s `warn_after: 6 hours`.
- **Alternatives**: Setting `error_after` (would fail the freshness task, violating FR-018;
  rejected).

## R12. CI dbt fixture and verification (FR-033)

- **Decision**: Extend `.github/workflows/ci.yml`'s `dbt` job:
  - Apply `infra/clickhouse/init/04_bronze_elering_prices.sql` after `03_bronze_open_meteo_weather.sql`.
  - Load a new fixture `dbt/ci/bronze_elering_prices.jsonl` into `bronze.elering_prices` using the
    same ClickHouse input settings as the ingestion job (`--date_time_input_format=best_effort
    --input_format_try_infer_datetimes=0`).
  - The fixture covers all US3 / FR-033 scenarios across `EE`, `FI`, `LV`, `LT`:
    - `2025-09-29 23:00Z` (leading boundary pre-switch hour)
    - Full UTC day `2025-09-30` (interior UTC day crossing the `2025-09-30T22:00:00Z` MTU switch:
      22 hourly pre-switch slots + 8 quarter-hour post-switch slots per zone), so the
      `fact_price_complete_interior_days` test exercises an actual MTU-transition interior day
    - `2025-10-01 00:00Z..00:45Z` (trailing boundary post-switch hour)
    - Negative price (e.g. `-25.50` EUR/MWh) and zero price (`0.00` EUR/MWh)
    - Exact 4-slot fractional mean (e.g. `10.01, 10.02, 10.03, 10.03` → `10.0225`)
    - Overlapping load with newer `loaded_at` winning over older `loaded_at`
    - Same-second `loaded_at` tie broken deterministically by larger `run_id`
    - Invalid/excluded bronze rows: missing `interval_start_utc`, unparsable string price `"bad"`,
      unknown zone `"se"`, price below `-500` (`-500.01`), price above `5000` (`5000.01`)
  - Extend `dbt/ci/assert_fixture_results.sql` with `throwIf(...)` assertions verifying silver row
    counts, excluded invalid rows, uppercase zones, negative/zero preservation, deduplication
    winner & tie-breaker, `dim_bidding_zone` SCD-2 rows, `dim_interval` covering both 2025 (prices)
    and 2026 (weather), and `fact_price` hourly aggregation & historical `zone_key` linkage.
- **Rationale**: Turns US3's independent test into an automated CI gate without adding Python SQL
  tests (Constitution III).
- **Alternatives**: Testing only with empty `bronze.elering_prices` in CI (would not verify
  aggregation, deduplication, or SCD-2 joins; rejected).

## R13. Offline pytest coverage (Constitution III & IV)

| Test file | Change | Core behaviour covered |
|---|---|---|
| `ingestion/tests/elering_prices/test_config.py` | **new** | Env/default settings parsing, destination validation, warehouse credential requirement, `bidding_zones.toml` validation (missing keys, empty list, duplicate zone codes, invalid timestamps/MTU). |
| `ingestion/tests/elering_prices/test_periods.py` | **new** | Daily `D+1` Europe/Tallinn resolution (standard, spring 23h DST, autumn 25h DST), backfill inclusive UTC resolution, invalid range refusal (`start > end`, malformed date, single bound, `end > D+1`), chunk splitting, and expected interval counts before/after/across `2025-09-30T22:00:00Z`. |
| `ingestion/tests/elering_prices/test_client.py` | **new** | Query parameter formatting (`start`, inclusive `end - 1s`), retry with exponential backoff on 429/5xx/connection errors, immediate `InvalidResponseError` on 4xx/non-JSON without retry. |
| `ingestion/tests/elering_prices/test_records.py` | **new** | Response validation (`success`, missing zone, empty list, bad timestamp/out-of-window, non-numeric/NaN/bool price, duplicate timestamps, wrong slot count) and record building preserving negative/zero prices and lower-case provider zone codes. |
| `ingestion/tests/elering_prices/test_bronze.py` | **new** | Bronze row wrapping (`record` unchanged + `run_id`, `mode`, `loaded_at`), single atomic POST request format, and `BronzeLoadError` on HTTP/connection error. |
| `ingestion/tests/elering_prices/test_job.py` | **new** | Multi-chunk run aggregation into one atomic bronze insert, destination modes (`warehouse`, `file`, `both` ordering), zero rows/no file on fetch/validation/insert failure, report formatting. |
| `ingestion/tests/elering_prices/test_bidding_zones_seed.py` | **new** | Parity between `ingestion/elering_prices/bidding_zones.toml` and `dbt/seeds/silver/bidding_zones.csv`. |

All tests run offline with stub openers/sleep functions and recorded fixtures in well under 10 s
(SC-007). No existing weather tests require modification because `open_meteo` behaviour is
unchanged.
