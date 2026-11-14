import json
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

from open_meteo.client import FetchError
from open_meteo.config import Settings, load_locations
from open_meteo.job import RunReport, run_job
from open_meteo.periods import resolve_period

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FORECAST_RESPONSE = json.loads((FIXTURES_DIR / "forecast_tallinn.json").read_text(encoding="utf-8"))
RECORDING_DATE = date.fromisoformat(FORECAST_RESPONSE["hourly"]["time"][0][:10])
RUN_ID = "3f2c9a8e-5b1d-4c47-9e0a-2d6f8b7c1a90"


def run_forecast_job(output_dir: Path, fetch: Callable[[str, Mapping[str, str]], Any]) -> RunReport:
    settings = Settings.from_env({"OPEN_METEO_OUTPUT_DIR": str(output_dir)})
    now = datetime.combine(RECORDING_DATE, time(9, 30, 12), tzinfo=UTC)
    period = resolve_period("forecast", now.date(), None, None, settings)
    locations = load_locations(settings.locations_file)
    return run_job("forecast", period, settings, locations, run_id=RUN_ID, now=now, fetch=fetch)


def test_successful_run_creates_folder_and_writes_one_complete_file(tmp_path: Path) -> None:
    output_dir = tmp_path / "a" / "b"

    report = run_forecast_job(output_dir, lambda url, params: FORECAST_RESPONSE)

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

    report = run_forecast_job(output_dir, fail_at_third_location)

    assert list(output_dir.iterdir()) == []
    assert report.outcome == "failure"
    assert report.failure == "location=parnu reason=HTTP 503 after 3 attempts"
    assert report.record_count == 0
    assert report.output_file is None
