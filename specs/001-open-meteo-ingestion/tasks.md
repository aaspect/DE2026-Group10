---

description: "Task list for the Open-Meteo weather ingestion job"
---

# Tasks: Open-Meteo Weather Ingestion Job

**Input**: Design documents from `specs/001-open-meteo-ingestion/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: Included. FR-022, SC-007, constitution principle III and research R12 require a small
offline pytest suite (about 7 focused tests). Do not add tests beyond the ones listed here
(constitution IV).

**Organization**: Tasks are grouped by user story. Mode-independent building blocks (configuration,
HTTP retry, response validation, atomic file writing) are in Phase 2. Each story adds its own mode
or input path on top.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story the task belongs to (US1, US2, US3)

## Path Conventions

- All source paths are relative to the repository root. The Python project root is `ingestion/`.
- Package: `ingestion/open_meteo/`. Tests: `ingestion/tests/open_meteo/`.
- All `uv` commands run from `ingestion/`.

## Conventions shared by all tasks

- Python 3.12, standard library only at runtime, plus `python-dotenv`. No other dependency.
- Public functions have type hints. Entities are `@dataclass(frozen=True)`.
- All datetimes are timezone-aware UTC (`datetime.UTC`). Output timestamps are formatted as
  `%Y-%m-%dT%H:%M:%SZ` (for example `"2026-11-14T00:00:00Z"`).
- The 7 hourly provider variables, in this order, are defined once as `HOURLY_VARIABLES` in
  `ingestion/open_meteo/client.py`: `temperature_2m, wind_speed_10m, wind_direction_10m,
  shortwave_radiation, direct_radiation, cloud_cover, precipitation`.
- Error types: `ConfigError` (in `config.py`, also used for invalid CLI dates via `PeriodError`
  in `periods.py`) → exit code `2`. `FetchError` and `InvalidResponseError` (in `client.py`) and
  `OSError` during output → exit code `1`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization, tooling and recorded fixtures

- [X] T001 Write `ingestion/pyproject.toml` (the file is currently empty): `[project]` with
  `name = "ingestion"`, `version = "0.1.0"`, `requires-python = ">=3.12"`,
  `dependencies = ["python-dotenv"]`; `[dependency-groups] dev = ["pytest", "ruff"]`;
  `[build-system]` using `hatchling` with `[tool.hatch.build.targets.wheel] packages =
  ["open_meteo"]` so the package (including `locations.toml`) is installed into the venv and
  `uv run --project ingestion python -m open_meteo` works from the repo root (quickstart §8);
  `[tool.ruff]` with `target-version = "py312"`, `line-length = 100`, `[tool.ruff.lint] select =
  ["E", "F", "I", "UP", "B"]`; `[tool.pytest.ini_options] testpaths = ["tests"]`.
- [X] T002 Run `uv sync` in `ingestion/` to create `ingestion/uv.lock` and the venv (depends on
  T001). Commit `uv.lock`.
- [X] T003 [P] Append `ingestion/output/` under the `# Project` section of `.gitignore` (`.env`
  is already ignored).
- [X] T004 [P] Create `ingestion/.env.example` starting with `# Copy to .env and uncomment to
  override.` followed by every variable from [contracts/configuration.md](contracts/configuration.md),
  commented out with its default: `OPEN_METEO_FORECAST_URL=https://api.open-meteo.com/v1/forecast`,
  `OPEN_METEO_ARCHIVE_URL=https://archive-api.open-meteo.com/v1/archive`,
  `OPEN_METEO_FORECAST_DAYS=3`, `OPEN_METEO_ARCHIVE_DAYS=7`, `OPEN_METEO_MAX_ATTEMPTS=3`,
  `OPEN_METEO_RETRY_BASE_SECONDS=2`, `OPEN_METEO_TIMEOUT_SECONDS=30`,
  `OPEN_METEO_OUTPUT_DIR=output/open_meteo`, `OPEN_METEO_LOCATIONS_FILE=open_meteo/locations.toml`.
