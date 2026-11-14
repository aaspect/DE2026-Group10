-- Checks on the tables dbt built from bronze_open_meteo_weather.jsonl (30 bronze rows). Each
-- statement throws, and so fails the CI job, when a silver or gold rule did not hold. The dbt
-- tests already cover grain, keys and value ranges; these cover what was kept and what was not.

-- Silver holds one row per valid grain key: tallinn 9 hours (two overlapping archive loads),
-- tartu 5 hours x 2 forecast versions, parnu 6 hours, riga 1 hour.
SELECT throwIf(count() != 26, 'silver must hold 26 rows')
FROM silver.open_meteo_weather;

-- The document without hour_utc stays in bronze only.
SELECT throwIf(count() != 0, 'the row without hour_utc must not reach silver')
FROM silver.open_meteo_weather
WHERE location_key = 'narva';

-- Both forecast versions survive, and the hour before the issue time has a negative lead time.
SELECT throwIf(
    uniqExact(forecast_issued_utc) != 2 OR min(lead_time_h) >= 0,
    'silver must keep both tartu forecast versions, with a negative lead time'
)
FROM silver.open_meteo_weather
WHERE location_key = 'tartu' AND source_type = 'forecast';

-- Each impossible value became NULL and its row was kept.
SELECT throwIf(
    count() != 6
    OR countIf(wind_speed_ms IS NULL) != 1
    OR countIf(wind_direction_deg IS NULL) != 1
    OR countIf(shortwave_radiation_wm2 IS NULL) != 1
    OR countIf(direct_radiation_wm2 IS NULL) != 1
    OR countIf(cloud_cover_pct IS NULL) != 1
    OR countIf(precipitation_mm IS NULL) != 1,
    'silver must keep the 6 parnu rows with exactly one impossible value each set to NULL'
)
FROM silver.open_meteo_weather
WHERE location_key = 'parnu';

SELECT throwIf(count() != 1, 'the cloud cover of 150 % must be NULL in silver')
FROM silver.open_meteo_weather
WHERE location_key = 'parnu'
  AND interval_start_utc = '2026-11-10 04:00:00'
  AND cloud_cover_pct IS NULL;

-- A missing value stays missing.
SELECT throwIf(count() != 1, 'the null temperature must stay NULL in silver')
FROM silver.open_meteo_weather
WHERE location_key = 'tallinn'
  AND interval_start_utc = '2026-11-10 00:00:00'
  AND temperature_c IS NULL;

-- A location that is not configured reaches silver but not gold.
SELECT throwIf(
    (SELECT count() FROM silver.open_meteo_weather WHERE location_key = 'riga') != 1
    OR (SELECT count() FROM gold.fact_weather WHERE location_key = 'riga') != 0,
    'riga must be in silver and missing from fact_weather'
);

-- The mart holds observed weather only: tallinn 9 hours and parnu 6 hours.
SELECT throwIf(count() != 15, 'the mart must hold the 15 archive rows of configured locations')
FROM gold.mart_past_weather;

-- Where two archive loads overlap, the later one wins (11.4, not 1.4), and a whole-number
-- value (cloud cover 100, stored as Int64 in bronze) is read like any other.
SELECT throwIf(
    count() != 1,
    'the overlapping tallinn hour must carry the later load in the mart'
)
FROM gold.mart_past_weather
WHERE location_key = 'tallinn'
  AND interval_start_utc = '2026-11-10 04:00:00'
  AND temperature_c = 11.4
  AND cloud_cover_pct = 100
  AND loaded_at = '2026-11-13 00:10:00';
