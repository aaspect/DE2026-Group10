# Feature Specification: Open-Meteo Weather Ingestion Job

**Feature Branch**: _not created_ (spec directory: `specs/001-open-meteo-ingestion`)

**Created**: 2026-11-10

**Status**: Draft

**Input**: User description: "Create the python ingestion job for the open-meteo weather data. See @docs/project_plan.pdf for extra context. The scope of this task should cover the python job which can be executed locally, further integrations will be implemented separately"

## User Scenarios & Testing *(mandatory)*

The project combines electricity prices, grid data and weather to answer questions such as "how do
wind speed and solar radiation affect electricity price and renewable production?". This feature
delivers the job that captures hourly weather for a fixed set of locations from Open-Meteo and
writes it unchanged to local files, one file per run, as records shaped for the raw (bronze)
layer. The job is run by a team member on their own machine. Loading the files into the warehouse
and scheduling the job are later, separate integrations.

### User Story 1 - Capture a weather forecast snapshot (Priority: P1)

A data engineer runs the weather job in **forecast** mode. The job retrieves the current hourly
forecast for every configured location and stores it as a new forecast version, labelled with the
time it was retrieved. Running the job again later stores another version next to the first one.
Forecasts made at different times can then be compared with the weather that actually occurred.

**Why this priority**: The job cannot reconstruct a forecast later if it was not captured while it
was current, so every missed snapshot is lost. Forecasts are also the weather information
available when the day-ahead price is set, which makes them central to the weather-vs-price
questions.

**Independent Test**: Run forecast mode once with the default locations. Check that the run's
output file holds one record per location per forecast hour, each marked as a forecast and all
sharing one run identifier and one retrieval time.

**Acceptance Scenarios**:

1. **Given** a valid location configuration and a reachable provider, **When** the engineer runs
   forecast mode, **Then** one record is stored for each location for each hour of the forecast
   horizon, marked as a forecast and carrying the retrieval time, run identifier and load time.
2. **Given** a forecast snapshot was stored by an earlier run, **When** forecast mode runs again,
   **Then** the new snapshot is written to a new file as a separate version, and the earlier file
   stays unchanged.
3. **Given** the provider fails or returns incomplete content for any location, **When** forecast
   mode runs, **Then** the job retries temporary failures. If the problem persists, the run ends
   with a failure status and a message naming the location and reason, and no output file is left
   behind.
4. **Given** a run has finished, **When** the engineer looks at the job's report, **Then** it
   shows the run identifier, mode, period covered, number of locations, number of records stored,
   the output file location and the outcome.

---

### User Story 2 - Capture observed weather for recent days (Priority: P2)

A data engineer runs the job in **archive** mode without giving a date range. The job retrieves
the observed hourly weather for each location over a rolling window of recent days and stores it.
Repeating this every day picks up observations the provider publishes late or corrects.

**Why this priority**: Observed weather is what gets compared with actual prices and production
(see example query 2 in `docs/examples.sql`). It ranks below forecasts because missed days can
still be recovered later with a backfill (User Story 3).

**Independent Test**: Run archive mode with default settings. Check that, for every location,
records exist for every hour of the 7 full UTC days before the run date (5 × 7 × 24 = 840 records),
all marked as archive.

**Acceptance Scenarios**:

1. **Given** no date range is supplied, **When** archive mode runs, **Then** one record is stored
   for each location for every hour of the 7 full UTC days before the run date.
2. **Given** the provider has not yet published values for some recent hours, **When** archive
   mode runs, **Then** those hours are stored with the values left missing. The run does not fail
   and nothing is filled in.
3. **Given** a day was already captured by an earlier run, **When** a later run captures it again,
   **Then** new records are added with a newer load time and a different run identifier, and the
   earlier records are left untouched.

---

### User Story 3 - Backfill historical observed weather (Priority: P3)

A data engineer runs archive mode with an explicit start and end date, for example covering the
whole period for which price data exists. This fills in the history needed for year-over-year,
seasonal and "historically best hours" analyses.

