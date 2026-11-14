#!/usr/bin/env bash
# Creates one role and one database per tool that keeps its state in Postgres.
# The image runs this once, when the data volume is empty. It may source the file instead of
# executing it, so the script does not change shell options.

psql --set ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
    --set airflow_password="$AIRFLOW_DB_PASSWORD" \
    --set superset_password="$SUPERSET_DB_PASSWORD" <<'SQL'
CREATE ROLE airflow LOGIN PASSWORD :'airflow_password';
CREATE DATABASE airflow OWNER airflow;

CREATE ROLE superset LOGIN PASSWORD :'superset_password';
CREATE DATABASE superset OWNER superset;
SQL
