# Feature Specification: Elering Electricity Prices Pipeline

**Feature Branch**: `elering_prices` (spec directory: `specs/004-elering-prices-pipeline`)

**Created**: 2026-11-22

**Status**: Draft

**Input**: User description: "start the implementation of the elering prices integration based on the project documentation in @docs/ . The scope of this implementation is data ingestion and transformation until the star schema. The dashboards will be implemented separately. If the docs is in conflict with the existing implementation of the weather pipeline, the decisions taken in the weather pipeline take precedence."

## Clarifications

### Session 2026-11-22

- Q: How should the Elering prices pipeline handle syntactically invalid JSON documents and malformed bronze records? → A: Match the weather pipeline: fail the run immediately on a non-JSON provider response, keep the native JSON bronze column (which atomically rejects syntactically invalid JSON on insert), and ignore (exclude) valid JSON records with missing or unparsable fields in silver without failing the build.
- Q: Now that a second data source exists alongside weather, where should the silver and gold transformation builds run? → A: Run silver and gold build steps inside the `elering_prices` pipeline itself (matching `open_meteo_weather`), with concurrency serialisation so overlapping weather and price builds never clash on shared tables.
- Q: What date window should daily mode capture on each scheduled or default run? → A: Tomorrow only (`D+1` in Europe/Tallinn time, 96 slots/zone on a standard day); recover any missed earlier days with backfill mode.

## User Scenarios & Testing *(mandatory)*

The project combines electricity day-ahead prices with weather and grid data to answer business
questions such as finding the cheapest consecutive consumption window on a given day, identifying
historically best hours to sell solar generation, and correlating weather with electricity prices.
The weather pipeline already established the project's end-to-end patterns across raw (bronze),
cleaned (silver), and star-schema (gold) layers. This feature brings day-ahead electricity prices
from Elering for the four Nordic/Baltic bidding zones (`EE`, `FI`, `LV`, `LT`) through the same
medallion architecture up to the gold star schema:

1. **Bronze** – an ingestion job fetches day-ahead electricity prices (daily for the next day, or
   over an explicit historical range for backfills) and inserts each run's flattened records straight
   into an append-only bronze table as native JSON documents, with an option to write local run
   files instead of or alongside the warehouse insert.
2. **Silver** – bronze price records are parsed into typed columns, standardized to uppercase zone
   codes and UTC timestamps, checked for validity, and deduplicated so each bidding zone and
   delivered market interval appears once, keeping the latest load.
3. **Gold (star schema)** – `fact_price` at 60-minute grain (aggregating post-October 2025
   15-minute intervals to hourly averages) joined to `dim_bidding_zone` (SCD type 2, tracking the
   October 2025 shift from 60-minute to 15-minute market intervals) and the shared 60-minute
   `dim_interval` (extended to cover the full year range of both weather and price data).
4. **Orchestration** – a scheduled daily pipeline fetches next-day prices after publication, retries
   hourly until all expected slots per zone are published, then builds and tests the silver and
   gold layers and runs a non-blocking bronze freshness check.

Where the earlier project documentation conflicts with decisions already established in the weather
pipeline, the weather pipeline's decisions take precedence. Marts and dashboards built on top of
this star schema are implemented separately.

### User Story 1 - Capture and load next-day electricity prices into bronze (Priority: P1)

A data engineer (or the orchestrator) runs the prices job in daily mode without specifying a date
range. The job retrieves the next day's day-ahead electricity prices for all configured bidding
zones (`EE`, `FI`, `LV`, `LT`), confirms that every zone has the complete set of expected price
intervals for that day, and inserts all records of the run into the bronze prices table in a single
all-or-nothing load. As in the weather job, the engineer can optionally choose to write a local run
file instead of, or in addition to, inserting into the warehouse.

**Why this priority**: Bronze is the immutable entry point for all downstream price layers; without
reliable daily capture and atomic loading into bronze, no silver or gold price data can exist.

**Independent Test**: With the stack running after day-ahead publication, run the prices job in
daily mode with default settings. Verify that the bronze prices table gains one row per configured
bidding zone per delivered interval of the next Europe/Tallinn calendar day (384 rows on a normal
15-minute day: 4 zones × 96 intervals), all sharing one run identifier and load time, and that no
local file was written. Run it again with the local-file option and verify that a JSON Lines run
file is written while leaving earlier files untouched.

**Acceptance Scenarios**:

1. **Given** the stack is running and next-day prices have been published for all configured
   bidding zones, **When** the prices job runs in daily mode with default settings, **Then** all
   records for the next Europe/Tallinn calendar day across all configured zones are inserted into
   bronze as JSON documents with run identifier and load time metadata, and no local file is
   written.
