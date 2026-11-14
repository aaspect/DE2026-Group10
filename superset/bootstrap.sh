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

# Imports the "Past weather" dashboard with its charts, its dataset and the warehouse connection
# from the bundle in /app/dashboards. Every object has a fixed UUID in the bundle, so a restart
# finds the objects of the earlier start and never creates them twice: the dashboard is
# overwritten, and the connection, dataset and charts are created only when they are missing.
python /app/render_bundle.py
superset import-dashboards --path /tmp/past_weather.zip --username "$SUPERSET_ADMIN_USER"

exec /usr/bin/run-server.sh
