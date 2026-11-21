# Feature Specification: Weather POC End-to-End Flow

**Feature Branch**: `weather-poc-e2e` (spec directory: `specs/003-weather-poc-e2e`)

**Created**: 2026-11-14

**Status**: Draft

**Input**: User description: "Implement a POC end-to-end flow for the weather data. This includes wiring the existing weather job to the bronze layer (the options to store a file locally should remain, but otherwise the job should do the insert). dbt transformation from bronze to silver to gold to marts, airflow orchestration and a demo dashboard for past weather data in superset. The data should be stored as json in bronze, cleaned deduplicated standardized in silver, inserted to the star schema in gold, and transformed to a mart suitable for the dashboard in marts. Note that gold and marts are in the same gold db."

## Clarifications

### Session 2026-11-14

Reviewed against `docs/project_plan.pdf` (architecture and data model diagrams) and
`infra/README.md`. Gold table and column names, the bronze freshness check, "dashboards stay on the
last good data" and the hourly dashboard refresh were aligned with the plan.

- Q: When silver finds a physically impossible value, should the build fail or clean the value? →
  A: Set the value to missing and continue (deliberate deviation from the plan's failing silver
  tests).
- Q: How much of the plan's `dim_interval` is built now? → A: Only attributes derivable from the
  timestamp and relevant now; `is_ee_holiday`, `tariff_period` and `quarter_of_hour` are deferred.
- Q: Should the mart be pre-aggregated (plan: one table per business question) or hourly? → A:
  Hourly rows per location.
