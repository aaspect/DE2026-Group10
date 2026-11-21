import io
import re
from urllib.error import HTTPError, URLError

import pytest

from open_meteo.client import FetchError, InvalidResponseError, fetch_json

URL = "https://example.invalid/v1/forecast"
OK_BODY = b'{"ok": true}'
REJECTION_BODY = b'{"error": true, "reason": "Parameter \'end_date\' is out of allowed range"}'


def http_error(code: int, body: bytes = b"") -> HTTPError:
    return HTTPError(URL, code, "provider error", {}, io.BytesIO(body))


@pytest.mark.parametrize(
    ("outcomes", "expected_error", "expected_sleeps"),
    [
        pytest.param(
            [URLError("connection refused"), OK_BODY],
            None,
            [2.0],
            id="connection-error-is-retried",
        ),
        pytest.param(
            [http_error(503), http_error(503), http_error(503)],
            (FetchError, "HTTP 503 after 3 attempts"),
            [2.0, 4.0],
            id="server-error-fails-after-last-attempt",
        ),
        pytest.param([http_error(429), OK_BODY], None, [2.0], id="rate-limit-is-retried"),
        pytest.param(
            [http_error(400, REJECTION_BODY)],
            (InvalidResponseError, "Parameter 'end_date' is out of allowed range"),
            [],
            id="rejected-request-is-not-retried",
        ),
        pytest.param([TimeoutError("timed out"), OK_BODY], None, [2.0], id="timeout-is-retried"),
    ],
)
def test_fetch_json_retries_only_temporary_failures(
    outcomes: list[Exception | bytes],
    expected_error: tuple[type[Exception], str] | None,
    expected_sleeps: list[float],
) -> None:
    remaining_outcomes = list(outcomes)
    requested_urls: list[str] = []
    sleeps: list[float] = []

    def opener(url: str, timeout: float) -> io.BytesIO:
        requested_urls.append(url)
        outcome = remaining_outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return io.BytesIO(outcome)

    def fetch() -> object:
        return fetch_json(
            URL,
            {"hourly": "temperature_2m,cloud_cover"},
            timeout=30.0,
            max_attempts=3,
            retry_base_seconds=2.0,
            sleep=sleeps.append,
            opener=opener,
        )

    if expected_error is None:
        assert fetch() == {"ok": True}
    else:
        error_type, message = expected_error
        with pytest.raises(error_type, match=re.escape(message)):
            fetch()

    assert requested_urls == [f"{URL}?hourly=temperature_2m,cloud_cover"] * len(outcomes)
    assert sleeps == expected_sleeps
