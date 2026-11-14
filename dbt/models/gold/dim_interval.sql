{#
    One row per UTC hour, with Europe/Tallinn calendar attributes. Covers 1 January of the
    earliest silver year to 31 December of the latest one, so every fact hour has a row; empty
    silver gives an empty table.

    Deferred attributes from the project plan: is_ee_holiday, tariff_period, quarter_of_hour.
#}
{{ config(materialized='table', engine='MergeTree()', order_by='interval_start_utc') }}

with bounds as (
    select
        toDateTime(toStartOfYear(min(interval_start_utc)), 'UTC') as range_start,
        toDateTime(toStartOfYear(max(interval_start_utc)) + interval 1 year, 'UTC') as range_end,
        count() as silver_rows
    from {{ ref('open_meteo_weather') }}
),

hours as (
    select
        range_start
        + toIntervalHour(arrayJoin(range(dateDiff('hour', range_start, range_end)))) as hour_start
    from bounds
    -- min() and max() of no rows are 1970-01-01, which would generate the hours of 1970.
    where silver_rows > 0
)

select
    toUInt64(formatDateTime(hour_start, '%Y%m%d%H%i', 'UTC')) as interval_key,
    hour_start as interval_start_utc,
    toTimeZone(hour_start, 'Europe/Tallinn') as interval_start_local,
    toDate(interval_start_local) as local_date,
    toHour(interval_start_local) as local_hour,
    toDayOfWeek(interval_start_local) as day_of_week,
    toBool(day_of_week >= 6) as is_weekend,
    toMonth(interval_start_local) as month,
    toYear(interval_start_local) as year,
    toISOWeek(interval_start_local) as iso_week,
    toLowCardinality(multiIf(
        month in (12, 1, 2), 'winter',
        month in (3, 4, 5), 'spring',
        month in (6, 7, 8), 'summer',
        'autumn'
    )) as season,
    -- Tallinn is 3 hours ahead of UTC in summer time and 2 hours otherwise.
    toBool(timeZoneOffset(interval_start_local) = 10800) as is_dst,
    toDateTime(now(), 'UTC') as loaded_at
from hours
