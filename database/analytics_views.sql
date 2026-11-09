-- Views over the analytics tables. Created by load_analytics.py after the tables exist.
SET search_path TO evision;

CREATE OR REPLACE VIEW v_ev_share_forecast AS
SELECT g.geo_code, g.geo_name, f.origin_year, f.target_year, f.horizon, f.method,
       f.last_share_pct, f.forecast_pct, f.persistence_pct, f.typical_error_p80_pp,
       f.range_low_pct, f.range_high_pct, f.near_saturation
FROM fact_ev_share_forecast f
JOIN dim_geography g ON g.geo_key = f.geo_key;

-- One row per economy in the readiness index, with its segment and 3-year forecast (when available).
-- Sri Lanka appears with a readiness score but no segment or forecast, because it has no EV data.
CREATE OR REPLACE VIEW v_country_analytics AS
SELECT g.geo_code, g.geo_name, g.continent, r.year,
       e.gdp_per_capita_usd, e.urban_pop_pct, e.population,
       r.core_index, r.core_percentile, r.core_rank, r.rank_p05_any_weights, r.rank_p95_any_weights,
       r.e_percentile, r.u_percentile, r.chargers_per_100k, r.ext_index,
       r.ev_share_pct, r.adoption_gap, r.freq_top10_gap,
       sg.segment_number, sg.segment_label, sg.share_change_pp_3y,
       fc.target_year AS forecast_target_year, fc.forecast_pct AS forecast_3y_pct,
       fc.persistence_pct AS persistence_3y_pct, fc.typical_error_p80_pp AS forecast_3y_typical_error_pp
FROM fact_readiness_index r
JOIN dim_geography g ON g.geo_key = r.geo_key
LEFT JOIN fact_economic_indicators e ON e.geo_key = r.geo_key AND e.year = r.year
LEFT JOIN fact_country_segment sg ON sg.geo_key = r.geo_key AND sg.year = r.year
LEFT JOIN (
    SELECT DISTINCT ON (geo_key) geo_key, target_year, forecast_pct, persistence_pct, typical_error_p80_pp
    FROM fact_ev_share_forecast
    WHERE horizon = 3
    ORDER BY geo_key, origin_year DESC, method
) fc ON fc.geo_key = r.geo_key;