- [X] T005 [P] Create `ingestion/open_meteo/locations.toml` with the comment `# Roles are a team
  decision; change here, not in code.` and five `[[locations]]` tables (keys `id`, `name`,
  `latitude`, `longitude`, `bidding_zone`, `role`) from research R10:
  `tallinn`/Tallinn/59.4370/24.7536/EE/demand, `tartu`/Tartu/58.3806/26.7251/EE/solar,
  `parnu`/Pärnu/58.3859/24.4971/EE/wind, `narva`/Narva/59.3772/28.1903/EE/demand,
  `kuressaare`/Kuressaare/58.2529/22.4848/EE/wind. Add a one-line comment per entry with its
  reasoning from R10.
- [X] T006 [P] Create empty `ingestion/open_meteo/__init__.py`, `ingestion/tests/__init__.py` and
  `ingestion/tests/open_meteo/__init__.py` (the test `__init__.py` files avoid basename clashes
  with the future Elering test packages).
- [X] T007 [P] Add `lint`, `format` and `test` targets to `Makefile` (create it if empty):
  `lint` → `cd ingestion && uv run ruff check . && uv run ruff format --check .`;
  `format` → `cd ingestion && uv run ruff format . && uv run ruff check --fix .`;
  `test` → `cd ingestion && uv run pytest`. Declare them `.PHONY`.
- [X] T008 [P] Write `.github/workflows/ci.yml` (currently empty): trigger on `pull_request` and
  `push` to `main`; one job on `ubuntu-latest` with `defaults.run.working-directory: ingestion`;
  steps `actions/checkout@v4`, `astral-sh/setup-uv@v5`, `uv sync --locked`,
  `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`.
- [X] T009 [P] Record the two fixtures with live calls and commit them unchanged (pretty-printing
  with `jq .` is fine):
  - `ingestion/tests/open_meteo/fixtures/forecast_tallinn.json` from
    `https://api.open-meteo.com/v1/forecast?latitude=59.4370&longitude=24.7536&hourly=temperature_2m,wind_speed_10m,wind_direction_10m,shortwave_radiation,direct_radiation,cloud_cover,precipitation&timezone=UTC&temperature_unit=celsius&wind_speed_unit=ms&precipitation_unit=mm&timeformat=iso8601&forecast_days=3`
    (72 hours; note the recording date, which is `hourly.time[0][:10]`, because tests use it as
    "today").
  - `ingestion/tests/open_meteo/fixtures/archive_tallinn.json` from
    `https://archive-api.open-meteo.com/v1/archive?latitude=59.4370&longitude=24.7536&hourly=temperature_2m,wind_speed_10m,wind_direction_10m,shortwave_radiation,direct_radiation,cloud_cover,precipitation&timezone=UTC&temperature_unit=celsius&wind_speed_unit=ms&precipitation_unit=mm&timeformat=iso8601&start_date=2026-11-10&end_date=2026-11-11`
    (48 hours).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Mode-independent building blocks used by every story

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

### Tests for Phase 2