2. **Given** next-day prices have not yet been published (or are incomplete for any configured
   zone), **When** the prices job runs in daily mode, **Then** the run fails with a clear message
   naming the missing or incomplete zone, signals failure to its caller, and inserts zero rows into
   bronze.
3. **Given** the local-file or both-destinations option is selected, **When** the prices job runs
   successfully, **Then** a new JSON Lines run file is written atomically containing all records of
   the run without altering any existing files; when both destinations are selected, the file is
   written only after the warehouse insert succeeds.
4. **Given** the warehouse is unreachable or rejects the insert, **When** the prices job runs with
   a warehouse destination, **Then** the run fails with a message stating the reason, signals
   failure to its caller, and leaves zero rows from that run in bronze.
5. **Given** prices for the same day were already loaded by an earlier run, **When** the job runs
   again for that day, **Then** the new rows are appended alongside the existing rows with a new
   run identifier and newer load time, and existing bronze rows remain unchanged.

---

### User Story 2 - Backfill historical electricity prices across market resolutions (Priority: P1)

A data engineer runs the prices job with an explicit inclusive start and end date to load
historical day-ahead prices—for example, a full year spanning dates both before and after the
October 2025 switch from 60-minute to 15-minute market intervals. The job validates the date range
before contacting the provider, fetches the full range (transparently splitting long ranges if
needed to respect provider limits), preserves the exact market resolution delivered for each
interval, and loads the run atomically into bronze.

**Why this priority**: Year-over-year, seasonal, and "best hours to sell" business questions
require at least 12 months of price history, and historical backfills are essential to populate and
verify the SCD type 2 bidding-zone transition from 60-minute to 15-minute prices.

**Independent Test**: Run the prices job with an explicit range crossing the October 2025 switch
(for example, 29 September 2025 through 2 October 2025). Verify that bronze receives 60-minute
intervals before `2025-09-30T22:00:00Z` and 15-minute intervals from `2025-09-30T22:00:00Z` onward
for all 4 configured zones, all under one run identifier.

**Acceptance Scenarios**:

1. **Given** a valid historical start and end date range, **When** the prices job runs in backfill
   mode, **Then** all delivered price intervals for every configured bidding zone across the
   inclusive UTC date range are loaded atomically into bronze.
2. **Given** a historical range that crosses the October 2025 market switch, **When** the backfill
   runs, **Then** pre-switch periods store 1 interval per UTC hour per zone and post-switch periods
   store 4 intervals per UTC hour per zone, with no gaps at the transition boundary.
3. **Given** an invalid date range (start after end, malformed date, or end date beyond the next
   publishable day), **When** the engineer starts the job, **Then** the job refuses to start with
   an explanatory message without contacting the provider or storing any data.
4. **Given** a backfill spanning at least one full year, **When** the prices job runs, **Then** it
   completes in a single run without failing due to per-request span limits.

---

### User Story 3 - Build cleaned silver prices and gold star schema from bronze (Priority: P1)

Once bronze contains raw price records, the transformation project builds the silver prices layer
and the gold star schema (`dim_bidding_zone`, `dim_interval`, and `fact_price`) and runs data
quality tests on keys, ranges, referential integrity, and grain. Silver holds one clean, typed,
deduplicated row per bidding zone and delivered market interval. Gold holds `dim_bidding_zone`
(SCD type 2 recording both the 60-minute and 15-minute market regimes), `dim_interval` (extended
to cover all years present in either weather or prices), and `fact_price` at 60-minute grain,
averaging post-switch 15-minute intervals to hourly prices so prices align cleanly with hourly
weather and grid analytics.

**Why this priority**: The star schema is the deliverable boundary of this feature and the trusted
analytical foundation that all future price and weather-vs-price marts and dashboards will read.

**Independent Test**: Load overlapping bronze price fixtures containing pre-switch hourly rows,
post-switch 15-minute rows, negative and zero prices, a duplicate load with a later timestamp, a
row with an implausible price, and a row with a missing key. Run the transformation build and
verify that: silver keeps one row per valid `(zone_code, interval_start_utc)` from the latest load
with uppercase zone codes and valid negative/zero prices intact; invalid/implausible bronze rows
are excluded from silver without failing the build; `dim_bidding_zone` holds both SCD type 2
versions per zone; `dim_interval` covers the price years even if weather bronze is empty;
`fact_price` has one row per bidding zone per UTC hour with 15-minute prices averaged to the hour
and linked to the correct historical `zone_key`; and all data tests pass.

**Acceptance Scenarios**:

1. **Given** bronze holds overlapping loads for the same bidding zone and market interval, **When**
   the build runs, **Then** silver holds that zone and interval once with the price from the latest
   load (breaking same-second ties deterministically by run identifier).
