#!/usr/bin/env bash
# Creates the read-only account Superset uses. It can read gold and nothing else.
# The image runs this once, when the data volume is empty. It may source the file instead of
# executing it, so the script does not change shell options.

clickhouse-client --host 127.0.0.1 --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" \
    --multiquery <<SQL
CREATE USER IF NOT EXISTS ${CLICKHOUSE_READER_USER} IDENTIFIED BY '${CLICKHOUSE_READER_PASSWORD}';
GRANT SELECT ON gold.* TO ${CLICKHOUSE_READER_USER};
SQL
