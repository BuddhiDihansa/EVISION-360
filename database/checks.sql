-- Example analytical queries to try in pgAdmin (Query Tool). They also double as smoke tests of the star schema.
SET search_path TO evision;

-- 1. Top 10 countries by EV share of new car sales in 2024 (IEA, historical)
SELECT g.geo_name, ROUND(f.value::numeric, 1) AS ev_sales_share_pct
FROM fact_ev_market_annual f
JOIN dim_geography g USING (geo_key)
JOIN dim_indicator i USING (indicator_key)
JOIN dim_scenario s USING (scenario_key)
WHERE g.geo_type = 'country' AND i.parameter_code = 'ev_sales_share' AND i.vehicle_mode = 'Cars'
  AND i.powertrain = 'EV' AND s.scenario_code = 'Historical' AND f.year = 2024
ORDER BY f.value DESC
LIMIT 10;

-- 2. Global EV registrations per year, 2018-2025 (Ember, countries only, 2026 left out because it is a partial year)
SELECT d.year, SUM(f.registrations) AS ev_registrations
FROM fact_ev_sales_monthly f
JOIN dim_geography g USING (geo_key)
JOIN dim_drivetrain dr USING (drivetrain_key)
JOIN dim_date d USING (month_start)
WHERE g.geo_type = 'country' AND dr.drivetrain_code = 'EV_TOTAL' AND d.year BETWEEN 2018 AND 2025
GROUP BY d.year
ORDER BY d.year;

-- 3. Sri Lanka: no EV data, but World Bank economic data is available (for the Readiness Index)
SELECT g.geo_name, g.has_ev_data, e.year, e.gdp_per_capita_usd, e.population, e.urban_pop_pct
FROM fact_economic_indicators e
JOIN dim_geography g USING (geo_key)
WHERE g.geo_code = 'LKA' AND e.year >= 2023
ORDER BY e.year;

-- 4. Economy vs adoption: GDP per capita against EV sales share, 2024
SELECT g.geo_name, ROUND(e.gdp_per_capita_usd::numeric) AS gdp_per_capita, ROUND(f.value::numeric, 1) AS ev_share_pct
FROM fact_ev_market_annual f
JOIN dim_geography g USING (geo_key)
JOIN dim_indicator i USING (indicator_key)
JOIN dim_scenario s USING (scenario_key)
JOIN fact_economic_indicators e ON e.geo_key = f.geo_key AND e.year = f.year
WHERE g.geo_type = 'country' AND i.parameter_code = 'ev_sales_share' AND i.vehicle_mode = 'Cars'
  AND i.powertrain = 'EV' AND s.scenario_code = 'Historical' AND f.year = 2024
ORDER BY e.gdp_per_capita_usd DESC
LIMIT 10;

-- 5. IEA 2035 projections for World: stated vs current policies (EV car sales)
SELECT s.scenario_code, f.year, ROUND((f.value / 1e6)::numeric, 1) AS ev_car_sales_millions
FROM fact_ev_market_annual f
JOIN dim_geography g USING (geo_key)
JOIN dim_indicator i USING (indicator_key)
JOIN dim_scenario s USING (scenario_key)
WHERE g.geo_code = 'WLD' AND i.parameter_code = 'ev_sales' AND i.vehicle_mode = 'Cars' AND i.powertrain = 'EV'
  AND (f.year = 2035 OR (f.year = 2025 AND s.scenario_code = 'Historical'))
ORDER BY f.year, s.scenario_code;

-- ---------------------------------------------------------------------------------------------
-- Queries on the dashboard views (views.sql, analytics_views.sql)
-- ---------------------------------------------------------------------------------------------

-- 6. Public chargers per 100k people, 2024 (countries with charging data)
SELECT geo_name, ROUND(chargers_per_100k::numeric) AS chargers_per_100k, ev_sales_share_pct
FROM v_country_year
WHERE year = 2024 AND chargers_per_100k IS NOT NULL
ORDER BY chargers_per_100k DESC
LIMIT 10;

-- 7. Sri Lanka readiness profile (no EV data, scored on structural factors only)
SELECT geo_name, core_index, core_rank, rank_p05_any_weights, rank_p95_any_weights, e_percentile, u_percentile
FROM v_country_analytics
WHERE geo_code = 'LKA';

-- 8. Segment profile (descriptive grouping, not natural clusters)
SELECT segment_label, COUNT(*) AS countries, ROUND(AVG(ev_share_pct)::numeric, 1) AS avg_ev_share_pct,
       ROUND(AVG(gdp_per_capita_usd)::numeric) AS avg_gdp_per_capita
FROM v_country_analytics
WHERE segment_label IS NOT NULL
GROUP BY segment_label, segment_number
ORDER BY segment_number;

-- 9. Forecast versus "no change" for the largest EV markets (2028, typical historical error shown, not a probability interval)
SELECT geo_name, last_share_pct, forecast_pct, persistence_pct, typical_error_p80_pp, near_saturation
FROM v_ev_share_forecast
WHERE target_year = 2028 AND geo_code IN ('CHN', 'USA', 'DEU', 'GBR', 'FRA')
ORDER BY forecast_pct DESC;

-- 10. Countries with readiness above adoption (opportunity candidates, robust ones appear in most random-weight draws)
SELECT geo_name, core_index, ev_share_pct, ROUND(adoption_gap::numeric) AS adoption_gap, ROUND(freq_top10_gap::numeric, 2) AS freq_top10_gap
FROM v_country_analytics
WHERE adoption_gap IS NOT NULL
ORDER BY adoption_gap DESC
LIMIT 8;
