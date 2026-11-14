# Feature Specification: Local Data Pipeline Components

**Feature Branch**: `pipeline_components` (spec directory: `specs/002-pipeline-components`)

**Created**: 2026-11-14

**Status**: Draft

**Input**: User description: "Let's set up the data pipeline components specifed in @docs/project_plan.pdf . For now only one job is used, the open_meteo job. This task involves creating all of the necessary components for serving the data via a dashboard. No actual implementation should be done, only the components. We'll keep it simple and run everything in docker locally, use docker compose. Before starting create a new branch from the current one for the task."

## User Scenarios & Testing *(mandatory)*

The project plan (`docs/project_plan.pdf`) describes a pipeline with four stages: sources →
ingestion → warehouse (bronze, silver, gold layers) → reporting. The only ingestion job that
exists today is the Open-Meteo weather job (feature 001), which writes run files to a local
folder. This feature puts every other stage in place as a running, connected component on a
team member's machine, so that later features only have to fill in logic (loading, models,
charts) rather than set up infrastructure.

The components are:

- **Orchestrator** – schedules and runs pipeline work, with its own web UI.
- **Warehouse** – the analytical database holding the bronze, silver and gold layers.
- **Metadata database** – stores the internal state of the orchestrator and the dashboard tool.
- **Transformation project** – the project that will build the silver and gold layers inside the
  warehouse.
- **Dashboard tool** – the web UI that will serve charts to stakeholders, reading only from gold.
- **Weather ingestion job** – the existing Open-Meteo job, packaged so the orchestrator can run it.

"Components only" means each component exists, starts, and can reach the components it depends
on, but carries no business logic: no data is loaded into the warehouse, no transformation models
are written, and no charts or dashboards are built.

### User Story 1 - Start the whole stack with one command (Priority: P1)

A team member clones the repository, copies the example environment file, and starts the stack
with a single command. All components start, become healthy, and their web UIs are reachable from
the browser. Stopping the stack is also a single command, and data survives a stop and restart.

**Why this priority**: Every later feature (loading, models, dashboards) needs this running
environment. The constitution also requires that the whole stack starts with one command and no
manual steps beyond setting environment variables.

**Independent Test**: On a machine with only the container runtime installed, follow the README:
copy the example environment file and run the start command. Check that every component reports
healthy and that the orchestrator UI and dashboard UI open in the browser and accept the
documented login.

**Acceptance Scenarios**:

1. **Given** a fresh clone and the example environment file copied unchanged, **When** the team
   member runs the start command, **Then** all components start and report healthy without any
   further manual step.
2. **Given** the stack is running, **When** the team member opens the orchestrator UI and the
   dashboard UI, **Then** both load and accept the login documented in the README.
3. **Given** the stack has been started before, **When** it is stopped and started again,
   **Then** warehouse data, orchestrator history and dashboard settings are still present.
4. **Given** the stack is running, **When** the team member runs the stop command, **Then** all
   components stop and no component is left running.
5. **Given** a required environment variable is missing, **When** the team member starts the
   stack, **Then** the affected component fails with a message naming the missing variable.

---

### User Story 2 - Components are wired together (Priority: P1)

Once the stack is running, each component can reach the components it depends on: the
orchestrator and dashboard tool store their state in the metadata database; the transformation
project can connect to the warehouse; the dashboard tool has the warehouse registered as a data
source; and the warehouse already holds the empty bronze, silver and gold layers.

**Why this priority**: A stack whose components start but cannot talk to each other does not
remove any work from later features. The connections are the actual "components" deliverable.

**Independent Test**: With the stack running, run the transformation project's connection check
against the warehouse, open the dashboard tool and confirm the warehouse data source exists and
can list the warehouse's layers, and query the warehouse to confirm the three layers exist.

**Acceptance Scenarios**:

1. **Given** the stack is running, **When** the warehouse is inspected, **Then** separate,
   empty areas exist for the bronze, silver and gold layers.
2. **Given** the stack is running, **When** the transformation project's connection check is run
   from inside the stack, **Then** it reports a successful connection to the warehouse.
3. **Given** the stack is running, **When** the team member opens the dashboard tool's list of
   data sources, **Then** the warehouse is listed and a connection test succeeds, without anyone
   having added it by hand.
