# Implementation Plan: Weather POC End-to-End Flow

**Branch**: `weather-poc-e2e` (spec directory `003-weather-poc-e2e`) | **Date**: 2026-11-14 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/003-weather-poc-e2e/spec.md`

## Summary

This plan fills every placeholder from feature 002 for the weather source.

- **Bronze**: the Open-Meteo job inserts each run's records straight into
  `bronze.open_meteo_weather`. Each record is kept in a native ClickHouse `JSON` column with all
  its keys and values, next to `run_id`, `source_type` and `loaded_at`. The insert is one atomic HTTP
  `INSERT ... FORMAT JSONEachRow` made with the standard library. The table is created by a new
  ClickHouse init script, and the job only inserts. A new `--destination warehouse|file|both` option (default
  `warehouse`) keeps the feature 001 file mode.
- **Silver, gold and mart**: dbt builds them as fully rebuilt `table` models.
  - Silver reads the JSON paths, casts and renames them, sets impossible values to `NULL` and
    deduplicates with `LIMIT 1 BY`.
  - Gold holds `dim_location` (from a seed copied from `locations.toml`), `dim_interval`
    (generated over the years present in silver) and `fact_weather`.
  - `gold.mart_past_weather` holds hourly observed weather per location.
  - Two in-repo generic tests enforce the grains and value ranges, and a source freshness check
    warns.
- **Orchestration**: the DAG's fetch tasks become `ingest_*`, and the `load_bronze` placeholder
  is dropped. `build_silver` and `build_gold` run `dbt build` on their folders, and a
  `check_bronze_freshness` task runs the freshness check even when an ingest failed.
- **Dashboard**: Superset imports a committed dashboard bundle on every start. The "Past
  weather" dashboard reads only the mart.
- **CI**: a new job runs the dbt build against a throwaway ClickHouse with a bronze fixture.

## Technical Context

**Language/Version**: Python 3.12 (job, DAG, Superset helper); ClickHouse SQL + Jinja (dbt
models, tests, DDL); YAML (dbt, Superset bundle, CI)

**Primary Dependencies**: Existing only. These are stdlib `urllib` for the ClickHouse HTTP
insert ([R3](research.md#r3-inserts-use-clickhouses-http-interface-through-the-standard-library)),
`dbt-clickhouse==1.9.8`, Airflow 3.1.8, Superset 5.0.0 and ClickHouse 25.8.33. No new packages,
and no `dbt_utils` ([R9](research.md#r9-data-tests-without-extra-packages)).

**Storage**: ClickHouse `bronze.open_meteo_weather` (MergeTree, append-only, record in a native
`JSON` column, [R1](research.md#r1-the-json-document-is-stored-in-a-native-json-column)). The `silver` and
`gold` tables are built by dbt. Local run files are written only in `file`/`both` mode.

**Testing**: pytest, offline. There is one new test file for bronze row building and insert error
handling, and one for the seed matching `locations.toml`. `test_job.py` and `test_config.py` are
updated ([R14](research.md#r14-python-tests-changed-or-added-constitution-iii-iv)). dbt tests
check grain, keys, relationships and ranges. A CI `dbt` job builds against a fixture
([R12](research.md#r12-ci-runs-the-dbt-build-against-a-throwaway-clickhouse)). The end-to-end
check is [quickstart.md](quickstart.md).

**Target Platform**: The local Docker Compose stack from feature 002 (macOS, Linux, WSL2), and
GitHub Actions for CI.

**Project Type**: Data pipeline (ingestion job + dbt project + orchestration + BI configuration)

**Performance Goals**: An end-to-end manual run takes under 10 min from a fresh stack (SC-001).
Dashboard filters respond in under 3 s for one year of data, about 44 k mart rows (SC-006).

**Constraints**: Bronze is append-only, and each run is all-or-nothing (FR-004, FR-005).
Rebuilds are idempotent (FR-019). Superset uses the reader account and gold only (FR-026).
There are no manual UI steps (FR-023). Secrets come only from `.env`.

**Scale/Scope**: 5 locations. Each run adds 360 forecast or 840 archive rows. Per year that is
about 530 k forecast and 44 k archive rows in silver. The feature has 1 bronze table, 1 seed,
1 silver, 3 gold and 1 mart model, 2 generic tests, a 5-task DAG, and 1 dashboard with 8 charts.

All Technical Context items are resolved in [research.md](research.md). No NEEDS CLARIFICATION
remains.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|---|---|---|
| I. Clean, readable Python | New code is small and in single-purpose places: `bronze.py` (row building, insert; no DDL), the same record dicts feeding the file and bronze paths (no second serialisation of records), and the destination setting in `config.py`. ClickHouse URL, user and password come from the environment. The password never appears in reports or logs. Everything passes ruff. | ✅ Pass |
| II. Simplicity first | No new dependencies: stdlib HTTP instead of `clickhouse-connect`, and in-repo generic tests instead of `dbt_utils`. Full-rebuild `table` models instead of incremental ones. Loading happens inside the job, with no extra task or staging table. The dashboard is a committed export bundle, not API scripting. Weather stays in its own module. | ✅ Pass |
| III. Minimal tests for core functionality | pytest covers the new core behaviour: bronze rows and the all-or-nothing insert decision, the destination rule, and the seed matching the config. Warehouse quality is checked with dbt tests on grain, keys, relationships and ranges, not with Python. | ✅ Pass |
| IV. Update tests, no regression accumulation | `test_job.py` and `test_config.py` are updated for the new destination behaviour. The two new test files cover new core functionality only. | ✅ Pass |
| V. Layered, documented data model | Data flows bronze → silver → gold → marts (in gold), and no layer is skipped. Bronze is append-only (insert only). Timestamps are UTC, and local time appears only in `dim_interval` and the mart. The `fact_weather` and mart grains are stated and tested. Superset reads gold only. `infra/README.md` is updated (FR-028). | ✅ Pass |
| Stack, layout, workflow | Uses exactly ClickHouse, dbt, Airflow, Superset and Compose. Files go under `ingestion/`, `dbt/`, `airflow/`, `superset/`, `infra/` and CI, with no new top-level folders. CI gains the dbt tests the workflow section asks for. | ✅ Pass |

**Deliberate deviations from the project plan (not the constitution)**, already agreed in the
spec's clarifications:

- Silver sets impossible values to `NULL` instead of failing tests.
- The mart is hourly, not pre-aggregated.
- The dbt build runs inside the weather DAG.
- Some `dim_interval` attributes are deferred.
- Bronze stores the record in a native `JSON` column rather than as raw text.

**Post-design re-check (after Phase 1)**: ✅ Pass. The design adds one Python module, one helper
script, one init script and two generic test macros. The DDL lives in one file, and both destinations use the
same record dicts, so no logic is duplicated. One sync point exists (the seed copy of `locations.toml`), guarded by a
test ([R8](research.md#r8-gold-keys-and-dimensions)).

## Project Structure

### Documentation (this feature)

```text
specs/003-weather-poc-e2e/
├── plan.md                  # this file
├── research.md              # Phase 0: decisions R1–R14
├── data-model.md            # Phase 1: bronze, silver, gold, mart, Superset objects
├── quickstart.md            # Phase 1: validation scenarios
├── contracts/
│   ├── bronze-table.md      # DDL, insert request, guarantees
│   ├── ingestion-cli.md     # --destination, new settings, run order, report changes
│   ├── weather-dag.md       # tasks, commands, outcomes (supersedes feature 002's)
│   ├── mart-past-weather.md # mart columns and guarantees (Superset's interface)
│   └── dashboard.md         # provisioning, filters, charts
├── checklists/
│   └── requirements.md
└── tasks.md                 # Phase 2 (/speckit-tasks; not created here)
```

### Source Code (repository root)

```text
ingestion/
├── .env.example                      # + OPEN_METEO_DESTINATION, CLICKHOUSE_URL/USER/PASSWORD
├── open_meteo/
│   ├── __main__.py                   # + --destination; wires the bronze inserter like fetch
│   ├── config.py                     # + destination + warehouse settings and validation
│   ├── job.py                        # run order per destination; RunReport + destination, bronze_table
│   └── bronze.py                     # NEW: build rows (record dict as JSON object), one atomic INSERT, BronzeLoadError
└── tests/open_meteo/
    ├── test_bronze.py                # NEW
    ├── test_locations_seed.py        # NEW: seed CSV == locations.toml
    ├── test_job.py                   # updated
    └── test_config.py                # updated

