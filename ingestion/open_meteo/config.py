"""Settings from the environment and locations from the TOML file."""

import math
import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self
from urllib.parse import urlsplit

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "OPEN_METEO_FORECAST_URL": "https://api.open-meteo.com/v1/forecast",
    "OPEN_METEO_ARCHIVE_URL": "https://archive-api.open-meteo.com/v1/archive",
    "OPEN_METEO_FORECAST_DAYS": "3",
    "OPEN_METEO_ARCHIVE_DAYS": "7",
    "OPEN_METEO_MAX_ATTEMPTS": "3",
    "OPEN_METEO_RETRY_BASE_SECONDS": "2",
    "OPEN_METEO_TIMEOUT_SECONDS": "30",
    "OPEN_METEO_OUTPUT_DIR": "output/open_meteo",
    "OPEN_METEO_LOCATIONS_FILE": "open_meteo/locations.toml",
}
PROVIDER_MAX_FORECAST_DAYS = 16

LOCATION_KEYS = ("id", "name", "latitude", "longitude", "bidding_zone", "role")
LOCATION_ID_PATTERN = re.compile(r"[a-z0-9_]+")


class ConfigError(Exception):
    """Settings, locations or arguments are invalid, so the job must not start."""


@dataclass(frozen=True)
class Location:
    location_id: str
    name: str
    latitude: float
    longitude: float
    bidding_zone: str
    role: str


@dataclass(frozen=True)
class Settings:
    forecast_url: str
    archive_url: str
    forecast_days: int
    archive_days: int
    max_attempts: int
    retry_base_seconds: float
    timeout_seconds: float
    output_dir: Path
    locations_file: Path

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Self:
        """Read settings from `environ`, or from the process environment and `.env` if omitted."""
        if environ is None:
            load_dotenv(PROJECT_DIR / ".env", override=False)
            environ = os.environ
        return cls(
            forecast_url=_read_url(environ, "OPEN_METEO_FORECAST_URL"),
            archive_url=_read_url(environ, "OPEN_METEO_ARCHIVE_URL"),
            forecast_days=_read_int(
                environ, "OPEN_METEO_FORECAST_DAYS", maximum=PROVIDER_MAX_FORECAST_DAYS
            ),
            archive_days=_read_int(environ, "OPEN_METEO_ARCHIVE_DAYS"),
            max_attempts=_read_int(environ, "OPEN_METEO_MAX_ATTEMPTS"),
            retry_base_seconds=_read_seconds(
                environ, "OPEN_METEO_RETRY_BASE_SECONDS", zero_allowed=True
            ),
            timeout_seconds=_read_seconds(
                environ, "OPEN_METEO_TIMEOUT_SECONDS", zero_allowed=False
            ),
            output_dir=_read_path(environ, "OPEN_METEO_OUTPUT_DIR"),
            locations_file=_read_path(environ, "OPEN_METEO_LOCATIONS_FILE"),
        )


def load_locations(path: Path) -> list[Location]:
    try:
        with path.open("rb") as file:
            document = tomllib.load(file)
    except OSError as exc:
        raise ConfigError(f"locations file {path} cannot be read: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"locations file {path} is not valid TOML: {exc}") from exc

    entries = document.get("locations")
    if not isinstance(entries, list) or not entries:
        raise ConfigError(f"locations file {path} has no [[locations]] entries")

    locations: list[Location] = []
    seen_ids: set[str] = set()
    for position, entry in enumerate(entries, start=1):
        location = _parse_location(entry, position)
        if location.location_id in seen_ids:
            raise ConfigError(f"location '{location.location_id}': duplicate id")
        seen_ids.add(location.location_id)
        locations.append(location)
    return locations


def _parse_location(entry: Any, position: int) -> Location:
    if not isinstance(entry, dict):
        raise ConfigError(f"location #{position}: must be a [[locations]] table")
    label = _entry_label(entry, position)

    unknown_keys = sorted(set(entry) - set(LOCATION_KEYS))
    if unknown_keys:
        raise ConfigError(f"{label}: unknown key '{unknown_keys[0]}'")

    location_id = _require_text(entry, "id", label)
    if not LOCATION_ID_PATTERN.fullmatch(location_id):
        raise ConfigError(f"{label}: 'id' must match {LOCATION_ID_PATTERN.pattern}")
    return Location(
        location_id=location_id,
        name=_require_text(entry, "name", label),
        latitude=_require_coordinate(entry, "latitude", 90, label),
        longitude=_require_coordinate(entry, "longitude", 180, label),
        bidding_zone=_require_text(entry, "bidding_zone", label),
        role=_require_text(entry, "role", label),
    )


def _entry_label(entry: dict[str, Any], position: int) -> str:
    entry_id = entry.get("id")
    if isinstance(entry_id, str) and entry_id:
        return f"location '{entry_id}'"
    return f"location #{position}"


def _require_value(entry: dict[str, Any], key: str, label: str) -> Any:
    if key not in entry:
        raise ConfigError(f"{label}: missing required key '{key}'")
    return entry[key]


def _require_text(entry: dict[str, Any], key: str, label: str) -> str:
    value = _require_value(entry, key, label)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{label}: '{key}' must be a non-empty string")
    return value


def _require_coordinate(entry: dict[str, Any], key: str, limit: int, label: str) -> float:
    value = _require_value(entry, key, label)
    # bool is a subclass of int, so `true` would otherwise pass as the coordinate 1.
    is_number = isinstance(value, int | float) and not isinstance(value, bool)
    if not is_number or not -limit <= value <= limit:
        raise ConfigError(f"{label}: '{key}' must be a number from {-limit} to {limit}")
    return float(value)


def _read(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, DEFAULTS[name]).strip()
    if not value:
        raise ConfigError(f"{name} must not be empty")
    return value


def _read_url(environ: Mapping[str, str], name: str) -> str:
    value = _read(environ, name)
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ConfigError(f"{name} must be an http(s) URL, got '{value}'")
    return value


def _read_int(environ: Mapping[str, str], name: str, maximum: int | None = None) -> int:
    raw_value = _read(environ, name)
    allowed = "1 or more" if maximum is None else f"from 1 to {maximum}"
    try:
        value = int(raw_value)
    except ValueError:
        value = 0
    if value < 1 or (maximum is not None and value > maximum):
        raise ConfigError(f"{name} must be a whole number, {allowed}, got '{raw_value}'")
    return value


def _read_seconds(environ: Mapping[str, str], name: str, *, zero_allowed: bool) -> float:
    raw_value = _read(environ, name)
    try:
        value = float(raw_value)
    except ValueError:
        value = math.nan
    minimum_met = value >= 0 if zero_allowed else value > 0
    if not math.isfinite(value) or not minimum_met:
        allowed = "0 or more" if zero_allowed else "greater than 0"
        raise ConfigError(f"{name} must be a number {allowed}, got '{raw_value}'")
    return value


def _read_path(environ: Mapping[str, str], name: str) -> Path:
    # A literal "~" from .env is not expanded by any shell and would create a folder named "~".
    path = Path(_read(environ, name)).expanduser()
    return path if path.is_absolute() else PROJECT_DIR / path
