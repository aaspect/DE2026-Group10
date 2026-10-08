-- 2. How wind speed and solar radiation relate to price and renewable production. Correlation: -1 = moves opposite, 0 = none, 1 = together.
WITH weather AS (
  SELECT
    interval_start_utc           AS hour_utc,
    avg(wind_speed_ms)           AS wind,
    avg(shortwave_radiation_wm2) AS radiation
  FROM core.fact_weather FINAL
  WHERE source_type = 'archive'
  GROUP BY hour_utc
)
SELECT
  round(corr(w.wind, toFloat64(p.price_eur_mwh)), 2)      AS wind_vs_price,
  round(corr(w.wind, g.renewable_production_mw), 2)       AS wind_vs_renewable_production,
  round(corr(w.radiation, toFloat64(p.price_eur_mwh)), 2) AS radiation_vs_price,
  round(corr(w.radiation, g.solar_production_mw), 2)      AS radiation_vs_solar_production
FROM core.fact_grid AS g FINAL
JOIN core.fact_price       AS p FINAL ON p.interval_key = g.interval_key
JOIN core.dim_bidding_zone AS z ON p.zone_key = z.zone_key
JOIN weather               AS w ON w.hour_utc = toStartOfHour(g.interval_start_utc)
WHERE g.series_type = 'actual' AND z.zone_code = 'EE';



-- 3. Daily consumption against the same weekday last year (364 days earlier) and the average of the previous 28 days.
WITH daily AS (
  SELECT
    i.local_date                 AS day,
    sum(g.consumption_mw) * 0.25 AS mwh
  FROM core.fact_grid AS g FINAL
  JOIN core.dim_interval AS i ON g.interval_key = i.interval_key
  WHERE g.series_type = 'actual' AND i.local_date < today()
  GROUP BY day
)
SELECT
  day,
  round(mwh) AS consumption_mwh,
  round(anyOrNull(mwh) OVER (ORDER BY day RANGE BETWEEN 364 PRECEDING AND 364 PRECEDING)) AS same_weekday_last_year_mwh,
  round(avgOrNull(mwh) OVER (ORDER BY day RANGE BETWEEN 28 PRECEDING AND 1 PRECEDING))    AS trailing_4w_avg_mwh
FROM daily
ORDER BY day DESC
LIMIT 30;



-- 4. Best hours for a homeowner with solar and storage to sell to the grid: the three highest-priced hours per season, last 12 months
SELECT
  i.season,
  i.local_hour,
  round(avg(f.price_eur_mwh), 2) AS avg_price_eur_mwh
FROM core.fact_price AS f FINAL
JOIN core.dim_interval     AS i ON f.interval_key = i.interval_key
JOIN core.dim_bidding_zone AS z ON f.zone_key = z.zone_key
WHERE z.zone_code = 'EE'
  AND i.local_date >= today() - INTERVAL 1 YEAR
  AND i.local_date <  today()
GROUP BY i.season, i.local_hour
ORDER BY i.season, avg_price_eur_mwh DESC
LIMIT 3 BY i.season;



-- 5. Accuracy of planned consumption and production against actual, by month and hour of day. MAE = mean absolute error.
SELECT
  i.month,
  i.local_hour,
  round(avg(abs(p.consumption_mw - a.consumption_mw)), 1) AS consumption_mae_mw,
  round(avg(abs(p.production_mw - a.production_mw)), 1)   AS production_mae_mw
FROM core.fact_grid AS a FINAL
JOIN core.fact_grid    AS p FINAL ON a.interval_key = p.interval_key
JOIN core.dim_interval AS i ON a.interval_key = i.interval_key
WHERE a.series_type = 'actual' AND p.series_type = 'plan'
GROUP BY i.month, i.local_hour
ORDER BY i.month, i.local_hour;
