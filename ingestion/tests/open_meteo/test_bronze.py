import io
import json
import urllib.request
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

import pytest

from open_meteo.bronze import BronzeLoadError, build_bronze_rows, insert_rows

URL = "http://clickhouse.invalid:8123"
PASSWORD = "s3cret-pipeline-password"
RUN_ID = "3f2c9a8e-5b1d-4c47-9e0a-2d6f8b7c1a90"
RECORDS = [
    {
        "location_id": "parnu",
        "hour_utc": "2026-11-14T00:00:00Z",
        "source_type": "forecast",
        "forecast_version_at": "2026-11-14T09:30:12Z",
        "temperature_2m_c": 4.2,
        "cloud_cover_pct": 100,
        "precipitation_mm": None,
        "run_id": RUN_ID,
        "loaded_at": "2026-11-14T09:30:15Z",
    },
    {
        "location_id": "parnu",
        "hour_utc": "2026-11-14T01:00:00Z",
        "source_type": "forecast",
        "forecast_version_at": "2026-11-14T09:30:12Z",
        "temperature_2m_c": 3.9,
        "cloud_cover_pct": 87,
        "precipitation_mm": 0.1,
        "run_id": RUN_ID,
        "loaded_at": "2026-11-14T09:30:15Z",
    },
]
AUTHENTICATION_FAILED_BODY = (
    b"Code: 516. DB::Exception: pipeline: Authentication failed: password is incorrect, or there "
    b"is no user with such name. (AUTHENTICATION_FAILED) (version 25.8.33.1 (official build))\n"
)


def insert(opener: Any) -> None:
    insert_rows(
        build_bronze_rows(RECORDS),
        url=URL,
        user="pipeline",
        password=PASSWORD,
        timeout=30.0,
        opener=opener,
    )


def test_bronze_rows_keep_the_whole_record_and_copy_out_the_metadata() -> None:
    rows = build_bronze_rows(RECORDS)

    assert [row["record"] for row in rows] == RECORDS
    assert rows[0] == {
        "record": RECORDS[0],
        "run_id": RUN_ID,
        "source_type": "forecast",
        "loaded_at": "2026-11-14T09:30:15Z",
    }


def test_insert_sends_all_rows_in_one_request() -> None:
    requests: list[urllib.request.Request] = []

    def opener(request: urllib.request.Request, timeout: float) -> io.BytesIO:
        requests.append(request)
        return io.BytesIO(b"")

    insert(opener)

    [request] = requests
    assert request.get_method() == "POST"
    assert request.full_url.startswith(f"{URL}/?")
    assert parse_qs(urlsplit(request.full_url).query) == {
        "query": [
            "INSERT INTO bronze.open_meteo_weather (record, run_id, source_type, loaded_at) "
            "FORMAT JSONEachRow"
        ],
        "date_time_input_format": ["best_effort"],
        "input_format_try_infer_datetimes": ["0"],
        "wait_end_of_query": ["1"],
        "input_format_parallel_parsing": ["0"],
    }
    assert request.get_header("X-clickhouse-user") == "pipeline"
    assert request.get_header("X-clickhouse-key") == PASSWORD
    lines = request.data.decode("utf-8").splitlines()
    assert [json.loads(line) for line in lines] == build_bronze_rows(RECORDS)


def test_rejected_insert_reports_the_clickhouse_error_without_the_password() -> None:
    def opener(request: urllib.request.Request, timeout: float) -> io.BytesIO:
        headers = {"X-ClickHouse-Exception-Code": "516"}
        raise HTTPError(
            request.full_url, 403, "Forbidden", headers, io.BytesIO(AUTHENTICATION_FAILED_BODY)
        )

    with pytest.raises(BronzeLoadError) as raised:
        insert(opener)

    assert str(raised.value) == "bronze insert failed: ClickHouse code 516 (AUTHENTICATION_FAILED)"
    assert PASSWORD not in str(raised.value)


def test_unreachable_warehouse_fails_the_insert() -> None:
    def opener(request: urllib.request.Request, timeout: float) -> io.BytesIO:
        raise URLError("connection refused")

    with pytest.raises(BronzeLoadError, match="bronze insert failed: connection refused"):
        insert(opener)
