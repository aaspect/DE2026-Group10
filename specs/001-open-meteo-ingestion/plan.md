# Implementation Plan: Open-Meteo Weather Ingestion Job

**Branch**: `weather_job` (spec directory `001-open-meteo-ingestion`) | **Date**: 2026-11-14 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-open-meteo-ingestion/spec.md`

## Summary

This plan builds a small, self-contained Python command-line job, `python -m open_meteo`, with
two modes:

- **forecast** captures the current 3-day hourly forecast.
- **archive** captures observed hourly weather, either for a rolling 7-day window or for an
  explicit backfill range.

The job covers 5 configured Estonian locations from Open-Meteo's free endpoints. It makes one
request per location and validates every response. Only after all locations succeed does it
write a single new JSON Lines file, using a temporary file and an atomic hard link. The output
folder is created if it is missing. Each line is one location-hour, with values exactly as delivered plus run metadata (`run_id`, `loaded_at`,
`forecast_version_at`). The job uses only the Python standard library at runtime, and its core
behaviour is covered by offline pytest tests with recorded fixtures.

## Technical Context

**Language/Version**: Python 3.12, managed with `uv`, in the `ingestion/` project ([research R1](research.md#r1-python-version-and-packaging))

**Primary Dependencies**:
- Runtime: the standard library (`urllib.request`, `json`, `tomllib`, `argparse`, `logging`,
  `uuid`, `datetime`) plus `python-dotenv`, which loads the optional `ingestion/.env`
  ([research R9](research.md#r9-configuration-fr-006-to-fr-008))
- Development: `pytest` and `ruff`

**Storage**: local JSON Lines files (`.jsonl`), one per successful run, in `OPEN_METEO_OUTPUT_DIR`
(default `ingestion/output/open_meteo/`, git-ignored, created when missing). The job does not write to the warehouse.

**Testing**: pytest with recorded Open-Meteo JSON fixtures. The fetch and wait functions are
injected as stubs. There is no network access and no mocking library.

**Target Platform**: macOS or Linux developer machines. The same code is later called from the
Airflow container.

**Project Type**: CLI batch job (a single ingestion module)

**Performance Goals**:
- A forecast run finishes in under 1 minute (SC-001).
- A one-year backfill for 5 locations finishes in under 5 minutes (SC-003).
- The test suite finishes in under 10 seconds (SC-007).

**Constraints**:
- A run is all-or-nothing: no partial files.
- Existing files are only ever added to, never overwritten.
- All times are in UTC.
- The job stays within Open-Meteo's free limits (600 calls per minute, 5,000 per hour, 10,000
  per day).
- No credentials are needed.

**Scale/Scope**:
- 5 locations and 7 variables.
- Run sizes: 360 records (forecast), 840 records (default archive), about 43,800 records
  (one-year backfill).
- About 25 requests per day in normal operation.

All Technical Context items are resolved, and no NEEDS CLARIFICATION items remain (see
[research.md](research.md)).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|---|---|---|
| I. Clean, readable Python | The code passes ruff lint and format. Public functions have type hints. No configuration is hard-coded: endpoints, horizon, window, retries, output directory and locations come from environment variables or the TOML file. No secrets are involved. | ✅ Pass |
| II. Simplicity first | One runtime dependency, `python-dotenv`, for `.env` support. It is justified in [research R9](research.md#r9-configuration-fr-006-to-fr-008) and must be justified again in the PR description. There is a single module `open_meteo/`, with no abstract base classes or plugin layer. Dependency injection is limited to plain function arguments (fetch and sleep) that the tests need. | ✅ Pass |
| III. Minimal tests for core functionality | There are about 7 focused tests covering parsing, validation, period resolution, retry classification, all-or-nothing writing and configuration validation, as listed in [research R12](research.md#r12-testing-approach-fr-022-sc-007). They run offline with fixtures. | ✅ Pass |
| IV. Update tests, no regression accumulation | This is a new feature, so only tests for new core behaviour are added. | ✅ Pass |
| V. Layered, documented data model | The job only produces raw/bronze-shaped files and never modifies them. Timestamps are in UTC. The grain is one row per location per hour per run, stated in [data-model.md](data-model.md). Deduplication and plausibility checks are left to silver/dbt. | ✅ Pass |
| Stack and layout | The code lives in the existing `ingestion/` folder, so no new top-level folder is needed. ruff and pytest are added to CI as the constitution requires. | ✅ Pass |

**Post-design re-check (after Phase 1)**: ✅ Pass. The only dependency added is `python-dotenv`,
which the team asked for to get `.env` support and which is justified in research R9. The JSON
Lines output format uses only the standard library and avoids `pyarrow`, and TOML avoids
`PyYAML`. No abstractions were added.

## Project Structure

### Documentation (this feature)

```text
specs/001-open-meteo-ingestion/
├── plan.md              # this file
├── research.md          # Phase 0: decisions R1–R12
├── data-model.md        # Phase 1: Location, Settings, Period, IngestionRun, RawWeatherRecord
├── quickstart.md        # Phase 1: end-to-end validation scenarios
├── contracts/
│   ├── cli.md                   # command, arguments, exit codes, run report
│   ├── configuration.md         # environment variables and locations TOML
│   ├── output-file.md           # JSON Lines file name, fields, guarantees (bronze hand-over)
│   └── open-meteo-requests.md   # consumed provider interface, errors, limits
└── tasks.md             # Phase 2 (/speckit-tasks; not created here)
```

### Source Code (repository root)

```text
ingestion/
├── pyproject.toml            # project metadata, requires-python >=3.12, dependency python-dotenv, dev group (pytest, ruff), ruff + pytest config
├── .env.example              # every OPEN_METEO_* variable with its default, commented out
├── uv.lock
├── open_meteo/
│   ├── __init__.py
│   ├── __main__.py           # argparse CLI → run_job(); prints report; exit code
│   ├── locations.toml        # default 5 EE locations
│   ├── config.py             # load .env, Settings.from_env(), project-relative path resolution, load_locations() + validation
│   ├── periods.py            # Period; resolve_period(mode, today, start, end, settings)
│   ├── client.py             # build_params(), fetch_json() with retry/backoff, error classes
│   ├── records.py            # validate_response(), build_records()
│   ├── output.py             # prepare_output_dir() (mkdir -p + writable check), write_records_atomically(), file naming
│   └── job.py                # run_job(): orchestrates config → period → fetch all → write → report
└── tests/
    └── open_meteo/
        ├── fixtures/
        │   ├── forecast_tallinn.json   # recorded 72-hour response
        │   └── archive_tallinn.json    # recorded 2-day response
        ├── test_config.py
        ├── test_periods.py
        ├── test_client.py
        ├── test_records.py
        └── test_job.py

.gitignore                    # + ingestion/output/
Makefile                      # + lint / test targets for ingestion
.github/workflows/ci.yml      # + ruff check, ruff format --check, pytest for ingestion/
```

**Structure Decision**:

- The job is one self-contained package, `ingestion/open_meteo/`, following constitution II
  ("each data source is handled by its own small, self-contained ingestion module"). The Elering
  jobs will be sibling packages in the same `ingestion/` project, sharing its `pyproject.toml`
  and tool configuration. Code is not shared between sources until the rule of three applies.
- Tests mirror the package under `ingestion/tests/open_meteo/`.
- The CI and Makefile changes are kept to the lint and test steps the constitution requires.
  Docker, Airflow and ClickHouse loading stay out of scope, as the spec states.

## Complexity Tracking

No violations, so nothing needs justifying.
