# Feature Specification: Elering Grid Data Ingestion Job

**Feature Branch**: _not created_ (spec directory: `specs/003-elering-grid-data`)

**Created**: 2026-11-10

**Status**: Draft

**Input**: User description:

> Create the Python ingestion job for Elering Estonian grid data: actual system data (GET https://dashboard.elering.ee/api/system) and planned vs actual consumption and production (GET https://dashboard.elering.ee/api/system/with-plan). See @docs/project_plan.pdf for context.
>
> Scope: the job runs locally from the command line. Airflow scheduling, Docker Compose and loading into ClickHouse are separate later integrations.
>
> Follow the same conventions as specs/001-open-meteo-ingestion: one new local file per run, records stored as delivered (flattened, no aggregation or filtering), UTC timestamps, run ID and load time on every record, all-or-nothing runs, retries for temporary failures, configuration from environment variables or config files, and core logic testable offline with recorded responses.
>
> The data covers Estonia only and comes in 15-minute intervals. Store it as delivered; aggregation to hourly happens later in dbt.
>
> Modes:
> 1. Actual: re-fetch the last 48 hours on every run to catch late corrections (the plan runs this hourly). Record content follows bronze.elering_system in infra/README.md: consumption, production, renewable production, solar production, losses, system balance, AC balance, frequency and renewable share. If the API does not provide a field, flag it in the spec rather than derive it.
> 2. Plan: a window from 24 hours ago to 48 hours ahead, on the same hourly schedule. Record content follows bronze.elering_system_plan: series type (plan or actual), consumption and production.
> 3. Backfill: an explicit start and end date for either series, going back at least 12 months, because the consumption analyses compare against the same day last year and a trailing 4-week average.
>
> Write actual and plan records to separate output files, because they feed separate bronze tables. Every plan pull is kept, so plan revisions stay visible. Deciding which plan version fact_grid uses is out of scope.
>
> Edge cases to cover:
> - Intervals at the end of the window that are not yet published.
> - Some fields missing for some intervals.
> - Overlapping windows between consecutive hourly runs.

## Clarifications

### Session 2026-11-10

- Q: The actual feed delivers a row every 5 minutes, with grid frequency on every row and the other
  values only on rows that start a quarter hour. Should the job store every delivered row, or only
  the rows that start a quarter hour? → A: Store every delivered 5-minute row, including rows on
  which only grid frequency is filled (FR-010).

## User Scenarios & Testing *(mandatory)*

The project combines electricity prices, grid data and weather. Grid data answers questions such as
"how does daily consumption compare to the same day last year and the trailing 4-week average?",
"how do wind and solar radiation affect renewable production?" and "how accurate is the planned
consumption and production compared to what actually happened?", and it gives the key metric
"renewable share of total production". This feature delivers the job that captures Estonian power
system data from Elering, the Estonian transmission system operator, and writes it unchanged to
local files, one file per run, as records shaped for the raw (bronze) layer. The job is run by a
team member on their own machine. Loading the files into the warehouse and scheduling the job are
later, separate integrations.

Elering offers two feeds that this job uses (see Assumptions for what they contain):

- the **actual feed**: measured consumption, production, renewable and solar production, losses,
  system balance, AC balance and grid frequency;
- the **plan feed**: planned consumption and production next to the actual values, for the past and
  the near future.

### User Story 1 - Capture actual grid data for the last 48 hours (Priority: P1)

A data engineer runs the job in **actual** mode without giving a date range. The job retrieves the
actual feed for the last 48 hours and stores every interval it receives in a new actual-data file.
Running it every hour, as the project plan intends, re-captures each interval many times, so late
publications and corrections by Elering are picked up.

**Why this priority**: Actual consumption and production feed most of the grid-related business
questions and the renewable-share key metric. Without them, neither the consumption comparison nor
the plan-accuracy comparison can be answered.

**Independent Test**: Run actual mode once with the default settings. Check that the run's output
file holds a record for every row the provider delivered for the window. Together they cover the
576 five-minute rows of the last 48 hours, 192 of which start a quarter hour and carry the full set
of values, apart from rows the provider has not published yet or has skipped. All records share one
run identifier and one load time.

**Acceptance Scenarios**:

1. **Given** a reachable provider, **When** the engineer runs actual mode, **Then** one record is
   stored for each interval the provider delivers for the window, carrying the values listed in
   FR-008, the interval start in UTC, the run identifier and the load time.
2. **Given** the provider has not yet published the values for the most recent intervals, **When**
   actual mode runs, **Then** the intervals the provider delivers without values are stored with
   those values left missing, intervals the provider does not deliver are not created, and the run
   does not fail.
3. **Given** an interval was already captured by an earlier run, **When** a later run captures it
   again, **Then** a new record is added in the new file with a newer load time and a different run
   identifier, and the earlier file stays unchanged.
4. **Given** the provider fails or returns unusable content, **When** actual mode runs, **Then** the
   job retries temporary failures. If the problem persists, the run ends with a failure status and
   a message giving the reason, and no output file is left behind.
5. **Given** a run has finished, **When** the engineer looks at the job's report, **Then** it shows
   the run identifier, mode, period covered, number of records stored, the first and last interval
   stored, the output file location and the outcome.
6. **Given** the actual feed delivers 5-minute rows on which only grid frequency is filled, **When**
   actual mode runs, **Then** each of those rows is stored as its own record with frequency filled
   and the other values left missing, next to the quarter-hour rows that carry the full set of
   values.

---

### User Story 2 - Capture a plan snapshot (Priority: P2)

A data engineer runs the job in **plan** mode without giving a date range. The job retrieves the
plan feed for a window from 24 hours ago to 48 hours ahead and stores both the planned and the
actual consumption and production for every interval in a new plan-data file, labelled with the
time the plan was retrieved. Running it again an hour later stores another snapshot next to the
first one, so changes to the plan stay visible.

**Why this priority**: Elering only offers the current plan. A plan version that is not captured
while it is current cannot be retrieved later. It ranks below actual data because the plan-accuracy
question can still be answered from the latest plan (see User Story 3), while revisions are a
refinement.

**Independent Test**: Run plan mode once with the default settings. Check that the run's output file
holds, for every interval the provider delivered in the window, one record marked `plan` and, for
every interval already published, one record marked `actual`. All records share one run identifier,
one retrieval time and one load time.

**Acceptance Scenarios**:

1. **Given** a reachable provider, **When** the engineer runs plan mode, **Then** one record is
   stored for each interval of each series (`plan` and `actual`) that the provider delivers for the
   window, carrying consumption, production, the interval start in UTC, the series type, the
   retrieval time, the run identifier and the load time.
2. **Given** the provider has not yet published the plan for the last part of the window, **When**
   plan mode runs, **Then** the intervals the provider delivers without values are stored with the
   values left missing, and the run does not fail.
3. **Given** a plan snapshot was stored by an earlier run, **When** plan mode runs again, **Then**
   the new snapshot is written to a new file with its own retrieval time, and the earlier file stays
   unchanged.
4. **Given** the provider fails or returns unusable content, **When** plan mode runs, **Then** the
   behaviour is the same as in User Story 1, scenario 4.

---

### User Story 3 - Backfill historical grid data (Priority: P3)

A data engineer runs actual mode or plan mode with an explicit start and end date, for example
covering the last 13 months. This fills in the history needed to compare daily consumption with the
same weekday a year earlier and with the trailing 4-week average, and to measure plan accuracy by
month and hour of day.

**Why this priority**: The consumption and plan-accuracy questions need at least a year of history.
A backfill is an occasional, one-off action, and it reuses the capabilities from User Stories 1 and
2.

**Independent Test**: Run actual mode and plan mode for one past calendar month. Check that each
file covers every interval of every day in that month that the provider delivered.

**Acceptance Scenarios**:

1. **Given** a valid start and end date in the past, **When** actual or plan mode runs with that
   range, **Then** every interval the provider delivers that starts within the inclusive range is
   stored, in the same kind of file the mode produces without a range.
2. **Given** a range whose start is after its end, a malformed date, or an end date after the
   current UTC date, **When** the engineer starts the job, **Then** it refuses to run with a message
   explaining the problem, without contacting the provider or storing anything.
3. **Given** a range of 12 months or more, **When** either mode runs with that range, **Then** the
   backfill completes in a single run and produces a single output file.

---

### Edge Cases

- **Intervals at the end of the window that are not yet published**: in the actual feed, the most
  recent intervals are either not delivered at all or delivered with some values missing (solar
  production, for example, is published about a day later than the other values). In the plan feed,
  the plan for the far end of the window is delivered with values missing, and the actual series
  ends at the latest published interval. The job stores what is delivered, leaves missing values
  missing and does not create intervals that were not delivered. The run does not fail. Later runs
  whose window still covers these intervals pick up the values once they are published.
- **Some fields missing for some intervals**: a value that is empty or absent for an interval is
  stored as missing, and the run does not fail. A field that is absent from every interval of a
  non-empty response is treated as a sign that the provider changed its format, and the response is
  invalid (see below).
- **Intervals missing entirely**: the provider occasionally skips intervals (gaps of several hours
  were seen in the past year). Nothing is filled in. Completeness is checked in later layers.
- **Overlapping windows between consecutive hourly runs**: consecutive actual runs share about 47
  hours and consecutive plan runs about 71 hours. Every run stores everything it receives in its
  own file. The same interval therefore appears in many files, told apart by run identifier and load
  time, and for plan records by retrieval time. Keeping only the latest actual value is the cleaned
  (silver) layer's job, and choosing which plan version to use is out of scope.
- **The same mode is run twice in quick succession**: each run has its own identifier and both are
  stored.
- **Provider unreachable, slow, rate-limited or returning server errors**: the job retries a
  limited number of times with increasing waits. If it still fails, the run fails and writes no
  output file.
- **Successful but unusable response** (does not report success, no intervals at all, the plan or
  actual series missing from a plan-feed response, an interval without a valid start time, or an
  expected field absent from every interval): the response is treated as invalid and is not retried.
  The run fails and stores nothing.
- **A backfill needs several requests and one of them fails**: the whole run fails and stores
  nothing. A run is either complete or absent, never partial.
- **Data resolution changes over history**: the provider's resolution differs by period (see
  Assumptions). Actual values are quarter-hourly since 27 November 2025 and hourly before that,
  while the actual feed's rows, and its frequency values, come every 5 minutes. Records are stored
  at the resolution delivered, one record per delivered row (FR-010). Aligning them to hours
  happens in later layers.
