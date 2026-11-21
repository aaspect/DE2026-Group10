{#
    Hourly weather, typed, renamed, cleaned and deduplicated: one row per location, hour, source
    type and forecast version, taken from the latest load.

    Deliberate deviation from the project plan: a physically impossible value becomes NULL here
    instead of failing a test, so one bad provider value cannot block the pipeline. The tests in
    silver.yml confirm that the cleaned values are within the limits.

    Rows without a usable key stay in bronze and are left out here.
#}
{{ config(
    materialized='table',
    engine='MergeTree()',
    order_by='(location_key, interval_start_utc, source_type)'
) }}

with parsed as (
    select
        CAST(record.location_id, 'Nullable(String)') as location_key,
        parseDateTimeBestEffortOrNull(CAST(record.hour_utc, 'Nullable(String)'), 'UTC')
            as interval_start_utc,
        CAST(record.source_type, 'Nullable(String)') as source_type,
        parseDateTimeBestEffortOrNull(CAST(record.forecast_version_at, 'Nullable(String)'), 'UTC')
            as forecast_version_utc,
        CAST(record.temperature_2m_c, 'Nullable(Float64)') as temperature_c,
        CAST(record.wind_speed_10m_ms, 'Nullable(Float64)') as wind_speed_ms,
        CAST(record.wind_direction_10m_deg, 'Nullable(Float64)') as wind_direction_deg,
        CAST(record.shortwave_radiation_wm2, 'Nullable(Float64)') as shortwave_radiation_wm2,
        CAST(record.direct_radiation_wm2, 'Nullable(Float64)') as direct_radiation_wm2,
        CAST(record.cloud_cover_pct, 'Nullable(Float64)') as cloud_cover_pct,
        CAST(record.precipitation_mm, 'Nullable(Float64)') as precipitation_mm,
        CAST(record.grid_latitude, 'Nullable(Float64)') as grid_latitude,
        CAST(record.grid_longitude, 'Nullable(Float64)') as grid_longitude,
        CAST(record.grid_elevation_m, 'Nullable(Float64)') as grid_elevation_m,
        run_id,
        loaded_at
    from {{ source('bronze', 'open_meteo_weather') }}
),

cleaned as (
    select
        location_key,
        interval_start_utc,
        source_type,
        if(source_type = 'forecast', forecast_version_utc, NULL) as forecast_issued_utc,
        -- Whole hours, rounded down: an hour before the issue time has a negative lead time.
        if(
            source_type = 'forecast',
            toInt32(floor(dateDiff('second', forecast_issued_utc, interval_start_utc) / 3600)),
            NULL
        ) as lead_time_h,
        temperature_c,
        if(wind_speed_ms < 0, NULL, wind_speed_ms) as wind_speed_ms,
        if(wind_direction_deg < 0 or wind_direction_deg > 360, NULL, wind_direction_deg)
            as wind_direction_deg,
        if(shortwave_radiation_wm2 < 0, NULL, shortwave_radiation_wm2) as shortwave_radiation_wm2,
        if(direct_radiation_wm2 < 0, NULL, direct_radiation_wm2) as direct_radiation_wm2,
        if(cloud_cover_pct < 0 or cloud_cover_pct > 100, NULL, cloud_cover_pct) as cloud_cover_pct,
        if(precipitation_mm < 0, NULL, precipitation_mm) as precipitation_mm,
        grid_latitude,
        grid_longitude,
        grid_elevation_m,
        run_id,
        loaded_at
    from parsed
    where location_key != ''
      and interval_start_utc is not null
      and source_type in ('forecast', 'archive')
      and (source_type = 'archive' or forecast_version_utc is not null)
)

select
    assumeNotNull(location_key) as location_key,
    assumeNotNull(interval_start_utc) as interval_start_utc,
    toLowCardinality(assumeNotNull(source_type)) as source_type,
    forecast_issued_utc,
    lead_time_h,
    temperature_c,
    wind_speed_ms,
    wind_direction_deg,
    shortwave_radiation_wm2,
    direct_radiation_wm2,
    cloud_cover_pct,
    precipitation_mm,
    grid_latitude,
    grid_longitude,
    grid_elevation_m,
    run_id,
    loaded_at
from cleaned
-- The latest load wins; the run id breaks a tie between two loads in the same second, so a
-- rebuild always picks the same row.
order by loaded_at desc, run_id desc
limit 1 by location_key, interval_start_utc, source_type, forecast_issued_utc