dbt/
├── dbt_project.yml                   # + seeds config (silver schema, column_types)
├── profiles.yml                      # host from CLICKHOUSE_HOST (default clickhouse) for CI
├── seeds/silver/
│   ├── weather_locations.csv         # NEW
│   └── weather_locations.yml         # NEW: column types, tests
├── models/
│   ├── sources.yml                   # bronze columns, loaded_at freshness (warn 6 h)
│   ├── silver/open_meteo_weather.sql + silver.yml
│   ├── gold/dim_location.sql, dim_interval.sql, fact_weather.sql + gold.yml
│   └── marts/mart_past_weather.sql + marts.yml
├── tests/generic/
│   ├── unique_combination_of_columns.sql
│   └── within_range.sql
└── ci/bronze_open_meteo_weather.jsonl  # NEW: CI fixture covering the US2 scenarios

airflow/dags/open_meteo_weather.py    # ingest_* → build_silver → build_gold, + check_bronze_freshness (contracts/weather-dag.md)
compose.yaml                          # airflow: + CLICKHOUSE_URL=http://clickhouse:8123

superset/
├── Dockerfile                        # + COPY dashboards/ and render_bundle.py
├── bootstrap.sh                      # set-database-uri → render bundle + import-dashboards
├── render_bundle.py                  # NEW: fill ${SUPERSET_WAREHOUSE_URI}, zip the bundle
└── dashboards/past_weather/          # NEW: metadata.yaml, databases/, datasets/, charts/, dashboards/

infra/
├── clickhouse/init/03_bronze_open_meteo_weather.sql  # NEW: bronze table DDL, runs on a fresh volume
└── README.md                         # data dictionary: bronze/silver/gold/mart weather tables (FR-028)
README.md                             # end-to-end run, --destination, dashboard URL, editing the dashboard (FR-029)
Makefile                              # + dbt-build target (docker compose exec ... dbt build)
.github/workflows/ci.yml              # + dbt job with ClickHouse service and fixture
```

**Structure Decision**: The layout stays organised by tool, as the constitution requires. The
warehouse layout, including the bronze DDL, lives in `infra/` and is created by the stack. The job
only inserts. dbt owns everything from silver on.
Superset's dashboard is configuration under `superset/`. The CI fixture sits inside `dbt/`,
because it exists only to test the dbt models.

## Complexity Tracking

No constitution violations to justify.
