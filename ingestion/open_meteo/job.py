"""One run of the job: fetch every location, then write one file or none."""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from open_meteo.client import FetchError, InvalidResponseError, build_params
from open_meteo.config import PROJECT_DIR, Location, Settings
from open_meteo.output import output_file_name, prepare_output_dir, write_records_atomically
from open_meteo.periods import Period
from open_meteo.records import build_records, validate_response

logger = logging.getLogger(__name__)

Fetch = Callable[[str, Mapping[str, str]], Any]


@dataclass
class RunReport:
    run_id: str
    mode: str
    period: Period | None
    retrieved_at: datetime
    location_count: int
    record_count: int = 0
    output_file: Path | None = None
    outcome: Literal["success", "failure"] = "failure"
    failure: str | None = None


class _LocationFailure(Exception):
    """One location could not be fetched or validated, which fails the whole run."""


def run_job(
    mode: str,
    period: Period,
    settings: Settings,
    locations: list[Location],
    *,
    run_id: str,
    now: datetime,
    fetch: Fetch,
) -> RunReport:
    """Capture `period` for every location and write one output file, or none on any failure."""
    retrieved_at = now.replace(microsecond=0)
    report = RunReport(run_id, mode, period, retrieved_at, location_count=len(locations))
    try:
        prepare_output_dir(settings.output_dir)
        responses = _fetch_responses(mode, period, settings, locations, fetch)
        loaded_at = datetime.now(UTC).replace(microsecond=0)
        records = [
            record
            for location, response in zip(locations, responses, strict=True)
            for record in build_records(response, location, mode, retrieved_at, loaded_at, run_id)
        ]
        file_name = output_file_name(mode, retrieved_at, run_id)
        report.output_file = write_records_atomically(records, settings.output_dir, file_name)
    except _LocationFailure as exc:
        report.failure = str(exc)
    except OSError as exc:
        report.failure = f"reason={exc}"
    else:
        report.record_count = len(records)
        report.outcome = "success"
        logger.info("wrote %d records to %s", report.record_count, report.output_file)
    return report


def format_report(report: RunReport) -> str:
    lines = [
        f"run_id: {report.run_id}",
        f"mode: {report.mode}",
        f"period: {report.period.label() if report.period else 'none'}",
        f"locations: {report.location_count}",
        f"records: {report.record_count}",
        f"output_file: {_display_path(report.output_file)}",
        f"outcome: {report.outcome}",
    ]
    if report.outcome == "failure":
        lines.append(f"failure: {report.failure}")
    return "\n".join(lines)


def _fetch_responses(
    mode: str, period: Period, settings: Settings, locations: list[Location], fetch: Fetch
) -> list[Any]:
    responses = []
    for location in locations:
        logger.info("fetching %s weather for %s", mode, location.location_id)
        url, params = build_params(location, mode, period, settings)
        try:
            response = fetch(url, params)
            validate_response(response, period)
        except (FetchError, InvalidResponseError) as exc:
            raise _LocationFailure(f"location={location.location_id} reason={exc}") from exc
        responses.append(response)
    return responses


def _display_path(path: Path | None) -> str:
    if path is None:
        return "none"
    if path.is_relative_to(PROJECT_DIR):
        return str(path.relative_to(PROJECT_DIR))
    return str(path)