2. **Given** bronze holds negative prices (such as `-25.50` EUR/MWh) and zero prices, **When** the
   build runs, **Then** negative and zero prices are preserved unchanged in silver and gold.
3. **Given** bronze holds a record with a missing/unparsable key, a missing/unparsable price, an
   unrecognised zone code, or a price outside market clearing plausibility bounds, **When** the
   build runs, **Then** the bad record remains untouched in bronze, is excluded from silver, and
   does not fail the build.
4. **Given** silver contains both pre-October 2025 hourly prices and post-October 2025 15-minute
   prices, **When** gold is built, **Then** `fact_price` contains one row per bidding zone per
   60-minute UTC interval, where pre-switch rows carry the hourly price and link to the 60-minute
   `dim_bidding_zone` version, and post-switch rows carry the arithmetic mean of the hour's
   15-minute prices and link to the 15-minute `dim_bidding_zone` version.
5. **Given** price data exists for a year that has no weather data (or weather bronze is empty),
   **When** gold is built, **Then** `dim_interval` covers every year present in silver prices as
   well as silver weather, so every `fact_price` and `fact_weather` row matches a `dim_interval`
   row.
6. **Given** a data test fails on silver or gold, **When** the build runs, **Then** models
   downstream of the failing test are not rebuilt and keep their last good data.
7. **Given** the build has run once, **When** it runs again with unchanged bronze data, **Then**
   silver and `fact_price` produce identical rows and values.

---

### User Story 4 - Orchestrate daily price ingestion and star-schema builds (Priority: P2)

A dedicated Elering prices pipeline in the orchestrator automates the daily flow: fetch and load
next-day prices into bronze after daily publication, retry hourly if next-day prices are not yet
published, then build and test the silver and gold layers. A team member can also trigger the
pipeline manually for daily capture or for a historical backfill range. A bronze freshness check
runs on every pipeline execution (even if ingestion failed) and warns without failing when price
loads become stale.

**Why this priority**: Automation turns the standalone job and transformations into a hands-free
daily pipeline matching the weather pipeline, while each stage can first be verified independently
in User Stories 1–3.

**Independent Test**: On a running stack with empty price bronze, trigger the prices pipeline by
hand. Confirm that ingestion loads next-day prices into bronze, silver and gold build and test
steps succeed in order, the bronze freshness check runs and succeeds, and running the prices
pipeline concurrently with the weather pipeline does not cause build conflicts.

**Acceptance Scenarios**:

1. **Given** the stack is running, **When** the orchestrator starts up, **Then** an Elering prices
   pipeline is registered, paused by default, configured not to run overlapping instances, and
   scheduled daily after day-ahead price publication.
2. **Given** next-day prices are not yet published when the scheduled run starts, **When** the
   ingest step fails due to incomplete data, **Then** the orchestrator retries the ingest step on
   an hourly cadence (up to the configured retry limit) and does not run downstream build steps
   until ingestion succeeds.
3. **Given** the ingest step succeeds, **When** the pipeline continues, **Then** the silver and
   gold build steps run in order and succeed; if a build or data test fails, it is not retried and
   downstream steps do not run.
4. **Given** a team member triggers the pipeline manually with explicit start and end dates,
   **When** the pipeline runs, **Then** it ingests that historical backfill range into bronze and
   rebuilds silver and gold.
5. **Given** ingestion has failed repeatedly so bronze prices are stale, **When** the pipeline
   runs, **Then** the bronze freshness check still executes after the failed ingest step, emits a
   warning without failing the step, and never blocks downstream builds on successful runs.
6. **Given** both the weather pipeline and the prices pipeline are active, **When** they trigger at
   overlapping times, **Then** their transformation builds do not corrupt or fail each other's
   shared or source-specific warehouse tables.

---

### Edge Cases

- **Empty bronze**: when `bronze.elering_prices` is empty, the transformation build succeeds and
  produces empty `silver.elering_prices` and `gold.fact_price` tables; `dim_bidding_zone` is still
  built from reference configuration, and `dim_interval` still builds cleanly from weather if
  weather exists (or stays empty if both weather and prices are empty).
- **Next-day prices delayed beyond scheduled time**: daily mode detects fewer than the expected
  number of slots for one or more configured zones, fails without writing partial records to
  bronze, and the orchestrator retries hourly until the full day is published.
- **Daylight-saving transitions (Europe/Tallinn)**:
  - On the spring clock-change day (23 local hours), a complete Europe/Tallinn day has 92
    quarter-hour intervals (23 hourly intervals pre-switch) per zone; daily ingestion accepts 92
    intervals as complete rather than falsely failing for missing 4 slots.
  - On the autumn clock-change day (25 local hours), a complete Europe/Tallinn day has 100
    quarter-hour intervals (25 hourly intervals pre-switch) per zone; daily ingestion accepts 100
    intervals as complete and stores every distinct UTC interval once.
  - Because `fact_price` and `dim_interval` are keyed by UTC hour, every UTC hour appears once per
    bidding zone with no duplicates or missing hours across DST boundaries.