**Why this priority**: Several business questions need at least a year of history. A backfill is
an occasional, one-off action, and it reuses the archive capability from User Story 2.

**Independent Test**: Run archive mode for one past calendar month. Check that every location has
a record for every hour of every day in that month.

**Acceptance Scenarios**:

1. **Given** a valid start and end date in the past, **When** archive mode runs with that range,
   **Then** one record is stored for each location for every hour of every day in the inclusive
   range.
2. **Given** a range whose start is after its end, a malformed date, or an end date in the future,
   **When** the engineer starts the job, **Then** it refuses to run with a message explaining the
   problem, without contacting the provider or storing anything.
3. **Given** a range of one year, **When** archive mode runs, **Then** the backfill completes in a
   single run and stays within the provider's free usage limits.

---

### Edge Cases

- **Provider unreachable, slow, rate-limited or returning server errors**: the job retries a
  limited number of times with increasing waits. If it still fails, the run fails and writes no
  output file.
- **Successful but unusable response** (empty, hourly series missing, a requested variable missing,
  series of different lengths, or the wrong number of hours): the response is treated as invalid
  and is not retried. The run fails and stores nothing.
- **One location fails while the others succeed**: the whole run fails and stores nothing. A run is
  either complete or absent, never partial.
- **Individual hourly values missing**: they are stored as missing and the run does not fail.
- **Implausible values** (such as negative wind speed or cloud cover above 100 %): they are stored
  exactly as delivered. Plausibility is checked in the cleaned (silver) layer, not by this job.
- **Forecast includes hours before the retrieval time** (the provider returns the whole current
  day): these hours are stored as delivered. Their lead time is negative, and downstream layers
  may leave them out.
- **Daylight-saving changes**: they have no effect, because all times are requested and stored in
  UTC and every UTC day has exactly 24 hourly records.
- **The same mode is run twice in quick succession or overlapping**: each run has its own
  identifier and both are stored. Choosing the latest record is done downstream.
- **The output location is missing**: the job creates it, including any missing parent folders,
  before contacting the provider.
- **The output location cannot be created, is not writable or runs out of space**: the run fails
  with a clear message and leaves no partial file behind. Re-running the job fetches the data
  again.
- **The output location already holds files from earlier runs**: they are left as they are. Each
  run writes a new file named so that it cannot clash with any other run's file.
- **Location configuration is empty or invalid** (duplicate identifiers, latitude or longitude out
  of range, a required attribute missing): the job refuses to start and names the faulty entry.
- **The provider moves a location to its nearest grid point**: the record stores the grid-point
  coordinates and elevation reported by the provider, together with the configured location
  identifier.

## Requirements *(mandatory)*

### Functional Requirements

**Running the job**

- **FR-001**: The job MUST be runnable on a team member's machine with a single command, without
  any orchestration tool.
- **FR-002**: The job MUST offer two modes. **Forecast** mode captures the current hourly forecast,
  and **archive** mode captures observed hourly weather.
- **FR-003**: In forecast mode, the job MUST capture every hour for each configured location, from
  the start of the current UTC day up to a configurable horizon. The default horizon is 3 days
  (today plus the next 2), so the next day-ahead market delivery day is always fully covered.
- **FR-004**: In archive mode without an explicit period, the job MUST capture a rolling window of
  the 7 full UTC days before the run date. The window length MUST be configurable.
- **FR-005**: In archive mode, the job MUST accept an explicit inclusive start and end date for
  backfills. It MUST reject a range whose start is after its end, a malformed date, or an end date
  in the future, and it MUST do so before contacting the provider.

**Locations and configuration**

- **FR-006**: Locations MUST be read from configuration, not code. Each location has a stable
  identifier, a name, a latitude, a longitude, a bidding zone code and a role (for example demand,
  wind or solar). The default configuration contains the project's 5 fixed locations (see
  Assumptions).
- **FR-007**: The job MUST refuse to start when the location configuration is empty, contains
  duplicate identifiers, lacks a required attribute or contains out-of-range coordinates. The
  message MUST name the faulty entry.