- [X] T010 [P] Write `ingestion/tests/open_meteo/test_config.py` with one parametrised test
  (R12 #7) calling `load_locations(path)` on TOML written to `tmp_path`. Cases: no
  `[[locations]]` entries; duplicate `id`; missing `role`; `latitude = 91`; `longitude = -181`;
  `id = "Tallinn!"` (breaks `[a-z0-9_]+`); unknown key `foo`; missing file. Each must raise
  `ConfigError` whose message names the entry by `id`, or by 1-based position when `id` is
  missing. Also assert the shipped `open_meteo/locations.toml` loads as 5 locations.
- [X] T011 [P] Write `ingestion/tests/open_meteo/test_client.py` with one parametrised test of
  retry classification (R12 #4) for `fetch_json`, passing a stub `opener` and a recording stub
  `sleep`: (a) `URLError` then a 200 body → returns the parsed dict, opener called twice, sleep
  called with `[2.0]`; (b) `HTTPError` 503 three times with `max_attempts=3` → raises
  `FetchError` whose message contains `HTTP 503 after 3 attempts`, sleep called with `[2.0, 4.0]`;
  (c) `HTTPError` 429 then 200 → retried; (d) `HTTPError` 400 with body
  `{"error": true, "reason": "Parameter 'end_date' is out of allowed range"}` → raises
  `InvalidResponseError` containing the reason, opener called once, sleep never called; (e)
  `TimeoutError` → retried. Build `HTTPError` as `urllib.error.HTTPError(url, code, msg, {},
  io.BytesIO(body))`.
- [X] T012 [P] Write the validation test in `ingestion/tests/open_meteo/test_records.py`
  (R12 #2): load `fixtures/forecast_tallinn.json`, build the `Period` for its recorded date
  (3 days), and parametrise over mutated copies that must raise `InvalidResponseError`:
  `{"error": true, "reason": "x"}`; a list instead of an object; `elevation` removed; `hourly`
  removed; `hourly.precipitation` removed; one series one element shorter; all series trimmed to
  48 (wrong hour count); `hourly.time[0]` shifted to `T01:00`. Also assert the unmodified fixture
  with some values replaced by `None` passes.

### Implementation for Phase 2

- [X] T013 Implement `Location` and `load_locations(path: Path) -> list[Location]` in
  `ingestion/open_meteo/config.py`, plus `class ConfigError(Exception)`. Fields and rules
  (data-model.md): `location_id` (TOML key `id`) "required; non-empty; `[a-z0-9_]+`; unique across
  the file"; `name` "required; non-empty"; `latitude` "required; −90 ≤ value ≤ 90"; `longitude`
  "required; −180 ≤ value ≤ 180"; `bidding_zone` "required; non-empty (for example `EE`)"; `role`
  "required; non-empty (for example `demand`, `wind`, `solar`)". Raise `ConfigError` if the file
  is missing, cannot be parsed (`tomllib.TOMLDecodeError`), has no `[[locations]]` entries, any
  entry breaks a rule, or any entry has an unknown key. "Every error message names the entry,
  using its `id` or, if the `id` is missing, its 1-based position." Accept TOML integers for
  coordinates (convert to `float`); reject booleans.
- [X] T014 Implement `Settings` and `Settings.from_env(environ: Mapping[str, str] | None = None)
  -> Settings` in `ingestion/open_meteo/config.py` (depends on T013, same file). Define
  `PROJECT_DIR = Path(__file__).resolve().parent.parent` (the `ingestion/` directory). When
  `environ` is `None`, call `load_dotenv(PROJECT_DIR / ".env", override=False)` and use
  `os.environ`. Read the 9 `OPEN_METEO_*` variables with the defaults from
  [contracts/configuration.md](contracts/configuration.md). Rules (data-model.md): `forecast_url`
  and `archive_url` "non-empty URL"; `forecast_days` int "1 ≤ value ≤ 16 (provider maximum)";
  `archive_days` int "≥ 1"; `max_attempts` int "≥ 1"; `retry_base_seconds` float "≥ 0";
  `timeout_seconds` float "> 0"; `output_dir` and `locations_file` are `Path`s, resolved against
  `PROJECT_DIR` when relative and used as given when absolute. An unparsable or out-of-range value
  raises `ConfigError` naming the variable. Do not create or check paths here.
- [X] T015 [P] Implement `Period` in `ingestion/open_meteo/periods.py`: frozen dataclass with
  `start_date: date`, `end_date: date` (inclusive), rule "`start_date` ≤ `end_date`" enforced in
  `__post_init__`, and property `expected_hours` = "`(end_date − start_date + 1 day) × 24`". Add
  `class PeriodError(ConfigError)` and a `__str__`-style helper `Period.label()` returning
  `"YYYY-MM-DD..YYYY-MM-DD"` for the report.
- [X] T016 [P] Implement in `ingestion/open_meteo/client.py`: `HOURLY_VARIABLES` (see
  conventions), `class FetchError(Exception)`, `class InvalidResponseError(Exception)`, and
  `fetch_json(url: str, params: Mapping[str, str], *, timeout: float, max_attempts: int,
  retry_base_seconds: float, sleep: Callable[[float], None] = time.sleep, opener: Callable =
  urllib.request.urlopen) -> Any`. Build the URL with `urllib.parse.urlencode(params, safe=",")`.
  Retry on `URLError`, `TimeoutError`, HTTP 429 and HTTP 5xx; before retry *n* sleep
  `retry_base_seconds × 2^(n-1)`; after the last attempt raise `FetchError("HTTP <code> after <n>
  attempts")` (or the exception text for connection errors/timeouts). Other HTTP 4xx: read the
  body, take `reason` from its JSON if present, raise `InvalidResponseError` without retrying.
  A 200 body that is not valid JSON raises `InvalidResponseError`. Log each retry at WARNING via
  `logging.getLogger(__name__)`. Also add `common_params(location: Location) -> dict[str, str]`
  returning `latitude`, `longitude`, `hourly=",".join(HOURLY_VARIABLES)`, `timezone=UTC`,
  `temperature_unit=celsius`, `wind_speed_unit=ms`, `precipitation_unit=mm`,
  `timeformat=iso8601` ([contracts/open-meteo-requests.md](contracts/open-meteo-requests.md)).
- [X] T017 [P] Implement `validate_response(response: Any, period: Period) -> None` in
  `ingestion/open_meteo/records.py`, raising `InvalidResponseError` (from `client.py`) when any of
  these fails, with a message saying which check failed: 1. "The response is a JSON object, and
  `error` is not `true`." 2. "`latitude`, `longitude` and `elevation` are present." 3. "`hourly`
  is an object containing `time` and all 7 variables." 4. "Every `hourly` series has a length
  equal to `Period.expected_hours`." 5. "`hourly.time[0]` equals `start_date` at 00:00" (compare
  with `f"{period.start_date.isoformat()}T00:00"`). `null` values inside series are allowed.
- [X] T018 [P] Implement in `ingestion/open_meteo/output.py`: `prepare_output_dir(path: Path) ->
  None` (`path.mkdir(parents=True, exist_ok=True)`, then `os.access(path, os.W_OK)`; raise
  `OSError` with a clear message on failure); `output_file_name(mode: str, retrieved_at: datetime,
  run_id: str) -> str` returning `open_meteo_<mode>_<YYYYMMDDTHHMMSSZ>_<run_id>.jsonl`; and
  `write_records_atomically(records: Sequence[Mapping[str, Any]], directory: Path, file_name: str)
  -> Path`: write to `directory / f".{file_name}.tmp"` with `encoding="utf-8"`, one
  `json.dumps(record, ensure_ascii=False, separators=(",", ":"))` plus `"\n"` per record, flush
  and `os.fsync`, then `os.link(tmp, final)` (fails if the final name exists, never overwrites),
  then unlink the temp file. In a `try/finally`, always remove the temp file if it still exists.
  Return the final path.

**Checkpoint**: `uv run pytest` passes T010–T012; foundation ready.

---

## Phase 3: User Story 1 - Capture a weather forecast snapshot (Priority: P1) 🎯 MVP

**Goal**: `uv run python -m open_meteo forecast` writes one new JSON Lines file with
5 × 72 = 360 forecast records, all sharing one `run_id`, `forecast_version_at` and `loaded_at`,
and prints the run report. Any failure leaves no file.

**Independent Test**: quickstart §1. Run forecast mode twice; two files appear, the first is
unchanged, each has 360 lines with `"source_type": "forecast"`.

### Tests for User Story 1

- [X] T019 [P] [US1] Write the forecast case in `ingestion/tests/open_meteo/test_periods.py`:
  `resolve_period("forecast", today=date(2026, 11, 14), start=None, end=None, settings=...)` with
  `forecast_days=3` returns `2026-11-14..2026-11-16` and `expected_hours == 72`. Make the test
  parametrised so US2 and US3 can add cases.
- [X] T020 [P] [US1] Write the forecast case of the response → records test (R12 #1) in
  `ingestion/tests/open_meteo/test_records.py`: `build_records(fixture, location, "forecast",
  retrieved_at, loaded_at, run_id)` on `forecast_tallinn.json` returns 72 dicts; keys equal, in
  order, the 16 keys of [contracts/output-file.md](contracts/output-file.md); `hour_utc` of the
  first is `"<recorded date>T00:00:00Z"`; `source_type == "forecast"`;
  `forecast_version_at` equals the formatted `retrieved_at`; `cloud_cover_pct` equals the
  fixture's value with the same type (int stays int); `grid_latitude/longitude/elevation_m` equal
  the response's `latitude/longitude/elevation`. Parametrise so US2 can add the archive case.
- [X] T021 [P] [US1] Write `ingestion/tests/open_meteo/test_job.py` (R12 #5 and #6) calling
  `run_job` with a stub `fetch` that returns `forecast_tallinn.json` for every location, `now` set
  to the fixture's recording date at 09:30:12 UTC, the 5 shipped locations and
  `Settings.from_env({"OPEN_METEO_OUTPUT_DIR": str(tmp_path / "a" / "b")})`:
  (a) success: the nested folder is created, it holds exactly one `*.jsonl` file and no `.tmp`
  file, the file has 360 lines, all with one `run_id`, and the report has `outcome == "success"`,
  `record_count == 360`; (b) all-or-nothing: the stub raises `FetchError("HTTP 503 after 3
  attempts")` for the 3rd location (`parnu`) → no `*.jsonl` and no `.tmp` file in the folder,
  `outcome == "failure"`, `failure` contains `location=parnu`.

### Implementation for User Story 1

- [X] T022 [US1] Implement `resolve_period(mode: str, today: date, start: str | None, end: str |
  None, settings: Settings) -> Period` in `ingestion/open_meteo/periods.py` with the forecast
  branch: "start_date = today, end_date = today + `forecast_days` − 1". Raise `PeriodError` for an
  unknown mode. Leave a clear place for the archive branches (US2, US3).
- [X] T023 [US1] Add `build_params(location: Location, mode: str, period: Period, settings:
  Settings) -> tuple[str, dict[str, str]]` to `ingestion/open_meteo/client.py`, returning
  `(settings.forecast_url, common_params(location) | {"forecast_days":
  str(settings.forecast_days)})` for `"forecast"`.
- [X] T024 [US1] Implement `build_records(response: Mapping[str, Any], location: Location, mode:
  str, retrieved_at: datetime, loaded_at: datetime, run_id: str) -> list[dict[str, Any]]` in
  `ingestion/open_meteo/records.py`. One dict per index `i` of `hourly.time`, keys in this order:
  `location_id`, `hour_utc` (parse `hourly.time[i]` with `datetime.fromisoformat`, set
  `tzinfo=UTC`, format as `%Y-%m-%dT%H:%M:%SZ`), `source_type` (= mode), `forecast_version_at`
  (formatted `retrieved_at` for forecast, `None` for archive), `temperature_2m_c`,
  `wind_speed_10m_ms`, `wind_direction_10m_deg`, `shortwave_radiation_wm2`,
  `direct_radiation_wm2`, `cloud_cover_pct`, `precipitation_mm` (each copied unchanged from
  `hourly.<variable>[i]`, `None` stays `None`), `grid_latitude`, `grid_longitude`,
  `grid_elevation_m` (from response `latitude`, `longitude`, `elevation`), `run_id`, `loaded_at`
  (formatted). No rounding, filling, filtering or range checks (FR-013).
- [X] T025 [US1] Implement `ingestion/open_meteo/job.py`: plain (non-frozen) dataclass `RunReport` with
  the IngestionRun fields from data-model.md (`run_id`, `mode`, `period: Period | None`,
  `retrieved_at`, `location_count`, `record_count` (0 until written), `output_file: Path | None`,
  `outcome: "success" | "failure"`, `failure: str | None`), and `run_job(mode: str, period:
  Period, settings: Settings, locations: list[Location], *, run_id: str, now: datetime, fetch:
  Callable[[str, Mapping[str, str]], Any]) -> RunReport`. Steps: `retrieved_at =
  now.replace(microsecond=0)`; `prepare_output_dir(settings.output_dir)` before any fetch; for each
  location in configuration order, `build_params` → `fetch` → `validate_response`, collecting
  responses in memory; only after all succeed take `loaded_at = datetime.now(UTC)` truncated to
  seconds, `build_records` for every location, then `write_records_atomically`. Catch
  `FetchError`/`InvalidResponseError` → `failure = f"location={id} reason={exc}"`; catch `OSError`
  from output → `failure = f"reason={exc}"` (no `location=`). Log progress per location at INFO.
- [X] T026 [US1] Add `format_report(report: RunReport) -> str` to `ingestion/open_meteo/job.py`,
  producing the `key: value` lines of [contracts/cli.md](contracts/cli.md) in this order:
  `run_id`, `mode`, `period` (`Period.label()` or `none`), `locations`, `records`, `output_file`
  (path relative to `PROJECT_DIR` when inside it, else absolute, or `none`), `outcome`, and
  `failure` only when the outcome is `failure`.
- [X] T027 [US1] Implement `ingestion/open_meteo/__main__.py`: `argparse` with a positional `mode`
  (choices `forecast`, `archive`); `logging.basicConfig(stream=sys.stderr, level=INFO)`; generate
  `run_id = str(uuid.uuid4())` and `now = datetime.now(UTC)`; load `Settings.from_env()` and
  `load_locations(settings.locations_file)`, then `resolve_period(...)`. On `ConfigError`
  (including `PeriodError`) print a failure report (`period: none` if not resolved, `locations:`
  count loaded so far or 0, `failure: reason=<message>`) to stdout and exit `2` without
  contacting the provider. Otherwise call `run_job` with `fetch = functools.partial(fetch_json,
  timeout=settings.timeout_seconds, max_attempts=settings.max_attempts,
  retry_base_seconds=settings.retry_base_seconds)`, print `format_report` to stdout, and exit `0`
  on success or `1` on failure. Wrap in `def main() -> int` and `raise SystemExit(main())`.
- [X] T028 [US1] Run quickstart §1 live and confirm: `exit=0` in under 1 minute, report shows
  `records: 360`, a second run adds a second file and leaves the first unchanged (`ls -l`).

**Checkpoint**: US1 is fully functional and testable on its own (MVP).

---

## Phase 4: User Story 2 - Capture observed weather for recent days (Priority: P2)

**Goal**: `uv run python -m open_meteo archive` writes 5 × 7 × 24 = 840 archive records for the
7 full UTC days before today, with `forecast_version_at` null.

**Independent Test**: quickstart §2. `records: 840`, period `<today-7>..<today-1>`, no duplicate
(`location_id`, `hour_utc`) pairs.

### Tests for User Story 2

- [X] T029 [P] [US2] Add the default-archive case to the parametrised test in
  `ingestion/tests/open_meteo/test_periods.py`: `resolve_period("archive", date(2026, 11, 14),
  None, None, settings)` with `archive_days=7` returns `2026-11-07..2026-11-13` and
  `expected_hours == 168`.
- [X] T030 [P] [US2] Add the archive case to the response → records test in
  `ingestion/tests/open_meteo/test_records.py`: `build_records` on `archive_tallinn.json` with
  mode `"archive"` returns 48 dicts, all with `source_type == "archive"` and
  `forecast_version_at is None`, first `hour_utc == "2026-11-10T00:00:00Z"`.

### Implementation for User Story 2

- [X] T031 [US2] Add the default archive branch to `resolve_period` in
  `ingestion/open_meteo/periods.py`: when `mode == "archive"` and both dates are `None`,
  "start_date = today − `archive_days`, end_date = today − 1".
- [X] T032 [US2] Add the archive branch to `build_params` in `ingestion/open_meteo/client.py`:
  return `(settings.archive_url, common_params(location) | {"start_date":
  period.start_date.isoformat(), "end_date": period.end_date.isoformat()})`.
- [X] T033 [US2] Run quickstart §2 live and confirm `records: 840`, `forecast_version_at` is
  `null` everywhere, and the `jq … | sort | uniq -d` duplicate check prints nothing.

**Checkpoint**: US1 and US2 both work independently.

---

## Phase 5: User Story 3 - Backfill historical observed weather (Priority: P3)

**Goal**: `archive --start-date S --end-date E` captures every hour of the inclusive range in one
run; invalid ranges are refused with exit code `2` before any provider contact.

**Independent Test**: quickstart §3 and §4. One past month gives 5 × days × 24 records; each
refused command exits `2` with no file written.

### Tests for User Story 3

- [X] T034 [P] [US3] Add to `ingestion/tests/open_meteo/test_periods.py`: the explicit case
  (`"2026-10-01"`, `"2026-10-31"` → `2026-10-01..2026-10-31`, `expected_hours == 744`), the
  `E == today` case (accepted), and one parametrised rejection test where each input raises
  `PeriodError`: `S > E` (`"2026-11-10"`, `"2026-11-01"`); malformed (`"2026-13-01"`,
  `"2026-13-02"`); only `start` given; only `end` given; `E > today` (`"2026-11-01"`,
  `"2099-01-01"`); dates given in forecast mode.

### Implementation for User Story 3

- [X] T035 [US3] Add the explicit-range branch and rejections to `resolve_period` in
  `ingestion/open_meteo/periods.py`. Rejected inputs (data-model.md), each raising `PeriodError`
  with a message explaining the problem: "a malformed date" (parse with `date.fromisoformat`);
  "only one of the two dates given"; "`S > E`"; "`E > today`"; "dates given in forecast mode".
- [X] T036 [US3] Add optional `--start-date` and `--end-date` (strings, `metavar="YYYY-MM-DD"`) to
  the parser in `ingestion/open_meteo/__main__.py` and pass them to `resolve_period`, so an
  invalid range takes the existing exit-`2` path before `run_job` is called.
- [X] T037 [US3] Run quickstart §3 (one month: `records: 3720`; one year: under 5 minutes) and
  §4 (each command exits `2`, the message explains the problem, no file is written).

**Checkpoint**: All user stories are independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final checks across all stories

- [X] T038 Run `uv run ruff check .` and `uv run ruff format --check .` in `ingestion/` and fix
  every finding without adding ignores.
- [X] T039 Run `uv run pytest --durations=5` with networking disabled (for example Wi-Fi off) and
  confirm all tests pass in under 10 seconds (SC-007). Confirm the suite has no more tests than
  listed in T010–T012, T019–T021, T029–T030 and T034.
- [X] T040 Run quickstart §5 (bad archive URL → `exit=1`, `failure:` names the first location, no
  `.jsonl` or `.tmp` file; nested missing `OPEN_METEO_OUTPUT_DIR` is created; uncreatable
  `/om-test` → `exit=1` before any request), §7 (two forecasts and one archive compare for one
  location-hour) and §8 (`.env` override, environment wins, run from repo root writes to
  `ingestion/output/open_meteo/`).
- [X] T041 Check that `ingestion/output/` and `ingestion/.env` show as ignored in `git status`,
  and that no file outside the plan's source tree was added.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies. T002 depends on T001; the rest are parallel.
- **Foundational (Phase 2)**: depends on Setup (T009 fixtures are needed by T012). Blocks all
  stories.
- **US1 (Phase 3)**: depends on Phase 2. Delivers the job pipeline (`job.py`, `__main__.py`).
- **US2 (Phase 4)**: depends on Phase 2 and on US1's `run_job` and CLI (T025–T027); it adds only
  the archive period and request parameters.
- **US3 (Phase 5)**: depends on US2 (archive mode) — the spec states the backfill reuses it.
- **Polish (Phase 6)**: depends on all stories.

### Within Each Phase

- Write the phase's tests first and see them fail, then implement.
- `config.py`: T013 → T014. `periods.py`: T015 → T022 → T031 → T035. `client.py`: T016 → T023 →
  T032. `records.py`: T017 → T024. `job.py`: T025 → T026 → T027.
- Tests in the same file are added sequentially across stories (`test_periods.py`: T019 → T029 →
  T034; `test_records.py`: T012 → T020 → T030).

### Parallel Opportunities

- Phase 1: T003–T009 in parallel after T001.
- Phase 2: T010, T011, T012 in parallel; T015, T016, T017, T018 in parallel with each other and
  with T013/T014.
- US1: T019, T020, T021 in parallel; T022, T023, T024 touch different files and can run in
  parallel before T025.
- US2: T029 and T030 in parallel; T031 and T032 in parallel.

---

## Parallel Example: User Story 1

```bash
# Tests for User Story 1 together:
Task: "Forecast case of resolve_period in ingestion/tests/open_meteo/test_periods.py"
Task: "Forecast case of build_records in ingestion/tests/open_meteo/test_records.py"
Task: "Success and all-or-nothing run_job tests in ingestion/tests/open_meteo/test_job.py"

# Independent implementation pieces, then the orchestrator:
Task: "resolve_period forecast branch in ingestion/open_meteo/periods.py"
Task: "build_params forecast in ingestion/open_meteo/client.py"
Task: "build_records in ingestion/open_meteo/records.py"
# then T025 → T026 → T027 in ingestion/open_meteo/job.py and __main__.py
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1: Setup
2. Phase 2: Foundational
3. Phase 3: US1 (forecast)
4. **Stop and validate** with quickstart §1. Forecast snapshots are the data that cannot be
   recovered later, so start capturing them as soon as this works.

### Incremental Delivery

1. Setup + Foundational → foundation ready
2. US1 → forecast snapshots (MVP)
3. US2 → daily rolling archive
4. US3 → backfill a year of history
5. Polish → lint, offline test timing, remaining quickstart scenarios

---

## Notes

- The PR description must justify the `python-dotenv` dependency (constitution II, research R9).
- Docker, Airflow, ClickHouse loading and bronze DDL changes are out of scope; do not touch
  `infra/`.
- Commit after each task or logical group.