- **Nord Pool delivery day vs UTC day boundary**: at daily publication (~14:30 Europe/Tallinn time
  on day D), Nord Pool has published delivery day D+1 in CET/CEST, which covers all of
  Europe/Tallinn day D+1 (`D 22:00 UTC`–`D+1 21:45 UTC` in winter, `D 21:00 UTC`–`D+1 20:45 UTC` in
  summer) but spans across two partial UTC days (2–3 hours at the end of UTC day D and 21–22 hours
  at the start of UTC day D+1). Daily mode targets the complete Europe/Tallinn day D+1 (so
  consecutive daily runs tile seamlessly with zero UTC gaps), and gold completeness checks verify
  interior UTC days (excluding leading and trailing boundary dates) rather than failing on a single
  daily run or on newly published D+1 boundaries.
- **October 2025 MTU transition boundary**: the switch from 60-minute to 15-minute intervals occurs
  at `2025-09-30T22:00:00Z` (delivery day 1 October 2025 00:00 CEST). Backfills crossing this
  boundary expect 1 interval per UTC hour before `2025-09-30T22:00:00Z` and 4 intervals per UTC
  hour from `2025-09-30T22:00:00Z` onward; `fact_price` links hours before that instant to the
  60-minute `dim_bidding_zone` key and hours at or after that instant to the 15-minute key.
- **Negative and zero prices**: Nord Pool day-ahead prices can legitimately be `0.00` or negative
  (down to the market floor of `-500` EUR/MWh). Both ingestion and transformations MUST preserve
  zero and negative values without treating them as missing or invalid.
- **Implausible or malformed bronze record (valid JSON)**: a valid JSON document in bronze with a
  missing or unparsable timestamp, missing/unknown zone code, missing/unparsable price, or a price
  outside market clearing bounds (`-500` to `5000` EUR/MWh) stays unchanged in bronze and is
  ignored (excluded) by silver without failing the build.
- **Syntactically invalid JSON**: a non-JSON provider response fails the ingestion run immediately
  without retries, and any syntactically invalid JSON cannot be stored in the native JSON bronze
  column so the insert is rejected atomically with zero rows stored (matching the weather
  pipeline).
- **Partial hour in silver (fewer than 4 quarter-hour slots for a post-switch UTC hour)**:
  `fact_price` computes the hourly average from the available valid slots in that UTC hour so the
  hour is not silently lost, while data tests surface incomplete days.
- **Provider temporary failure vs invalid payload**: temporary failures (connection errors,
  timeouts, rate limits, server errors) are retried with increasing waits up to the configured
  attempt limit; structurally invalid responses (missing expected zones, malformed records, empty
  data) fail immediately without futile immediate retries inside the job.
- **Duplicate timestamps within a single provider response**: rejected as an invalid response
  before loading so one run never produces ambiguous duplicate rows for the same zone and interval.
- **Bidding zone configuration invalid or empty**: duplicate zone codes, missing required fields,
  or empty zone list causes the job to refuse to start before contacting the provider, naming the
  faulty entry.
- **Stack restarted**: bronze price data, built silver/gold tables, and orchestrator state survive
  restarts without manual intervention.

## Requirements *(mandatory)*

### Functional Requirements

**Ingestion & configuration**

- **FR-001**: The prices job MUST be runnable locally with a single command without an
  orchestrator, and MUST support two operating modes: **daily** mode (default, capturing next-day
  prices) and **backfill** mode (capturing an explicit inclusive date range).
- **FR-002**: In daily mode without an explicit date range, the job MUST capture only the day-ahead
  price intervals for the next Europe/Tallinn calendar day (`D+1`) across all configured bidding
  zones; any missed earlier days are recovered via backfill mode.
- **FR-003**: In backfill mode, the job MUST accept an explicit inclusive start date and end date
  (UTC calendar dates) and capture all day-ahead price intervals for every configured bidding zone
  across that range, transparently splitting long ranges across multiple provider requests when
  necessary so backfills of at least one year complete in a single run.
- **FR-004**: Before contacting the provider, the job MUST reject invalid backfill ranges (start
  date after end date, malformed date, or end date beyond tomorrow `D+1` in Europe/Tallinn time)
  with a clear explanatory message.
- **FR-005**: Configured bidding zones (`EE`, `FI`, `LV`, `LT` by default) and all runtime
  settings (provider address, retry policy, request timeout, chunk size, destination, local output
  folder, warehouse connection settings) MUST be read from configuration files or environment
  variables rather than hard-coded. An optional local environment file MUST be supported with
  existing environment variables taking precedence, and relative paths MUST NOT depend on the
  working directory.
