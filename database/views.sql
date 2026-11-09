-- Dashboard-friendly views over the core warehouse (Power BI imports these instead of joining 10 tables).
-- Created by load_warehouse.py right after the tables. All views are country-level unless the name says otherwise.
SET search_path TO evision;

-- Countries only: use this as the geography dimension in Power BI so aggregates never double count.
CREATE OR REPLACE VIEW v_geography_country AS
SELECT geo_key, geo_code, geo_name, continent, ember_region, is_eu, is_oecd, is_g20, is_g7, is_asean,
       in_ember, in_iea, in_worldbank, has_ev_data
FROM dim_geography
WHERE geo_type = 'country';

-- Ember monthly registrations by drivetrain, countries only.
-- Aggregate drivetrains (EV_TOTAL, ALL) overlap with components: filter is_aggregate or pick one drivetrain.
CREATE OR REPLACE VIEW v_ev_sales_monthly AS
SELECT f.geo_key, g.geo_code, g.geo_name, f.month_start, d.year, d.month, d.year_month,
       dr.drivetrain_code, dr.drivetrain_group, dr.is_aggregate,
       f.registrations, f.share_pct, f.yoy_change_pct, f.roll12m_registrations,
       f.is_partial_year, f.is_complete_period
FROM fact_ev_sales_monthly f
JOIN dim_geography g  ON g.geo_key = f.geo_key
JOIN dim_date d       ON d.month_start = f.month_start
JOIN dim_drivetrain dr ON dr.drivetrain_key = f.drivetrain_key
WHERE g.geo_type = 'country';

-- One row per country and year: EV market (IEA, cars, historical), charging, and World Bank economy.
-- Powers the overview, country, charging and economic pages. Impossible values flagged by the cleaning step are excluded.
-- Fast, slow and ultra-fast public charging points are treated as separate categories (see notebook 04).
CREATE OR REPLACE VIEW v_country_year AS
WITH ev AS (
    SELECT f.geo_key, f.year,
           MAX(f.value) FILTER (WHERE i.parameter_code = 'ev_sales'       AND i.powertrain = 'EV')   AS ev_sales_cars,
           MAX(f.value) FILTER (WHERE i.parameter_code = 'ev_sales'       AND i.powertrain = 'BEV')  AS bev_sales_cars,
           MAX(f.value) FILTER (WHERE i.parameter_code = 'ev_sales'       AND i.powertrain = 'PHEV') AS phev_sales_cars,
           MAX(f.value) FILTER (WHERE i.parameter_code = 'ev_stock'       AND i.powertrain = 'EV')   AS ev_stock_cars,
           MAX(f.value) FILTER (WHERE i.parameter_code = 'ev_sales_share' AND i.powertrain = 'EV')   AS ev_sales_share_pct,
           MAX(f.value) FILTER (WHERE i.parameter_code = 'ev_stock_share' AND i.powertrain = 'EV')   AS ev_stock_share_pct
    FROM fact_ev_market_annual f
    JOIN dim_indicator i ON i.indicator_key = f.indicator_key
    JOIN dim_scenario s  ON s.scenario_key = f.scenario_key
    WHERE s.scenario_code = 'Historical' AND i.vehicle_mode = 'Cars' AND NOT f.is_suspect_value
    GROUP BY f.geo_key, f.year
), ch AS (
    SELECT f.geo_key, f.year,
           MAX(f.value) FILTER (WHERE i.parameter_code = 'charging_points' AND i.powertrain = 'Publicly available fast')       AS chargers_fast,
           MAX(f.value) FILTER (WHERE i.parameter_code = 'charging_points' AND i.powertrain = 'Publicly available slow')       AS chargers_slow,
           MAX(f.value) FILTER (WHERE i.parameter_code = 'charging_points' AND i.powertrain = 'Publicly available ultra-fast') AS chargers_ultra_fast,
           MAX(f.value) FILTER (WHERE i.parameter_code = 'ev_per_charging_point')                                              AS evs_per_charging_point
    FROM fact_charging_infrastructure f
    JOIN dim_indicator i ON i.indicator_key = f.indicator_key
    JOIN dim_scenario s  ON s.scenario_key = f.scenario_key
    WHERE s.scenario_code = 'Historical' AND NOT f.is_suspect_value
    GROUP BY f.geo_key, f.year
), keys AS (
    SELECT geo_key, year FROM ev UNION SELECT geo_key, year FROM ch UNION SELECT geo_key, year FROM fact_economic_indicators
)
SELECT g.geo_key, g.geo_code, g.geo_name, g.continent, k.year,
       ev.ev_sales_cars, ev.bev_sales_cars, ev.phev_sales_cars, ev.ev_stock_cars, ev.ev_sales_share_pct, ev.ev_stock_share_pct,
       ch.chargers_fast, ch.chargers_slow, ch.chargers_ultra_fast,
       CASE WHEN ch.chargers_fast IS NULL AND ch.chargers_slow IS NULL AND ch.chargers_ultra_fast IS NULL THEN NULL
            ELSE COALESCE(ch.chargers_fast, 0) + COALESCE(ch.chargers_slow, 0) + COALESCE(ch.chargers_ultra_fast, 0) END AS chargers_total,
       ch.evs_per_charging_point,
       e.gdp_per_capita_usd, e.gdp_growth_pct, e.population, e.urban_pop_pct, e.inflation_pct,
       CASE WHEN e.population > 0 AND (ch.chargers_fast IS NOT NULL OR ch.chargers_slow IS NOT NULL OR ch.chargers_ultra_fast IS NOT NULL)
            THEN (COALESCE(ch.chargers_fast, 0) + COALESCE(ch.chargers_slow, 0) + COALESCE(ch.chargers_ultra_fast, 0)) / e.population * 100000
       END AS chargers_per_100k
FROM keys k
JOIN dim_geography g ON g.geo_key = k.geo_key AND g.geo_type = 'country'
LEFT JOIN ev ON ev.geo_key = k.geo_key AND ev.year = k.year
LEFT JOIN ch ON ch.geo_key = k.geo_key AND ch.year = k.year
LEFT JOIN fact_economic_indicators e ON e.geo_key = k.geo_key AND e.year = k.year;

-- IEA scenarios for the future page: EV cars sales, stock and shares for countries AND aggregates, historical and 2035 projections.
-- Filter scenario_code (Historical / STEPS / CPS) and geo_type.
CREATE OR REPLACE VIEW v_ev_scenarios AS
SELECT g.geo_code, g.geo_name, g.geo_type, s.scenario_code, s.is_projection, f.year, i.parameter_code, f.value
FROM fact_ev_market_annual f
JOIN dim_geography g ON g.geo_key = f.geo_key
JOIN dim_indicator i ON i.indicator_key = f.indicator_key
JOIN dim_scenario s  ON s.scenario_key = f.scenario_key
WHERE i.vehicle_mode = 'Cars' AND i.powertrain = 'EV'
  AND i.parameter_code IN ('ev_sales', 'ev_stock', 'ev_sales_share', 'ev_stock_share')
  AND NOT f.is_suspect_value;

-- IEA vehicle price percentiles (2025 USD) for the technology page. geo_code is NULL for rows the source gives no country for.
CREATE OR REPLACE VIEW v_vehicle_prices AS
SELECT g.geo_code, g.geo_name, p.country_missing, p.vehicle_mode, p.powertrain, p.year,
       p.price_p0, p.price_p25, p.price_p50, p.price_p75, p.price_p95, p.price_p100, p.price_mean, p.currency
FROM fact_vehicle_prices p
LEFT JOIN dim_geography g ON g.geo_key = p.geo_key;
