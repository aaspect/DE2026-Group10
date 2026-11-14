"""Command line entry point: `python -m open_meteo forecast|archive [--destination ...]`.

A run is stored in the bronze table by default; `--destination file|both` writes the run file
instead or as well.
"""

import argparse
import functools
import logging
import sys
import uuid
from datetime import UTC, datetime

from open_meteo.bronze import insert_rows
from open_meteo.client import fetch_json
from open_meteo.config import DESTINATIONS, ConfigError, Settings, load_locations
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

    refusal = RunReport(
        run_id,
        args.mode,
        None,
        now.replace(microsecond=0),
        location_count=0,
        destination=args.destination or "none",
    )
    try:
        settings = Settings.from_env(destination=args.destination)
        refusal.destination = settings.destination
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
    insert = functools.partial(
        insert_rows,
        url=settings.clickhouse_url,
        user=settings.clickhouse_user,
        password=settings.clickhouse_password,
        timeout=settings.timeout_seconds,
    )
    report = run_job(
        args.mode, period, settings, locations, run_id=run_id, now=now, fetch=fetch, insert=insert
    )
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
    parser.add_argument(
        "--destination",
        choices=DESTINATIONS,
        help="where to store the run; overrides OPEN_METEO_DESTINATION (default: warehouse)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