- **FR-006**: The job MUST refuse to start when the bidding-zone configuration is empty, contains
  duplicate zone codes, or lacks required fields, with an error message naming the faulty entry.
- **FR-007**: For every captured price interval, the raw record MUST include:
  - the bidding zone code as delivered by the provider
  - the interval start timestamp in UTC
  - the electricity price in EUR/MWh as delivered (preserving negative and zero values without
    rounding or filtering)
  - the ingestion mode (`daily` or `backfill`)
  - the run identifier
  - the load timestamp in UTC
- **FR-008**: Before storing any records, the job MUST validate each provider response: it reports
  success, is non-empty, contains every configured bidding zone, contains valid interval timestamps
  and numeric prices with no duplicate `(zone, interval_start_utc)` pairs within the run, and
  matches the expected number of intervals per zone for the requested period (accounting for
  60-minute intervals before `2025-09-30T22:00:00Z`, 15-minute intervals from
  `2025-09-30T22:00:00Z` onward, and 23/24/25-hour Europe/Tallinn DST days in daily mode).
- **FR-009**: The job MUST retry temporary provider failures (connection errors, timeouts, rate
  limiting, server errors) with increasing waits up to a configurable attempt limit (default 3).
  Invalid or incomplete responses (FR-008) MUST NOT be retried inside the job invocation; they fail
  immediately so callers (such as the orchestrator's hourly retry) can decide when to re-try.
- **FR-010**: Each run MUST report its run identifier, mode, period covered, number of bidding
  zones, number of records stored, destination, target bronze table and/or output file, and outcome
  (plus failure reason on failure), and MUST signal success to its caller only when all records
  were stored.

**Loading into bronze**

- **FR-011**: By default, the prices job MUST insert each successful run's records into the bronze
  prices table (`bronze.elering_prices`).
- **FR-012**: The job MUST also support writing each run's records to a local JSON Lines file
  (named to identify the mode and run without colliding with earlier files) instead of, or in
  addition to, the warehouse insert. The destination (`warehouse`, `file`, or `both`, defaulting to
  `warehouse`) MUST be selectable by configuration or command option. When `both` is selected, the
  warehouse insert MUST succeed before the local file is written.
- **FR-013**: Each bronze row MUST store one flattened price record as a native JSON document
  preserving every key and value produced by the job (with timestamps kept as strings so typing
  happens in silver), alongside separate metadata columns for `run_id`, ingestion `mode`, and
  `loaded_at` (UTC) so runs can be traced without inspecting the JSON document.
- **FR-014**: The bronze prices table MUST be append-only: the job MUST only insert new rows and
  MUST NOT update or delete existing rows.
- **FR-015**: Every run's bronze load MUST be atomic (all rows of the run appear in bronze or none
  do). If the insert fails, the job MUST fail with the reason, signal failure to its caller, and
  leave zero rows from that run in bronze.
- **FR-016**: The bronze prices table MUST be created automatically by the stack during warehouse
  initialisation without a manual step; the ingestion job MUST NOT create or alter warehouse
  tables.
- **FR-017**: Warehouse connection credentials for the prices job MUST come from environment
  variables and MUST use the loading account, never the read-only reporting account.
- **FR-018**: A freshness check on the bronze prices table's `loaded_at` timestamp MUST warn (and
  never fail) when the newest load is older than 26 hours (the daily 24-hour cycle plus a 2-hour
  publication grace window). It MUST run on every pipeline execution—including executions where
  ingestion failed—and MUST NOT block downstream builds.

**Silver**

- **FR-019**: Silver MUST contain `silver.elering_prices`, reading each bronze JSON document into
  typed, renamed columns: `zone_code` (standardized to uppercase), `interval_start_utc` (UTC
  timestamp), `price_eur_mwh` (numeric price in EUR/MWh), `run_id`, and `loaded_at` (UTC). All
  timestamps MUST be in UTC, and delivered market intervals (60-minute pre-switch, 15-minute
  post-switch) MUST be preserved.
- **FR-020**: Silver MUST deduplicate to one row per `(zone_code, interval_start_utc)`, keeping the
  row with the latest `loaded_at` and breaking ties deterministically by `run_id`.
- **FR-021**: Following the weather pipeline's non-blocking cleaning rule, silver MUST leave invalid
  rows untouched in bronze and exclude from silver any bronze row that lacks a valid/parsable
  `zone_code`, `interval_start_utc`, or `price_eur_mwh`, has a `zone_code` outside the configured
  bidding zones (`EE`, `FI`, `LV`, `LT`), or has a price outside Nord Pool market clearing
  plausibility bounds (`-500` to `5000` EUR/MWh). Negative prices down to `-500` EUR/MWh and zero
  prices MUST be kept.
