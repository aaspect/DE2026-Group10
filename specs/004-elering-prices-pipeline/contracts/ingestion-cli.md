# Contract: Elering Prices Ingestion CLI & Configuration

Command-line and environment interface for `ingestion/elering_prices`. Mirrors
`ingestion/open_meteo` so both jobs share predictable operational semantics.

## Invocation

```bash
python -m elering_prices [daily | backfill] [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD] [--destination warehouse|file|both]
```

- Positional `mode` is optional and defaults to `daily` (`choices=("daily", "backfill")`).
- **`daily`** (default):
  - Captures the next Europe/Tallinn calendar day (`D+1`) across all configured zones (96 slots/zone
    on standard post-switch days, 92 on spring DST, 100 on autumn DST).
  - Passing `--start-date` or `--end-date` in `daily` mode is rejected with exit code `2`.
- **`backfill`**:
  - Requires both `--start-date` and `--end-date` (inclusive UTC calendar dates, `YYYY-MM-DD`).
  - Rejects before contacting Elering (exit code `2`) if: either date is missing, either date is
    malformed, `start_date > end_date`, or `end_date > local_tomorrow` (where `local_tomorrow` is
    `D+1` in `Europe/Tallinn`).

## Environment Variables & Defaults

Loaded from process environment, with `ingestion/.env` loaded via `load_dotenv(..., override=False)`
so existing environment variables always take precedence. Relative paths are resolved against
`ingestion/` (`PROJECT_DIR`), independent of the caller's working directory.

| Variable | Default | Validation |
|---|---|---|
| `ELERING_PRICES_URL` | `https://dashboard.elering.ee/api/nps/price` | Valid `http(s)` URL |
| `ELERING_CHUNK_DAYS` | `31` | Whole number `1..365` |
| `ELERING_MAX_ATTEMPTS` | `3` | Whole number `>= 1` |
| `ELERING_RETRY_BASE_SECONDS` | `2` | Finite float `>= 0` |
| `ELERING_TIMEOUT_SECONDS` | `30` | Finite float `> 0` |
| `ELERING_OUTPUT_DIR` | `output/elering_prices` | Path (expanded `~`, relative to `ingestion/`) |
| `ELERING_ZONES_FILE` | `elering_prices/bidding_zones.toml` | Readable TOML with valid `[[zones]]` entries |
| `ELERING_DESTINATION` | `warehouse` | `warehouse`, `file`, or `both` (`--destination` overrides) |
| `CLICKHOUSE_URL` | `http://localhost:8123` | Valid `http(s)` URL |
| `CLICKHOUSE_USER` | *(none)* | Required when destination is `warehouse` or `both` |
| `CLICKHOUSE_PASSWORD` | *(none)* | Required when destination is `warehouse` or `both`; never logged |

## Destination Behaviour

| Destination | Bronze Insert | Local Run File | Failure Behaviour |
|---|---|---|---|
| `warehouse` (default) | Yes (single atomic POST) | No (output dir not created) | Zero rows in bronze; exit `1` |
| `file` | No (ClickHouse credentials not required) | Yes (atomic `os.link`) | No partial file; exit `1` |
| `both` | Yes, executed **first** | Yes, written only after insert succeeds | If insert fails: zero rows, no file, exit `1`. If file write fails after insert: bronze keeps the complete run, no partial file, exit `1`. |

## Local Output File Format (`file` / `both`)

- Directory: `ELERING_OUTPUT_DIR` (default `ingestion/output/elering_prices/`).
- File name: `elering_prices_{mode}_{YYYYMMDDTHHMMSSZ}_{run_id}.jsonl`.
- Atomic creation via temp file + `fsync` + `os.link` (never overwrites an existing file).
- One UTF-8 compact JSON object per line (`separators=(",", ":")`), preserving the exact six raw
  record keys:
  ```json
  {"zone_code":"ee","interval_start_utc":"2025-09-30T22:00:00Z","price_eur_mwh":98.95,"mode":"backfill","run_id":"...","loaded_at":"2026-11-22T12:30:05Z"}
  ```

## Structured Run Report (stdout)

Printed on every invocation (including refusals and failures); progress logs go to `stderr`:

```text
run_id: <uuid>
mode: daily | backfill
period: <YYYY-MM-DD (Europe/Tallinn) | YYYY-MM-DD..YYYY-MM-DD (UTC) | none>
zones: <int>
records: <int>
destination: warehouse | file | both | none
bronze_table: bronze.elering_prices | none
output_file: <relative or absolute path | none>
outcome: success | failure
failure: reason=<message>   # omitted on success
```

## Exit Codes

| Code | Meaning |
|---|---|
| `0` | All expected records fetched, validated, and stored to every requested destination |
| `1` | Runtime failure (API fetch error, invalid/incomplete response, ClickHouse insert error, or file write error) |
| `2` | Configuration or CLI validation refusal (before contacting Elering or ClickHouse) |
