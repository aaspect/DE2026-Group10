"""Weather pipeline for Open-Meteo: ingest → build silver → build gold, plus a freshness check.

- **Ingest**: the job in `ingestion/open_meteo` fetches the weather and inserts each run's records
  into `bronze.open_meteo_weather`.
- **Build silver**: dbt builds the location seed and `silver.open_meteo_weather`, and runs their
  tests.
- **Build gold**: dbt builds the dimensions, `fact_weather` and the `mart_past_weather` mart, and
  runs their tests.
- **Check bronze freshness**: dbt warns when the newest load is older than 6 hours. It runs after
  the ingest tasks whatever their outcome, and nothing waits for it.

Schedule: every 6 hours (UTC). The forecast is ingested on every run, observed weather (archive)
only on the 00:00 UTC run. On a manual run, set the `archive` param to ingest it as well.
"""

from datetime import UTC, datetime, timedelta

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG, Param

# The job's default destination is the warehouse, so each command loads its run into bronze.
INGEST_FORECAST = "cd /opt/ingestion && /opt/venvs/ingestion/bin/python -m open_meteo forecast"
INGEST_ARCHIVE = "cd /opt/ingestion && /opt/venvs/ingestion/bin/python -m open_meteo archive"

# A BashOperator that exits with this code is marked skipped instead of failed.
SKIP_EXIT_CODE = 99
INGEST_ARCHIVE_ONCE_A_DAY = (
    "{% if params.archive or (dag_run.run_type == 'scheduled' and logical_date.hour == 0) %}"
    f"{INGEST_ARCHIVE}"
    "{% else %}"
    f"echo 'Not the 00:00 UTC run and the archive param is off: skipping.'; exit {SKIP_EXIT_CODE}"
    "{% endif %}"
)

DBT = "/opt/venvs/dbt/bin/dbt"
PROJECT = "--project-dir /opt/dbt"
NO_RETRIES_NOTE = (
    "No retries: a failed model or test is not a temporary problem, and a retry would only "
    "rebuild the same failing models."
)

with DAG(
    dag_id="open_meteo_weather",
    description="Ingest Open-Meteo weather into bronze and build silver, gold and the "
    "past-weather mart.",
    doc_md=__doc__,
    schedule="0 */6 * * *",
    start_date=datetime(2026, 11, 1, tzinfo=UTC),
    catchup=False,
    is_paused_upon_creation=True,
    max_active_runs=1,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=5)},
    params={
        "archive": Param(
            False,
            type="boolean",
            description="Also ingest observed (archive) weather on this run.",
        ),
    },
    tags=["open_meteo", "weather"],
):
    ingest_forecast = BashOperator(
        task_id="ingest_forecast",
        bash_command=INGEST_FORECAST,
        doc_md=(
            "Fetches the forecast for every location and inserts the run into "
            "`bronze.open_meteo_weather` with one statement: all rows or none."
        ),
    )
    ingest_archive = BashOperator(
        task_id="ingest_archive",
        bash_command=INGEST_ARCHIVE_ONCE_A_DAY,
        skip_on_exit_code=SKIP_EXIT_CODE,
        doc_md=(
            "Fetches the last 7 days of observed weather and inserts the run into "
            "`bronze.open_meteo_weather`. Runs on the 00:00 UTC schedule or when the `archive` "
            "param is on; otherwise it is skipped."
        ),
    )

    build_silver = BashOperator(
        task_id="build_silver",
        bash_command=f"{DBT} build {PROJECT} --select silver",
        # Runs when the archive ingest was skipped, but not when any ingest failed.
        trigger_rule="none_failed_min_one_success",
        retries=0,
        doc_md=(
            "Runs `dbt build --select silver`: the location seed, `silver.open_meteo_weather` "
            f"and their tests. {NO_RETRIES_NOTE}"
        ),
    )
    build_gold = BashOperator(
        task_id="build_gold",
        bash_command=f"{DBT} build {PROJECT} --select gold marts",
        retries=0,
        doc_md=(
            "Runs `dbt build --select gold marts`: `dim_location`, `dim_interval`, "
            "`fact_weather`, `mart_past_weather` and their tests. A failing test skips the "
            f"models downstream of it, which keep their last good data. {NO_RETRIES_NOTE}"
        ),
    )
    check_bronze_freshness = BashOperator(
        task_id="check_bronze_freshness",
        bash_command=f"{DBT} source freshness {PROJECT} --select source:bronze.open_meteo_weather",
        # Staleness matters most when ingestion is failing, so this runs after failed ingests too.
        trigger_rule="all_done",
        retries=0,
        doc_md=(
            "Runs `dbt source freshness` on `bronze.open_meteo_weather`. A newest load older "
            "than 6 hours gives a `WARN` line in the log; the task still succeeds."
        ),
    )

    [ingest_forecast, ingest_archive] >> build_silver >> build_gold
    [ingest_forecast, ingest_archive] >> check_bronze_freshness