- **FR-022**: Silver data tests MUST verify grain uniqueness on `(zone_code, interval_start_utc)`,
  not-null on `zone_code`, `interval_start_utc`, `price_eur_mwh`, `run_id`, and `loaded_at`,
  accepted values for `zone_code` (`EE`, `FI`, `LV`, `LT`), and plausibility bounds (`-500` to
  `5000` EUR/MWh) on `price_eur_mwh`.

**Gold (star schema)**

- **FR-023**: Gold MUST contain `dim_bidding_zone` (SCD type 2) built from reference bidding-zone
  data (matching the ingestion bidding-zone configuration), with `zone_key` (unique integer
  surrogate key per zone version), `zone_code`, `zone_name`, `mtu_minutes`, `valid_from` (UTC),
  `valid_to` (UTC, open-ended for the current version), `is_current`, and `loaded_at` (UTC). Each
  configured zone (`EE`, `FI`, `LV`, `LT`) MUST have two versions:
  - Historical 60-minute version: `mtu_minutes = 60`, active until `2025-09-30T22:00:00Z`,
    `is_current = false`.
  - Current 15-minute version: `mtu_minutes = 15`, active from `2025-09-30T22:00:00Z` with no end
    timestamp, `is_current = true`.
- **FR-024**: Gold's shared `dim_interval` (static, 60-minute grain, Europe/Tallinn local calendar
  attributes) MUST be updated so its generated year span covers from 1 January of the earliest year
  present across both silver weather and silver prices through 31 December of the latest year
  present across both sources, continuing to produce an empty table only when both silver sources
  are empty and preserving all existing columns and semantics established by the weather pipeline.
- **FR-025**: Gold MUST contain `fact_price` at 60-minute grain: one row per bidding zone per UTC
  hour, with `interval_key`, `zone_key`, `interval_start_utc`, `price_eur_mwh`, and `loaded_at`.
  - For pre-switch hourly intervals, `price_eur_mwh` is the cleaned hourly price and `zone_key`
    references the zone's 60-minute `dim_bidding_zone` version.
  - For post-switch 15-minute intervals, `price_eur_mwh` is the arithmetic mean of the valid
    15-minute prices within that UTC hour, `loaded_at` is the latest `loaded_at` among those
    intervals, and `zone_key` references the zone's 15-minute `dim_bidding_zone` version.
- **FR-026**: Gold data tests MUST enforce:
  - `dim_bidding_zone`: `zone_key` unique and not null; non-overlapping validity windows per
    `zone_code`; exactly one current row (`is_current = true`) per `zone_code`.
  - `fact_price`: grain uniqueness on `(zone_key, interval_key)` and `(zone_key,
    interval_start_utc)`; not-null on `interval_key`, `zone_key`, `interval_start_utc`,
    `price_eur_mwh`, and `loaded_at`; referential integrity confirming every `interval_key` exists
    in `dim_interval` and every `zone_key` exists in `dim_bidding_zone`.
  - Completeness: a check verifying that every interior UTC day strictly between the earliest and
    latest UTC dates in `fact_price` (excluding leading and trailing boundary dates caused by the
    Europe/Tallinn / CET delivery-day boundary) contains 24 hourly rows per bidding zone.
  - A failing test MUST halt downstream models so previously built good data is preserved.
- **FR-027**: Silver and gold models MUST be built exclusively by the transformation project (never
  by the ingestion job), and rebuilding with unchanged bronze data MUST produce identical silver
  and `fact_price` results (apart from dimension `loaded_at` build timestamps).

**Orchestration**

- **FR-028**: The orchestrator MUST provide a dedicated `elering_prices` pipeline that starts
  paused on creation, prevents overlapping runs, and runs on a daily schedule after day-ahead price
  publication (~14:30 Europe/Tallinn time) to ingest next-day (`D+1`) prices into bronze and then
  build and test the silver and gold layers inside the `elering_prices` pipeline itself (matching
  `open_meteo_weather`, rather than a separate shared build pipeline).
- **FR-029**: On scheduled daily runs, when the ingest step fails (for example because next-day
  prices are not yet published), the orchestrator MUST retry it on an hourly cadence (default 6
  hourly retries) and MUST NOT run the downstream silver or gold build steps until ingestion
  succeeds. Build and test steps MUST NOT be retried on failure.
- **FR-030**: Manual runs of the `elering_prices` pipeline MUST support running the default daily
  `D+1` capture as well as optional explicit start and end date parameters for historical
  backfills.
