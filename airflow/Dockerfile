# Airflow for the local stack, plus two isolated Python environments for the work it runs:
#   /opt/venvs/ingestion  the weather job's locked dependencies (the code itself is bind-mounted)
#   /opt/venvs/dbt        dbt with the ClickHouse adapter
# Keeping them apart from Airflow's own environment avoids dependency conflicts.
#
# Build context is the repository root, so the ingestion lock file can be copied.
FROM apache/airflow:3.1.8-python3.12

USER root
RUN mkdir /opt/venvs && chown airflow:0 /opt/venvs
USER airflow

COPY ingestion/pyproject.toml ingestion/uv.lock /tmp/ingestion/
RUN UV_PROJECT_ENVIRONMENT=/opt/venvs/ingestion \
    uv sync --project /tmp/ingestion --locked --no-dev --no-install-project

RUN uv venv /opt/venvs/dbt \
    && uv pip install --python /opt/venvs/dbt/bin/python dbt-clickhouse==1.9.8

COPY airflow/entrypoint.sh /opt/airflow/entrypoint.sh
CMD ["bash", "/opt/airflow/entrypoint.sh"]
