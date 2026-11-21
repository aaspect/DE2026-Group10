import re
from datetime import date

import pytest

from open_meteo.config import Settings
from open_meteo.periods import PeriodError, resolve_period

TODAY = date(2026, 11, 14)
SETTINGS = Settings.from_env(
    {"OPEN_METEO_FORECAST_DAYS": "3", "OPEN_METEO_ARCHIVE_DAYS": "7"}, destination="file"
)


@pytest.mark.parametrize(
    ("mode", "start", "end", "expected_label", "expected_hours"),
    [
        pytest.param("forecast", None, None, "2026-11-14..2026-11-16", 72, id="forecast"),
        pytest.param("archive", None, None, "2026-11-07..2026-11-13", 168, id="archive-default"),
        pytest.param(
            "archive",
            "2026-10-01",
            "2026-10-31",
            "2026-10-01..2026-10-31",
            744,
            id="archive-explicit",
        ),
        pytest.param(
            "archive",
            "2026-11-14",
            "2026-11-14",
            "2026-11-14..2026-11-14",
            24,
            id="archive-ending-today",
        ),
    ],
)
def test_resolve_period(
    mode: str, start: str | None, end: str | None, expected_label: str, expected_hours: int
) -> None:
    period = resolve_period(mode, TODAY, start, end, SETTINGS)

    assert period.label() == expected_label
    assert period.expected_hours == expected_hours


@pytest.mark.parametrize(
    ("mode", "start", "end", "expected_message"),
    [
        pytest.param(
            "archive", "2026-11-10", "2026-11-01", "is after end date", id="start-after-end"
        ),
        pytest.param("archive", "2026-13-01", "2026-13-02", "is not a valid date", id="malformed"),
        pytest.param("archive", "2026-11-01", None, "must be given together", id="only-start"),
        pytest.param("archive", None, "2026-11-01", "must be given together", id="only-end"),
        pytest.param("archive", "2026-11-01", "2099-01-01", "is after today", id="end-in-future"),
        pytest.param(
            "forecast",
            "2026-11-01",
            "2026-11-02",
            "only allowed in archive mode",
            id="dates-in-forecast-mode",
        ),
    ],
)
def test_resolve_period_rejects_invalid_input(
    mode: str, start: str | None, end: str | None, expected_message: str
) -> None:
    with pytest.raises(PeriodError, match=re.escape(expected_message)):
        resolve_period(mode, TODAY, start, end, SETTINGS)