4. **Given** the stack is running, **When** the metadata database is inspected, **Then** the
   orchestrator and the dashboard tool each have their own separate database in it.
5. **Given** the dashboard tool's data source, **When** its permissions are checked, **Then** it
   can read the gold layer and cannot write to any layer.

---

### User Story 3 - Weather job is runnable from the orchestrator (Priority: P2)

The orchestrator shows one pipeline for the weather data. It contains the steps from the project
plan in order — fetch weather, load into bronze, build silver and gold — where only the fetch step
does real work (it runs the existing Open-Meteo job) and the remaining steps are placeholders that
succeed without doing anything. The pipeline is paused by default and can be triggered by hand.

**Why this priority**: It proves the existing job can run inside the stack and shows the shape of
the end-to-end flow, but the stack is still useful without it (User Stories 1–2).

**Independent Test**: In the orchestrator UI, trigger the weather pipeline by hand in forecast
mode. Check that all steps succeed, in order, and that a new weather run file appears in the
shared output folder.

**Acceptance Scenarios**:

1. **Given** the stack has just started, **When** the team member opens the orchestrator UI,
   **Then** exactly one weather pipeline is listed, it is paused, and it shows the fetch, load,
   transform steps in order.
2. **Given** the weather pipeline, **When** the team member triggers it by hand, **Then** the
   fetch step runs the existing weather job, a new run file appears in the output folder, and the
   placeholder steps that follow succeed.
3. **Given** the weather job fails (for example the provider is unreachable), **When** the
   pipeline runs, **Then** the fetch step is retried according to the orchestrator's retry
   setting, then marked failed, and the steps after it do not run.
4. **Given** the weather pipeline, **When** it is un-paused, **Then** it follows the schedule from
   the project plan: forecast snapshot every 6 hours and observed (archive) weather once a day.

---

### Edge Cases

- **A port used by a web UI or database is already taken on the host**: the affected component
  fails to start with the runtime's port-conflict error; ports are configurable through
  environment variables so the team member can pick another.
- **A dependency is not yet ready** (e.g. the orchestrator starts before the metadata database
  accepts connections): the dependent component waits for the dependency's health check instead
  of failing.
- **Initialisation runs twice** (the stack is started a second time): creating databases, layers,
  admin users and the dashboard data source is idempotent and does not fail or duplicate entries.
- **The machine has limited memory**: the stack documents its minimum memory requirement, and
  only components needed by this feature are started (no worker clusters or extra brokers).
- **Weather run files from local runs (feature 001) already exist** in the output folder: they
  are left as they are and are visible to the stack's weather job.
- **Secrets**: no real password is committed; the example environment file contains only
  local-development placeholder values.

## Requirements *(mandatory)*

### Functional Requirements

**Stack lifecycle**

- **FR-001**: The whole stack MUST start with a single documented command from the repository
  root, after copying the example environment file, with no other manual step.
- **FR-002**: The whole stack MUST stop with a single documented command.
- **FR-003**: Every component MUST run locally in a container managed by one compose file at the
  repository root.
- **FR-004**: Every long-running component MUST have a health check, and components MUST start
  only after the components they depend on are healthy.
- **FR-005**: Warehouse data, metadata database contents and dashboard settings MUST persist
  across stop and restart, and MUST be removable with a documented reset command.
- **FR-006**: All credentials, hosts and ports MUST come from environment variables. An example
  environment file with local placeholder values MUST be committed; the real environment file
  MUST be ignored by version control.

**Warehouse**

- **FR-007**: The warehouse MUST be created with three separate, empty areas for the bronze,
  silver and gold layers when first started.
- **FR-008**: The warehouse MUST have separate accounts for (a) loading and transforming data and
  (b) reading by the dashboard tool; the dashboard account MUST be read-only.
- **FR-009**: Existing warehouse initialisation scripts that do not match the layer structure or
  the weather job's output contract MUST be removed or replaced, so that only the layer areas are
  created at start-up.

**Metadata database**

- **FR-010**: The metadata database MUST hold a separate database for the orchestrator and for
  the dashboard tool, created on first start.

**Orchestrator**

- **FR-011**: The orchestrator MUST run with its web UI reachable from the host and an admin login
  created from environment variables.
