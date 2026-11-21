# Research: Open-Meteo Weather Ingestion Job

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-11-14

Facts marked *(verified)* were checked with live calls to the Open-Meteo API on 2026-11-14.

## R1. Python version and packaging

- **Decision**: Python 3.12, managed with `uv`. The job lives in its own project at
  `ingestion/pyproject.toml` (currently empty) with `uv.lock` committed.
- **Rationale**: 3.12 is supported by current Airflow and dbt releases, so the later orchestration
  integration can run the same code. It includes `tomllib` (3.11+), which the configuration needs.
  `uv` is already on team machines and gives a one-command setup (`uv sync`).
- **Alternatives considered**: system Python 3.9 (no `tomllib`, end of life); Python 3.14 (newer
  than Airflow images support); pip + venv (works, but two manual steps instead of one).

## R2. HTTP client

- **Decision**: standard library `urllib.request` plus `json`, behind a single `fetch_json(url,
  params)` function.
- **Rationale**: Constitution II prefers the standard library. The job makes about 5 GET requests
  per run. A retry loop and status classification take a few lines and need no session pooling,
  async or streaming.
- **Alternatives considered**: `requests` or `httpx` (nicer API, but a new dependency for 5
  requests); `openmeteo-requests` (official client, but returns FlatBuffers and adds `numpy`,
  `requests-cache` and `retry-requests`, which is far more than needed).

## R3. Provider endpoints and request parameters

- **Decision**:
  - Forecast: `GET https://api.open-meteo.com/v1/forecast` with `forecast_days=<horizon>`.
  - Archive: `GET https://archive-api.open-meteo.com/v1/archive` with `start_date` and `end_date`.
  - Both use `hourly=temperature_2m,wind_speed_10m,wind_direction_10m,shortwave_radiation,direct_radiation,cloud_cover,precipitation`,
    `timezone=UTC`, `wind_speed_unit=ms`, `temperature_unit=celsius`, `precipitation_unit=mm`
    and `timeformat=iso8601`.
  - One request per location. Full parameters are in [contracts/open-meteo-requests.md](contracts/open-meteo-requests.md).
- **Rationale**:
  - `forecast_days=3` with no `past_days` returns 72 hours, starting at 00:00 UTC of the current
    day *(verified)*. This matches FR-003 exactly.
  - The response states its units in `hourly_units`, and they match FR-009 *(verified)*. Units
    are requested explicitly so that a change to the provider's defaults cannot change them.
  - One request per location means a failure is tied to exactly one location (FR-019), and
    validation stays a check on a single object.
  - Normal operation needs (4 forecast + 1 archive) × 5 = 25 requests per day, as the spec states.
- **Alternatives considered**: a single multi-location request (comma-separated coordinates). It
  returns a list of responses and saves 4 requests per run, but makes failures harder to
  attribute. Not needed at this volume.

## R4. Archive date limits and late data

- **Decision**: refuse an explicit `--end-date` later than today (UTC). The default window is the
  7 full UTC days before today (`today-7` … `today-1`).
- **Rationale**:
  - The archive API rejects later end dates with HTTP 400:
    `"Parameter 'end_date' is out of allowed range from 1940-01-01 to <today>"` *(verified)*.
    Checking locally first meets FR-005, which requires rejection before any provider contact.
  - With the default `best_match` model, the archive returned non-null values up to the current
    day *(verified)*. The most recent days are filled from high-resolution models and are later
    replaced by reanalysis (ERA5 and similar, about 5 days behind). The daily rolling re-pull
    (FR-004, FR-018) picks up these replacements. Any nulls the provider returns are stored as
    nulls (FR-013).
- **Alternatives considered**: forbidding `today` as an end date. Rejected because the provider
  accepts it and the spec only rules out *future* dates.

## R5. Grid-point coordinates

- **Decision**: store the `latitude`, `longitude` and `elevation` from each response as
  `grid_latitude`, `grid_longitude` and `grid_elevation_m`.
- **Rationale**: the provider snaps to its grid, and the grid differs between endpoints. For
  Tallinn (59.437, 24.7536), forecast returned (59.4395, 24.7571) and archive returned
  (59.4376, 24.8064) *(verified)*. Storing per-record grid coordinates keeps this visible for the
  silver layer.