- **FR-031**: Transformation build steps across `open_meteo_weather` and `elering_prices` MUST be
  serialised so concurrent runs of both pipelines never clash on or corrupt shared warehouse tables
  (such as `dim_interval`).

**Quality and documentation**

- **FR-032**: Core ingestion logic (daily and backfill period resolution including DST and October
  2025 boundary handling, response validation and record building, bronze row wrapping, atomic
  insert failure handling, and parity between ingestion bidding-zone configuration and
  transformation reference data) MUST be verifiable offline without network access.
- **FR-033**: Automated transformation verification (continuous integration) MUST exercise the
  Elering bronze-to-silver-to-gold flow on a representative fixture covering pre-switch hourly
  rows, post-switch 15-minute aggregation, overlapping loads, negative/zero prices, and invalid
  bronze records, alongside the existing weather fixture checks.
- **FR-034**: The data dictionary (`infra/README.md`) MUST be updated to document
  `bronze.elering_prices`, the bidding-zone reference table, `silver.elering_prices`,
  `gold.dim_bidding_zone`, the expanded `gold.dim_interval`, and `gold.fact_price` as built,
  replacing the stale planned `bronze.elering_prices` entry.
- **FR-035**: The project `README.md` MUST be updated to document how to run the Elering prices
  job (daily mode, backfill mode, destination options) and how to trigger and monitor the
  `elering_prices` pipeline.

### Key Entities *(include if feature involves data)*

- **Bidding zone configuration**: the maintained list of electricity bidding zones (`EE`, `FI`,
  `LV`, `LT`) with display names and historical market time unit (MTU) transition metadata;
  mirrored in transformation reference data to build `dim_bidding_zone`.
- **Bronze price row**: one raw day-ahead price record for one bidding zone and one delivered
  market interval from one ingestion run, stored as a native JSON document alongside `run_id`,
  `mode`, and `loaded_at`. Append-only and never modified after insert.
- **Silver price record**: the parsed, typed, standardized (uppercase zone code, UTC timestamp),
  plausibility-checked, and deduplicated version of a bronze price row; grain is one row per
  `(zone_code, interval_start_utc)` at delivered market resolution (60-minute pre-switch, 15-minute
  post-switch).
- **`dim_bidding_zone` (SCD type 2)**: bidding zone dimension storing both the pre-October 2025
  60-minute regime and the post-October 2025 15-minute regime per zone, with surrogate `zone_key`,
  `zone_code`, `zone_name`, `mtu_minutes`, `valid_from`, `valid_to`, `is_current`, and `loaded_at`.
- **`dim_interval` (static, shared)**: existing 60-minute UTC time dimension with Europe/Tallinn
  calendar attributes, extended to span all years present across both weather and price silver
  data.
- **`fact_price`**: gold fact table at 60-minute grain (one row per bidding zone per UTC hour),
  linking each hourly price (delivered directly pre-switch, or averaged from 15-minute intervals
  post-switch) to `dim_interval` and the historically valid `dim_bidding_zone` version.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: From a freshly started stack with an empty price bronze table, one manual pipeline
  run loads next-day prices for all 4 configured bidding zones and populates silver and the gold
  star schema (`dim_bidding_zone`, `dim_interval`, `fact_price`) in under 5 minutes with no manual
  warehouse setup.
- **SC-002**: A one-year historical backfill covering all 4 bidding zones across the October 2025
  market resolution switch completes in a single run in under 5 minutes, with zero missing UTC
  hours across the transition boundary.
- **SC-003**: After any number of overlapping daily or backfill loads, `fact_price` contains
  exactly one row per bidding zone per 60-minute UTC interval (24 rows per zone per full UTC day),
  and every hourly price equals either the latest loaded hourly price (pre-switch) or the exact
  arithmetic mean of the latest loaded 15-minute prices for that hour (post-switch).
- **SC-004**: 100 % of negative and zero Nord Pool day-ahead prices within market clearing bounds
  are preserved from bronze through `fact_price`, while 100 % of malformed or out-of-bounds bronze
  records are excluded from silver without failing the build.
- **SC-005**: 100 % of data quality tests on silver and gold grain, keys, referential integrity,
  SCD type 2 validity, and completeness pass after every successful pipeline run, including when
  weather bronze is empty and only prices exist.
- **SC-006**: Every failed ingestion or warehouse insert leaves zero rows of that run in bronze and
  writes no partial local file.
- **SC-007**: All offline automated ingestion tests run without network access and complete in
  under 10 seconds.

## Assumptions

- **Stack and governance**: Implementation follows `.specify/memory/constitution.md` and the
  existing Docker Compose stack: Python for ingestion and Airflow DAGs, ClickHouse for bronze /
  silver / gold databases, dbt for silver and gold transformations and tests, and ruff + pytest in
  CI.
