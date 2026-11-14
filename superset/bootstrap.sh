#!/usr/bin/env bash
# Prepares Superset on every start, then runs the web server. Every step is safe to repeat.
set -euo pipefail

superset db upgrade

# Prints "already exists" and carries on when the admin was created by an earlier start.
superset fab create-admin \
    --username "$SUPERSET_ADMIN_USER" \
    --password "$SUPERSET_ADMIN_PASSWORD" \
    --firstname Superset \
    --lastname Admin \
    --email admin@localhost

superset init

# Registers the warehouse as a data source, or updates it if it is already there.
superset set-database-uri \
    --database_name "ClickHouse warehouse" \
    --uri "$SUPERSET_WAREHOUSE_URI"

exec /usr/bin/run-server.sh
