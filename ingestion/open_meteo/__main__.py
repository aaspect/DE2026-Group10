"""Command line entry point: `python -m open_meteo forecast|archive`."""

import argparse
import functools
import logging
import sys
import uuid
from datetime import UTC, datetime

from open_meteo.client import fetch_json
from open_meteo.config import ConfigError, Settings, load_locations
from open_meteo.job import RunReport, format_report, run_job
from open_meteo.periods import resolve_period

EXIT_SUCCESS = 0
EXIT_RUN_FAILED = 1
EXIT_REFUSED = 2


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    run_id = str(uuid.uuid4())
    now = datetime.now(UTC)

    refusal = RunReport(run_id, args.mode, None, now.replace(microsecond=0), location_count=0)
    try:
        settings = Settings.from_env()
        locations = load_locations(settings.locations_file)
        refusal.location_count = len(locations)
        period = resolve_period(args.mode, now.date(), args.start_date, args.end_date, settings)
    except ConfigError as exc:
        refusal.failure = f"reason={exc}"
        print(format_report(refusal))
        return EXIT_REFUSED

    fetch = functools.partial(
        fetch_json,
        timeout=settings.timeout_seconds,
        max_attempts=settings.max_attempts,
        retry_base_seconds=settings.retry_base_seconds,
    )
    report = run_job(args.mode, period, settings, locations, run_id=run_id, now=now, fetch=fetch)
    print(format_report(report))
    return EXIT_SUCCESS if report.outcome == "success" else EXIT_RUN_FAILED


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m open_meteo",
        description="Capture hourly Open-Meteo weather for the configured locations.",
    )
    parser.add_argument("mode", choices=("forecast", "archive"), help="what to capture")
    parser.add_argument(
        "--start-date",
        metavar="YYYY-MM-DD",
        help="first UTC day of an archive backfill (inclusive); needs --end-date",
    )
    parser.add_argument(
        "--end-date",
        metavar="YYYY-MM-DD",
        help="last UTC day of an archive backfill (inclusive, not after today); needs --start-date",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