- **Weather pipeline precedence over earlier documentation**:
  - **Bronze storage**: `infra/README.md` previously listed a typed-column `bronze.elering_prices`
    sketch; following the weather pipeline (`specs/003-weather-poc-e2e`), `bronze.elering_prices`
    uses ClickHouse's native `JSON` `record` column plus tracing metadata columns (`run_id`,
    `mode`, `loaded_at`), created by a ClickHouse init script, append-only, loaded via a single
    atomic insert, with `warehouse` (default) / `file` / `both` destination support.
  - **Gold grain and `dim_interval`**: Page 2 of `docs/project_plan.pdf` and `docs/examples.sql`
    query 1 reference 15-minute gold intervals (96/day), while page 3 of `docs/project_plan.pdf`
    and the implemented weather pipeline (`gold.dim_interval`) standardize gold on **60-minute
    grain**. Following both page 3 and the weather pipeline, `dim_interval` stays at 60-minute
    grain (keeping `is_ee_holiday`, `tariff_period`, and `quarter_of_hour` deferred),
    `silver.elering_prices` preserves delivered market intervals (60-minute pre-switch, 15-minute
    post-switch), and `gold.fact_price` aggregates post-switch 15-minute intervals to 60-minute
    hourly averages.
  - **Non-blocking silver cleaning**: Following the weather pipeline's deliberate deviation from
    failing silver tests on provider anomalies, bad/unparsable/out-of-bounds price records stay in
    bronze and are excluded from silver rather than blocking the pipeline, while silver dbt tests
    confirm all surviving rows satisfy not-null, accepted zone, uniqueness, and plausibility
    bounds.
  - **Bronze freshness check**: Following the weather pipeline, `dbt source freshness` runs in its
    own non-blocking Airflow task (`all_done`) after ingestion and only warns (never fails) when
    loads are stale.
  - **Orchestration structure**: Following the weather pipeline (`airflow/dags/open_meteo_weather.py`),
    each source has its own DAG that runs ingestion followed by silver and gold dbt build steps and
    bronze freshness check, with concurrency protection so weather and prices DAGs never clash on
    shared models like `dim_interval`. Failure alerts remain out of scope as in the weather
    pipeline.
  - **Table naming**: Gold table and column names follow `docs/project_plan.pdf` (in ClickHouse
    database `gold`, not the outdated `core.` schema prefix in `docs/examples.sql`).
- **Elering price source**: Public keyless Elering Dashboard day-ahead price endpoint
  (`https://dashboard.elering.ee/api/nps/price`) returning UTC timestamps and EUR/MWh spot prices
  for `ee`, `fi`, `lv`, and `lt`. Zone codes are lower-case in the raw payload and standardized to
  upper-case (`EE`, `FI`, `LV`, `LT`) in silver.
- **October 2025 MTU transition**: European Single Day-Ahead Coupling (SDAC) and Nord Pool switched
  from 60-minute to 15-minute Market Time Units on delivery day 1 October 2025 (00:00 CEST), whose
  first 15-minute interval starts at `2025-09-30T22:00:00Z`. `dim_bidding_zone` uses
  `2025-09-30T22:00:00Z` as the SCD type 2 boundary between `mtu_minutes = 60` and
  `mtu_minutes = 15` for all four zones.
- **Nord Pool price plausibility bounds**: SDAC harmonized day-ahead clearing price limits allow
  negative prices down to `-500` EUR/MWh and upper bounds up to `+4000` EUR/MWh (with automatic
  upward adjustment increments to `+5000` EUR/MWh); silver uses `[-500, 5000]` EUR/MWh as
  plausibility bounds.
- **Partial post-switch hours**: If silver ever contains fewer than 4 quarter-hour slots for a
  post-switch UTC hour (for example due to a single corrupted bronze record excluded in silver),
  `fact_price` averages the available valid slots for that hour rather than dropping the hour.
- **Daily schedule timing**: Nord Pool typically publishes D+1 prices by ~13:45 Europe/Tallinn
  time (12:45 CET/CEST). Scheduling the daily pipeline around 14:30 Europe/Tallinn time (accounting
  for UTC offset across winter/summer) with hourly retries handles occasional publication delays.

**Out of scope**

- Price marts (business-question / dashboard tables) and Superset dashboards — to be implemented
  separately.
- Elering grid / system data ingestion (`api/system`, `api/system/with-plan`) and `gold.fact_grid`.
- Deferred `dim_interval` attributes (`is_ee_holiday`, `tariff_period`, `quarter_of_hour`).
- Orchestrator failure alerts (email/Slack/etc.).
- Weather-vs-price combined marts or analyses.
- Retention or cleanup of bronze rows and local run files.
- Production deployment, TLS, or external secret managers.
