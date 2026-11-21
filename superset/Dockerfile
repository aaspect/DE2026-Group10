# Superset for the local stack: the base image plus the two database drivers it needs
# (Postgres for its own metadata, ClickHouse for the warehouse), our settings, the committed
# dashboard bundle and the start script that imports it.
FROM docker.io/apache/superset:5.0.0

USER root
RUN uv pip install --python /app/.venv/bin/python \
    psycopg2-binary==2.9.13 \
    clickhouse-connect==0.15.1
COPY superset_config.py /app/pythonpath/superset_config.py
COPY dashboards/ /app/dashboards/
COPY render_bundle.py /app/render_bundle.py
COPY --chmod=755 bootstrap.sh /app/bootstrap.sh
USER superset

CMD ["/app/bootstrap.sh"]
