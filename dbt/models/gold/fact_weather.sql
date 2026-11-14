{#
    Hourly weather values. Grain: one row per location per hour per source type per forecast
    version; archive rows have no forecast version.

    The inner join drops rows for locations that are not in dim_location.
#}
{{ config(
    materialized='table',
    engine='MergeTree()',
    order_by='(location_key, interval_start_utc, source_type)'
) }}

select
    toUInt64(formatDateTime(weather.interval_start_utc, '%Y%m%d%H%i', 'UTC')) as interval_key,
    weather.location_key as location_key,
    weather.interval_start_utc as interval_start_utc,
    weather.source_type as source_type,
    weather.forecast_issued_utc as forecast_issued_utc,
    weather.lead_time_h as lead_time_h,
    weather.temperature_c as temperature_c,
    weather.wind_speed_ms as wind_speed_ms,
    weather.wind_direction_deg as wind_direction_deg,
    weather.shortwave_radiation_wm2 as shortwave_radiation_wm2,
    weather.direct_radiation_wm2 as direct_radiation_wm2,
    weather.cloud_cover_pct as cloud_cover_pct,
    weather.precipitation_mm as precipitation_mm,
    weather.loaded_at as loaded_at
from {{ ref('open_meteo_weather') }} as weather
inner join {{ ref('dim_location') }} as dim_location
    on weather.location_key = dim_location.location_key
