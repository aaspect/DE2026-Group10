import copy
import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from open_meteo.client import HOURLY_VARIABLES, InvalidResponseError
from open_meteo.config import Location
from open_meteo.periods import Period
from open_meteo.records import build_records, validate_response

FIXTURES_DIR = Path(__file__).parent / "fixtures"
TALLINN = Location("tallinn", "Tallinn", 59.4370, 24.7536, "EE", "demand")
RETRIEVED_AT = datetime(2026, 11, 14, 9, 30, 12, tzinfo=UTC)
LOADED_AT = datetime(2026, 11, 14, 9, 30, 15, tzinfo=UTC)
RUN_ID = "3f2c9a8e-5b1d-4c47-9e0a-2d6f8b7c1a90"
RECORD_KEYS = [
    "location_id",
    "hour_utc",
    "source_type",
    "forecast_version_at",
    "temperature_2m_c",
    "wind_speed_10m_ms",
    "wind_direction_10m_deg",
    "shortwave_radiation_wm2",
    "direct_radiation_wm2",
    "cloud_cover_pct",
    "precipitation_mm",
    "grid_latitude",
    "grid_longitude",
    "grid_elevation_m",
    "run_id",
    "loaded_at",
]


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def fixture_period(response: dict[str, Any]) -> Period:
    times = response["hourly"]["time"]
    start_date = date.fromisoformat(times[0][:10])
    return Period(start_date, start_date + timedelta(days=len(times) // 24 - 1))


def report_error(response: dict[str, Any]) -> Any:
    return {"error": True, "reason": "x"}


def wrap_in_list(response: dict[str, Any]) -> Any:
    return [response]


def remove_elevation(response: dict[str, Any]) -> Any:
    del response["elevation"]
    return response


def remove_hourly(response: dict[str, Any]) -> Any:
    del response["hourly"]
    return response


def remove_precipitation(response: dict[str, Any]) -> Any:
    del response["hourly"]["precipitation"]
    return response


def shorten_one_series(response: dict[str, Any]) -> Any:
    response["hourly"]["cloud_cover"].pop()
    return response


def trim_to_48_hours(response: dict[str, Any]) -> Any:
    response["hourly"] = {name: series[:48] for name, series in response["hourly"].items()}
    return response


def shift_first_hour(response: dict[str, Any]) -> Any:
    first_hour = response["hourly"]["time"][0]
    response["hourly"]["time"][0] = first_hour.replace("T00:00", "T01:00")
    return response


@pytest.mark.parametrize(
    "mutate",
    [
        report_error,
        wrap_in_list,
        remove_elevation,
        remove_hourly,
        remove_precipitation,
        shorten_one_series,
        trim_to_48_hours,
        shift_first_hour,
    ],
)
def test_validate_response_rejects_invalid_shapes(
    mutate: Callable[[dict[str, Any]], Any],
) -> None:
    fixture = load_fixture("forecast_tallinn.json")
    period = fixture_period(fixture)

    with pytest.raises(InvalidResponseError):
        validate_response(mutate(copy.deepcopy(fixture)), period)


def test_validate_response_accepts_missing_values() -> None:
    response = load_fixture("forecast_tallinn.json")
    for variable in HOURLY_VARIABLES:
        response["hourly"][variable][5] = None

    validate_response(response, fixture_period(response))


@pytest.mark.parametrize(
    ("fixture_name", "mode", "expected_count", "expected_first_hour", "expected_version"),
    [
        pytest.param(
            "forecast_tallinn.json",
            "forecast",
            72,
            "2026-11-14T00:00:00Z",
            "2026-11-14T09:30:12Z",
            id="forecast",
        ),
        pytest.param(
            "archive_tallinn.json", "archive", 48, "2026-11-10T00:00:00Z", None, id="archive"
        ),
    ],
)
def test_build_records_flattens_response(
    fixture_name: str,
    mode: str,
    expected_count: int,
    expected_first_hour: str,
    expected_version: str | None,
) -> None:
    response = load_fixture(fixture_name)

    records = build_records(response, TALLINN, mode, RETRIEVED_AT, LOADED_AT, RUN_ID)

    assert len(records) == expected_count
    assert all(list(record) == RECORD_KEYS for record in records)
    assert {record["source_type"] for record in records} == {mode}
    assert {record["forecast_version_at"] for record in records} == {expected_version}

    first_record = records[0]
    assert first_record["location_id"] == "tallinn"
    assert first_record["hour_utc"] == expected_first_hour
    assert first_record["grid_latitude"] == response["latitude"]
    assert first_record["grid_longitude"] == response["longitude"]
    assert first_record["grid_elevation_m"] == response["elevation"]
    assert first_record["run_id"] == RUN_ID
    assert first_record["loaded_at"] == "2026-11-14T09:30:15Z"

    delivered_cloud_cover = response["hourly"]["cloud_cover"]
    stored_cloud_cover = [record["cloud_cover_pct"] for record in records]
    assert stored_cloud_cover == delivered_cloud_cover
    assert [type(value) for value in stored_cloud_cover] == [
        type(value) for value in delivered_cloud_cover
    ]