- **Implausible or negative values** (negative system or AC balance, which is normal, or frequency
  far from 50 Hz): stored exactly as delivered. Plausibility is checked in the cleaned (silver)
  layer.
- **Daylight-saving changes**: they have no effect, because all times are stored in UTC.
- **The output location is missing, not writable or runs out of space**: the run fails with a clear
  message and leaves no partial file behind. Re-running the job fetches the data again.
- **The output location already holds files from earlier runs**: they are left as they are. Each run
  writes a new file named so that it cannot clash with any other run's file.
- **Plan for past intervals**: the provider returns only its latest plan for an interval, never the
  versions that were current earlier. A backfilled plan therefore holds one version per interval,
  and plan revisions are only visible for periods captured by regular plan runs.

## Requirements *(mandatory)*

### Functional Requirements

**Running the job**

- **FR-001**: The job MUST be runnable on a team member's machine with a single command, without
  any orchestration tool.
- **FR-002**: The job MUST offer two modes, and each run runs exactly one of them. **Actual** mode
  captures the actual feed. **Plan** mode captures the plan feed, both its plan series and its
  actual series.
- **FR-003**: In actual mode without an explicit period, the job MUST capture the window from 48
  hours before the start of the current UTC hour up to the run time. The look-back length MUST be
  configurable.
