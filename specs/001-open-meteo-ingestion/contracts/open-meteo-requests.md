# Contract: Open-Meteo Requests (consumed interface)

The job is a client of two public, keyless Open-Meteo endpoints. It makes one GET request per
location per run.

## Common query parameters

| Parameter | Value |
|---|---|
| `latitude`, `longitude` | from the location configuration |
| `hourly` | `temperature_2m,wind_speed_10m,wind_direction_10m,shortwave_radiation,direct_radiation,cloud_cover,precipitation` |
| `timezone` | `UTC` |
| `temperature_unit` | `celsius` |
| `wind_speed_unit` | `ms` |
| `precipitation_unit` | `mm` |
| `timeformat` | `iso8601` |

## Forecast

`GET $OPEN_METEO_FORECAST_URL` with `forecast_days=$OPEN_METEO_FORECAST_DAYS`.

The response covers 00:00 UTC today through 23:00 UTC on the last forecast day, which is
`forecast_days × 24` hours.

## Archive

`GET $OPEN_METEO_ARCHIVE_URL` with `start_date=YYYY-MM-DD&end_date=YYYY-MM-DD`, both inclusive.

The provider rejects an `end_date` after today with HTTP 400.

## Expected success response (HTTP 200)

Only the fields shown here are used:

```json
{
  "latitude": 59.439518,
  "longitude": 24.75708,
  "elevation": 10.0,
  "hourly_units": {"time": "iso8601", "temperature_2m": "°C", "wind_speed_10m": "m/s", "...": "..."},
  "hourly": {
    "time": ["2026-11-14T00:00", "2026-11-14T01:00", "..."],
    "temperature_2m": [2.8, 3.3, "..."],
    "wind_speed_10m": [3.0, 4.1, "..."],
    "wind_direction_10m": [238, 221, "..."],
    "shortwave_radiation": [0.0, 0.0, "..."],
    "direct_radiation": [0.0, 0.0, "..."],
    "cloud_cover": [97, 98, "..."],
    "precipitation": [2.3, 0.0, "..."]
  }
}
```

Series values may be `null`. The checks that make a response valid are listed in
[data-model.md](../data-model.md#validation-of-a-provider-response-fr-014).

## Error responses and handling

| Response | Handling |
|---|---|
| HTTP 400 `{"error": true, "reason": "..."}` | invalid: no retry, run fails with `reason` |
| other HTTP 4xx except 429 | invalid: no retry |
| HTTP 429, HTTP 5xx | temporary: retry with backoff |
| connection error, timeout | temporary: retry with backoff |
| HTTP 200 that fails validation | invalid: no retry |

## Usage limits (FR-020)

Free tier: 600 calls per minute, 5,000 per hour and 10,000 per day. Requests covering long
periods count as several calls, roughly one call per 14 days per 10 variables.

| Use | Weighted calls (approx.) |
|---|---|
| normal operation, (4 + 1) runs × 5 locations per day | about 25 per day |
| one-year backfill for 5 locations | about 135 |

Both are far below the limits.
