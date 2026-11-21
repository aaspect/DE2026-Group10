import json
from collections.abc import Mapping
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

from open_meteo.bronze import BronzeLoadError
from open_meteo.client import FetchError
from open_meteo.config import Settings, load_locations
from open_meteo.job import Fetch, Insert, RunReport, format_report, run_job
from open_meteo.periods import resolve_period

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FORECAST_RESPONSE = json.loads((FIXTURES_DIR / "forecast_tallinn.json").read_text(encoding="utf-8"))
RECORDING_DATE = date.fromisoformat(FORECAST_RESPONSE["hourly"]["time"][0][:10])
RUN_ID = "3f2c9a8e-5b1d-4c47-9e0a-2d6f8b7c1a90"
CREDENTIALS = {"CLICKHOUSE_USER": "pipeline", "CLICKHOUSE_PASSWORD": "pipeline"}


def fetch_recording(url: str, params: Mapping[str, str]) -> Any:
    return FORECAST_RESPONSE


def fail_fetch(url: str, params: Mapping[str, str]) -> Any:
    raise FetchError("HTTP 503 after 3 attempts")


def refuse_insert(rows: list[dict[str, Any]]) -> None:
    raise AssertionError("this run must not insert into bronze")


def run_forecast_job(
    output_dir: Path,
    fetch: Fetch = fetch_recording,
    *,
    destination: str = "warehouse",
    insert: Insert = refuse_insert,
) -> RunReport:
    settings = Settings.from_env(
        CREDENTIALS | {"OPEN_METEO_OUTPUT_DIR": str(output_dir)}, destination=destination
    )
    now = datetime.combine(RECORDING_DATE, time(9, 30, 12), tzinfo=UTC)
    period = resolve_period("forecast", now.date(), None, None, settings)
    locations = load_locations(settings.locations_file)
    return run_job(
        "forecast", period, settings, locations, run_id=RUN_ID, now=now, fetch=fetch, insert=insert
    )


def test_successful_run_creates_folder_and_writes_one_complete_file(tmp_path: Path) -> None:
    output_dir = tmp_path / "a" / "b"

    report = run_forecast_job(output_dir, destination="file")

    output_files = list(output_dir.iterdir())
    assert [file.suffix for file in output_files] == [".jsonl"]
    lines = output_files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 360
    assert {json.loads(line)["run_id"] for line in lines} == {RUN_ID}
    assert report.outcome == "success"
    assert report.record_count == 360
    assert report.output_file == output_files[0]


def test_failure_at_one_location_leaves_no_file(tmp_path: Path) -> None:
    output_dir = tmp_path / "a" / "b"
    requested_urls: list[str] = []

    def fail_at_third_location(url: str, params: Mapping[str, str]) -> Any:
        requested_urls.append(url)
        if len(requested_urls) == 3:
            raise FetchError("HTTP 503 after 3 attempts")
        return FORECAST_RESPONSE

    report = run_forecast_job(output_dir, fail_at_third_location, destination="file")

    assert list(output_dir.iterdir()) == []
    assert report.outcome == "failure"
    assert report.failure == "location=parnu reason=HTTP 503 after 3 attempts"
    assert report.record_count == 0
    assert report.output_file is None


def test_default_destination_inserts_the_whole_run_once_and_writes_no_file(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    inserts: list[list[dict[str, Any]]] = []

    report = run_forecast_job(output_dir, insert=inserts.append)

    [rows] = inserts
    assert len(rows) == 360
    assert {row["run_id"] for row in rows} == {RUN_ID}
    assert {row["record"]["location_id"] for row in rows} == {
        "tallinn",
        "tartu",
        "parnu",
        "narva",
        "kuressaare",
    }
    assert not output_dir.exists()
    assert report.outcome == "success"
    assert report.record_count == 360
    assert report.bronze_table == "bronze.open_meteo_weather"
    assert report.output_file is None


def test_failed_insert_fails_the_run_and_leaves_no_file(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"

    def fail_insert(rows: list[dict[str, Any]]) -> None:
        raise BronzeLoadError("bronze insert failed: ClickHouse code 60 (UNKNOWN_TABLE)")

    report = run_forecast_job(output_dir, destination="both", insert=fail_insert)

    assert list(output_dir.iterdir()) == []
    assert report.outcome == "failure"
    assert report.failure == "reason=bronze insert failed: ClickHouse code 60 (UNKNOWN_TABLE)"
    assert report.bronze_table is None
    assert report.output_file is None


def test_both_destinations_insert_before_writing_the_file(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    events: list[str] = []

    def insert(rows: list[dict[str, Any]]) -> None:
        events.append(f"insert with {len(list(output_dir.iterdir()))} files written")

    report = run_forecast_job(output_dir, destination="both", insert=insert)
    events.append(f"finished with {len(list(output_dir.iterdir()))} files written")

    assert events == ["insert with 0 files written", "finished with 1 files written"]
    assert report.outcome == "success"
    assert report.bronze_table == "bronze.open_meteo_weather"
    assert report.output_file == next(output_dir.iterdir())


def test_fetch_failure_never_inserts(tmp_path: Path) -> None:
    report = run_forecast_job(tmp_path / "output", fail_fetch)

    assert report.outcome == "failure"
    assert report.failure == "location=tallinn reason=HTTP 503 after 3 attempts"
    assert report.bronze_table is None


def test_report_names_the_destination_and_the_bronze_table(tmp_path: Path) -> None:
    loaded = run_forecast_job(tmp_path / "output", insert=lambda rows: None)
    failed = run_forecast_job(tmp_path / "output", fail_fetch)

    assert format_report(loaded).splitlines()[4:8] == [
        "records: 360",
        "destination: warehouse",
        "bronze_table: bronze.open_meteo_weather",
        "output_file: none",
    ]
    assert format_report(failed).splitlines()[4:8] == [
        "records: 0",
        "destination: warehouse",
        "bronze_table: none",
        "output_file: none",
    ]