- **FR-008**: All other settings MUST come from environment variables or configuration files. This
  covers provider addresses, forecast horizon, archive window, retry policy and output location.
  The job MUST also read these settings from an optional local `.env` file, where variables
  already set in the environment take precedence. Relative paths MUST NOT depend on the folder the
  job is started from. Credentials MUST NOT be stored in the repository.

**Data captured**

- **FR-009**: For every location and hour, the job MUST capture these values:
  - air temperature at 2 m (°C)
  - wind speed at 10 m (m/s)
  - wind direction at 10 m (degrees)
  - global horizontal (shortwave) solar radiation (W/m²)
  - direct solar radiation (W/m²)
  - total cloud cover (%)
  - precipitation (mm)

  The job MUST request these units from the provider rather than convert them itself.
- **FR-010**: Every stored record MUST carry:
  - the location identifier
  - the hour it describes, in UTC
  - its source type, `forecast` or `archive`
  - the grid-point latitude, longitude and elevation reported by the provider
  - the run identifier
  - the load time, in UTC
- **FR-011**: Forecast records MUST also carry the forecast version time, which is the UTC time the
  snapshot was retrieved. This lets lead time (hour described minus version time) be derived and
  lets different forecast versions be compared.
- **FR-012**: All times MUST be requested from the provider and stored in UTC.
- **FR-013**: Records MUST be stored as the provider delivered them, flattened into one record per
  location per hour. The job MUST NOT round, fill gaps, filter or check plausibility, and missing
  values MUST stay missing.

**Validation, failure handling and re-runs**

- **FR-014**: Before storing anything, the job MUST validate each provider response. A valid
  response reports success, is not empty, contains the hourly time series and every requested
  variable, and has series of equal length that match the expected number of hours.
- **FR-015**: The job MUST retry temporary failures with increasing waits, up to a configurable
  number of attempts (default 3). Temporary failures are connection errors, timeouts, rate
  limiting and provider-side errors. Invalid responses (FR-014) MUST NOT be retried.
- **FR-016**: Each run MUST store all of its records or none of them. If any location's data cannot
  be fetched or validated, or if writing the file fails, no output file from that run may remain,
  not even a partial one.
- **FR-017**: The job MUST signal success to whatever started it only when all records were
  stored, and signal failure otherwise. A future scheduler can then detect failures and retry.
- **FR-018**: Each run MUST only add a new output file and MUST NOT modify, overwrite or delete
  existing ones. Capturing the same location and hour again adds new records in the new file,
  told apart by run identifier and load time. Keeping only the latest record is the cleaned
  (silver) layer's job.
- **FR-019**: Each run MUST report its run identifier, mode, period covered, number of locations,
  number of records stored, output file location and outcome. A failed run MUST also report the
  location and the reason.
- **FR-020**: The job MUST stay within the provider's free usage limits during normal operation
  (4 forecast runs and 1 archive run per day) and during a backfill of at least one year.

**Destination**

- **FR-021**: The job MUST write each run's records to one new file in a configurable local output
  location. The file name MUST identify the mode and the run. Each file MUST hold only that run's
  records, in JSON format (JSON Lines: one JSON object per record). It MUST include every attribute from FR-009 to
  FR-011, so a later integration can load it into the warehouse's raw (bronze) weather table
  without reshaping. The job MUST NOT write to the warehouse.

**Verifiability**

- **FR-022**: The core behaviour MUST be verifiable without network access, using recorded sample
  responses. Core behaviour covers turning provider responses into records, validating responses
  and working out the period to capture in each mode.

### Key Entities *(include if feature involves data)*

- **Location**: a fixed place for which weather is captured. It has an identifier, name, latitude,
  longitude, bidding zone code and role. It is maintained in configuration and is the origin of
  the location dimension (`dim_location`) in the data model.
