# Contract: Weather Job CLI and Configuration (changes)

This contract changes the feature 001 contracts
[cli.md](../../001-open-meteo-ingestion/contracts/cli.md) and
[configuration.md](../../001-open-meteo-ingestion/contracts/configuration.md). Anything not listed
here stays as defined there. In file mode, the run file format is unchanged
([output-file.md](../../001-open-meteo-ingestion/contracts/output-file.md)).

## Command

```text
python -m open_meteo forecast [--destination warehouse|file|both]
python -m open_meteo archive  [--start-date YYYY-MM-DD --end-date YYYY-MM-DD] [--destination ...]
```

`--destination` overrides `OPEN_METEO_DESTINATION` for one run.

## New settings

| Variable | Default | Required | Meaning |
|---|---|---|---|
| `OPEN_METEO_DESTINATION` | `warehouse` | no | `warehouse`: insert into bronze only. `file`: write the run file only (feature 001 behaviour). `both`: insert, then write the file. |
| `CLICKHOUSE_URL` | `http://localhost:8123` | no | ClickHouse HTTP endpoint. In the Airflow container it is `http://clickhouse:8123`. |
| `CLICKHOUSE_USER` | none | when the destination includes `warehouse` | the loading (pipeline) account, never the reader account |
| `CLICKHOUSE_PASSWORD` | none | when the destination includes `warehouse` | |

The same rules as feature 001 apply: values come from the process environment, then
`ingestion/.env`, and an invalid value refuses the run with exit code 2. `OPEN_METEO_OUTPUT_DIR` is
used only when the destination includes `file`.

## Run order

1. Validate settings and arguments (exit 2 on error, no provider contact).
2. If the destination includes `file`, prepare the output directory.
3. Fetch and validate every location (any failure fails the run, nothing is stored).
4. If the destination includes `warehouse`, insert all records in one statement. The table is
   created by the stack ([bronze-table.md](bronze-table.md)), not by the job.
5. If the destination includes `file`, write the run file atomically.

With `both`, a file-write failure in step 5 fails the run (exit 1), but the run's rows inserted in
step 4 stay in bronze. They are a complete run, and bronze is append-only.

## Exit codes (unchanged meanings)

| Code | Meaning | Bronze | File |
|---|---|---|---|
| `0` | success | all rows of the run (if `warehouse`/`both`) | one file (if `file`/`both`) |
| `1` | run failure: provider, validation, insert or file error | none, except the `both` case above | none |
| `2` | refused to start | none | none |

## Run report

Two new lines, `destination` and `bronze_table`. All other lines are unchanged.

```text
run_id: 3f2c9a8e-5b1d-4c47-9e0a-2d6f8b7c1a90
mode: archive
period: 2026-11-07..2026-11-13
locations: 5
records: 840
destination: warehouse
bronze_table: bronze.open_meteo_weather
output_file: none
outcome: success
```

`bronze_table` is `none` when nothing was inserted. An insert failure is reported without a
location:

```text
outcome: failure
failure: reason=bronze insert failed: ClickHouse code 516 (AUTHENTICATION_FAILED)
```

The number is ClickHouse's error code from the `X-ClickHouse-Exception-Code` response header and
the name is the `(NAME)` token in the error body. Without the header, the message reads
`bronze insert failed: HTTP <status>`; a connection error reads
`bronze insert failed: <reason>`. The message never contains the password.
