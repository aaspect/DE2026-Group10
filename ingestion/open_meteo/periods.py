"""The UTC date range one run captures."""

from dataclasses import dataclass
from datetime import date, timedelta

from open_meteo.config import ConfigError, Settings


class PeriodError(ConfigError):
    """The mode and dates given on the command line do not describe a valid period."""


@dataclass(frozen=True)
class Period:
    start_date: date
    end_date: date  # inclusive

    def __post_init__(self) -> None:
        if self.start_date > self.end_date:
            raise PeriodError(f"start date {self.start_date} is after end date {self.end_date}")

    @property
    def expected_hours(self) -> int:
        return ((self.end_date - self.start_date).days + 1) * 24

    def label(self) -> str:
        return f"{self.start_date.isoformat()}..{self.end_date.isoformat()}"


def resolve_period(
    mode: str, today: date, start: str | None, end: str | None, settings: Settings
) -> Period:
    """Work out the period a run captures. `today` is the current UTC date."""
    dates_given = start is not None or end is not None
    if mode == "forecast":
        if dates_given:
            raise PeriodError("--start-date and --end-date are only allowed in archive mode")
        return Period(today, today + timedelta(days=settings.forecast_days - 1))
    if mode == "archive":
        if dates_given:
            return _explicit_period(today, start, end)
        return Period(today - timedelta(days=settings.archive_days), today - timedelta(days=1))
    raise PeriodError(f"unknown mode '{mode}'")


def _explicit_period(today: date, start: str | None, end: str | None) -> Period:
    if start is None or end is None:
        raise PeriodError("--start-date and --end-date must be given together")
    period = Period(_parse_date(start, "--start-date"), _parse_date(end, "--end-date"))
    if period.end_date > today:
        raise PeriodError(f"end date {period.end_date} is after today ({today} UTC)")
    return period


def _parse_date(text: str, option: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise PeriodError(f"{option} '{text}' is not a valid date (expected YYYY-MM-DD)") from exc
