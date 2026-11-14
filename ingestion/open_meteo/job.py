"""One run of the job: fetch every location, then insert into bronze and/or write one file."""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from open_meteo.bronze import BRONZE_TABLE, BronzeLoadError, build_bronze_rows
from open_meteo.client import FetchError, InvalidResponseError, build_params
from open_meteo.config import PROJECT_DIR, Location, Settings
from open_meteo.output import output_file_name, prepare_output_dir, write_records_atomically
from open_meteo.periods import Period
from open_meteo.records import build_records, validate_response

logger = logging.getLogger(__name__)

Fetch = Callable[[str, Mapping[str, str]], Any]
Insert = Callable[[list[dict[str, Any]]], None]


@dataclass
class RunReport:
    run_id: str
    mode: str
    period: Period | None
    retrieved_at: datetime
    location_count: int
    destination: str
    record_count: int = 0
    bronze_table: str | None = None
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
    insert: Insert,
) -> RunReport:
    """Capture `period` for every location, then store the run where `settings` says.

    Nothing is stored unless every location was fetched. With both destinations, the file is
    written only after the insert succeeded.
    """
    retrieved_at = now.replace(microsecond=0)
    report = RunReport(
        run_id, mode, period, retrieved_at, len(locations), destination=settings.destination
    )
    try:
        if settings.writes_file:
            prepare_output_dir(settings.output_dir)
        responses = _fetch_responses(mode, period, settings, locations, fetch)
        loaded_at = datetime.now(UTC).replace(microsecond=0)
        records = [
            record
            for location, response in zip(locations, responses, strict=True)
            for record in build_records(response, location, mode, retrieved_at, loaded_at, run_id)
        ]
        _store_records(records, report, settings, insert)
    except _LocationFailure as exc:
        report.failure = str(exc)
    except (BronzeLoadError, OSError) as exc:
        report.failure = f"reason={exc}"
    else:
        report.record_count = len(records)
        report.outcome = "success"
    return report


def format_report(report: RunReport) -> str:
    lines = [
        f"run_id: {report.run_id}",
        f"mode: {report.mode}",
        f"period: {report.period.label() if report.period else 'none'}",
        f"locations: {report.location_count}",
        f"records: {report.record_count}",
        f"destination: {report.destination}",
        f"bronze_table: {report.bronze_table or 'none'}",
        f"output_file: {_display_path(report.output_file)}",
        f"outcome: {report.outcome}",
    ]
    if report.outcome == "failure":
        lines.append(f"failure: {report.failure}")
    return "\n".join(lines)


def _store_records(
    records: list[dict[str, Any]], report: RunReport, settings: Settings, insert: Insert
) -> None:
    """Insert into bronze and/or write the run file, noting on `report` what was stored."""
    if settings.writes_warehouse:
        insert(build_bronze_rows(records))
        report.bronze_table = BRONZE_TABLE
        logger.info("inserted %d records into %s", len(records), BRONZE_TABLE)
    if settings.writes_file:
        file_name = output_file_name(report.mode, report.retrieved_at, report.run_id)
        report.output_file = write_records_atomically(records, settings.output_dir, file_name)
        logger.info("wrote %d records to %s", len(records), report.output_file)


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