- **FR-004**: In plan mode without an explicit period, the job MUST capture the window from 24 hours
  before to 48 hours after the start of the current UTC hour. Both lengths MUST be configurable.
- **FR-005**: Both modes MUST accept an explicit inclusive start and end date (UTC calendar days) for
  backfills, and MUST handle a range of at least 12 months in one run. The job MUST reject a range
  whose start is after its end, a malformed date, or an end date after the current UTC date, and it
  MUST do so before contacting the provider.

**Configuration**

- **FR-006**: All settings MUST come from environment variables or configuration files, not code.
  This covers provider addresses, window lengths, retry policy and output location. The provider
  needs no credentials. Should one be needed later, it MUST NOT be stored in the repository.

**Data captured**

- **FR-007**: All data MUST be for Estonia, the only area the feeds cover. Records therefore carry no
  area or zone attribute.
- **FR-008**: For every interval delivered by the actual feed, the job MUST capture:
  - the interval start, in UTC
  - consumption (MW)
  - production (MW)
  - renewable production (MW)
  - solar production (MW)
  - losses (MW)
  - system balance (MW)
  - AC balance (MW)
  - grid frequency (Hz)
- **FR-009**: The job MUST NOT derive, calculate or fill any value the provider does not deliver.
  Two attributes of `bronze.elering_system` are affected and are flagged here:
  - **Renewable share** is not delivered by either feed. The job does not capture it. Whether it is
    derived later (for example from renewable production and consumption or production) is
    decided in the cleaned or business layer.
  - **Losses** are delivered as a field by the actual feed but were empty for every interval in
    samples covering the past 12 months. The job stores the field as delivered, so it is expected
    to stay empty.
    Planned losses exist only in the plan feed (see Assumptions).