## R6. Response validation (FR-014)

- **Decision**: a response is valid when all of the following hold. Otherwise it raises
  `InvalidResponseError`, which is not retried:
  1. it is a JSON object without `"error": true`
  2. it has `latitude`, `longitude`, `elevation` and an `hourly` object
  3. `hourly` has `time` and all 7 requested variables
  4. every series has the same length, equal to `days × 24`
  5. the first `time` equals 00:00 of the requested start date
- **Rationale**: these are the conditions FR-014 lists. Check 5 makes "the expected number of
  hours" mean the expected *hours* as well, which catches a shifted time zone. Null values inside
  a series are allowed (FR-013).
- **Alternatives considered**: a schema library such as `pydantic` or `jsonschema`. Rejected
  under constitution II, since the checks are about 20 lines.

## R7. Retry policy (FR-015)

- **Decision**:
  - Retry on `URLError` (connection errors), `TimeoutError`, HTTP 429 and HTTP 5xx.
  - Do not retry other HTTP 4xx responses. Open-Meteo returns 400 with a JSON `reason` for bad
    parameters *(verified)*. That reason is included in the failure message.
  - Waits are `base × 2^(attempt-1)` seconds. Defaults: 3 attempts, 2 s base, 30 s timeout per
    request.
  - The wait function is injected so tests do not sleep.
- **Rationale**: this is the simplest exponential backoff that meets FR-015. Worst case for a run
  of 5 locations is a few minutes, well within the SC-001 budget for runs that succeed.
- **Alternatives considered**: honouring `Retry-After` (Open-Meteo does not document it); the
  `tenacity` library (an extra dependency for one loop).

## R8. Output format and atomic write (FR-016, FR-018, FR-021)

- **Decision**:
  - The format is JSON Lines: UTF-8, one JSON object per record per line, written with the
    standard library `json`. Missing values are JSON `null`. The layout is in
    [contracts/output-file.md](contracts/output-file.md).
  - The file is named `open_meteo_<mode>_<YYYYMMDDTHHMMSSZ>_<run_id>.jsonl`.
  - All locations are fetched and validated into memory first. Writing starts only after every
    location has succeeded.
  - Records go to a hidden temporary file (`.<name>.tmp`) in the output directory. The temporary
    file is then hard-linked to the final name with `os.link`, which fails if that name exists,
    and removed. On any exception during writing, the temporary file is deleted.
  - Before any provider call, the output directory is created if it is missing
    (`Path.mkdir(parents=True, exist_ok=True)`) and checked to be writable. Failure at this step
    stops the run with exit code `1` before any data is fetched.
- **Rationale**:
  - JSON Lines needs no extra package and keeps types explicit: numbers stay numbers, and
    missing values are `null` rather than empty strings. ClickHouse loads it directly with
    `FORMAT JSONEachRow`, and line-by-line files are easy to inspect with `head` or `jq`.
  - Python's `json` writes floats in their shortest round-trip form, so the values in the file
    are exactly the values the provider delivered (FR-013).
  - Creating the directory removes a manual setup step. Doing it before fetching means that a
    bad path fails fast, without spending provider requests.
  - At most about 44k rows per run (SC-003) fit easily in memory.
  - Writing and renaming within one directory is atomic on POSIX file systems, so a reader never
    sees a partial file and a crash leaves at most a dot-prefixed `.tmp` file. A `.tmp` file left
    by a crash is not a valid output file, and no loader should pick it up.
  - Using `os.link` instead of `os.replace` means an existing file can never be overwritten
    (FR-018). The UUID in the name already makes a clash practically impossible.
- **Alternatives considered**:
  - Parquet: typed, but needs `pyarrow`, which is large.
  - CSV: tabular, but cannot tell a missing value apart from an empty string, and every value
    becomes text.
  - A single JSON array per file: valid JSON, but it has to be read in full and cannot be loaded
    line by line.
  - Failing when the output directory is missing: rejected at the team's request, because it adds
    a manual setup step.

## R9. Configuration (FR-006 to FR-008)

