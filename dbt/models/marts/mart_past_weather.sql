{#
    Observed (archive) weather, one row per location per hour, with the location and local-time
    attributes joined in. The only table Superset reads: the "Past weather" dashboard in
    superset/dashboards/past_weather/ depends on these columns.

    Deliberate deviation from the project plan: hourly rows, not pre-aggregated. The dashboard
    aggregates as needed.
#}
{{ config(
    materialized='table',
    engine='MergeTree()',
    order_by='(location_key, interval_start_utc)'
) }}

select
    fact_weather.location_key as location_key,
    dim_location.location_name as location_name,
    dim_location.location_role as location_role,
    dim_location.zone_code as zone_code,
    fact_weather.interval_start_utc as interval_start_utc,
    dim_interval.interval_start_local as interval_start_local,
    dim_interval.local_date as local_date,
    dim_interval.local_hour as local_hour,
    dim_interval.day_of_week as day_of_week,
    dim_interval.is_weekend as is_weekend,
    fact_weather.temperature_c as temperature_c,
    fact_weather.wind_speed_ms as wind_speed_ms,
    fact_weather.wind_direction_deg as wind_direction_deg,
    fact_weather.shortwave_radiation_wm2 as shortwave_radiation_wm2,
    fact_weather.direct_radiation_wm2 as direct_radiation_wm2,
    fact_weather.cloud_cover_pct as cloud_cover_pct,
    fact_weather.precipitation_mm as precipitation_mm,
    fact_weather.loaded_at as loaded_at
from {{ ref('fact_weather') }} as fact_weather
inner join {{ ref('dim_location') }} as dim_location
    on fact_weather.location_key = dim_location.location_key
inner join {{ ref('dim_interval') }} as dim_interval
    on fact_weather.interval_key = dim_interval.interval_key
where fact_weather.source_type = 'archive'
