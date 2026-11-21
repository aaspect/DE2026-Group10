# Contract: "Past weather" Superset dashboard

The layout and colours are a demo choice (spec assumption), so this contract fixes only what
can be checked.

## Provisioning

| Item | Value |
|---|---|
| Source in repo | `superset/dashboards/past_weather/` (Superset export bundle, YAML) |
| Applied by | `superset/bootstrap.sh` on every container start: `render_bundle.py`, then `superset import-dashboards --path <zip> --username $SUPERSET_ADMIN_USER` |
| Identity | fixed UUIDs for the database, dataset, charts and dashboard. A restart finds them by UUID and does not duplicate them: the dashboard is overwritten, and the database, dataset and charts are created only when missing (Superset 5.0 `import-dashboards` behaviour). |
| Database | `ClickHouse warehouse`, URI from `SUPERSET_WAREHOUSE_URI` (reader account, `gold`). It replaces the `set-database-uri` step. |
| Dataset | physical table `gold.mart_past_weather`, the only dataset the dashboard uses |
| Dashboard title / slug | `Past weather` / `past-weather`, URL `http://localhost:${SUPERSET_PORT}/superset/dashboard/past-weather/` |
| Auto-refresh | every 3600 s (`refresh_frequency`) |

To change the dashboard, edit it in the UI, export it with
`superset export-dashboards`, replace the bundle files and restore the `${SUPERSET_WAREHOUSE_URI}`
placeholder in the database YAML. The README documents these steps.

A stack that already holds the dashboard picks up a changed layout or filter on its next start.
A changed chart or dataset reaches such a stack only after the old object is deleted in the UI
or the stack is reset (`make reset`), because the import does not overwrite them.

## Native filters (apply to every chart)

| Filter | Column | Default |
|---|---|---|
| Location | `location_name` (multi-select) | none selected, which shows all locations |
| Time range | `interval_start_utc` | `Last week` |

## Charts

| Chart | Type | Metric(s) | Series |
|---|---|---|---|
| Average temperature | Big number | `AVG(temperature_c)` | — |
| Average wind speed | Big number | `AVG(wind_speed_ms)` | — |
| Total precipitation | Big number | `SUM(precipitation_mm)` / number of selected locations, labelled "per location" | — |
| Temperature | Line, hourly | `AVG(temperature_c)` | `location_name` |
| Wind speed | Line, hourly | `AVG(wind_speed_ms)` | `location_name` |
| Solar radiation | Line, hourly | `AVG(shortwave_radiation_wm2)` | `location_name` |
| Cloud cover | Line, hourly | `AVG(cloud_cover_pct)` | `location_name` |
| Precipitation | Bar, hourly | `SUM(precipitation_mm)` | `location_name` |

All time-series charts use `interval_start_utc` at hour grain and label the axis "UTC".

## Behaviour

- Empty mart: charts show Superset's "No results" state, not an error. Before the first dbt
  build the mart table does not exist yet, and the charts show a query error until it does.
- Every chart's query targets only `gold.mart_past_weather`. The reader account cannot read any
  other layer.