- **Raw weather record**: one hour of weather for one location from one run. It holds the weather
  values from FR-009 and the metadata from FR-010 and FR-011. Its natural key is location + hour +
  source type, plus forecast version time for forecasts. Records are never updated, and later runs
  add newer copies. This entity feeds `fact_weather`, whose grain is one row per location per hour
  per forecast version.
- **Ingestion run**: one execution of the job. It has a run identifier, mode, requested period,
  start time, outcome, record count and output file. Every record it stores carries its
  identifier.
- **Run output file**: the result of one successful run, holding that run's raw weather records
  and nothing else. Files are never changed after they are written. They are the hand-over point
  to the later warehouse-loading integration.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A team member with the documented settings in place can capture a forecast snapshot
  for all configured locations with one command in under 1 minute.
- **SC-002**: A default archive run stores exactly locations × 7 days × 24 hours records (840 for 5
  locations), with no missing or duplicate location-hour pairs within the run.
- **SC-003**: A one-year backfill for 5 locations (about 43,800 records) completes in one run in
  under 5 minutes without exceeding the provider's free usage limits.
- **SC-004**: Every run that hits an unrecoverable provider or file-writing problem ends with a
  failure status and leaves no output file, complete or partial, behind.
- **SC-005**: Every stored record has location, hour, source type, run identifier and load time
  filled in, and every forecast record also has its forecast version time.
- **SC-006**: After two forecast runs at different times and one archive run, an analyst can
  compare both forecasts for the same location and hour with the observed value for that hour,
  using only the three output files.
- **SC-007**: The automated checks for the core behaviour run without network access and complete
  in under 10 seconds.

## Assumptions

**Users and operation**

- The job is run by team members (data engineers) on their own machines. A future orchestrator
  will invoke the same modes on the cadence in the project plan: a forecast snapshot every 6 hours
  and an archive run daily.
- Implementation language, tooling and testing approach follow `.specify/memory/constitution.md`.

**Locations**

- The default configuration contains 5 locations in the Estonian (EE) bidding zone, chosen to
  cover the main demand centres and wind and solar production areas. The proposed set is Tallinn,
  Tartu, Pärnu, Narva and Kuressaare.
- The final list and each location's role are a team decision that can be changed in
  configuration without code changes.

**Provider data**

- The provider's free, keyless access is used. The project is non-commercial, and normal
  operation needs only about 25 provider requests per day.
- The provider's default "best match" model selection is used for both forecasts and archive data.
- The forecast version is identified by the retrieval time. The provider's standard forecast
  response does not state which model run produced it.
- "Observed" weather means the provider's historical archive. This is model reanalysis rather
  than station measurements, and it is accepted as the actual weather for this project. The
  archive is published with a delay of a few days, which is why the rolling 7-day re-pull exists.
- For averaged or accumulated variables (radiation, precipitation), the provider's hourly
  timestamp refers to the preceding hour. Records are stored with the provider's timestamps, and
  aligning them to market intervals is done in the cleaned layer.
- Wind is captured at 10 m, the standard height available in both forecast and archive data.
  Hub-height wind could be added later if the analysis needs it.

**Existing project files**

- The repository holds two raw weather definitions that disagree with each other and with the
  project plan: `staging.raw_weather` in `infra/clickhouse/init/02_bronze_tables.sql` and
  `bronze.weather_hour` in `infra/README.md`. Neither has the forecast version time or run
  identifier, and the DDL also lacks wind direction, direct radiation and precipitation. FR-009 to
  FR-011 are the authoritative record content for this feature. This feature does not change
  those definitions. They are aligned with this record content as part of the warehouse-loading
  integration.
- Output files are kept until someone removes them. Retention and clean-up are left to the later
  integrations.

**Out of scope**

- Loading the output files into ClickHouse, and updating the bronze weather DDL and data
  dictionary.
- Scheduling and orchestration (the Airflow DAG).
- Container and Docker Compose setup.
- Cleaned and business-layer models (dbt), including deduplication, `dim_location` and
  `fact_weather`.
- Dashboards.
- Other data sources (Elering).
- Recovering forecast versions issued before the job started running.
