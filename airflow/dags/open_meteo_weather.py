"""Weather pipeline for Open-Meteo: fetch → load to bronze → build silver → build gold.

Only the fetch tasks do real work: they run the ingestion job in `ingestion/open_meteo`, which
writes one run file per run to `ingestion/output/open_meteo/`. The load and build tasks are
placeholders that succeed without touching the warehouse.

Schedule: every 6 hours (UTC). The forecast is fetched on every run, observed weather (archive)
only on the 00:00 UTC run. On a manual run, set the `archive` param to fetch it as well.
"""

from datetime import UTC, datetime, timedelta

from airflow.providers.standard.operators.bash import BashOperator
from airflow.providers.standard.operators.empty import EmptyOperator
from airflow.sdk import DAG, Param

FETCH_FORECAST = "cd /opt/ingestion && /opt/venvs/ingestion/bin/python -m open_meteo forecast"
FETCH_ARCHIVE = "cd /opt/ingestion && /opt/venvs/ingestion/bin/python -m open_meteo archive"

# A BashOperator that exits with this code is marked skipped instead of failed.
SKIP_EXIT_CODE = 99
FETCH_ARCHIVE_ONCE_A_DAY = (
    "{% if params.archive or (dag_run.run_type == 'scheduled' and logical_date.hour == 0) %}"
    f"{FETCH_ARCHIVE}"
    "{% else %}"
    f"echo 'Not the 00:00 UTC run and the archive param is off: skipping.'; exit {SKIP_EXIT_CODE}"
    "{% endif %}"
)

with DAG(
    dag_id="open_meteo_weather",
    description="Fetch Open-Meteo weather; loading and transforming are placeholders.",
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
            description="Also fetch observed (archive) weather on this run.",
        ),
    },
    tags=["open_meteo", "weather"],
):
    fetch_forecast = BashOperator(task_id="fetch_forecast", bash_command=FETCH_FORECAST)
    fetch_archive = BashOperator(
        task_id="fetch_archive",
        bash_command=FETCH_ARCHIVE_ONCE_A_DAY,
        skip_on_exit_code=SKIP_EXIT_CODE,
    )

    load_bronze = EmptyOperator(
        task_id="load_bronze",
        # Runs when the archive fetch was skipped, but not when any fetch failed.
        trigger_rule="none_failed_min_one_success",
        doc_md=(
            "**Placeholder: does nothing.** The bronze loading feature replaces it with a task "
            "that loads the new run files into `bronze.open_meteo_weather`."
        ),
    )
    build_silver = EmptyOperator(
        task_id="build_silver",
        doc_md=(
            "**Placeholder: does nothing.** The modelling feature replaces it with "
            "`dbt build --select silver`."
        ),
    )
    build_gold = EmptyOperator(
        task_id="build_gold",
        doc_md=(
            "**Placeholder: does nothing.** The modelling feature replaces it with "
            "`dbt build --select gold marts`."
        ),
    )

    [fetch_forecast, fetch_archive] >> load_bronze >> build_silver >> build_gold
