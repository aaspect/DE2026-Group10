import re
from pathlib import Path

import pytest

from open_meteo.config import PROJECT_DIR, ConfigError, Settings, load_locations

VALID_ENTRY = """
[[locations]]
id = "tallinn"
name = "Tallinn"
latitude = 59.4370
longitude = 24.7536
bidding_zone = "EE"
role = "demand"
"""
CREDENTIALS = {"CLICKHOUSE_USER": "pipeline", "CLICKHOUSE_PASSWORD": "pipeline"}


@pytest.mark.parametrize(
    ("toml_text", "expected_message"),
    [
        pytest.param("", "no [[locations]] entries", id="no-entries"),
        pytest.param(VALID_ENTRY + VALID_ENTRY, "location 'tallinn': duplicate id", id="duplicate"),
        pytest.param(
            VALID_ENTRY.replace('role = "demand"', ""),
            "location 'tallinn': missing required key 'role'",
            id="missing-role",
        ),
        pytest.param(
            VALID_ENTRY.replace("59.4370", "91"),
            "location 'tallinn': 'latitude' must be a number from -90 to 90",
            id="latitude-out-of-range",
        ),
        pytest.param(
            VALID_ENTRY.replace("24.7536", "-181"),
            "location 'tallinn': 'longitude' must be a number from -180 to 180",
            id="longitude-out-of-range",
        ),
        pytest.param(
            VALID_ENTRY.replace('"tallinn"', '"Tallinn!"'),
            "location 'Tallinn!': 'id' must match [a-z0-9_]+",
            id="invalid-id",
        ),
        pytest.param(
            VALID_ENTRY + "foo = 1",
            "location 'tallinn': unknown key 'foo'",
            id="unknown-key",
        ),
        pytest.param(
            VALID_ENTRY + VALID_ENTRY.replace('id = "tallinn"', ""),
            "location #2: missing required key 'id'",
            id="missing-id-named-by-position",
        ),
        pytest.param(None, "cannot be read", id="missing-file"),
    ],
)
def test_load_locations_rejects_invalid_file(
    tmp_path: Path, toml_text: str | None, expected_message: str
) -> None:
    path = tmp_path / "locations.toml"
    if toml_text is not None:
        path.write_text(toml_text, encoding="utf-8")

    with pytest.raises(ConfigError, match=re.escape(expected_message)):
        load_locations(path)


def test_shipped_locations_file_has_five_locations() -> None:
    locations = load_locations(PROJECT_DIR / "open_meteo" / "locations.toml")

    assert [location.location_id for location in locations] == [
        "tallinn",
        "tartu",
        "parnu",
        "narva",
        "kuressaare",
    ]


def test_destination_defaults_to_the_warehouse_on_localhost() -> None:
    settings = Settings.from_env(CREDENTIALS)

    assert settings.destination == "warehouse"
    assert settings.clickhouse_url == "http://localhost:8123"
    assert (settings.writes_warehouse, settings.writes_file) == (True, False)


@pytest.mark.parametrize(
    ("destination", "writes_warehouse", "writes_file"),
    [("file", False, True), ("both", True, True)],
)
def test_destination_can_be_file_or_both(
    destination: str, writes_warehouse: bool, writes_file: bool
) -> None:
    settings = Settings.from_env(CREDENTIALS | {"OPEN_METEO_DESTINATION": destination})

    assert settings.destination == destination
    assert (settings.writes_warehouse, settings.writes_file) == (writes_warehouse, writes_file)


def test_unknown_destination_is_refused() -> None:
    expected_message = "OPEN_METEO_DESTINATION must be one of warehouse, file, both, got 'bronze'"

    with pytest.raises(ConfigError, match=re.escape(expected_message)):
        Settings.from_env(CREDENTIALS | {"OPEN_METEO_DESTINATION": "bronze"})


def test_destination_argument_overrides_the_environment() -> None:
    settings = Settings.from_env({"OPEN_METEO_DESTINATION": "warehouse"}, destination="file")

    assert settings.destination == "file"


@pytest.mark.parametrize("destination", ["warehouse", "both"])
@pytest.mark.parametrize(
    "credentials",
    [
        pytest.param({"CLICKHOUSE_PASSWORD": "pipeline"}, id="no-user"),
        pytest.param({"CLICKHOUSE_USER": "pipeline"}, id="no-password"),
        pytest.param({"CLICKHOUSE_USER": "pipeline", "CLICKHOUSE_PASSWORD": " "}, id="blank"),
    ],
)
def test_warehouse_destination_needs_credentials(
    destination: str, credentials: dict[str, str]
) -> None:
    expected_message = (
        "CLICKHOUSE_USER and CLICKHOUSE_PASSWORD must be set when the destination includes "
        "warehouse"
    )

    with pytest.raises(ConfigError, match=re.escape(expected_message)):
        Settings.from_env(credentials | {"OPEN_METEO_DESTINATION": destination})


def test_file_destination_needs_no_credentials() -> None:
    settings = Settings.from_env({"OPEN_METEO_DESTINATION": "file"})

    assert settings.clickhouse_user is None
    assert settings.clickhouse_password is None
