# Implementation Plan: Elering Electricity Prices Pipeline

**Branch**: `004-elering-prices-pipeline` (spec directory `specs/004-elering-prices-pipeline`) | **Date**: 2026-11-22 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/004-elering-prices-pipeline/spec.md`

## Summary

Implement end-to-end day-ahead electricity price ingestion and medallion transformation from
Elering (`https://dashboard.elering.ee/api/nps/price`) for bidding zones `EE`, `FI`, `LV`, and `LT`
up to the gold star schema (`dim_bidding_zone`, shared `dim_interval`, and `fact_price`), mirroring
the architecture and design conventions established by the weather pipeline (`003-weather-poc-e2e`).

- **Ingestion & Bronze**: A new self-contained Python package `ingestion/elering_prices` captures
  either tomorrow (`D+1` in `Europe/Tallinn` time, DST-aware) in `daily` mode or an explicit
  inclusive UTC date range in `backfill` mode (splitting ranges into `ELERING_CHUNK_DAYS` chunks,
  default 31, to stay well below Elering's 1-year API limit). Each run validates completeness and
  uniqueness across all configured zones (handling the `2025-09-30T22:00:00Z` 60-min → 15-min MTU
  switch and 23/24/25-hour DST days) and inserts all records atomically into
  `bronze.elering_prices` (native `JSON` `record` + `run_id`, `mode`, `loaded_at`) via stdlib HTTP,
  with `--destination warehouse|file|both` support. The bronze table is created by a new ClickHouse
  init script `infra/clickhouse/init/04_bronze_elering_prices.sql`.
- **Silver & Gold Star Schema**: dbt builds `silver.bidding_zones` (seed synced with
  `bidding_zones.toml`), `silver.elering_prices` (safe `accurateCastOrNull` parsing, uppercase zone
  codes, `[-500, 5000]` EUR/MWh plausibility filter preserving negative/zero prices, `LIMIT 1 BY`
  deduplication keeping latest `loaded_at` then largest `run_id`), `gold.dim_bidding_zone` (SCD
  type 2 recording 60-min and 15-min market regimes), updated `gold.dim_interval` (spanning the
  union of weather and price silver years), and `gold.fact_price` (60-minute grain averaging
  post-switch 15-minute intervals and joining the historically valid `zone_key`). Data quality is
  enforced with dbt generic and singular tests, including SCD-2 integrity and interior-day
  completeness.
- **Orchestration & Concurrency**: A new Airflow DAG `elering_prices` runs daily at 14:30
  `Europe/Tallinn` time (`CronTriggerTimetable`) with 6 hourly retries on ingestion, manual
  `start_date`/`end_date` backfill params, `build_silver` / `build_gold` dbt tasks (`retries=0`),
  and a non-blocking `check_bronze_freshness` task (`all_done`, 26-hour warn threshold). Both
  `open_meteo_weather` and `elering_prices` serialise their dbt builds through a 1-slot Airflow
  pool (`dbt_build`) provisioned idempotently in `airflow/entrypoint.sh`.
- **CI & Docs**: Extend the CI `dbt` job with `04_bronze_elering_prices.sql`, a representative
  bronze fixture, and `throwIf(...)` SQL assertions; update `infra/README.md` and `README.md`.

## Technical Context

**Language/Version**: Python 3.12 (ingestion job, Airflow DAGs, tests); ClickHouse SQL + Jinja
(dbt models, seeds, tests, DDL); YAML / TOML (configuration, CI)

**Primary Dependencies**: Existing stack dependencies only — Python 3.12 standard library
(`urllib.request`, `zoneinfo`, `tomllib`, `json`, `argparse`) + `python-dotenv` (already in
`ingestion/pyproject.toml`), `dbt-clickhouse==1.9.8`, Apache Airflow 3.1.8, ClickHouse 25.8.33,
pytest, ruff. Zero new packages added ([R1–R10](research.md)).

**Storage**: ClickHouse `bronze.elering_prices` (MergeTree, append-only, native `JSON` `record`
column, [R4](research.md#r4-native-json-bronze-table-created-by-clickhouse-init-script)); dbt-managed
`silver.bidding_zones`, `silver.elering_prices`, `gold.dim_bidding_zone`, `gold.dim_interval`, and
`gold.fact_price`. Optional local JSONL files under `ingestion/output/elering_prices/`.

**Testing**: Offline pytest suite under `ingestion/tests/elering_prices/` (no network access,
`< 10 s`, [R13](research.md#r13-offline-pytest-coverage-constitution-iii--iv)) including a parity
test between `bidding_zones.toml` and `bidding_zones.csv`; dbt schema, generic, and singular tests
verified in CI against a throwaway ClickHouse service with bronze fixtures
([R12](research.md#r12-ci-dbt-fixture-and-verification-fr-033)); end-to-end validation in
[quickstart.md](quickstart.md).

**Target Platform**: Local Docker/Podman Compose stack (`compose.yaml`, Linux/macOS/WSL2) and
GitHub Actions (`ubuntu-latest`) for CI.

**Project Type**: Data pipeline (ingestion package + ClickHouse DDL + dbt project + Airflow DAGs).

**Performance Goals**: End-to-end manual daily pipeline run in under 5 minutes from a fresh stack
(SC-001); 1-year backfill (~140 k rows across 4 zones) in a single run in under 5 minutes (SC-002);
offline pytest suite in under 10 seconds (SC-007).

**Constraints**: Bronze is append-only and all-or-nothing per run (FR-014, FR-015, SC-006);
negative and zero prices preserved untouched (SC-004); rebuilds are idempotent (FR-027); concurrent
weather and price dbt builds never collide on shared tables (FR-031); no hard-coded credentials,
hosts, or zone lists; no new dependencies.

**Scale/Scope**: 4 bidding zones (`EE`, `FI`, `LV`, `LT`). Daily runs add 384 rows (368 spring DST,
400 autumn DST); a full post-switch year adds ~140 160 bronze/silver rows and 35 040 hourly
`fact_price` rows. Adds 1 ingestion package, 1 bronze DDL script, 1 dbt seed, 1 silver model, 2 new
gold models + 1 updated shared dimension (`dim_interval`), 3 singular dbt tests, 1 Airflow DAG +
pool serialisation, CI fixture/assertions, and updated documentation.

All Technical Context items are resolved in [research.md](research.md). No `NEEDS CLARIFICATION`
remains.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|---|---|---|
| I. Clean, Readable Python | Self-contained, focused modules under `ingestion/elering_prices/` (`config`, `periods`, `client`, `records`, `bronze`, `output`, `job`, `__main__`) with type hints, clear verb/noun naming, no hard-coded URLs/credentials/zones/dates, and ruff compliance. Second data source, so keeping modules self-contained obeys the Rule of Three (no premature shared framework). | ✅ Pass |
| II. Simplicity First | Zero new dependencies: stdlib `urllib`, `zoneinfo`, `tomllib`; full-rebuild dbt `table` models; native Airflow `CronTriggerTimetable` and 1-slot `dbt_build` pool; self-contained ingestion package per source. | ✅ Pass |
| III. Minimal Tests for Core Functionality | Focused offline pytest suite covering period/DST/MTU resolution, HTTP retries, response validation, bronze insert error handling, destination rules, config validation, and config-vs-seed parity. Warehouse data quality and SQL rules verified via dbt tests and CI fixtures rather than Python tests. | ✅ Pass |
| IV. Update Tests, Do Not Accumulate Regression Tests | All new pytest files cover new core functionality for `elering_prices`. Existing `open_meteo` tests stay intact because weather ingestion behaviour does not change. | ✅ Pass |
| V. Layered, Documented Data Model | Strict `bronze` (append-only, raw) → `silver` (typed, cleaned, deduplicated) → `gold` (star schema: `dim_bidding_zone`, `dim_interval`, `fact_price`) flow; all stored timestamps in UTC; `fact_price` grain explicitly stated and tested; `infra/README.md` and `README.md` updated. | ✅ Pass |
| Stack, Layout, Workflow | Uses ClickHouse, dbt, Airflow, Docker Compose, ruff, pytest; all files placed in existing top-level tool directories (`ingestion/`, `dbt/`, `airflow/`, `infra/`, `.github/`); no new top-level folders. | ✅ Pass |

**Deliberate alignment with weather pipeline precedence over earlier docs** (agreed in spec):
- `bronze.elering_prices` uses native `JSON` `record` + metadata columns rather than the stale
  typed sketch in `infra/README.md`.
- Gold stays at 60-minute grain (`dim_interval` and `fact_price`), aggregating post-switch
  15-minute silver prices to hourly averages; `is_ee_holiday`, `tariff_period`, and
  `quarter_of_hour` remain deferred.
- Malformed or out-of-bounds bronze rows are excluded in silver without failing the build.
- Silver/gold dbt builds run inside `elering_prices` (matching `open_meteo_weather`), serialised
  across DAGs via `pool="dbt_build"`.

**Post-design re-check (after Phase 1)**: ✅ Pass. Every design artifact (`data-model.md`,
`contracts/*`, `quickstart.md`) adheres to all five principles with zero new dependencies, one
guarded config-to-seed sync point (`test_bidding_zones_seed.py`), and explicit contracts at every
boundary.

## Project Structure

### Documentation (this feature)

```text
specs/004-elering-prices-pipeline/
├── plan.md                      # This file
├── research.md                  # Phase 0 decisions (R1–R13)
├── data-model.md                # Phase 1 medallion data model & lineage
├── quickstart.md                # Phase 1 end-to-end validation guide
├── contracts/
│   ├── elering-api.md           # Elering HTTP API request/response & validation contract
│   ├── ingestion-cli.md         # CLI modes, env vars, output file, report & exit codes
│   ├── bronze-table.md          # bronze.elering_prices DDL, insert request & guarantees
│   └── elering-dag.md           # elering_prices DAG & multi-DAG dbt_build pool contract
├── checklists/
│   └── requirements.md
└── tasks.md                     # Phase 2 (/speckit-tasks; not created by /speckit-plan)
```

### Source Code (repository root)

```text
ingestion/
├── pyproject.toml                           # + "elering_prices" in wheel packages
├── .env.example                             # + ELERING_* environment variable documentation
├── elering_prices/
│   ├── __init__.py                          # NEW
│   ├── __main__.py                          # NEW: CLI (daily|backfill, --start-date, --end-date, --destination)
│   ├── bidding_zones.toml                   # NEW: EE, FI, LV, LT metadata & 2025-09-30T22:00:00Z MTU switch
│   ├── config.py                            # NEW: Settings.from_env(), load_bidding_zones(), ConfigError
│   ├── periods.py                           # NEW: daily D+1 (Europe/Tallinn), backfill UTC, chunking, expected slots
│   ├── client.py                            # NEW: Elering HTTP GET with retries & backoff
│   ├── records.py                           # NEW: response validation & raw record building
│   ├── bronze.py                            # NEW: bronze.elering_prices row wrapping & atomic HTTP INSERT
│   ├── output.py                            # NEW: atomic JSONL run-file writer (file/both modes)
│   └── job.py                               # NEW: run_job orchestration, destination order, RunReport
└── tests/elering_prices/
    ├── __init__.py                          # NEW
    ├── test_config.py                       # NEW
    ├── test_periods.py                      # NEW
    ├── test_client.py                       # NEW
    ├── test_records.py                      # NEW
    ├── test_bronze.py                       # NEW
    ├── test_job.py                          # NEW
    └── test_bidding_zones_seed.py           # NEW: parity between bidding_zones.toml & dbt seed CSV

infra/
├── clickhouse/init/
│   └── 04_bronze_elering_prices.sql         # NEW: bronze.elering_prices DDL (native JSON)
└── README.md                                # Updated data dictionary (replaces planned bronze.elering_prices)

dbt/
├── dbt_project.yml                          # + bidding_zones seed column_types
├── seeds/silver/
│   ├── bidding_zones.csv                    # NEW: 8 SCD-2 reference rows (2 per zone)
│   └── bidding_zones.yml                    # NEW: seed docs & tests
├── models/
│   ├── sources.yml                          # + bronze.elering_prices source & 26h freshness warning
│   ├── silver/
│   │   ├── elering_prices.sql               # NEW: safe JSON parse, uppercase, [-500, 5000] filter, LIMIT 1 BY dedup
│   │   └── silver.yml                       # + elering_prices docs & tests
│   └── gold/
│       ├── dim_bidding_zone.sql             # NEW: SCD type 2 dimension from bidding_zones seed
│       ├── dim_interval.sql                 # Updated: year bounds union open_meteo_weather + elering_prices
│       ├── fact_price.sql                   # NEW: 60-min grain hourly mean + SCD-2 zone_key join
│       └── gold.yml                         # + dim_bidding_zone & fact_price docs/tests, updated dim_interval doc
├── tests/
│   ├── dim_bidding_zone_no_overlapping_windows.sql   # NEW singular test
│   ├── dim_bidding_zone_one_current_per_zone.sql     # NEW singular test
│   └── fact_price_complete_interior_days.sql         # NEW singular test
└── ci/
    ├── bronze_elering_prices.jsonl          # NEW: CI fixture (MTU switch, overlaps, negatives, invalid rows)
    └── assert_fixture_results.sql           # Updated: + Elering silver & gold throwIf assertions

airflow/
├── entrypoint.sh                            # Updated: airflow db migrate + idempotent 1-slot dbt_build pool
└── dags/
    ├── elering_prices.py                    # NEW: daily 14:30 Europe/Tallinn DAG, 6 hourly retries, backfill params
    └── open_meteo_weather.py                # Updated: pool="dbt_build" on build tasks, isolated freshness target-path

Makefile                                     # Updated: pre-create ingestion/output/elering_prices in `up`
README.md                                    # Updated: Elering CLI usage, backfill, and DAG documentation
.github/workflows/ci.yml                     # Updated: apply 04_bronze_elering_prices.sql & load price CI fixture
```

**Structure Decision**: Preserves the repository's tool-oriented top-level layout (`ingestion/`,
`infra/`, `dbt/`, `airflow/`, `.github/`) per the constitution. `ingestion/elering_prices/` stays
self-contained alongside `ingestion/open_meteo/` (Rule of Three), `infra/` owns bronze DDL, `dbt/`
owns all silver/gold models and SQL tests, and `airflow/` owns scheduling and cross-DAG dbt build
serialisation.

## Complexity Tracking

No constitution violations to justify.
