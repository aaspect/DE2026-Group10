{#
    One row per configured weather location. SCD type 1: rebuilt from the seed on every run, so a
    change to the location configuration overwrites the old values.
#}
{{ config(materialized='table', engine='MergeTree()', order_by='location_key') }}

select
    location_key,
    location_name,
    latitude,
    longitude,
    zone_code,
    location_role,
    toDateTime(now(), 'UTC') as loaded_at
from {{ ref('weather_locations') }}
