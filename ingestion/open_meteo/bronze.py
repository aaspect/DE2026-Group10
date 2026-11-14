"""Rows for `bronze.open_meteo_weather`, whose `record` column is native JSON, and the one insert.

The table is created by the stack (`infra/clickhouse/init/`); this module only inserts.
"""

import http.client
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from typing import Any

BRONZE_TABLE = "bronze.open_meteo_weather"
INSERT_QUERY = (
    f"INSERT INTO {BRONZE_TABLE} (record, run_id, source_type, loaded_at) FORMAT JSONEachRow"
)
INSERT_SETTINGS = {
    # `loaded_at` arrives as `2026-11-14T09:30:15Z`.
    "date_time_input_format": "best_effort",
    # Timestamps inside `record` stay strings, as delivered; silver types them.
    "input_format_try_infer_datetimes": "0",
    # The HTTP status then reflects the final outcome of the insert.
    "wait_end_of_query": "1",
    # One parser means one block, and one block is inserted atomically.
    "input_format_parallel_parsing": "0",
}
ERROR_NAME_PATTERN = re.compile(r"\(([A-Z][A-Z0-9_]*)\)")


class BronzeLoadError(Exception):
    """The insert did not succeed, so the run is not in bronze."""


def build_bronze_rows(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Wrap each record, unchanged, with the metadata columns copied out of it."""
    return [
        {
            "record": dict(record),
            "run_id": record["run_id"],
            "source_type": record["source_type"],
            "loaded_at": record["loaded_at"],
        }
        for record in records
    ]


def insert_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    url: str,
    user: str,
    password: str,
    timeout: float,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> None:
    """Insert `rows` with one statement, so all of them appear in bronze or none do.

    Raises BronzeLoadError on any failure. The insert is never retried here: a retry after an
    unclear outcome could load the run twice under the same run id.
    """
    query_string = urllib.parse.urlencode({"query": INSERT_QUERY, **INSERT_SETTINGS})
    body = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    request = urllib.request.Request(
        f"{url.rstrip('/')}/?{query_string}",
        data=body.encode("utf-8"),
        method="POST",
        headers={
            "X-ClickHouse-User": user,
            "X-ClickHouse-Key": password,
            "Content-Type": "application/x-ndjson; charset=utf-8",
        },
    )
    try:
        with opener(request, timeout=timeout) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        raise BronzeLoadError(f"bronze insert failed: {_describe_rejection(exc)}") from exc
    except (OSError, http.client.HTTPException) as exc:
        raise BronzeLoadError(f"bronze insert failed: {_describe_connection_error(exc)}") from exc


def _describe_rejection(error: urllib.error.HTTPError) -> str:
    """Name ClickHouse's error by code and name only: its full text can quote the request."""
    code = error.headers.get("X-ClickHouse-Exception-Code") if error.headers else None
    if code is None:
        return f"HTTP {error.code}"
    try:
        body = error.read().decode("utf-8", errors="replace")
    except OSError:
        body = ""
    names = ERROR_NAME_PATTERN.findall(body)
    return f"ClickHouse code {code} ({names[-1]})" if names else f"ClickHouse code {code}"


def _describe_connection_error(error: Exception) -> str:
    cause = error.reason if isinstance(error, urllib.error.URLError) else error
    return str(cause) or type(cause).__name__
