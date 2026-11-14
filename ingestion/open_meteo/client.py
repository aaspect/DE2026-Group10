"""Requests to the Open-Meteo endpoints, with retries for temporary failures."""

import http.client
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

from open_meteo.config import Location, Settings
from open_meteo.periods import Period

logger = logging.getLogger(__name__)

HOURLY_VARIABLES = (
    "temperature_2m",
    "wind_speed_10m",
    "wind_direction_10m",
    "shortwave_radiation",
    "direct_radiation",
    "cloud_cover",
    "precipitation",
)

HTTP_TOO_MANY_REQUESTS = 429
CONNECTION_ERRORS = (
    urllib.error.URLError,
    TimeoutError,
    ConnectionError,
    http.client.HTTPException,
)


class FetchError(Exception):
    """A temporary failure was still there after the last attempt."""


class InvalidResponseError(Exception):
    """The provider answered, but the answer cannot be used. Retrying would not help."""


def common_params(location: Location) -> dict[str, str]:
    return {
        "latitude": str(location.latitude),
        "longitude": str(location.longitude),
        "hourly": ",".join(HOURLY_VARIABLES),
        "timezone": "UTC",
        "temperature_unit": "celsius",
        "wind_speed_unit": "ms",
        "precipitation_unit": "mm",
        "timeformat": "iso8601",
    }


def build_params(
    location: Location, mode: str, period: Period, settings: Settings
) -> tuple[str, dict[str, str]]:
    """Return the endpoint URL and query parameters for one location's request."""
    if mode == "forecast":
        return (
            settings.forecast_url,
            common_params(location) | {"forecast_days": str(settings.forecast_days)},
        )
    date_range = {
        "start_date": period.start_date.isoformat(),
        "end_date": period.end_date.isoformat(),
    }
    return settings.archive_url, common_params(location) | date_range


def fetch_json(
    url: str,
    params: Mapping[str, str],
    *,
    timeout: float,
    max_attempts: int,
    retry_base_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> Any:
    """GET `url` with `params` and return the parsed JSON body.

    Raises FetchError when temporary failures outlast `max_attempts`, and InvalidResponseError
    when the provider rejects the request or the body is not JSON.
    """
    full_url = f"{url}?{urllib.parse.urlencode(params, safe=',')}"
    for attempt in range(1, max_attempts + 1):
        try:
            with opener(full_url, timeout=timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            if not _is_temporary_status(exc.code):
                raise InvalidResponseError(_describe_rejection(exc)) from exc
            problem = f"HTTP {exc.code}"
        except CONNECTION_ERRORS as exc:
            problem = _describe_connection_error(exc)
        else:
            return _parse_json(body)

        if attempt < max_attempts:
            wait_seconds = retry_base_seconds * 2 ** (attempt - 1)
            logger.warning(
                "attempt %d of %d failed (%s); retrying in %s s",
                attempt,
                max_attempts,
                problem,
                wait_seconds,
            )
            sleep(wait_seconds)
    attempts_text = "1 attempt" if max_attempts == 1 else f"{max_attempts} attempts"
    raise FetchError(f"{problem} after {attempts_text}")


def _is_temporary_status(status: int) -> bool:
    return status == HTTP_TOO_MANY_REQUESTS or status >= 500


def _describe_rejection(error: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(error.read())
    except (OSError, ValueError):
        payload = None
    reason = payload.get("reason") if isinstance(payload, dict) else None
    return f"HTTP {error.code}: {reason}" if reason else f"HTTP {error.code}"


def _describe_connection_error(error: Exception) -> str:
    cause = error.reason if isinstance(error, urllib.error.URLError) else error
    return str(cause) or type(cause).__name__


def _parse_json(body: bytes) -> Any:
    try:
        return json.loads(body)
    except ValueError as exc:
        raise InvalidResponseError("response body is not valid JSON") from exc
