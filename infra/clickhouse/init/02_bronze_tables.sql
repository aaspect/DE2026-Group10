CREATE TABLE staging.raw_weather (
    location_id      String,
    observed_at      DateTime('UTC'),
    temperature_c    Nullable(Float64),
    wind_speed_ms    Nullable(Float64),
    solar_radiation  Nullable(Float64),
    cloud_cover_pct  Nullable(Float64),
    _source          String,
    _ingested_at     DateTime DEFAULT now()
);


CREATE TABLE staging.raw_prices (
    bidding_zone     String,
    delivery_start   DateTime('UTC'),
    delivery_end     DateTime('UTC'),
    price_eur_mwh    Float64,
    _source          String,
    _ingested_at     DateTime DEFAULT now()
);


CREATE TABLE staging.raw_consumption (
    area             String,
    period_start     DateTime('UTC'),
    consumption_mwh  Float64,
    _source          String,
    _ingested_at     DateTime DEFAULT now()
);


CREATE TABLE staging.raw_production (
    area             String,
    period_start     DateTime('UTC'),
    production_type  String,
    production_mwh   Float64,
    _source          String,
    _ingested_at     DateTime DEFAULT now()
);