- **FR-010**: The actual feed delivers a row every 5 minutes. Grid frequency is filled on every row,
  while the other values are filled only on rows that start a quarter hour (or, before 27 November
  2025, a full hour). The job MUST store every delivered row as its own record, with that row's
  start time, including rows on which only frequency is filled. Values not filled on a row MUST stay
  missing. Each delivered 5-minute row counts as one interval for FR-008, FR-014 and SC-002.
  Dropping or aggregating the frequency-only rows is the cleaned (silver) layer's job.
- **FR-011**: For every interval delivered by the plan feed, the job MUST capture one record per
  series with:
  - the interval start, in UTC
  - the series type, `plan` or `actual` (the provider's "real" series is stored as `actual`)
  - consumption (MW)
  - production (MW)
- **FR-012**: Every stored record MUST carry the run identifier and the load time, in UTC. Every
  record from plan mode MUST also carry the retrieval time, which is the UTC time at which the run
  retrieved the plan and identifies the plan version. All records from one run share the same run
  identifier, load time and retrieval time.
- **FR-013**: All times MUST be stored in UTC.
- **FR-014**: Records MUST be stored as the provider delivered them, flattened into one record per
  delivered interval (per series in plan mode). The job MUST NOT round, convert units, fill gaps,
  aggregate to hours, filter rows or check plausibility, and missing values MUST stay missing.

**Validation, failure handling and re-runs**

- **FR-015**: Before storing anything, the job MUST validate each provider response. A valid
  response reports success, contains at least one interval, contains both series in plan mode,
  gives every interval a valid start time, and contains every expected field (FR-008 or FR-011) in
  at least one interval.
- **FR-016**: The job MUST retry temporary failures with increasing waits, up to a configurable
  number of attempts (default 3). Temporary failures are connection errors, timeouts, rate limiting
  and provider-side errors. Invalid responses (FR-015) MUST NOT be retried.
- **FR-017**: Each run MUST store all of its records or none of them. If any part of the period
  cannot be fetched or validated, or if writing the file fails, no output file from that run may
  remain, not even a partial one.
- **FR-018**: The job MUST signal success to whatever started it only when all records were stored,
  and signal failure otherwise. A future scheduler can then detect failures and retry.
- **FR-019**: Each run MUST only add a new output file and MUST NOT modify, overwrite or delete
  existing ones. Every plan snapshot is kept. Capturing the same interval again adds new records in
  the new file, told apart by run identifier and load time. Keeping only the latest actual value is
  the cleaned (silver) layer's job, and choosing a plan version is out of scope.
- **FR-020**: Each run MUST report its run identifier, mode, period covered, number of records stored
  (per series in plan mode), first and last interval stored, output file location and outcome. A
  failed run MUST also report the reason.
- **FR-021**: The job MUST keep its load on the provider small. In normal operation a run contacts
  its feed once (apart from retries). A backfill MAY be split into several retrievals, which
  together form one run.

**Destination**

- **FR-022**: The job MUST write each run's records to one new file in a configurable local output
  location. The file name MUST identify the mode and the run. Actual-mode records and plan-mode
  records MUST go to separate files, because they feed separate raw tables (`bronze.elering_system`
  and `bronze.elering_system_plan`). Each file MUST hold only that run's records, in a
  machine-readable tabular format, with every attribute from FR-008 to FR-012, so a later
  integration can load it without reshaping. The job MUST NOT write to the warehouse.

**Verifiability**

- **FR-023**: The core behaviour MUST be verifiable without network access, using recorded sample
  responses. Core behaviour covers turning provider responses into records, validating responses
  and working out the period to capture in each mode.

### Key Entities *(include if feature involves data)*

- **Actual grid record**: one 5-minute row of measured Estonian power system data from one run
  (FR-010). It holds the values from FR-008, of which only frequency is filled on rows that do not
  start a quarter hour (or, for older periods, a full hour), and the run identifier and load time.
  Its natural key is the interval start. Records are never updated, and later runs add newer copies.
  It feeds `bronze.elering_system`, whose grain is therefore 5 minutes, and, through the cleaned
  layer, the `actual` rows of `fact_grid`, whose grain is one row per 60-minute interval per series
  type.
- **Plan grid record**: one interval of one series (`plan` or `actual`) from one plan snapshot. It
  holds consumption and production, the series type, the retrieval time, the run identifier and the
  load time. Its natural key is interval start + series type + retrieval time. It feeds
  `bronze.elering_system_plan` and, through the cleaned layer, the `plan` rows of `fact_grid`.
- **Plan snapshot**: all plan grid records from one plan-mode run. It is identified by its retrieval
  time and shows the plan as Elering published it at that moment.
- **Ingestion run**: one execution of the job. It has a run identifier, mode, requested period, start
  time, outcome, record count and output file. Every record it stores carries its identifier.
- **Run output file**: the result of one successful run, holding that run's records of one kind
  (actual or plan) and nothing else. Files are never changed after they are written. They are the
  hand-over point to the later warehouse-loading integration.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A team member with the documented settings in place can capture the last 48 hours of
  actual data, or a plan snapshot, with one command in under 1 minute.
- **SC-002**: In every output file, the number of records equals the number of intervals the
  provider delivered for the period (counted per series in plan mode), and no interval appears twice
  for the same series.
- **SC-003**: A 12-month backfill of either mode completes in one run in under 5 minutes.
- **SC-004**: Every run that hits an unrecoverable provider or file-writing problem ends with a
  failure status and leaves no output file, complete or partial, behind.
- **SC-005**: Every stored record has its interval start, run identifier and load time filled in,
  and every plan-mode record also has its series type and retrieval time.
- **SC-006**: After a 13-month backfill of actual data, an analyst can compute, for each of the last
  30 days, daily consumption, consumption on the same weekday 364 days earlier and the average over
  the previous 28 days, using only the output files.
- **SC-007**: After two plan runs at different times, an analyst can compare both plan versions for
  the same interval with the actual value for that interval, using only the two output files.
- **SC-008**: The automated checks for the core behaviour run without network access and complete in
  under 10 seconds.

## Assumptions

**Users and operation**

- The job is run by team members (data engineers) on their own machines. A future orchestrator will
  invoke both modes every hour, as in the project plan.
- Implementation language, tooling and testing approach follow `.specify/memory/constitution.md`.
- Backfill is not a separate mode. It is actual or plan mode run with an explicit date range, in the
  same way as the archive backfill in `specs/001-open-meteo-ingestion`.

**Provider data** (observed in sample responses retrieved on 2026-11-10, covering 2025-11-01 to
2026-11-12)

- The two feeds are the Elering services named in the feature description. They are public and need
  no key, and no usage limits are published. Normal operation needs about 2 requests per hour. A
  full year of either feed was retrieved in one request in a few seconds (about 20 MB).
- The provider gives each interval as a point in time that marks the interval start. It is stored
  as a UTC time.
- Values are average power in MW over the interval, and frequency is in Hz. The responses do not
  state units, and the job does not convert anything.
- **Actual feed resolution**: rows come every 5 minutes. Grid frequency is filled on every row. The
  other values are filled only on rows that start a quarter hour since 27 November 2025, and only
  on rows that start a full hour before that. This differs from the "15-minute intervals" in the
  feature description. Every row is stored (FR-010), so a 48-hour actual run yields about 576
  records and a year about 105,000.
- **Actual feed publication**: values are published roughly an hour after the interval. Solar
  production is published about a day later and is zero at night. A 48-hour re-fetch therefore
  covers both, as long as the provider's delays stay below 48 hours.
- **Actual feed fields**: renewable share is not delivered, and losses are delivered but always
  empty (FR-009). Every other `bronze.elering_system` attribute is delivered.
- **Plan feed**: it contains a plan series and an actual ("real") series, each with one row per
  quarter hour. Plan values are published up to about the end of the next day. Later intervals in
  the window are delivered with values missing. The actual series matches the actual feed's
  quarter-hour values, including the hourly-only values before 27 November 2025. Its frequency is a
  constant placeholder, which is one reason it is not used as the source of actual data.
- **Plan feed extra fields**: the plan series also delivers planned losses, system balance, AC
  balance, renewable production and solar forecasts. They are not part of
  `bronze.elering_system_plan` and are not captured. They can be added later if an analysis needs
  them.
- **Plan versions**: the plan feed has no version or issue time of its own, so the retrieval time
  identifies the version. Only the latest plan is available for past intervals.

**Existing project files**

- `infra/README.md` defines `bronze.elering_system` and `bronze.elering_system_plan`. Neither has the
  run identifier or the retrieval time, `bronze.elering_system` describes its time column as the
  start of the market interval while this feature stores 5-minute rows (FR-010),
  `renewable_share_pct` has no source, and the plan table
  describes the series type as "Real or plan" while `fact_grid` and `docs/examples.sql` use `actual`
  and `plan`. `infra/clickhouse/init/02_bronze_tables.sql` holds older raw consumption and
  production tables that match neither. FR-008 to FR-012 are the authoritative record content for
  this feature. This feature does not change those definitions. They are aligned with this record
  content as part of the warehouse-loading integration.
- Output files are kept until someone removes them. Retention and clean-up are left to the later
  integrations.

**Out of scope**

- Loading the output files into ClickHouse, and updating the bronze DDL and data dictionary.
- Scheduling and orchestration (the Airflow DAG).
- Container and Docker Compose setup.
- Cleaned and business-layer models (dbt), including deduplication, dropping or aggregating the
  frequency-only 5-minute rows, aggregation to hours, deriving
  renewable share, deciding which source provides the `actual` rows of `fact_grid`, and choosing
  which plan version `fact_grid` uses.
- Day-ahead prices and weather, which are separate ingestion jobs.
- Planned values other than consumption and production.
- Recovering plan versions issued before the job started running.
- Dashboards.
