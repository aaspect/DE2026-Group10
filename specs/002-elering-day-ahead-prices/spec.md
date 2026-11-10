# Feature Specification: Elering Day-Ahead Price Ingestion Job

**Feature Branch**: _not created_ (spec directory: `specs/002-elering-day-ahead-prices`)

**Created**: 2026-11-10

**Status**: Draft

**Input**: User description:

> Create the Python ingestion job for Elering day-ahead electricity prices (GET
> https://dashboard.elering.ee/api/nps/price) for the EE, FI, LV and LT bidding zones. See
> @docs/project_plan.pdf for context.
>
> Scope: the job runs locally from the command line. Airflow scheduling, Docker Compose and loading
> into ClickHouse are separate later integrations.
>
> Follow the same conventions as specs/001-open-meteo-ingestion: one new local file per run, records
> stored as delivered (flattened, no aggregation or filtering), UTC timestamps, run ID and load time
> on every record, all-or-nothing runs, retries for temporary failures, configuration from
> environment variables or config files, and core logic testable offline with recorded responses.
>
> Record content follows bronze.elering_prices in infra/README.md: zone code, interval start (UTC)
> and price in EUR/MWh. Also capture the interval end or length, so 15-minute and hourly prices can
> be told apart.
>
> Modes:
> 1. Next-day: fetch the next delivery day's prices. The plan runs this daily around 14:30 EET and
>    retries hourly until every zone has its full day. If any zone is incomplete, the run must fail
>    with a distinct "not yet published" outcome and write nothing.
> 2. Backfill: an explicit start and end date, going back at least 12 months, for the
>    year-over-year and seasonal analyses.
>
> Edge cases to cover:
> - Prices are 15-minute (96 per day) since October 2025 and hourly (24 per day) before that.
> - Daylight-saving change days have 92 or 100 quarter-hours (23 or 25 hours before October 2025).
> - Negative prices are valid and must not be rejected.
> - A delivery day can span two UTC dates.

## User Scenarios & Testing *(mandatory)*

The project's central metric is the day-ahead electricity price, and most business questions start
from it: the cheapest consecutive window to consume electricity on a given day, the hours that
historically paid best for selling solar power, and how wind and solar radiation move the price.
This feature delivers the job that captures day-ahead prices for the Estonian (EE), Finnish (FI),
Latvian (LV) and Lithuanian (LT) bidding zones from Elering and writes them unchanged to local
files, one file per run, as records shaped for the raw (bronze) layer. The job is run by a team
member on their own machine. Loading the files into the warehouse and scheduling the job are later,
separate integrations.

Day-ahead prices for a delivery day are set in a single daily auction and published early in the
afternoon of the day before. Until October 2025 the market priced every hour. Since then it prices
every quarter-hour. Both kinds of history must be captured and told apart.

### User Story 1 - Capture the next delivery day's prices (Priority: P1)

A data engineer runs the price job in **next-day** mode in the afternoon. The job retrieves the
prices for every interval of the next delivery day for all four zones and stores them in a new
file. If the prices are not yet fully published, the run ends with a distinct "not yet published"
outcome and stores nothing, so it can simply be run again an hour later.

**Why this priority**: Next-day prices are what consumers and producers act on ("when should I run
my heat pump tomorrow?"). The project plan expects them to be loaded by 16:00 EET every day. This
is the job's recurring daily task.

**Independent Test**: After the next day's prices are published, run next-day mode once with the
default zones. Check that the run's output file holds exactly one record per zone for every
interval of the next delivery day (4 × 96 = 384 records on a normal day), and that all records share
one run identifier and one load time.

**Acceptance Scenarios**:

1. **Given** the next delivery day's prices are published for every configured zone, **When** the
   engineer runs next-day mode, **Then** one record is stored for each zone for each market interval
   of that day. Each record holds the zone code, interval start and end in UTC, the price in
   EUR/MWh, the run identifier and the load time.
2. **Given** at least one configured zone is missing some or all intervals of the next delivery day
   (for example, the run starts before the daily auction results are out, when the provider holds
   only the day's first local hour), **When** next-day mode runs, **Then** the run ends with the
   "not yet published" outcome. This outcome can be told apart from a failure, its message names
   each incomplete zone with the number of intervals delivered and expected, and no output file is
   left behind.
3. **Given** an earlier next-day run ended with "not yet published", **When** next-day mode runs
   again after publication, **Then** it succeeds and stores the full day in one new file. The
   earlier attempt left nothing to clean up.
4. **Given** the next delivery day contains negative or zero prices, **When** next-day mode runs,
   **Then** those prices are stored exactly as delivered and the run succeeds.
5. **Given** the provider fails or times out, **When** next-day mode runs, **Then** the job retries
   temporary failures. If the problem persists, the run ends with a failure status and a message
   naming the reason, and no output file is left behind.
6. **Given** a run has finished, **When** the engineer looks at the job's report, **Then** it shows
   the run identifier, mode, delivery days covered, zones, number of records stored per zone, the
   output file location and the outcome.

---

### User Story 2 - Backfill historical prices (Priority: P2)

A data engineer runs the job in **backfill** mode with an explicit start and end delivery day, for
example the last 12 or 24 months. The job retrieves every interval of every day in the range for
all four zones and stores them in one new file. This provides the history for year-over-year,
seasonal and "historically best hours" analyses, and also recovers any day a next-day run missed.

**Why this priority**: Several business questions need at least a year of price history, for
example the best selling hours per season over the last 12 months (example query 4 in
`docs/examples.sql`). A backfill is an occasional action, and missed next-day runs can be recovered
with it, so it ranks below the daily capture.

**Independent Test**: Run backfill mode for a past range that contains the October 2025 switch to
15-minute prices and at least one daylight-saving change. Check that every zone has one record per
market interval for every day in the range, that intervals before the switch are 60 minutes long
and those after it 15 minutes, and that each day's intervals cover the whole day without gaps or
overlaps.

**Acceptance Scenarios**:

1. **Given** a valid start and end delivery day in the past, **When** backfill mode runs with that
   range, **Then** one record is stored for each zone for every market interval of every day in the
   inclusive range.
2. **Given** a range covering both hourly and 15-minute history, **When** backfill mode runs,
   **Then** each record's interval end shows whether it is an hourly (60-minute) or a quarter-hour
   (15-minute) price, and each zone's intervals for a day add up to exactly the length of that day.
3. **Given** a range that includes daylight-saving change days, **When** backfill mode runs,
   **Then** those days have 23 or 25 hourly intervals before October 2025 and 92 or 100
   quarter-hour intervals after it, per zone.
4. **Given** a range longer than one year (for example 24 months), **When** backfill mode runs,
   **Then** the backfill completes in a single run and stores one output file.
5. **Given** a range whose start is after its end, a malformed date, or an end after the current
   delivery day, **When** the engineer starts the job, **Then** it refuses to run with a message
   explaining the problem, without contacting the provider or storing anything.
6. **Given** a range that reaches back to days for which the provider has no prices for some zone,
   **When** backfill mode runs, **Then** the run fails, naming the zone and the first incomplete
   day, and no output file is left behind.
7. **Given** some days in the range were already captured by earlier runs, **When** the backfill
   runs, **Then** new records are added in a new file with a newer load time and a different run
   identifier, and the earlier files are left untouched.

---

### Edge Cases

- **Hourly and 15-minute history**: delivery days before the 15-minute go-live have one price per
  hour (24 per zone), and days after it one price per quarter-hour (96 per zone). The interval end
  on each record tells them apart.
- **The switchover day**: on 1 October 2025 (Estonian time) the first local hour still belongs to
  the last hourly market day. That day therefore has 1 hourly interval followed by 92 quarter-hour
  intervals, 93 per zone in total. This is a complete day and must not be treated as incomplete or
  invalid.
- **Daylight-saving change days**: the spring change day lasts 23 hours (23 hourly or 92
  quarter-hour intervals) and the autumn change day 25 hours (25 hourly or 100 quarter-hour
  intervals). Examples: 27 October 2024 (25), 30 March 2025 (23), 26 October 2025 (100), 29 March
  2026 (92).
- **A delivery day spans two UTC dates**: an Estonian delivery day runs from 22:00 UTC on the
  previous date to 22:00 UTC in winter, and from 21:00 UTC to 21:00 UTC in summer. Records of one
  delivery day therefore carry two different UTC dates. Completeness is always judged per delivery
  day, never per UTC date.
- **Negative, zero and extreme prices**: all are valid market outcomes (including prices at the
  market's price limits) and are stored exactly as delivered. Plausibility is checked in the
  cleaned (silver) layer, not by this job.
- **Next day partly available before publication**: before the auction results are out, the
  provider already holds the next day's first local hour, because it belongs to the previous
  auction. The day is incomplete, so next-day mode ends with "not yet published".
- **One zone late, others complete**: next-day mode ends with "not yet published" and stores
  nothing for any zone, even the complete ones. The report names only the incomplete zone.
- **Next-day run started around local midnight**: the next delivery day is worked out in Estonian
  time when the run starts. A run that starts just after midnight targets the following day. A day
  that was missed this way is recovered with a backfill.
- **Provider unreachable, slow, rate-limited or returning server errors**: the job retries a
  limited number of times with increasing waits. If it still fails, the run fails and writes no
  output file.
- **Successful but unusable response** (error status, unreadable content, a configured zone
  missing, an interval without a numeric price, an interval that is not one of the day's expected
  market intervals, the same interval twice, or intervals outside the requested days): the response
  is treated as invalid and is not retried. The run fails and stores nothing.
- **Backfill range longer than the provider allows in one request** (one year): the job still
  completes the whole range in one run and one output file.
- **Backfill reaching before a zone's price history starts**: the zone's days are incomplete, so
  the run fails, naming the zone and the first incomplete day.
- **The same days are captured twice** (repeated next-day runs after success, overlapping
  backfills, or a provider correction picked up later): each run has its own identifier and file,
  and both are kept. Choosing the latest record is done downstream.
- **The output location is missing, not writable or runs out of space**: the run fails with a clear
  message and leaves no partial file behind. Re-running the job fetches the data again.
- **The output location already holds files from earlier runs**: they are left as they are. Each
  run writes a new file named so that it cannot clash with any other run's file.
- **Zone configuration is empty or invalid** (no zones, duplicate codes, a code that is not two
  letters): the job refuses to start and names the faulty entry. A well-formed code the provider
  does not offer makes the response invalid (FR-015), so the run fails naming that zone.

## Requirements *(mandatory)*

### Functional Requirements

**Running the job**

- **FR-001**: The job MUST be runnable on a team member's machine with a single command, without
  any orchestration tool.
- **FR-002**: The job MUST offer two modes. **Next-day** mode captures the prices of the next
  delivery day, and **backfill** mode captures the prices of an explicit range of past delivery
  days.
- **FR-003**: In next-day mode, the job MUST capture every market interval of the delivery day that
  follows the current date, in delivery-day local time (FR-008), at the moment the run starts.
- **FR-004**: In backfill mode, the job MUST require an explicit inclusive start and end delivery
  day. It MUST reject a range whose start is after its end, a malformed date, or an end later than
  the current delivery day (today in delivery-day local time), and it MUST do so before contacting
  the provider.
- **FR-005**: Backfill mode MUST handle ranges of at least 12 months, including ranges longer than
  the provider's maximum period per request (one year), in a single run.

**Zones and configuration**

- **FR-006**: The bidding zones MUST be read from configuration, not code. The default configuration
  contains EE, FI, LV and LT. The job MUST refuse to start when the zone list is empty, contains
  duplicates or contains a code that is not two letters, and the message MUST name the faulty
  entry.
- **FR-007**: All other settings MUST come from environment variables or configuration files. This
  covers the provider address, the time zone that defines a delivery day (default Estonian local
  time), the moment 15-minute prices started (FR-009), the retry policy, the request timeout and
  the output location. The provider needs no credentials, and none MUST be stored in the
  repository.

**Delivery days and market intervals**

- **FR-008**: A delivery day MUST be a calendar day in the configured delivery-day time zone,
  running from local midnight to the next local midnight and expressed in UTC. It therefore spans
  two UTC dates and lasts 23, 24 or 25 hours.
- **FR-009**: The expected market intervals of a delivery day MUST be the consecutive intervals
  that cover the whole day: 60-minute intervals for intervals starting before the 15-minute go-live
  and 15-minute intervals from it on. The go-live moment defaults to 2025-09-30 22:00 UTC (the start
  of delivery day 1 October 2025 in market time). This gives 24 (23 or 25) hourly or 96 (92 or 100)
  quarter-hour intervals per zone, and 93 on the Estonian switchover day.
- **FR-010**: A zone's delivery day MUST count as complete only when the provider has delivered
  exactly one price for each of the day's expected intervals.

**Data captured**

- **FR-011**: For every configured zone and every delivered interval of the requested delivery
  days, the job MUST store one record carrying:
  - the zone code (EE, FI, LV or LT)
  - the interval start, in UTC
  - the interval end, in UTC
  - the price in EUR/MWh
  - the run identifier
  - the load time, in UTC
- **FR-012**: The provider reports only the start of each interval. The job MUST set the interval
  end to the start plus the interval length from FR-009, so that every hourly price has a 60-minute
  interval and every quarter-hour price a 15-minute interval, and each zone's intervals for a day
  meet end to start from the first to the last.
- **FR-013**: All times MUST be stored in UTC. Delivery days given by the engineer are local
  calendar dates (FR-008).
- **FR-014**: Records MUST be stored as the provider delivered them, flattened into one record per
  zone per interval. The job MUST NOT round prices, convert currency or units, aggregate
  quarter-hours into hours, fill gaps, or filter or reject prices by value. Negative and zero prices
  are valid.

**Validation, outcomes and re-runs**

- **FR-015**: Before storing anything, the job MUST validate each provider response. A valid
  response reports success, can be read, contains every configured zone, has a numeric price for
  every interval, contains only intervals that are expected intervals of the requested days, and
  contains no interval twice. An invalid response MUST fail the run with a message naming the zone
  and the reason.
- **FR-016**: In next-day mode, if the response is valid but any configured zone's day is
  incomplete (FR-010), the run MUST end with a **"not yet published"** outcome. The message MUST
  name each incomplete zone with the number of intervals delivered and expected, and nothing MUST
  be stored.
- **FR-017**: In backfill mode, if any configured zone has an incomplete day in the range, the run
  MUST fail, naming the zone, the first incomplete day and the number of incomplete days, and
  nothing MUST be stored.
- **FR-018**: The job MUST retry temporary failures with increasing waits, up to a configurable
  number of attempts (default 3). Temporary failures are connection errors, timeouts, rate limiting
  and provider-side errors. Invalid responses (FR-015) and incomplete days (FR-016, FR-017) MUST NOT
  be retried within the run. Re-running next-day mode later is the caller's job.
- **FR-019**: Each run MUST store all of its records or none of them. If any zone's data cannot be
  fetched, validated or completed, or if writing the file fails, no output file from that run may
  remain, not even a partial one.
- **FR-020**: The job MUST signal one of three outcomes to whatever started it: success (all records
  stored), not yet published (FR-016) and failure (anything else, including refusing to start). The
  caller MUST be able to tell the three apart without reading the message, so that a future
  scheduler can retry "not yet published" and raise an alert on failure.
- **FR-021**: Each run MUST only add a new output file and MUST NOT modify, overwrite or delete
  existing ones. Capturing the same zone and interval again adds new records in the new file, told
  apart by run identifier and load time. Keeping only the latest record is the cleaned (silver)
  layer's job.
- **FR-022**: Each run MUST report its run identifier, mode, delivery days covered, zones, number
  of records stored per zone and in total, output file location and outcome. A failed run MUST also
  report the zone, the day and the reason. A "not yet published" run MUST also report the
  incomplete zones as in FR-016.
- **FR-023**: The job MUST keep its load on the provider low. Apart from retries, a next-day run
  MUST need no more than one provider request, and a backfill no more than one request per started
  year of its range.

**Destination**

- **FR-024**: The job MUST write each run's records to one new file in a configurable local output
  location. The file name MUST identify the mode, the delivery days covered and the run. Each file
  MUST hold only that run's records, in a machine-readable tabular format. It MUST include every
  attribute from FR-011, so a later integration can load it into the warehouse's raw (bronze) price
  table without reshaping. The job MUST NOT write to the warehouse.

**Verifiability**

- **FR-025**: The core behaviour MUST be verifiable without network access, using recorded sample
  responses. Core behaviour covers working out delivery days and their expected intervals, turning
  provider responses into records with interval ends, validating responses, and deciding between
  complete, "not yet published" and invalid. The recorded samples MUST cover at least a 15-minute
  day, an hourly day, a daylight-saving change day, the switchover day, a partly published next day
  and negative prices.

### Key Entities *(include if feature involves data)*

- **Bidding zone**: a price area of the day-ahead market, identified by its two-letter code (EE, FI,
  LV, LT). It is maintained in configuration and is the origin of the bidding zone dimension
  (`dim_bidding_zone`), which records each zone's interval length over time.
- **Delivery day**: one local calendar day for which the market sets prices. It has a date, a start
  and end in UTC, a length (23, 24 or 25 hours) and a set of expected market intervals per zone.
  It is the unit for next-day capture, backfill ranges and completeness checks.
- **Raw price record**: the price of one market interval in one zone from one run. It holds the
  zone code, interval start and end in UTC, price in EUR/MWh, run identifier and load time. Its
  natural key is zone + interval start. Records are never updated, and later runs add newer copies.
  This entity feeds `fact_price`, whose grain is one row per zone per 60-minute interval after the
  cleaned layer aggregates quarter-hours.
- **Ingestion run**: one execution of the job. It has a run identifier, mode, requested delivery
  days, start time, outcome (success, not yet published or failed), record count and output file.
  Every record it stores carries its identifier.
- **Run output file**: the result of one successful run, holding that run's raw price records and
  nothing else. Files are never changed after they are written. They are the hand-over point to the
  later warehouse-loading integration.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Once the next day's prices are published, a team member with the documented settings
  in place can capture them for all four zones with one command in under 1 minute.
- **SC-002**: A successful next-day run stores exactly zones × expected intervals records: 384 for
  four zones on a normal day, 368 or 400 on a daylight-saving change day, with no missing or
  duplicate zone-interval pairs.
- **SC-003**: Every next-day run made before the next day is fully published for all zones ends
  with the "not yet published" outcome, which the caller tells apart from a failure without reading
  the message, and leaves no output file behind.
- **SC-004**: A backfill of the 12 months before the run date for four zones (about 140,000 records)
  completes in one run in under 2 minutes, and a 24-month backfill also completes in one run.
- **SC-005**: In a backfill that spans the October 2025 switch and daylight-saving changes, 100 % of
  zone-days have intervals that cover the whole day without gaps or overlaps, and 100 % of records
  have a 60-minute interval before the switch and a 15-minute interval after it.
- **SC-006**: Every run that hits an unrecoverable provider or file-writing problem ends with a
  failure status and leaves no output file, complete or partial, behind.
- **SC-007**: Every stored record has zone code, interval start, interval end, price, run
  identifier and load time filled in, and every stored price, including negative prices, equals the
  delivered value exactly.
- **SC-008**: An analyst can calculate the average price per zone per hour for the last 12 months,
  correctly combining hourly and quarter-hour intervals, using only the output files.
- **SC-009**: The automated checks for the core behaviour run without network access and complete
  in under 10 seconds.

## Assumptions

**Users and operation**

- The job is run by team members (data engineers) on their own machines. A future orchestrator will
  invoke next-day mode on the cadence in the project plan: daily around 14:30 EET, re-run hourly
  while the outcome is "not yet published". The plan's freshness target is next-day prices loaded
  by 16:00 EET. Backfills are started by hand when needed.
- Implementation language, tooling and testing approach follow `.specify/memory/constitution.md`.

**Delivery days and market intervals**

- A delivery day is the Estonian calendar day (EET, UTC+2 in winter; EEST, UTC+3 in summer). All
  four zones share this time zone, and the business questions and `dim_interval` use Estonian local
  dates. The time zone is configurable in case the team prefers the market's own day, which is
  defined in Central European Time.
- Because the market day is defined in Central European Time, the first local hour of an Estonian
  day (00:00 to 01:00) belongs to the previous day's auction. The whole next Estonian day is
  therefore available once the daily auction results are published, around 14:00 EET.
- The 15-minute go-live was delivery day 1 October 2025 in market time, which starts at 2025-09-30
  22:00 UTC. Interval lengths are determined from this moment rather than from the spacing of the
  delivered data, because the provider does not report them. Checking the delivered start times
  against the expected intervals (FR-015) confirms the lengths for every run.
- Both daylight-saving changes happen at 01:00 UTC on the last Sunday of March and October, in
  Estonian and Central European Time alike.

**Provider data** (checked against the live service on 2026-11-10)

- The provider is Elering's public day-ahead price service at
  `https://dashboard.elering.ee/api/nps/price`, which republishes Nord Pool day-ahead results. It is
  free and needs no key. It has no documented rate limits, and normal operation needs only a few
  requests per day.
- One request returns all four zones for a requested UTC period. For each zone (keyed in lower
  case: `ee`, `fi`, `lv`, `lt`) it returns a list of intervals, each with its start time as a UTC
  epoch timestamp and its price in EUR/MWh. **The interval end or length is not delivered** and is
  derived as described above. The stored zone code is the configured upper-case code, matching the
  data dictionary.
- The requested period includes both its start and its end, so a period ending exactly at the next
  local midnight would also return the first interval of the following day. The job must ask for
  periods that end just before the next delivery day starts.
- The maximum period per request is one year. Longer requests are refused with an error, so a
  longer backfill is split by the job.
- For days not yet published, the provider still reports success. It returns empty lists, or for
  the next day only the intervals of the first local hour.
- Prices are delivered with up to four decimal places. Negative prices occur regularly in all four
  zones.
- Price history for all four zones covers at least the 24 months before 2026-11-10 without gaps.
  Earlier history differs by zone (for example, Finland has prices in January 2012 and Estonia does
  not).

**Existing project files**

- The repository holds two raw price definitions that differ from each other and from this
  record content: `bronze.elering_prices` in `infra/README.md` (no interval end, no run
  identifier) and `staging.raw_prices` in `infra/clickhouse/init/02_bronze_tables.sql` (has an
  interval end but no run identifier, and uses other names). FR-011 is the authoritative record
  content for this feature. This feature does not change those definitions. They are aligned with
  this record content as part of the warehouse-loading integration.
- The plan's gold-layer completeness check (96 price intervals per zone per UTC day) holds only for
  days after the 15-minute go-live. That check belongs to the later dbt work.
- Output files are kept until someone removes them. Retention and clean-up are left to the later
  integrations.

**Out of scope**

- Loading the output files into ClickHouse, and updating the bronze price DDL and data dictionary.
- Scheduling and orchestration (the Airflow DAG), including the hourly re-runs and the 16:00 EET
  freshness alert.
- Container and Docker Compose setup.
- Cleaned and business-layer models (dbt), including deduplication, aggregation of quarter-hours to
  60-minute intervals, plausibility bounds, `dim_bidding_zone` and `fact_price`.
- Dashboards.
- Other data sources (Elering system and system-plan data, Elering trading volumes, Open-Meteo).
- Intraday or balancing prices, and prices in other currencies.
