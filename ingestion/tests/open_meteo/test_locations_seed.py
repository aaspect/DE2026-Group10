"""The dbt location seed is a copy of `locations.toml`, because dbt cannot read TOML.

This test keeps the two in sync: a location missing from the seed would silently lose its data
in gold.
"""

import csv

from open_meteo.config import PROJECT_DIR, load_locations

SEED_FILE = PROJECT_DIR.parent / "dbt" / "seeds" / "silver" / "weather_locations.csv"


def test_dbt_location_seed_matches_the_locations_file() -> None:
    with SEED_FILE.open(encoding="utf-8", newline="") as file:
        seed_rows = [
            row | {"latitude": float(row["latitude"]), "longitude": float(row["longitude"])}
            for row in csv.DictReader(file)
        ]

    locations = load_locations(PROJECT_DIR / "open_meteo" / "locations.toml")

    assert seed_rows == [
        {
            "location_key": location.location_id,
            "location_name": location.name,
            "latitude": location.latitude,
            "longitude": location.longitude,
            "zone_code": location.bidding_zone,
            "location_role": location.role,
        }
        for location in locations
    ]
