-- Analytics output tables (segments, forecasts, readiness index) and dashboard notes.
-- These come from the analysis notebooks (06, 07, 07b), not from the raw sources, so they are created
-- by load_analytics.py AFTER the main warehouse load. Re-running wipes and recreates them.
SET search_path TO evision;

DROP TABLE IF EXISTS fact_country_segment, fact_ev_share_forecast, fact_readiness_index, analytics_notes CASCADE;

-- Descriptive grouping of countries by EV adoption profile (notebook 06). Not natural clusters: structure is weak.
CREATE TABLE fact_country_segment (
    geo_key             INT NOT NULL REFERENCES dim_geography (geo_key),
    year                INT NOT NULL REFERENCES dim_year (year),
    segment_number      SMALLINT NOT NULL,          -- 1 = lowest median adoption
    segment_label       TEXT NOT NULL,
    ev_share_pct        DOUBLE PRECISION,           -- IEA EV share of new car sales in `year`
    share_change_pp_3y  DOUBLE PRECISION,           -- change in EV share versus three years earlier (pp)
    gdp_per_capita_usd  DOUBLE PRECISION,
    urban_pop_pct       DOUBLE PRECISION,
    PRIMARY KEY (geo_key, year)
);

-- Short-term EV share forecasts (notebook 07). typical_error_p80_pp is the historical typical error,
-- NOT a probability interval (empirical intervals under-covered in the backtest).
CREATE TABLE fact_ev_share_forecast (
    geo_key               INT NOT NULL REFERENCES dim_geography (geo_key),
    origin_year           INT NOT NULL REFERENCES dim_year (year),
    target_year           INT NOT NULL REFERENCES dim_year (year),
    horizon               SMALLINT NOT NULL,
    method                TEXT NOT NULL,
    last_share_pct        DOUBLE PRECISION,
    forecast_pct          DOUBLE PRECISION,
    persistence_pct       DOUBLE PRECISION,         -- "no change" reference
    typical_error_p80_pp  DOUBLE PRECISION,
    range_low_pct         DOUBLE PRECISION,
    range_high_pct        DOUBLE PRECISION,
    near_saturation       BOOLEAN NOT NULL,         -- trend extrapolation not meaningful near the ceiling
    PRIMARY KEY (geo_key, origin_year, target_year, method)
);

-- EV Structural Readiness Index (notebook 07b): an analytical index created for this project, NOT an official ranking.
-- Core index = mean of GDP-per-capita and urban-share percentile ranks. The extended index adds chargers per 100k people.
CREATE TABLE fact_readiness_index (
    geo_key              INT NOT NULL REFERENCES dim_geography (geo_key),
    year                 INT NOT NULL REFERENCES dim_year (year),
    e_percentile         DOUBLE PRECISION,          -- economy component (GDP per capita, log)
    u_percentile         DOUBLE PRECISION,          -- urbanization component
    core_index           DOUBLE PRECISION,
    core_percentile      DOUBLE PRECISION,
    core_rank            INT,                       -- 1 = most ready
    rank_p05_any_weights DOUBLE PRECISION,          -- rank range (5th-95th pct) under arbitrary weights
    rank_p95_any_weights DOUBLE PRECISION,
    rank_p05_near_equal  DOUBLE PRECISION,          -- rank range under near-equal weights
    rank_p95_near_equal  DOUBLE PRECISION,
    chargers_per_100k    DOUBLE PRECISION,          -- extended index inputs (countries with charging data only)
    c_percentile         DOUBLE PRECISION,
    ext_index            DOUBLE PRECISION,
    ev_share_pct         DOUBLE PRECISION,          -- observed adoption (for comparison; NOT part of the index)
    adoption_gap         DOUBLE PRECISION,          -- readiness percentile minus adoption percentile (EV countries only)
    freq_top10_gap       DOUBLE PRECISION,          -- share of random-weight draws in which the country is in the top-10 gap
    PRIMARY KEY (geo_key, year)
);

-- Caveats the dashboard should show next to the numbers.
CREATE TABLE analytics_notes (
    note_key  INT PRIMARY KEY,
    topic     TEXT NOT NULL,
    note      TEXT NOT NULL
);
INSERT INTO analytics_notes (note_key, topic, note) VALUES
 (1, 'segments',   'Country segments are a descriptive grouping, not natural clusters: the structure in the data is weak and the boundaries are unstable.'),
 (2, 'forecasts',  'Forecasts are short-term (up to 3 years) trend extrapolations. In backtests they were not reliably better than assuming no change. The range shown is the typical historical error, not a probability interval.'),
 (3, 'readiness',  'The EV Structural Readiness Index is an analytical index created for this project. It is not an official ranking. It uses structural factors only and excludes policy, prices and vehicle supply.'),
 (4, 'readiness',  'The readiness index aligns only moderately with EV adoption and is not better aligned than GDP per capita alone. Do not use it to predict adoption.'),
 (5, 'charging',   'Charging infrastructure and EV adoption influence each other. Charger counts are not evidence that chargers cause adoption.'),
 (6, 'scenarios',  'IEA STEPS and CPS are scenarios, not forecasts. Shares are rounded by the IEA.'),
 (7, 'aggregation','Always filter geo_type = country when summing across geographies. World, European Union and the IEA regions are aggregates and would double count.'),
 (8, 'sri_lanka',  'Sri Lanka has no EV data in the sources used. It is scored on structural factors only, and its urban-share component should be read with caution because urban definitions differ between countries.');