- **Decision**:
  - Locations are read from a TOML file (`ingestion/open_meteo/locations.toml` by default,
    overridable with `OPEN_METEO_LOCATIONS_FILE`) and parsed with `tomllib`.
  - Other settings come from `OPEN_METEO_*` environment variables, each with a default.
  - At start-up the job loads `ingestion/.env`, if the file exists, using `python-dotenv`
    (`load_dotenv(path, override=False)`). Variables already set in the environment take
    precedence over the file. `.env` is already git-ignored. A committed `ingestion/.env.example`
    lists every variable with its default. The job needs no credentials.
  - Every relative path, whether a default or a value from the environment or `.env`, is
    resolved against the `ingestion/` project directory, found from the package location, not
    against the current working directory. The job therefore reads and writes the same places
    whichever folder it is started from.
  - The full contract is in [contracts/configuration.md](contracts/configuration.md).
- **Rationale**:
  - TOML is in the standard library, readable, and supports an array of tables for locations.
  - Environment variables match how the later Airflow and Docker integrations pass settings.
    The `.env` file is a local convenience on top of them, so teammates don't have to export
    overrides by hand.
  - `python-dotenv` is the job's only runtime dependency. It is small and widely used, and it
    handles comments, quoting and `export` prefixes that a hand-written parser would need to
    reimplement. It needs a justification in the PR, per constitution II.
  - Resolving paths against the project directory stops a run from the repo root from creating
    an untracked top-level `output/` folder or failing to find the locations file.
- **Alternatives considered**:
  - YAML: needs `PyYAML`.
  - JSON: no comments, which matter for documenting each location's role.
  - `pydantic-settings`: a dependency for 8 values.
  - `uv run --env-file .env`: needs no code, but only works when the job is started through `uv`
    with the flag, which is easy to forget.
  - A hand-written `KEY=VALUE` parser: no dependency, but edge cases (quotes, comments, `export`)
    make it longer than it looks, and it would need its own tests.
  - Resolving paths against the current working directory: rejected because results would depend
    on where the command is run.

## R10. Default locations

- **Decision**: these 5 locations are proposed. Coordinates are city centres, and roles are a
  team decision that can be changed in configuration:

  | id | name | lat | lon | zone | role | reasoning |
  |---|---|---|---|---|---|---|
  | `tallinn` | Tallinn | 59.4370 | 24.7536 | EE | demand | largest demand centre |
  | `tartu` | Tartu | 58.3806 | 26.7251 | EE | solar | second city, south-east solar parks |
  | `parnu` | Pärnu | 58.3859 | 24.4971 | EE | wind | west-coast wind, offshore plans |
  | `narva` | Narva | 59.3772 | 28.1903 | EE | demand | north-east industry and oil-shale generation |
  | `kuressaare` | Kuressaare | 58.2529 | 22.4848 | EE | wind | Saaremaa island wind |

- **Rationale**: these locations cover the demand centres and the wind and solar areas named in
  the spec's assumptions.

## R11. Run identity and times

- **Decision**:
  - `run_id` is a UUID4 string.
  - `retrieved_at` is the UTC time the run starts, truncated to seconds. It becomes every
    forecast record's `forecast_version_at`.
  - `loaded_at` is the UTC time when records are built, just before writing, truncated to
    seconds. It is the same for every record in the run.
- **Rationale**: the spec requires one retrieval time and one run identifier for each forecast
  run (User Story 1). A single `loaded_at` per run makes "newer load time" comparisons between
  runs straightforward.

## R12. Testing approach (FR-022, SC-007)

- **Decision**:
  - pytest uses recorded fixtures: a 72-hour forecast and a 2-day archive response for one
    location, captured live once and committed under `ingestion/tests/open_meteo/fixtures/`.
  - The job takes its fetch function and wait function as arguments, so tests pass stubs and no
    mocking library is needed.
  - The tests cover:
    1. response → records (forecast and archive)
    2. validation rejects each invalid shape (one parametrised test)
    3. period resolution for forecast, default archive, explicit archive and rejected ranges
    4. retry classification (temporary errors are retried, invalid responses are not)
    5. all-or-nothing: a failure at one location leaves no file
    6. a successful run creates a missing output folder and writes exactly one file with the
       expected record count
    7. location configuration validation
- **Rationale**: these are the core behaviours named in constitution III and FR-022. Each one is
  covered by one focused test, and no test needs the network.