- Q: Are failure alerts (plan's Airflow box) in scope? → A: No, ignored for now.
- Q: Should the dbt build run inside the weather pipeline or in a separate pipeline triggered by
  each successful load? → A: Inside the weather pipeline, after the load step; moving it to a
  shared, load-triggered pipeline is deferred until a second source exists.
- Q: How is each record stored in bronze: as JSON text in a `String` column or in ClickHouse's
  native `JSON` type? → A: Native `JSON` type. Every key and value of the record is kept and
  readable by path; the original text (key order, formatting) is not kept, and a document that is
  not valid JSON cannot be stored, so it fails the run's insert.
- Q: The bronze freshness check only helps if it runs when loading has stopped. Where does it run?
  → A: In its own pipeline step after the fetch steps, which runs even when a fetch failed and does
  not block the build steps.

## User Scenarios & Testing *(mandatory)*

Feature 001 built the weather job, which writes run files to a local folder. Feature 002 set up
the local stack (orchestrator, warehouse with empty bronze/silver/gold layers, transformation
project, dashboard tool) with a weather pipeline whose load and build steps are placeholders. This
feature fills in every placeholder for weather only, so that weather data flows from the provider
to a dashboard without any manual step:

1. **Bronze** – the weather job writes each run's records straight into the warehouse, each record
   kept as a native JSON document with every key and value the job produced.
2. **Silver** – records are parsed into typed columns, renamed to the data model's names, checked
   for plausibility and deduplicated so each location, hour and source version appears once,
   keeping the latest load.
3. **Gold (star schema)** – `fact_weather` joined to `dim_location` and `dim_interval`, as in the
   project plan's data model.
4. **Marts** – a dashboard-ready table of observed (past) weather, stored in the same gold layer.
5. **Dashboard** – a demo dashboard of past weather, reading only the mart.

It is a proof of concept: it proves the layers, the orchestration and the dashboard work together
for one source, and sets the pattern the Elering price and grid sources will follow.

### User Story 1 - Weather job loads its records into bronze (Priority: P1)

A data engineer runs the weather job (by hand or from the orchestrator). By default the job
inserts the run's records into the bronze weather table. Anyone who still wants local files can
ask the job to write the run file as before, instead of or in addition to the insert.

**Why this priority**: Nothing downstream can be built or shown without data in bronze; it is the
entry point of the whole flow.

**Independent Test**: With the stack running, run the job in archive mode with default settings.
Check that the bronze weather table gained exactly one row per location per hour of the run (840
for the default run), all carrying the run's identifier, and that no local file was written. Run
it again with the file option and check that a run file appears as in feature 001.

**Acceptance Scenarios**:

1. **Given** the stack is running, **When** the job runs with default settings, **Then** all the
   run's records are inserted into bronze, each stored as its JSON document together with the run
   identifier and load time, and no local file is written.
2. **Given** the file option is selected, **When** the job runs, **Then** the run file is written
   exactly as specified in feature 001 (name, format, all-or-nothing).
3. **Given** the warehouse is unreachable or rejects the insert, **When** the job runs, **Then**
   the run fails with a message naming the reason, signals failure to its caller, and no rows from
   that run remain in bronze.
4. **Given** the same hours were already loaded by an earlier run, **When** the job runs again,
   **Then** the new records are added next to the old ones and the old rows are left untouched.

---

### User Story 2 - Silver, gold and mart are built from bronze (Priority: P1)

After bronze has data, the transformation project builds the silver, gold and mart layers. Silver
holds one clean, typed row per location, hour and source version. Gold holds `fact_weather`,
`dim_location` and `dim_interval` as a star schema. The mart holds past (observed) weather in the
shape the dashboard needs. Data quality tests on keys and grain run as part of the build.

**Why this priority**: The layers are the core of the project's data model and what the
dashboard reads; without them bronze data cannot be used.

**Independent Test**: Load two overlapping archive runs and one forecast run into bronze, run the
build, and check that: silver has no duplicate location-hour-source-version rows and keeps the
latest loaded values; every `fact_weather` row joins to a `dim_location` and a `dim_interval` row;
the mart holds only observed weather; and all data tests pass.

**Acceptance Scenarios**:

1. **Given** bronze holds the same location and hour from two archive runs, **When** the build
   runs, **Then** silver and gold hold that hour once, with the values from the later load.
2. **Given** bronze holds forecasts from two different forecast versions, **When** the build
   runs, **Then** silver and gold keep both versions as separate rows, each with its issue time.
3. **Given** bronze holds a record with a missing value or a physically impossible value (e.g.
   cloud cover above 100 %), **When** the build runs, **Then** the missing value stays missing,
   the impossible value is set to missing in silver, the rest of the record is kept, and the build
   does not fail because of it.
4. **Given** a successful build, **When** the data tests run, **Then** the grain of `fact_weather`
   (one row per location per hour per source type per forecast version) and the dimension keys are
   verified.
5. **Given** a data test fails, **When** the build runs, **Then** the models downstream of the
   failing test are not rebuilt and the mart and dashboard keep the last good data.
6. **Given** the build has run once, **When** it runs again with no new bronze data, **Then** the
   results are identical.

---

### User Story 3 - The orchestrator runs the whole flow (Priority: P2)

The weather pipeline in the orchestrator runs every step for real: fetch-and-load into bronze,
build silver, build gold and marts. A team member can trigger it by hand or let it run on the
schedule from the project plan.

**Why this priority**: Needed for the flow to be end-to-end without manual commands, but each
step can be proven by hand first (User Stories 1–2).

**Independent Test**: On a stack with empty bronze, trigger the weather pipeline by hand with the
archive option on. Check that every step succeeds in order and that the mart then contains the
observed weather for the last 7 days.

**Acceptance Scenarios**:

1. **Given** the stack is running, **When** the weather pipeline is triggered by hand, **Then**
   the fetch steps insert into bronze and the silver, gold and mart builds run afterwards, in
   order, and all succeed.
2. **Given** a fetch step fails, **When** the pipeline runs, **Then** it is retried as configured,
   then marked failed, and the build steps do not run.
3. **Given** a build or data test fails, **When** the pipeline runs, **Then** the step is marked
   failed and the following steps do not run.
4. **Given** the pipeline is un-paused, **When** time passes, **Then** forecasts are captured
   every 6 hours, observed weather once a day, and the layers are rebuilt after each capture.

---

### User Story 4 - Demo dashboard of past weather (Priority: P2)

A stakeholder opens the dashboard tool and finds a ready-made weather dashboard. It shows the
observed weather for the configured locations over a selectable period: temperature, wind speed,
solar radiation, cloud cover and precipitation over time, with the ability to filter by location
and date range.

**Why this priority**: It is the visible result of the POC, but it depends on every earlier
story.

**Independent Test**: After a pipeline run, open the dashboard tool with the documented login and
open the weather dashboard. Check that its charts show data for the last 7 days, that filtering to
one location changes every chart, and that the values match the mart.

**Acceptance Scenarios**:

1. **Given** the stack has started and the pipeline has run, **When** a user opens the dashboard
   tool, **Then** the weather dashboard exists without anyone creating it by hand.
2. **Given** the weather dashboard, **When** the user filters by location or date range, **Then**
   every chart updates to show only that selection.
3. **Given** the mart is rebuilt with new data, **When** the dashboard next refreshes (at most
   hourly) or the user refreshes it, **Then** the new data appears without changing the dashboard.
4. **Given** the dashboard tool, **When** its data access is checked, **Then** the dashboard reads
   only from the mart in the gold layer.

---

### Edge Cases

- **Empty bronze**: the build succeeds and produces empty silver, gold and mart tables; the
  dashboard shows "no data" rather than an error.
- **Bronze document that lacks a key field or has an unparsable one** (location, hour, source
  type): it is left in bronze unchanged and excluded from silver; the build does not fail because
  of it.
- **Record that is not valid JSON**: it cannot be stored in the native JSON column, so the whole
  insert is rejected and the run fails (FR-005); nothing of that run reaches bronze.
- **Record for a location not in the location configuration**: it is excluded from gold (no
  matching `dim_location` row) and the relationship tests report no broken keys.
- **Archive values published late or corrected**: the next daily run re-captures the last 7 days
  and silver keeps the latest load, so the dashboard shows the corrected values.
- **Forecast hours before the issue time** (negative lead time): kept in silver and gold, not
  shown in the mart.
- **Insert partially succeeds** (connection lost mid-run): no rows from that run remain visible in
  bronze, so a re-run cannot create a partial duplicate.
- **No new weather loaded for a long time** (fetch steps keep failing): the bronze freshness check
  still runs after the failed fetch and warns once the newest load is older than 6 hours; it never
  fails the step. While the pipeline is paused nothing runs, and the first run after resuming
  loads fresh data before the check.
- **Pipeline triggered again while a run is in progress**: runs do not overlap; the second waits
  or is skipped.
- **Stack restarted**: bronze, built layers and the dashboard survive the restart; the dashboard is
  not duplicated on restart.
- **Daylight-saving changes**: times are stored in UTC; local date and hour are derived only in
  `dim_interval` and the mart, and every UTC hour appears exactly once per location.

## Requirements *(mandatory)*

### Functional Requirements

**Loading into bronze**

- **FR-001**: The weather job MUST insert each successful run's records into the bronze weather
  table by default.
- **FR-002**: The job MUST keep the option to write the run file locally as in feature 001. The
  destination (warehouse, file, or both) MUST be selectable by configuration or command option,
  with warehouse as the default.
- **FR-003**: Each bronze row MUST hold one record in a native JSON column, with every key and
  value the job produced readable by path (no key dropped, renamed or converted), together with
  the run identifier, source type and load time as separate columns, so rows can be traced to a run
  without reading the document.
- **FR-004**: Bronze MUST be append-only: the job MUST only add rows and MUST NOT update or delete
  existing ones.
- **FR-005**: A run's records MUST appear in bronze all together or not at all. If the insert
  fails, the run MUST fail, report the reason and signal failure to its caller.
- **FR-006**: The bronze weather table MUST be created automatically by the stack (or by the job
  before its first insert) without a manual step.
- **FR-007**: Warehouse connection details for the job MUST come from environment variables, and
  the job MUST use the loading account, not the read-only dashboard account.
- **FR-008**: A freshness check on the bronze weather load time MUST warn (not fail) when no
  weather has been loaded for longer than the expected cadence (forecast every 6 hours). It MUST
  run on every pipeline run, including runs whose fetch steps failed, and MUST NOT block the build
  steps.

**Silver**

- **FR-009**: Silver MUST read each bronze JSON document's paths into typed columns and rename them to the
  data model's names: `location_key`, `interval_start_utc`, `source_type`, `forecast_issued_utc`,
  `temperature_c`, `wind_speed_ms`, `wind_direction_deg`, `shortwave_radiation_wm2`,
  `direct_radiation_wm2`, `cloud_cover_pct`, `precipitation_mm`, grid-point coordinates and
  elevation, `run_id` and `loaded_at`. All times MUST be in UTC.
- **FR-010**: Silver MUST deduplicate to one row per location, hour, source type and forecast
  version, keeping the row with the latest `loaded_at`.
- **FR-011**: Silver MUST exclude rows whose key fields are missing or unparsable.
- **FR-012**: Silver MUST set physically impossible values to missing and keep the rest of the
  row: negative wind speed, radiation or precipitation, cloud cover outside 0–100 %, and wind
  direction outside 0–360°. Such values MUST NOT fail the build. Data tests MUST confirm that the
  cleaned values are within these limits.
- **FR-013**: Silver MUST compute `lead_time_h` (hours between `forecast_issued_utc` and
  `interval_start_utc`) for forecast rows.

**Gold (star schema)**

- **FR-014**: Gold MUST contain `dim_location` (SCD type 1) built from the location
  configuration, with `location_key`, `location_name`, `latitude`, `longitude`, `zone_code`,
  `location_role` and `loaded_at`.
- **FR-015**: Gold MUST contain `dim_interval` (static) at 60-minute grain, covering at least every
  hour present in `fact_weather`, with an integer `interval_key`, `interval_start_utc`,
  `interval_start_local`, `local_date`, `local_hour`, `day_of_week`, `is_weekend`, `month`,
  `year`, `iso_week`, `season`, `is_dst` and `loaded_at`, local time being Europe/Tallinn.
- **FR-016**: Gold MUST contain `fact_weather` with `interval_key`, `location_key`,
  `interval_start_utc`, `source_type`, `forecast_issued_utc`, `lead_time_h`, the seven weather
  values from FR-009 and `loaded_at`. Its grain is one row per location per hour per source type
  per forecast version (archive rows have no forecast version).
- **FR-017**: Data tests MUST enforce the `fact_weather` grain (uniqueness), not-null keys, and
  that every fact key exists in its dimension. They run as part of the build, and a failing test
  MUST stop the models downstream of it, so the mart keeps the last good data.

**Marts**

- **FR-018**: A mart in the gold layer MUST provide observed (archive) weather only, one row per
  location per hour (not pre-aggregated), with the location name and role, the Europe/Tallinn
  local date and hour, and the weather values, ready for the dashboard without further joins.
- **FR-019**: Silver, gold and the mart MUST be built by the transformation project, never by the
  ingestion job, and rebuilding with unchanged bronze MUST give identical results, except the
  dimensions' `loaded_at`, which records the build time.

**Orchestration**

- **FR-020**: The weather pipeline MUST replace all placeholder steps with real ones: fetch and
  load into bronze, build silver, build gold and marts, each running only after the previous step
  succeeds. The build steps run inside the weather pipeline itself, not in a separate pipeline.
- **FR-021**: The pipeline MUST keep the schedule from feature 002 (forecast every 6 hours,
  archive once a day, archive on demand for manual runs), stay paused when first loaded, and not
  run overlapping instances.
- **FR-022**: A failed fetch, load, build or data test MUST mark its step failed and stop the
  following steps.

**Dashboard**

- **FR-023**: The dashboard tool MUST provide a "Past weather" demo dashboard, created
  automatically on stack start-up and not duplicated on restart.
- **FR-024**: The dashboard MUST show, over time, temperature, wind speed, solar radiation, cloud
  cover and precipitation for the configured locations, plus a summary of the selected period
  (e.g. average temperature, average wind speed, total precipitation).
- **FR-025**: The dashboard MUST offer filters for location and date range that apply to every
  chart, defaulting to all locations and the last 7 days, and MUST refresh its data at most hourly.
- **FR-026**: The dashboard MUST read only from the mart in the gold layer using the read-only
  account.

**Quality and documentation**

- **FR-027**: Core new behaviour (turning records into bronze rows and the all-or-nothing insert
  decision) MUST be verifiable without network access; existing tests MUST be updated where
  behaviour changed, not supplemented by regression tests.
- **FR-028**: The data dictionary (`infra/README.md`) MUST describe the bronze, silver, gold and
  mart weather tables as built, replacing the stale `bronze.weather_hour` entry.
- **FR-029**: The README MUST describe how to run the end-to-end flow, how to choose the job's
  destination, and how to open the weather dashboard.

### Key Entities *(include if feature involves data)*

- **Bronze weather row**: one raw weather record from one run, kept as a native JSON document
  plus run identifier, source type and load time. Never changed after insert.
- **Silver weather record**: the parsed, typed, renamed, cleaned and deduplicated version of a
  bronze row; one per location, hour, source type and forecast version, with lead time for
  forecasts.
- **`dim_location`** (SCD1): one row per configured location.
- **`dim_interval`** (static): one row per UTC hour, with UTC and Europe/Tallinn calendar
  attributes; shared later by the price and grid facts.
- **`fact_weather`**: grain one row per location per hour per source type per forecast version;
  holds the weather values and keys to the dimensions.
- **Past weather mart**: observed weather only, one row per location per hour, denormalised with
  location and local time attributes for the dashboard.
- **Past weather dashboard**: the demo dashboard and its charts and filters, reading the mart.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: From a freshly started stack with empty bronze, one manual pipeline run with the
  archive option produces a dashboard showing the last 7 days of observed weather for all 5
  locations in under 10 minutes, with no manual step in any UI.
- **SC-002**: After any number of overlapping runs, the mart contains exactly one row per location
  per observed hour (840 rows for one default 7-day window over 5 locations).
- **SC-003**: Every value shown on the dashboard for a chosen location and hour equals the latest
  loaded observed value for that location and hour in bronze, apart from impossible values set to
  missing.
- **SC-004**: 100 % of data tests on grain and keys pass after every successful pipeline run.
- **SC-005**: A run that fails to load leaves zero rows of that run in bronze.
- **SC-006**: Applying a location or date-range filter updates all dashboard charts in under 3
  seconds for one year of data.
- **SC-007**: The existing local-file mode still produces files identical in format to feature 001.

## Assumptions

- Tools follow the constitution, the project plan and feature 002: ClickHouse warehouse, dbt,
  Airflow, Superset, all in the Docker Compose stack. Bronze, silver and gold are separate
  databases; marts are built into the gold database (`dbt/dbt_project.yml` already routes `marts`
  to `gold`).
- Gold table and column names follow the data model in `docs/project_plan.pdf`.
  `docs/examples.sql` uses outdated `core.` table names and is not a source of truth for naming.
- "Stored as JSON in bronze" means each record, the JSON object from the feature 001 output
  contract (already flattened to one per location per hour, as the plan's bronze layer
  describes), is stored in a ClickHouse native `JSON` column with all its keys and values, plus a
  few metadata columns copied out for tracing. Paths keep the values as delivered (timestamps stay
  strings); typing happens in silver.
- The bronze table name `bronze.open_meteo_weather` declared in feature 002 is kept.
- The default destination becomes the warehouse; the local file mode stays available for local
  runs without the stack and for debugging.
- Forecast data flows through silver and gold (the fact grain includes the forecast version) so
  later forecast-vs-actual analysis is possible, but the POC mart and dashboard cover only past
  (observed) weather.
- `dim_location` is built from the existing location configuration (copied into the
  transformation project as reference data), not from bronze.
- Silver deliberately sets impossible values to missing instead of failing tests as the plan's
  silver checks describe, so one bad provider value cannot block the pipeline.
- The mart deliberately holds hourly rows per location rather than the plan's pre-aggregated
  tables; the dashboard aggregates as needed.
- Weather values keep the provider's hourly timestamps; aligning accumulated values (radiation,
  precipitation refer to the preceding hour) with price intervals is left to the later
  weather-vs-price work.
- The plan's "each successful load triggers dbt build" is met by build steps inside the weather
  pipeline; a shared build pipeline triggered by every source is deferred until the Elering
  sources are added.
- Implausible-value limits are physical limits only; no statistical outlier detection.
- Backfills use the existing archive date-range option and load into bronze the same way.
- The dashboard is a demo: its layout, chart types and colours are chosen during implementation;
  no access control beyond the existing admin login.
- The dashboard definition is kept in the repository so it can be recreated on a fresh stack.

**Out of scope**

- Elering price and grid ingestion, models and dashboards, and `dim_bidding_zone`.
- `dim_interval` attributes not needed now: `is_ee_holiday`, `tariff_period`, `quarter_of_hour`.
- Failure alerts from the orchestrator.
- Forecast-vs-actual and weather-vs-price analyses and their dashboards.
- Hub-height wind, additional locations or providers.
- Retention or clean-up of bronze rows and local files.
- Production deployment, TLS.
