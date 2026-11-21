"""Checks on a provider response and its flattening into raw weather records."""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from open_meteo.client import HOURLY_VARIABLES, InvalidResponseError
from open_meteo.config import Location
from open_meteo.periods import Period

GRID_POINT_KEYS = ("latitude", "longitude", "elevation")
RECORD_KEY_BY_VARIABLE = {
    "temperature_2m": "temperature_2m_c",
    "wind_speed_10m": "wind_speed_10m_ms",
    "wind_direction_10m": "wind_direction_10m_deg",
    "shortwave_radiation": "shortwave_radiation_wm2",
    "direct_radiation": "direct_radiation_wm2",
    "cloud_cover": "cloud_cover_pct",
    "precipitation": "precipitation_mm",
}


def validate_response(response: Any, period: Period) -> None:
    """Raise InvalidResponseError unless `response` holds every hour of `period`.

    Missing (`null`) values inside a series are allowed.
    """
    if not isinstance(response, dict):
        raise InvalidResponseError("response is not a JSON object")
    if response.get("error") is True:
        raise InvalidResponseError(f"provider reported an error: {response.get('reason')}")
    for key in GRID_POINT_KEYS:
        if response.get(key) is None:
            raise InvalidResponseError(f"response has no '{key}'")
    _validate_hourly(response.get("hourly"), period)


def _validate_hourly(hourly: Any, period: Period) -> None:
    if not isinstance(hourly, dict):
        raise InvalidResponseError("response has no 'hourly' object")
    for name in ("time", *HOURLY_VARIABLES):
        series = hourly.get(name)
        if not isinstance(series, list):
            raise InvalidResponseError(f"hourly series '{name}' is missing")
        if len(series) != period.expected_hours:
            raise InvalidResponseError(
                f"hourly series '{name}' has {len(series)} values, expected {period.expected_hours}"
            )
    expected_first_hour = f"{period.start_date.isoformat()}T00:00"
    if hourly["time"][0] != expected_first_hour:
        raise InvalidResponseError(
            f"hourly series starts at {hourly['time'][0]}, expected {expected_first_hour}"
        )


def build_records(
    response: Mapping[str, Any],
    location: Location,
    mode: str,
    retrieved_at: datetime,
    loaded_at: datetime,
    run_id: str,
) -> list[dict[str, Any]]:
    """Flatten a validated response into one record per hour, with values as delivered."""
    hourly = response["hourly"]
    forecast_version_at = _format_timestamp(retrieved_at) if mode == "forecast" else None
    formatted_loaded_at = _format_timestamp(loaded_at)
    records = []
    for index, provider_time in enumerate(hourly["time"]):
        hour = datetime.fromisoformat(provider_time).replace(tzinfo=UTC)
        values = {
            RECORD_KEY_BY_VARIABLE[variable]: hourly[variable][index]
            for variable in HOURLY_VARIABLES
        }
        records.append(
            {
                "location_id": location.location_id,
                "hour_utc": _format_timestamp(hour),
                "source_type": mode,
                "forecast_version_at": forecast_version_at,
                **values,
                "grid_latitude": response["latitude"],
                "grid_longitude": response["longitude"],
                "grid_elevation_m": response["elevation"],
                "run_id": run_id,
                "loaded_at": formatted_loaded_at,
            }
        )
    return records


def _format_timestamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")