- **FR-012**: The orchestrator MUST be able to run the existing weather ingestion job without
  changing the job's code, and the job's output folder MUST be shared between the job and the
  host.
- **FR-013**: The orchestrator MUST be able to run the transformation project against the
  warehouse.
- **FR-014**: The orchestrator MUST contain one weather pipeline with the steps fetch → load to
  bronze → build silver → build gold. Only the fetch step performs real work; the other steps
  MUST be clearly marked placeholders that succeed without changing any data.
- **FR-015**: The weather pipeline MUST be paused when first loaded, retry the fetch step a
  limited number of times, and stop the following steps when the fetch step fails.

**Transformation project**

- **FR-016**: The transformation project MUST be configured to connect to the warehouse with the
  loading/transforming account, and its connection check MUST succeed from inside the stack.
- **FR-017**: The transformation project MUST contain an empty folder per layer (silver, gold,
  marts) and a declaration of the bronze weather source, but no models.

**Dashboard tool**

- **FR-018**: The dashboard tool MUST run with its web UI reachable from the host and an admin
  login created from environment variables.
- **FR-019**: The warehouse MUST be registered automatically as a data source in the dashboard
  tool on start-up, using the read-only account.
- **FR-020**: No datasets, charts or dashboards are created by this feature.

**Documentation and tooling**

- **FR-021**: The README MUST describe how to start, stop and reset the stack, the URL and login
  of each web UI, the minimum machine resources, and which parts are placeholders.
- **FR-022**: Any Python code added (e.g. the pipeline definition) MUST pass the project's linter
  and formatter, and the existing tests MUST keep passing.

### Key Entities

- **Component**: one service in the stack (orchestrator, warehouse, metadata database,
  transformation runner, dashboard tool), with its dependencies, health check and exposed port.
- **Warehouse layer**: one of bronze, silver, gold; an isolated area in the warehouse. Bronze is
  written by ingestion, silver and gold only by the transformation project, and gold is the only
  layer the dashboard tool reads.
- **Pipeline**: the orchestrator's definition of the weather flow, with its schedule, steps,
  retry policy and paused state.
- **Data source registration**: the dashboard tool's stored connection to the warehouse, tied to
  the read-only account.
- **Environment configuration**: the set of variables (credentials, ports, hosts) that configure
  all components; committed only as an example file.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A team member with no prior setup gets every component healthy in under 10 minutes
  from a fresh clone (excluding image download time), following only the README.
- **SC-002**: On a machine where the stack has started before, all components report healthy
  within 3 minutes of the start command.
- **SC-003**: 100 % of the connections listed in User Story 2 succeed on the first start, with no
  manual configuration in any UI.
- **SC-004**: A manually triggered weather pipeline run completes with all steps successful and
  produces exactly one new weather run file.
- **SC-005**: The stack runs on a laptop with 8 GB of memory available to containers.
- **SC-006**: After a stop and restart, 100 % of previously created warehouse layers, orchestrator
  run history and dashboard data sources are still present.

## Assumptions

- The stack follows the tools fixed in the constitution and project plan: ClickHouse (warehouse),
  PostgreSQL (metadata database), Airflow (orchestrator), dbt (transformation), Superset
  (dashboards), Docker Compose (local runtime). No alternatives are evaluated.
- "No actual implementation" means: no loading into the warehouse, no bronze/silver/gold tables,
  no dbt models or tests, no Superset datasets/charts/dashboards, and no Elering ingestion jobs.
  These are separate, later features.
- The weather job keeps writing files to a shared output folder exactly as specified in feature
  001; loading those files into bronze is a later feature (the "load" step is a placeholder).
- The schedules for the weather pipeline (forecast every 6 h, archive daily) come from the
  architecture diagram in the project plan.
- The stack is for local development only: no TLS, no external exposure, single-node services,
  and the simplest orchestrator executor that runs tasks without extra brokers or workers.
- The current `infra/clickhouse/init` scripts (a `staging` area with `raw_*` tables) predate the
  layer model and the weather job's output contract; they are replaced by the layer areas only.
- The bronze weather source declared in the transformation project names the future bronze table
  but its columns are defined by the later loading feature.
- Team members use a recent Docker Desktop (or equivalent) with Compose v2 on macOS, Linux or
  Windows/WSL2.
