---

description: "Task list for the Weather POC end-to-end flow"
---

# Tasks: Weather POC End-to-End Flow

**Input**: Design documents from `specs/003-weather-poc-e2e/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Included. FR-027 and research R14 ask for offline pytest coverage of the new core
behaviour (bronze rows, all-or-nothing insert, destination rule, seed sync) and updates to
existing tests. R9 and R12 ask for dbt data tests and a CI dbt job. No regression-only tests
(constitution IV).

**Organization**: Tasks are grouped by user story so each story can be implemented and tested on
its own.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: The user story the task belongs to (US1–US4)
- Paths are relative to the repository root

## Conventions every task must follow

- Python: 3.12, standard library only for new code (no new packages), passes `make lint`
  (ruff check + ruff format). Follow the style of the existing `ingestion/open_meteo/*.py`
  modules (module docstring, small functions, type hints, `ConfigError` for refused starts).
- Never log or report `CLICKHOUSE_PASSWORD` or a URI containing it.
- dbt: project `energy_analytics`, adapter `dbt-clickhouse==1.9.8`, ClickHouse 25.8. Models are
  `materialized='table'` with `engine='MergeTree()'` and an explicit `order_by`. Do not put a
  `Nullable` column in `order_by` (ClickHouse rejects it without `allow_nullable_key`).
- All timestamps are `DateTime('UTC')`. Local time (`Europe/Tallinn`) appears only in
  `gold.dim_interval` and `gold.mart_past_weather`.
- Bronze record keys (from `ingestion/open_meteo/records.py`): `location_id`, `hour_utc`,
  `source_type`, `forecast_version_at`, `temperature_2m_c`, `wind_speed_10m_ms`,
  `wind_direction_10m_deg`, `shortwave_radiation_wm2`, `direct_radiation_wm2`,
  `cloud_cover_pct`, `precipitation_mm`, `grid_latitude`, `grid_longitude`, `grid_elevation_m`,
  `run_id`, `loaded_at`. Timestamps are formatted `YYYY-MM-DDTHH:MM:SSZ`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Configuration surface shared by the job, dbt and CI.

- [X] T001 [P] Add commented entries for the new job settings to `ingestion/.env.example`, in the existing `# NAME=default` style: `# OPEN_METEO_DESTINATION=warehouse` (with a comment line `# warehouse | file | both`), `# CLICKHOUSE_URL=http://localhost:8123`, `# CLICKHOUSE_USER=pipeline`, `# CLICKHOUSE_PASSWORD=pipeline` (comment: loading account from the root `.env`, never the reader account; required only when the destination includes warehouse).
- [X] T002 [P] Make the dbt host configurable in `dbt/profiles.yml`: `host: "{{ env_var('CLICKHOUSE_HOST', 'clickhouse') }}"`, and update the file's header comment to say CI sets `CLICKHOUSE_HOST=localhost` (R12). Leave everything else unchanged.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The bronze table is the hand-over point between the job (US1) and dbt (US2); both
need it to exist.

**⚠️ CRITICAL**: No user story work can be verified until this phase is complete.

- [X] T003 Create `infra/clickhouse/init/03_bronze_open_meteo_weather.sql` with a header comment (created once on a fresh volume after `01_databases.sql`; append-only; written only by the ingestion job; a change needs a migration or `make reset`) and exactly this DDL from `contracts/bronze-table.md`: `CREATE TABLE IF NOT EXISTS bronze.open_meteo_weather (record JSON, run_id UUID, source_type LowCardinality(String), loaded_at DateTime('UTC')) ENGINE = MergeTree PARTITION BY toYYYYMM(loaded_at) ORDER BY (source_type, loaded_at, run_id);`. `record` is ClickHouse's native `JSON` type with no type hints (research R1); mention in the header comment that timestamps inside it stay strings because the job inserts with `input_format_try_infer_datetimes=0`.
- [X] T004 Update the comment at the top of `infra/clickhouse/init/01_databases.sql` so it no longer says no tables are created here by any init script: bronze tables are created by later init scripts (`03_*.sql`), silver and gold by dbt.

**Checkpoint**: `make reset && make up`, then
`docker compose exec -T clickhouse clickhouse-client --user pipeline --password pipeline --query "SELECT count() FROM bronze.open_meteo_weather"` prints `0`.

---

## Phase 3: User Story 1 - Weather job loads its records into bronze (Priority: P1) 🎯 MVP

**Goal**: By default the job inserts each run's records into `bronze.open_meteo_weather` in one
atomic statement; `--destination file|both` keeps the feature 001 run file.

**Independent Test**: With the stack running, run
`docker compose exec airflow bash -c 'cd /opt/ingestion && /opt/venvs/ingestion/bin/python -m open_meteo archive'`
→ bronze gains 840 rows with one `run_id`, no new file in `ingestion/output/open_meteo/`. Repeat
with `--destination both` and check the file and the bronze documents hold the same values (quickstart §2); run with
a wrong password and check exit 1 and an unchanged count (quickstart §3).

### Tests for User Story 1 ⚠️

> Write these first; they fail until T009–T012 are done. All run offline (no network, no ClickHouse).

- [X] T005 [P] [US1] Create `ingestion/tests/open_meteo/test_bronze.py` covering: (a) `build_bronze_rows(records)` returns one dict per record, in order, with `record` equal to the original record dict (all keys, values unchanged, `None` kept) and `run_id`, `source_type`, `loaded_at` copied from it; (b) `insert_rows(rows, url=..., user=..., password=..., timeout=..., opener=stub)` sends exactly one POST whose URL query contains `INSERT INTO bronze.open_meteo_weather (record, run_id, source_type, loaded_at) FORMAT JSONEachRow`, `date_time_input_format=best_effort`, `input_format_try_infer_datetimes=0`, `wait_end_of_query=1`, `input_format_parallel_parsing=0`, with headers `X-ClickHouse-User`/`X-ClickHouse-Key` and a body of one JSON line per row in which `record` decodes to a JSON object (not a string); (c) a stub raising `urllib.error.HTTPError` (with `X-ClickHouse-Exception-Code: 516` header and body containing `(AUTHENTICATION_FAILED)`) raises `BronzeLoadError` whose message is `bronze insert failed: ClickHouse code 516 (AUTHENTICATION_FAILED)` and does not contain the password; (d) a stub raising `urllib.error.URLError` raises `BronzeLoadError`. Use a small stub opener callable, no mocking library.
- [X] T006 [P] [US1] Update `ingestion/tests/open_meteo/test_config.py`: add tests that `Settings.from_env({...})` defaults `destination` to `"warehouse"` and `clickhouse_url` to `http://localhost:8123`; accepts `file` and `both`; refuses any other value with `ConfigError`; refuses a warehouse/both destination when `CLICKHOUSE_USER` or `CLICKHOUSE_PASSWORD` is missing or empty; accepts `file` without them; and that the `destination=` keyword argument overrides `OPEN_METEO_DESTINATION`. Update any existing test that builds `Settings` from an env mapping so it still passes (pass `OPEN_METEO_DESTINATION=file` where it relies on no credentials).
- [X] T007 [P] [US1] Update `ingestion/tests/open_meteo/test_job.py`: change `run_forecast_job` to accept `destination` and an `insert` callable (a list-appending stub); make the two existing tests pass `destination="file"` (unchanged assertions). Add: default `warehouse` destination calls `insert` exactly once with all records (as bronze rows) and writes no file and does not create the output dir; an `insert` stub raising `BronzeLoadError` gives `outcome == "failure"`, `failure` starting `reason=bronze insert failed`, `bronze_table is None`, no file; `both` calls `insert` before writing the file (assert order via a shared event list) and the file exists afterwards; a fetch failure in warehouse mode never calls `insert`.
- [X] T008 [US1] Add an offline test to `ingestion/tests/open_meteo/test_job.py` that `format_report` prints the two new lines `destination: <value>` and `bronze_table: bronze.open_meteo_weather` (or `bronze_table: none` when nothing was inserted), placed after `records:` and before `output_file:` as in `contracts/ingestion-cli.md`.

### Implementation for User Story 1

- [X] T009 [US1] Create `ingestion/open_meteo/bronze.py` (module docstring: rows for `bronze.open_meteo_weather`, whose `record` column is native JSON, and the one atomic insert) with: constant `BRONZE_TABLE = "bronze.open_meteo_weather"`; `class BronzeLoadError(Exception)` (not an `OSError` subclass); `build_bronze_rows(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]` producing `{"record": dict(r), "run_id": r["run_id"], "source_type": r["source_type"], "loaded_at": r["loaded_at"]}` (the record itself, nothing renamed or dropped); `insert_rows(rows, *, url, user, password, timeout, opener=urllib.request.urlopen) -> None` that builds the query string with `urllib.parse.urlencode` (`query`, `date_time_input_format=best_effort`, `input_format_try_infer_datetimes=0`, `wait_end_of_query=1`, `input_format_parallel_parsing=0`), POSTs one body of `"\n".join(json.dumps(row, ensure_ascii=False) for row in rows)` encoded UTF-8 with `Content-Type: application/x-ndjson; charset=utf-8` and the two `X-ClickHouse-*` headers, never retries, and turns `HTTPError` into `BronzeLoadError("bronze insert failed: ClickHouse code {code} ({NAME})")` (code = `X-ClickHouse-Exception-Code` header; NAME = the last `(UPPER_CASE)` token in the response body, omitted with its parentheses if absent; without the header the message is `bronze insert failed: HTTP {status}`) and `URLError`/`TimeoutError`/`OSError` into `BronzeLoadError(f"bronze insert failed: {reason}")`. `ingestion/open_meteo/output.py` stays unchanged, so the run file format is untouched (SC-007). Never include the password or headers in a message. Makes T005 pass.
- [X] T010 [US1] Extend `ingestion/open_meteo/config.py`: add `DESTINATIONS = ("warehouse", "file", "both")`; defaults `OPEN_METEO_DESTINATION=warehouse`, `CLICKHOUSE_URL=http://localhost:8123`; `Settings` fields `destination: str`, `clickhouse_url: str` (validated with `_read_url`), `clickhouse_user: str | None`, `clickhouse_password: str | None` (password field `repr=False`); properties `writes_warehouse` (`destination in ("warehouse", "both")`) and `writes_file` (`destination in ("file", "both")`); `from_env(environ=None, *, destination: str | None = None)` where the argument overrides the env var, an unknown value raises `ConfigError("OPEN_METEO_DESTINATION must be one of warehouse, file, both, got '<v>'")`, and when `writes_warehouse` a missing/blank user or password raises `ConfigError("CLICKHOUSE_USER and CLICKHOUSE_PASSWORD must be set when the destination includes warehouse")` (exit 2 via `__main__`). Makes T006 pass.
- [X] T011 [US1] Update `ingestion/open_meteo/job.py` per `contracts/ingestion-cli.md` run order: add `Insert = Callable[[list[dict[str, Any]]], None]` and a keyword parameter `insert: Insert` to `run_job`; add `destination: str` and `bronze_table: str | None = None` to `RunReport`; call `prepare_output_dir` only if `settings.writes_file`; after building records, if `settings.writes_warehouse` call `insert(build_bronze_rows(records))` then set `report.bronze_table = BRONZE_TABLE`; then, if `settings.writes_file`, write the file; catch `BronzeLoadError` as `report.failure = f"reason={exc}"` (a file error after a successful insert keeps `bronze_table` set); log the insert (`inserted %d records into %s`) and/or the file write; add `destination:` and `bronze_table:` lines to `format_report` after `records:`. Update the module docstring (fetch every location, then insert into bronze and/or write one file). Makes T007–T008 pass.
- [X] T012 [US1] Update `ingestion/open_meteo/__main__.py`: add `--destination {warehouse,file,both}` (help: where to store the run; overrides OPEN_METEO_DESTINATION; default warehouse); pass `destination=args.destination` to `Settings.from_env`; give the refusal `RunReport` `destination=args.destination or "none"`; build `insert = functools.partial(insert_rows, url=settings.clickhouse_url, user=settings.clickhouse_user, password=settings.clickhouse_password, timeout=settings.timeout_seconds)` and pass it to `run_job`. Update the module docstring with the new option.
- [X] T013 [US1] Run `make lint && make test` and fix failures until clean; then with the stack up (`make up`) run the US1 independent test above and `specs/003-weather-poc-e2e/quickstart.md` §2–§3 (file vs bronze comparison prints `identical values`; wrong password → `outcome: failure`, `exit=1`, password absent from output, count unchanged).

**Checkpoint**: The job loads bronze by default and the file mode is unchanged. US2 can use real
bronze data from here on.

---

## Phase 4: User Story 2 - Silver, gold and mart are built from bronze (Priority: P1)

**Goal**: `dbt build` produces `silver.weather_locations`, `silver.open_meteo_weather`,
`gold.dim_location`, `gold.dim_interval`, `gold.fact_weather` and `gold.mart_past_weather`, with
grain, key, relationship and range tests, and a warn-only freshness check on bronze.

**Independent Test**: Against a ClickHouse with `01_databases.sql` + `03_*.sql` applied and the
fixture `dbt/ci/bronze_open_meteo_weather.jsonl` inserted (the CI `dbt` job, or locally via
`make dbt-build` after inserting the fixture), `dbt seed && dbt build` passes every test; silver
has no duplicate grain rows and keeps the later archive load; both forecast versions survive; the
150 % cloud cover value is `NULL`; the row without `hour_utc` and the `riga` row are absent from gold; the mart
contains archive rows only. A second build gives the same `sum(cityHash64(*))` (quickstart §6).

### Tests (dbt generic tests and seed sync) for User Story 2 ⚠️

- [X] T014 [P] [US2] Create `dbt/tests/generic/unique_combination_of_columns.sql`: `{% test unique_combination_of_columns(model, combination_of_columns) %}` selecting `{{ combination_of_columns | join(', ') }}, count() AS n FROM {{ model }} GROUP BY {{ ... }} HAVING count() > 1`, with a comment that ClickHouse groups `NULL` with `NULL`, so archive rows (no forecast version) are checked too.
- [X] T015 [P] [US2] Create `dbt/tests/generic/within_range.sql`: `{% test within_range(model, column_name, min_value=none, max_value=none) %}` returning rows where `{{ column_name }} IS NOT NULL AND (` value `< min_value` if given `OR` `> max_value` if given `)`; both bounds inclusive.
- [X] T016 [P] [US2] Create `ingestion/tests/open_meteo/test_locations_seed.py`: read `dbt/seeds/silver/weather_locations.csv` with `csv.DictReader` (path from `PROJECT_DIR.parent`) and assert it equals, row for row and in order, `load_locations(PROJECT_DIR / "open_meteo/locations.toml")` mapped to `location_key=id, location_name=name, latitude, longitude, zone_code=bidding_zone, location_role=role` (compare coordinates as floats). Docstring: the seed is a copy because dbt cannot read TOML; this test keeps them in sync (R8).

### Implementation for User Story 2

- [X] T017 [P] [US2] Create the seed `dbt/seeds/silver/weather_locations.csv` with header `location_key,location_name,latitude,longitude,zone_code,location_role` and the 5 rows from `ingestion/open_meteo/locations.toml` in file order (tallinn, tartu, parnu, narva, kuressaare; `Pärnu` in UTF-8). Makes T016 pass.
- [X] T018 [P] [US2] Create `dbt/seeds/silver/weather_locations.yml` (version 2, `seeds:`) describing the seed as a copy of `locations.toml` kept in sync by `test_locations_seed.py`, with column descriptions and tests: `location_key` `unique` + `not_null`; `location_name`, `zone_code`, `location_role` `not_null`; `location_role` `accepted_values: [demand, solar, wind]`.
- [X] T019 [US2] Update `dbt/dbt_project.yml`: add `seed-paths: ["seeds"]` and `test-paths: ["tests"]`; add a `seeds: energy_analytics: silver: +schema: silver` block with `weather_locations: +column_types: {location_key: String, location_name: String, latitude: Float64, longitude: Float64, zone_code: "LowCardinality(String)", location_role: "LowCardinality(String)"}`; keep the existing models block and comments.
- [X] T020 [US2] Rewrite `dbt/models/sources.yml`: drop "Planned" wording; table `open_meteo_weather` described as created by `infra/clickhouse/init/03_bronze_open_meteo_weather.sql`, written only by the ingestion job, one row per location per hour per run; `loaded_at_field: loaded_at`; `freshness: {warn_after: {count: 6, period: hour}}` with no `error_after` (FR-008); columns `record` (native JSON: every key and value of one run-file line, read as `record.<key>`; timestamps are strings; `null` values read as `NULL`), `run_id`, `source_type`, `loaded_at` with descriptions and `not_null` tests on the three metadata columns.
- [X] T021 [US2] Create `dbt/models/silver/open_meteo_weather.sql` (`materialized='table'`, `order_by='(location_key, interval_start_utc, source_type)'`) per data-model.md §Silver: a `parsed` CTE from `{{ source('bronze', 'open_meteo_weather') }}` reading the native JSON sub-columns (no `JSONExtract*`, no `isValidJSON`): `location_key = CAST(record.location_id, 'Nullable(String)')`, `interval_start_utc = parseDateTimeBestEffortOrNull(CAST(record.hour_utc, 'Nullable(String)'), 'UTC')`, `source_type = CAST(record.source_type, 'Nullable(String)')`, `forecast_issued_utc = if(source_type = 'forecast', parseDateTimeBestEffortOrNull(CAST(record.forecast_version_at, 'Nullable(String)'), 'UTC'), NULL)`, and each value via `CAST(record.<key>, 'Nullable(Float64)')` (accepts the `Int64` and `Float64` variants; a missing path or `null` gives `NULL`); a `cleaned` CTE that keeps only rows with non-empty `location_key`, non-null `interval_start_utc`, `source_type IN ('forecast', 'archive')`, and non-null `forecast_issued_utc` for forecasts (FR-011), applies the FR-012 limits verbatim — "`NULL` if `< 0`" for `wind_speed_ms`, `shortwave_radiation_wm2`, `direct_radiation_wm2`, `precipitation_mm`; "`NULL` if outside `[0, 360]`" for `wind_direction_deg`; "`NULL` if outside `[0, 100]`" for `cloud_cover_pct`; `temperature_c` and grid columns "as delivered" — and computes `lead_time_h = if(source_type = 'forecast', toInt32(floor(dateDiff('second', forecast_issued_utc, interval_start_utc) / 3600)), NULL)`; final select with the exact column names/types of data-model.md (`assumeNotNull`/casts so key columns are non-Nullable `String`/`DateTime('UTC')`/`LowCardinality(String)`; values `Nullable(Float64)`; `run_id`, `loaded_at` from bronze) and `ORDER BY loaded_at DESC, run_id DESC LIMIT 1 BY location_key, interval_start_utc, source_type, forecast_issued_utc` (FR-010). Header comment: deliberate deviation — impossible values become NULL instead of failing tests.
- [X] T022 [US2] Create `dbt/models/silver/silver.yml` documenting `open_meteo_weather` (grain, dedupe rule, cleaning limits, excluded rows stay in bronze) and every column, with tests: model-level `unique_combination_of_columns: {combination_of_columns: [location_key, interval_start_utc, source_type, forecast_issued_utc]}`; `not_null` on `location_key`, `interval_start_utc`, `source_type`, `run_id`, `loaded_at`; `accepted_values` `[forecast, archive]` on `source_type`; `within_range` with `min_value: 0` on `wind_speed_ms`, `shortwave_radiation_wm2`, `direct_radiation_wm2`, `precipitation_mm`, `min_value: 0, max_value: 360` on `wind_direction_deg`, `min_value: 0, max_value: 100` on `cloud_cover_pct`.
- [X] T023 [P] [US2] Create `dbt/models/gold/dim_location.sql` (`materialized='table'`, `order_by='location_key'`): select from `{{ ref('weather_locations') }}` the columns `location_key`, `location_name`, `latitude`, `longitude`, `zone_code`, `location_role`, plus `toDateTime(now(), 'UTC') AS loaded_at` (dbt build time). Header comment: SCD type 1, rebuilt from the seed each run.
- [X] T024 [P] [US2] Create `dbt/models/gold/dim_interval.sql` (`materialized='table'`, `order_by='interval_start_utc'`) per data-model.md: a `bounds` CTE with `toDateTime(toStartOfYear(min(interval_start_utc)), 'UTC')` and `toDateTime(toStartOfYear(max(interval_start_utc)) + INTERVAL 1 YEAR, 'UTC')` from `{{ ref('open_meteo_weather') }}`, a `hours` CTE generating `start + INTERVAL number HOUR` from `numbers(...)` up to the exclusive end (empty when silver is empty — guard with `WHERE (SELECT count() FROM silver) > 0` or equivalent so `numbers()` never gets a NULL), then columns exactly as specified: `interval_key UInt64 = toUInt64(formatDateTime(t, '%Y%m%d%H%i', 'UTC'))`, `interval_start_utc DateTime('UTC')`, `interval_start_local = toTimeZone(t, 'Europe/Tallinn')`, `local_date = toDate(interval_start_local)`, `local_hour UInt8`, `day_of_week UInt8` (1 = Monday), `is_weekend Bool = day_of_week >= 6`, `month UInt8`, `year UInt16`, `iso_week UInt8`, `season LowCardinality(String)` ("Dec–Feb `winter`, Mar–May `spring`, Jun–Aug `summer`, Sep–Nov `autumn`" from the local month), `is_dst Bool` (UTC offset at `t` in Tallinn is +3 h, i.e. `timeZoneOffset(interval_start_local) = 10800`), `loaded_at = toDateTime(now(), 'UTC')`. Header comment: deferred attributes `is_ee_holiday`, `tariff_period`, `quarter_of_hour`.
- [X] T025 [US2] Create `dbt/models/gold/fact_weather.sql` (`materialized='table'`, `order_by='(location_key, interval_start_utc, source_type)'`): silver `{{ ref('open_meteo_weather') }}` `INNER JOIN {{ ref('dim_location') }} USING (location_key)` (drops unknown locations), selecting `toUInt64(formatDateTime(interval_start_utc, '%Y%m%d%H%i', 'UTC')) AS interval_key`, `location_key`, `interval_start_utc`, `source_type`, `forecast_issued_utc`, `lead_time_h`, the seven values `temperature_c`, `wind_speed_ms`, `wind_direction_deg`, `shortwave_radiation_wm2`, `direct_radiation_wm2`, `cloud_cover_pct`, `precipitation_mm`, and silver `loaded_at`. Depends on T021, T023.
- [X] T026 [US2] Create `dbt/models/gold/gold.yml` documenting `dim_location`, `dim_interval`, `fact_weather` and all columns (grain statements from data-model.md), with tests: `dim_location.location_key` `unique` + `not_null`; `dim_interval.interval_key` and `interval_start_utc` `unique` + `not_null`; `fact_weather` model-level `unique_combination_of_columns` on `[location_key, interval_start_utc, source_type, forecast_issued_utc]`, `not_null` on `interval_key`, `location_key`, `interval_start_utc`, `source_type`, `relationships` `interval_key` → `ref('dim_interval')` field `interval_key` and `location_key` → `ref('dim_location')` field `location_key` (FR-017).
- [X] T027 [US2] Create `dbt/models/marts/mart_past_weather.sql` (`materialized='table'`, `order_by='(location_key, interval_start_utc)'`) per `contracts/mart-past-weather.md`: `{{ ref('fact_weather') }}` filtered to `source_type = 'archive'`, inner-joined to `dim_location` (on `location_key`) and `dim_interval` (on `interval_key`), selecting exactly, in contract order: `location_key`, `location_name`, `location_role`, `zone_code`, `interval_start_utc`, `interval_start_local`, `local_date`, `local_hour`, `day_of_week`, `is_weekend`, `temperature_c`, `wind_speed_ms`, `wind_direction_deg`, `shortwave_radiation_wm2`, `direct_radiation_wm2`, `cloud_cover_pct`, `precipitation_mm`, `loaded_at` (the fact's). Header comment: Superset's only source; hourly, not pre-aggregated (deliberate deviation). Depends on T024–T025.
- [X] T028 [US2] Create `dbt/models/marts/marts.yml` documenting `mart_past_weather` (grain, archive only, interface for `superset/dashboards/past_weather/`, a column change is breaking) and every column with units from the contract, with tests: model-level `unique_combination_of_columns` on `[location_key, interval_start_utc]`; `not_null` on `location_key` and `interval_start_utc`.
- [X] T029 [US2] Delete the placeholder files `dbt/models/silver/.gitkeep`, `dbt/models/gold/.gitkeep`, `dbt/models/marts/.gitkeep`.
- [X] T030 [P] [US2] Create the CI fixture `dbt/ci/bronze_open_meteo_weather.jsonl` (JSONEachRow lines with keys `record` (a nested JSON object with the 16 record keys from `records.py`, numbers as numbers, timestamps as `YYYY-MM-DDTHH:MM:SSZ` strings), `run_id`, `source_type`, `loaded_at`), about 30 rows covering: two archive runs (different `run_id`, `loaded_at` 1 day apart) overlapping on the same `tallinn` hours with different `temperature_2m_c` so the later value must win; two forecast runs for `tartu` with different `forecast_version_at` over the same hours (both must survive), including one hour before the issue time (negative `lead_time_h`); one record with `"temperature_2m_c":null`; one impossible value per limit (`wind_speed_10m_ms` -1, `wind_direction_10m_deg` 400, `shortwave_radiation_wm2` -5, `direct_radiation_wm2` -5, `cloud_cover_pct` 150, `precipitation_mm` -0.1); one integer value (`"cloud_cover_pct":100`) to exercise the `Int64` variant; one row with `location_id` `riga`; one row missing `hour_utc`. No invalid-JSON row: the native `JSON` column would reject the whole fixture insert. Use timestamps in one month of 2026; `loaded_at` must be recent enough not to matter (freshness only warns).
- [X] T031 [US2] Add a `dbt-build` target to `Makefile` (and to `.PHONY`) with a comment "Build and test all dbt models (the stack must be running)": `docker compose exec airflow /opt/venvs/dbt/bin/dbt build --project-dir /opt/dbt` (dbt build runs seeds too).
- [X] T032 [US2] Add a `dbt` job to `.github/workflows/ci.yml`: `services.clickhouse` image `clickhouse/clickhouse-server:25.8.33` with env `CLICKHOUSE_USER: pipeline`, `CLICKHOUSE_PASSWORD: pipeline`, `CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT: "1"`, port `8123:8123`, health options using `clickhouse-client --query "SELECT 1"`; job env `CLICKHOUSE_HOST: localhost`, `CLICKHOUSE_USER: pipeline`, `CLICKHOUSE_PASSWORD: pipeline`, `DBT_PROFILES_DIR: dbt`; steps: checkout, `astral-sh/setup-uv@v5`, `uv venv .dbt-venv && uv pip install --python .dbt-venv/bin/python dbt-clickhouse==1.9.8` (same pin as `airflow/Dockerfile`), apply `infra/clickhouse/init/01_databases.sql` then `03_bronze_open_meteo_weather.sql` in file-name order with `docker exec -i ${{ job.services.clickhouse.id }} clickhouse-client --user pipeline --password pipeline --multiquery < <file>` (multi-statement files cannot go through one HTTP request; `02_users.sh` is not needed), insert the fixture with `docker exec -i ... clickhouse-client ... --date_time_input_format=best_effort --input_format_try_infer_datetimes=0 --query "INSERT INTO bronze.open_meteo_weather FORMAT JSONEachRow" < dbt/ci/bronze_open_meteo_weather.jsonl` (the same input settings as the job), then `.dbt-venv/bin/dbt build --project-dir dbt` and `.dbt-venv/bin/dbt source freshness --project-dir dbt`, then one `clickhouse-client` assertion step that fails the job unless: the `cloud_cover_pct` 150 row is in silver with `NULL`, `silver` has 2 distinct `forecast_issued_utc` for `tartu`, `fact_weather` has no `riga` rows, silver has one row fewer than the distinct valid grain keys in the fixture (the row without `hour_utc` is dropped), and the overlapping `tallinn` archive hour carries the later load's temperature in `gold.mart_past_weather`.
- [X] T033 [US2] Validate: with the stack up and bronze loaded by US1, run `make dbt-build` (all PASS), then run quickstart §4 duplicate checks and §6 idempotency hashes (run `make dbt-build` twice; `sum(cityHash64(*))` equal for silver, fact and mart; dimensions compared with `* EXCEPT loaded_at`). Also run `make test` (T016 passes). Fix any model or test failures.

**Checkpoint**: US1 + US2 give a working pipeline driven by hand: job → bronze → `make dbt-build`
→ mart.

---

## Phase 5: User Story 3 - The orchestrator runs the whole flow (Priority: P2)

**Goal**: The `open_meteo_weather` DAG runs `ingest_forecast`/`ingest_archive` →
`build_silver` → `build_gold` for real, plus `check_bronze_freshness` after the ingests whatever
their outcome, per `contracts/weather-dag.md`.

**Independent Test**: On a fresh stack (`make reset && make up`), un-pause the DAG and trigger it
with `archive = true`: all five tasks succeed, the builds in order, and `gold.mart_past_weather` has 840 rows
(quickstart §1–§2, §7 second half).

### Implementation for User Story 3

- [X] T034 [P] [US3] In `compose.yaml`, add `CLICKHOUSE_URL: http://clickhouse:8123` to the `airflow` service environment, next to `CLICKHOUSE_USER`/`CLICKHOUSE_PASSWORD`, with a comment that the weather job inserts into bronze through it (the pipeline account).
- [X] T035 [US3] Rewrite `airflow/dags/open_meteo_weather.py` per `contracts/weather-dag.md`: module docstring describing ingest (fetch + insert into bronze) → build silver (seed, silver, tests) → build gold (dimensions, fact, mart, tests), the separate freshness check, the unchanged schedule and archive rule; rename constants `FETCH_*` → `INGEST_FORECAST`/`INGEST_ARCHIVE` (same commands, default destination warehouse) and keep the `SKIP_EXIT_CODE`/once-a-day Jinja logic; add `DBT = "/opt/venvs/dbt/bin/dbt"` and `PROJECT = "--project-dir /opt/dbt"`; tasks `ingest_forecast` and `ingest_archive` (`skip_on_exit_code=SKIP_EXIT_CODE`); `build_silver = BashOperator(bash_command=f"{DBT} build {PROJECT} --select silver", trigger_rule="none_failed_min_one_success", retries=0)`; `build_gold = BashOperator(bash_command=f"{DBT} build {PROJECT} --select gold marts", retries=0)`; `check_bronze_freshness = BashOperator(bash_command=f"{DBT} source freshness {PROJECT} --select source:bronze.open_meteo_weather", trigger_rule="all_done", retries=0)` (runs even when an ingest failed, FR-008; a warning exits 0); dependencies `[ingest_forecast, ingest_archive] >> build_silver >> build_gold` and `[ingest_forecast, ingest_archive] >> check_bronze_freshness` (a leaf: nothing depends on it); remove `load_bronze` and the `EmptyOperator` import; DAG `description="Ingest Open-Meteo weather into bronze and build silver, gold and the past-weather mart."`; keep `dag_id`, schedule, `start_date`, `catchup=False`, `is_paused_upon_creation=True`, `max_active_runs=1`, `default_args`, `params`, tags. Add a short `doc_md` per task (what it runs, why dbt tasks have no retries).
- [X] T036 [US3] Validate: `make lint`; `make reset && make up`; check `docker compose exec airflow airflow dags list-import-errors` is empty; trigger `open_meteo_weather` with `{"archive": true}` (UI or `docker compose exec airflow airflow dags trigger open_meteo_weather --conf '{"archive": true}'` after `airflow dags unpause`); confirm the five tasks succeed (builds in order) and the mart has 840 rows; trigger with default params and confirm `ingest_archive` is skipped while both builds and `check_bronze_freshness` succeed; run quickstart §7 (`docker compose stop clickhouse` → ingest tasks retry and fail, builds `upstream_failed`, `check_bronze_freshness` still runs; then `docker compose start clickhouse`) and quickstart §9 (stale bronze → `WARN` in `check_bronze_freshness`, task succeeds).

**Checkpoint**: The flow runs end to end without manual commands.

---

## Phase 6: User Story 4 - Demo dashboard of past weather (Priority: P2)

**Goal**: Superset imports a committed "Past weather" dashboard bundle on every start, reading
only `gold.mart_past_weather` via the reader account, per `contracts/dashboard.md`.

**Independent Test**: After a pipeline run, `make down && make up`, open
`http://localhost:8088/superset/dashboard/past-weather/` (admin/admin): 8 charts show the last 7
days for 5 locations, the Location filter changes every chart, auto-refresh is 1 hour, the
dashboard exists exactly once, and SQL Lab cannot read `silver` (quickstart §8).

### Implementation for User Story 4

- [X] T037 [US4] Create `superset/render_bundle.py` (stdlib only, ruff-clean, module docstring): `main()` reads `SUPERSET_WAREHOUSE_URI` from the environment (exit with a clear message, not the value, if missing), takes the bundle directory (default `/app/dashboards/past_weather`) and output zip path (default `/tmp/past_weather.zip`) as optional argv, and writes a zip whose entries are `past_weather/<relative path>` for every file in the bundle, replacing the literal `${SUPERSET_WAREHOUSE_URI}` (plain `str.replace`, not `string.Template`, so other `$` stay) in `databases/*.yaml` only. Prints only the output path.
- [X] T038 [US4] Update `superset/bootstrap.sh`: replace the `superset set-database-uri` block with `python /app/render_bundle.py` followed by `superset import-dashboards --path /tmp/past_weather.zip --username "$SUPERSET_ADMIN_USER"`, with a comment that the import matches database, dataset, charts and dashboard by their fixed UUIDs and overwrites them, so restarts update rather than duplicate (FR-023).
- [X] T039 [US4] Update `superset/Dockerfile`: `COPY dashboards/ /app/dashboards/` and `COPY render_bundle.py /app/render_bundle.py`; update the header comment to mention the committed dashboard bundle.
- [X] T040 [US4] Author the bundle under `superset/dashboards/past_weather/` (Superset 5.0 export format): with the stack up and the mart filled (after T036), create in Superset — through the UI or a throwaway REST API script kept in the scratchpad, never committed — the dataset on physical table `gold.mart_past_weather` (database `ClickHouse warehouse`) and the 8 charts from `contracts/dashboard.md` exactly: big numbers "Average temperature" `AVG(temperature_c)`, "Average wind speed" `AVG(wind_speed_ms)`, "Total precipitation" `SUM(precipitation_mm) / COUNT(DISTINCT location_key)` labelled "per location"; line charts "Temperature" `AVG(temperature_c)`, "Wind speed" `AVG(wind_speed_ms)`, "Solar radiation" `AVG(shortwave_radiation_wm2)`, "Cloud cover" `AVG(cloud_cover_pct)` and bar chart "Precipitation" `SUM(precipitation_mm)`, all series by `location_name`, x-axis `interval_start_utc` at hour grain with axis title "UTC"; dashboard title `Past weather`, slug `past-weather`, native filters "Location" (`location_name`, multi-select, no default = all) and "Time range" (`interval_start_utc`, default `Last week`), both scoped to all charts. Export with `docker compose exec superset superset export-dashboards -f /tmp/export.zip`, `docker compose cp superset:/tmp/export.zip <scratchpad>`, unzip, and copy `metadata.yaml`, `databases/`, `datasets/`, `charts/`, `dashboards/` into `superset/dashboards/past_weather/`.
- [X] T041 [US4] Clean the exported bundle in `superset/dashboards/past_weather/`: in `databases/*.yaml` set `sqlalchemy_uri: ${SUPERSET_WAREHOUSE_URI}`, `database_name: ClickHouse warehouse`, remove any password/masked field, keep `expose_in_sqllab: true` and its fixed `uuid`; in `dashboards/*.yaml` ensure `slug: past-weather` and `metadata.refresh_frequency: 3600` (FR-025); confirm every chart's `dataset_uuid` points to the single `mart_past_weather` dataset and the dataset's `schema: gold`, `table_name: mart_past_weather`; strip instance-specific ids that are not UUIDs (e.g. numeric `id`s, `datasource: "<n>__table"` references in `params`) where the import does not need them; rename files to stable names (`Past_weather.yaml`, `mart_past_weather.yaml`, chart titles) without the numeric suffixes.
- [X] T042 [US4] Validate: `make down && docker compose build superset && make up`; superset logs show the import with no error; the dashboard list shows exactly one "Past weather" and Settings → Database connections exactly one `ClickHouse warehouse`; run the US4 independent test and quickstart §5 (dashboard tooltip value equals the mart and bronze value) and §8; with an empty mart (`make reset && make up`, before any run) the charts show "No results", not an error. Restart twice more to confirm no duplication. Finally run quickstart §10 (one-year backfill, filter change updates every chart in under 3 s, SC-006).

**Checkpoint**: All four stories work; SC-001 can be timed.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Documentation (FR-028, FR-029) and the full quickstart run.

- [X] T043 [P] Update `infra/README.md` data dictionary: replace the "planned" paragraph and the stale `bronze.weather_hour` section with as-built entries for `bronze.open_meteo_weather` (columns with `record` as native `JSON`, how to read paths, grain, append-only, init script, freshness), `silver.weather_locations`, `silver.open_meteo_weather`, `gold.dim_location`, `gold.dim_interval`, `gold.fact_weather` and `gold.mart_past_weather` (columns, types, grain, keys, cleaning limits, tests) taken from `data-model.md`; keep the Elering planned sections unchanged; mention that the reader account (Superset) sees only gold.
- [X] T044 [P] Update `README.md`: an "End-to-end weather flow" section (start the stack, un-pause and trigger `open_meteo_weather` with `archive = true`, `make dbt-build` for a manual rebuild, where to look in ClickHouse); the job's `--destination warehouse|file|both` / `OPEN_METEO_DESTINATION` and the ClickHouse settings, including running file mode without the stack (`cd ingestion && uv run python -m open_meteo forecast --destination file`); how to open the dashboard (`http://localhost:8088/superset/dashboard/past-weather/`, admin login from `.env`); and how to change the dashboard (edit in UI → `superset export-dashboards` → replace bundle files → restore `${SUPERSET_WAREHOUSE_URI}` in the database YAML → keep UUIDs).
- [X] T045 [P] Update the feature 001/002 cross-references that described placeholders: the docstring of `ingestion/open_meteo/job.py` is done in T011; check `airflow/dags/open_meteo_weather.py`, `dbt/models/sources.yml` and `infra/clickhouse/init/01_databases.sql` comments no longer say "placeholder" or "planned" for weather (`grep -rn -i "placeholder\|planned" airflow dbt infra ingestion/open_meteo`).
- [X] T046 Run `make lint && make test`, then the whole of `specs/003-weather-poc-e2e/quickstart.md` §0–§9 on a fresh stack (`make reset && make up`), timing §1 against SC-001 (< 10 min); record any deviation and fix it before finishing.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none.
- **Foundational (Phase 2)**: after Setup. Blocks verification of every story (the bronze table).
- **US1 (Phase 3)**: after Phase 2.
- **US2 (Phase 4)**: after Phase 2. Implementation is independent of US1 (CI fixture supplies
  bronze data); its in-stack validation T033 uses bronze data loaded by US1.
- **US3 (Phase 5)**: needs US1 (ingest commands insert) and US2 (dbt selections exist).
- **US4 (Phase 6)**: T037–T039 can start after Phase 2; T040 needs a filled mart (US3, or
  US1 + `make dbt-build`).
- **Polish (Phase 7)**: after the stories it documents.

### User Story Dependencies

```text
Setup → Foundational ─┬─► US1 ─┐
                      ├─► US2 ─┼─► US3 ─► US4 (bundle export T040+)
                      └─► US4 scaffolding (T037–T039)
```

### Within Each User Story

- US1: tests T005–T008 → `bronze.py` T009 → `config.py` T010 → `job.py` T011
  → `__main__.py` T012 → validation T013.
- US2: generic tests T014–T015 and seed T016–T019 → sources T020 → silver T021–T022 → gold
  dimensions T023–T024 → fact T025 → gold.yml T026 → mart T027–T028 → T029 → fixture/CI
  T030–T032 → validation T033.
- US3: T034 and T035 in parallel → T036.
- US4: T037 → T038 → T039 → T040 → T041 → T042.

### Parallel Opportunities

- T001, T002 (Setup).
- T005, T006, T007/T008 (different test files; T007 and T008 share a file, run them in sequence).
- T014, T015, T016, T017, T018 (separate dbt/pytest files); T023 and T024; T030 alongside the
  models.
- T034 alongside T035; T037 alongside any US2/US3 task.
- T043, T044, T045 (Polish).
- With two people: one on US1, one on US2 right after Phase 2.

---

## Parallel Example: User Story 1

```bash
Task: "Create ingestion/tests/open_meteo/test_bronze.py (T005)"
Task: "Update ingestion/tests/open_meteo/test_config.py for destination and credentials (T006)"
Task: "Update ingestion/tests/open_meteo/test_job.py for destinations and insert order (T007)"
```

## Parallel Example: User Story 2

```bash
Task: "Create dbt/tests/generic/unique_combination_of_columns.sql (T014)"
Task: "Create dbt/tests/generic/within_range.sql (T015)"
Task: "Create ingestion/tests/open_meteo/test_locations_seed.py (T016)"
Task: "Create dbt/seeds/silver/weather_locations.csv (T017)"
Task: "Create dbt/seeds/silver/weather_locations.yml (T018)"
# after silver exists:
Task: "Create dbt/models/gold/dim_location.sql (T023)"
Task: "Create dbt/models/gold/dim_interval.sql (T024)"
```

---

## Implementation Strategy

### MVP First (User Story 1)

1. Phase 1 + Phase 2 (bronze table exists).
2. Phase 3: the job loads bronze by default; file mode unchanged.
3. **Stop and validate** with quickstart §2–§3.

### Incremental Delivery

1. US1 → data lands in bronze.
2. US2 → `make dbt-build` turns bronze into silver, gold and the mart; CI guards the models.
3. US3 → the DAG does all of it on schedule or on a manual trigger.
4. US4 → the "Past weather" dashboard shows the mart; then Polish and the full quickstart (SC-001).

---

## Notes

- [P] tasks touch different files and do not depend on unfinished tasks.
- Commit after each task or logical group; keep commits scoped to one story where possible.
- Bronze DDL changes after a stack holds data need `make reset` (init scripts run only on an empty
  volume).
- If a Superset export field differs from what T041 expects in 5.0.0, keep the export's structure
  and only apply the URI placeholder, slug, refresh and UUID rules.
