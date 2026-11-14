# Contract: Configuration

## Environment variables (FR-008)

All are optional and have defaults. No credentials are needed.

Values are taken in this order, highest priority first:

1. variables set in the process environment
2. `ingestion/.env`, if it exists
3. the defaults below

`ingestion/.env` is git-ignored. `ingestion/.env.example` is committed and lists every variable
with its default, commented out:

```dotenv
# Copy to .env and uncomment to override.
# OPEN_METEO_FORECAST_DAYS=3
# OPEN_METEO_OUTPUT_DIR=output/open_meteo
```

| Variable | Default | Meaning |
|---|---|---|
| `OPEN_METEO_FORECAST_URL` | `https://api.open-meteo.com/v1/forecast` | forecast endpoint |
| `OPEN_METEO_ARCHIVE_URL` | `https://archive-api.open-meteo.com/v1/archive` | archive endpoint |
| `OPEN_METEO_FORECAST_DAYS` | `3` | forecast horizon in UTC days, today included (1–16) |
| `OPEN_METEO_ARCHIVE_DAYS` | `7` | rolling archive window, in full UTC days before today |
| `OPEN_METEO_MAX_ATTEMPTS` | `3` | attempts per request, including the first one |
| `OPEN_METEO_RETRY_BASE_SECONDS` | `2` | wait before retry *n* is `base × 2^(n-1)` |
| `OPEN_METEO_TIMEOUT_SECONDS` | `30` | timeout per HTTP request |
| `OPEN_METEO_OUTPUT_DIR` | `output/open_meteo` | where run files are written; created, with any missing parents, if it does not exist |
| `OPEN_METEO_LOCATIONS_FILE` | `open_meteo/locations.toml` | locations file |

Relative paths, whether defaults or values from the environment or `.env`, are resolved against
the `ingestion/` project directory, not the current working directory. The defaults therefore
always mean `ingestion/output/open_meteo/` and `ingestion/open_meteo/locations.toml`. Absolute
paths are used as given. An invalid value, such as a non-integer or an out-of-range number,
makes the job exit with code `2`. The message names the variable.

## Locations file (FR-006, FR-007)

TOML, with one `[[locations]]` table per location:

```toml
# Roles are a team decision; change here, not in code.
[[locations]]
id = "tallinn"
name = "Tallinn"
latitude = 59.4370
longitude = 24.7536
bidding_zone = "EE"
role = "demand"

[[locations]]
id = "tartu"
# ...
```

| Key | Type | Rule |
|---|---|---|
| `id` | string | required, `[a-z0-9_]+`, unique |
| `name` | string | required, non-empty |
| `latitude` | number | required, −90 to 90 |
| `longitude` | number | required, −180 to 180 |
| `bidding_zone` | string | required, non-empty |
| `role` | string | required, non-empty |

The job exits with code `2`, naming the entry by `id` or by position, if:

- the file is missing, cannot be parsed or has no `[[locations]]` entries
- any entry breaks one of the rules above
- any entry has an unknown key

The default file ships the 5 locations from [research.md § R10](../research.md#r10-default-locations).
