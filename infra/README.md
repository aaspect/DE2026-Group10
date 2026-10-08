# Data Dictionary

Currently bronze tables are brought out here.

## bronze.elering_prices

| Name | Type | Description |
|---|---|---|
| id | serial int | |
| zone_code | char(2) | Bidding zone (EE, FI, LV, LT) |
| interval_start_utc | timestamptz | Start of the market interval |
| price_eur_mwh | numeric | Electricity price EUR/MWh |
| loaded_at | timestampz | When the row was loaded |

## bronze.elering_system

| Name | Type | Description |
|---|---|---|
| id | serial int | |
| interval_start_utc | timestamptz | Start of the market interval |
| consumption_mw | numeric | Estonian electricity consumption |
| production_mw | numeric | Total Estonian production |
| renewable_production_mw | numeric | Production from renewable sources |
| solar_production_mw | numeric | Solar production |
| losses_mw | numeric | Grid losses |
| system_balance_mw | numeric | Production minus consumption |
| ac_balance_mw | numeric | Balance on the AC cross-border connections |
| frequency_hz | numeric | Grid frequency |
| renewable_share_pct | numeric | Portion of renewable energy being consumed |
| loaded_at | timestampz | When the row was loaded |

## bronze.elering_system_plan

| Name | Type | Description |
|---|---|---|
| id | serial int | |
| interval_start_utc | timestamptz | Start of the market interval |
| series_type | varschar | Real or plan |
| consumption_mw | numeric | Actual or planned electricity consumption |
| production_mw | numeric | Actual or planned production |
| loaded_at | timestampz | When the row was loaded |

## bronze.weather_hour

| Name | Type | Description |
|---|---|---|
| id | serial int | |
| location_name | varchar | Place name like Tallinn or Tartu |
| latitude | numeric | Location latitude |
| longitude | numeric | Location longitude |
| elevation_m | numeric | Location elevation |
| observation_hour_utc | timestamptz | Start of the prediction or achieved weather hour |
| temperature_c | numeric | Air temperature |
| wind_speed | numeric | Wind speed (m/s) |
| wind_direction | integer | Wind direction |
| shortwave_radiation | numeric | Global horizontal solar radiation |
| direct_radiation | numeric | Direct solar radiation |
| cloud_cover | integer | Total cloud cover (%) |
| precipitation | numeric | Precipitation (mm) |
| source_type | varchar | Forecast or archive |
| loaded_at | timestampz | When the row was loaded |
