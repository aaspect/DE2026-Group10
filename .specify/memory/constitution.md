# DE2026-Group10 Constitution

## Core Principles

### I. Clean, Readable Python

Python is the primary language of the project; all application code (ingestion, Airflow DAGs,
helpers) MUST be written in Python unless the tool dictates otherwise (SQL for dbt models and DDL,
YAML for configuration).

- Code MUST pass the project linter/formatter (ruff) with no ignored warnings left unexplained.
- Names MUST describe intent: functions are verbs, variables and modules are nouns, no
  single-letter names outside short comprehensions or loops.
- Functions MUST do one thing and stay short; if a function needs a comment to explain its
  sections, split it.
- Public functions MUST have type hints. Docstrings are required only where the behaviour is not
  obvious from the name and signature.
- Comments explain *why*, never *what*. Dead code, commented-out code and unused imports MUST be
  removed rather than kept "for later".
- Configuration (credentials, hosts, dates, zone lists) MUST NOT be hard-coded; it comes from
  environment variables or configuration files. Secrets MUST never be committed.
- Duplicate logic MUST be extracted once it appears in a third place (rule of three).

Rationale: the codebase is maintained by a small student team and graded on quality; readable
code is cheaper to review, debug and hand over than clever code.

### II. Simplicity First

- Build the simplest solution that meets the current requirement (YAGNI). Abstractions, plugin
  systems and generic frameworks MUST be justified by at least two concrete current uses.
- Prefer the standard library and the tools already in the stack over new dependencies. Adding a
  dependency MUST be justified in the PR description.
- Each data source is handled by its own small, self-contained ingestion module.

Rationale: the course timeline is short; complexity added early is paid for in every later change.

### III. Minimal Tests for Core Functionality

- Tests MUST cover the core functionality: parsing and transforming source data, the logic that
  decides what gets loaded, and the key business rules (e.g. interval aggregation, time zone
  handling).
- Tests SHOULD be few and focused: one test per behaviour, not per code path. Trivial code
  (getters, thin wrappers around libraries, configuration glue) does not need tests.
- Python tests use pytest and MUST run offline and quickly; external APIs are replaced with
  small recorded fixtures or stubs.
- Data quality in the warehouse is checked with dbt tests (e.g. `not_null`, `unique`,
  `relationships`) on keys and grain, not with Python tests.

Rationale: a small, meaningful test suite is maintained; a large one gets ignored or deleted.

### IV. Update Tests, Do Not Accumulate Regression Tests

- When a change alters behaviour, the existing tests covering that behaviour MUST be updated to
  reflect the new expected behaviour.
- New tests MUST NOT be added solely to guard against a specific past bug or change (regression
  tests). If a bug shows that a core behaviour was untested or wrongly specified, the relevant
  existing test is corrected or extended instead.
- A new test is added only when new core functionality is introduced.
- Tests that no longer describe current behaviour MUST be removed in the same change.

Rationale: keeps the test suite a description of how the system behaves today, rather than a
growing history of past bugs.

### V. Layered, Documented Data Model

- Data flows through fixed layers, each a separate ClickHouse database: bronze (raw, as
  ingested, append-only) → silver (cleaned, typed, deduplicated) → gold (facts and dimensions,
  plus the marts Superset reads). Silver and gold are built with dbt. Layers MUST NOT be skipped,
  and bronze data MUST NOT be modified in place.
- Superset reads only from gold.
- All timestamps are stored in UTC; local time is derived only in dimensions or marts.
- The grain of every fact table MUST be stated explicitly (e.g. one row per bidding zone per
  interval) and enforced with dbt tests.

Rationale: a predictable layout keeps queries correct and makes the project understandable to
graders and teammates.

## Technology Stack & Constraints

- Language: Python 3 for ingestion and orchestration code; SQL for dbt models and DDL.
- Storage: ClickHouse as the analytical warehouse; Postgres for Airflow and Superset metadata.
- Transformation: dbt. Orchestration: Airflow. Visualisation: Superset.
- Local environment: the whole stack MUST start with Docker Compose (`compose.yaml`) without
  manual steps beyond setting environment variables.
- Tooling: ruff for linting and formatting, pytest for tests; CI runs both on every pull request.
- Repository layout is organised by tool (`ingestion/`, `dbt/`, `airflow/`, `superset/`,
  `infra/`); new top-level folders require team agreement.

## Development Workflow

- Work happens on feature branches and is merged to `main` through pull requests; direct pushes
  to `main` are not allowed.
- Every pull request MUST be reviewed by at least one other team member and pass CI (lint,
  tests, dbt tests where applicable) before merging.
- Reviewers check compliance with this constitution, in particular clean code (I), test updates
  rather than added regression tests (IV) and the data model layering (V).
- Pull requests SHOULD be small and focused on one change.

## Governance

- This constitution takes precedence over other development practices in the repository. Where
  a practice conflicts with it, the constitution wins until it is amended.
- Amendments are proposed in a pull request that edits this file, explains the reason, and is
  approved by the team.
- Versioning follows semantic versioning: MAJOR for removing or redefining a principle, MINOR
  for adding a principle or section or materially expanding guidance, PATCH for clarifications
  and wording.
- Any deviation from a principle MUST be justified in the pull request description; unjustified
  complexity is grounds to request changes.

**Version**: 1.0.1 | **Ratified**: 2026-11-10 | **Last Amended**: 2026-11-14
