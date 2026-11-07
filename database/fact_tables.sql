SET search_path TO evision;

-- Ember monthly EV sales, countries and region rows (EU, World). Grain: geography x month x drivetrain.
CREATE TABLE fact_ev_sales_monthly (
    geo_key              INT  NOT NULL REFERENCES dim_geography (geo_key),
    month_start          DATE NOT NULL REFERENCES dim_date (month_start),
    drivetrain_key       INT  NOT NULL REFERENCES dim_drivetrain (drivetrain_key),
    registrations        BIGINT,
    share_pct            DOUBLE PRECISION,
    yoy_change           DOUBLE PRECISION,
    yoy_change_pct       DOUBLE PRECISION,
    ytd_registrations    BIGINT,
    ytd_share_pct        DOUBLE PRECISION,
    roll3m_registrations BIGINT,
    roll3m_share_pct     DOUBLE PRECISION,
    roll12m_registrations BIGINT,
    roll12m_share_pct    DOUBLE PRECISION,
    is_partial_year      BOOLEAN NOT NULL,
    is_complete_period   BOOLEAN NOT NULL,
    PRIMARY KEY (geo_key, month_start, drivetrain_key)
);

-- Countries Ember reports quarterly only (Canada, South Africa). period_date is the date given in the source;
-- the source dates fall in Mar/Jun/Sep/Dec and whether that marks quarter start or end is still to be confirmed.
CREATE TABLE fact_ev_sales_quarterly (
    geo_key              INT  NOT NULL REFERENCES dim_geography (geo_key),
    period_date          DATE NOT NULL REFERENCES dim_date (month_start),
    drivetrain_key       INT  NOT NULL REFERENCES dim_drivetrain (drivetrain_key),
    registrations        BIGINT,
    share_pct            DOUBLE PRECISION,
    yoy_change           DOUBLE PRECISION,
    yoy_change_pct       DOUBLE PRECISION,
    ytd_registrations    BIGINT,
    ytd_share_pct        DOUBLE PRECISION,
    roll12m_registrations BIGINT,
    roll12m_share_pct    DOUBLE PRECISION,
    is_partial_year      BOOLEAN NOT NULL,
    PRIMARY KEY (geo_key, period_date, drivetrain_key)
);

-- IEA annual facts. Three tables share one structure and differ by indicator_category.
-- Grain: geography x year x scenario x indicator. Projections (STEPS / CPS) live here with is_projection scenarios.
-- is_suspect_value flags impossible values kept as-is (e.g. UAE Vans sales share above 100 percent).
CREATE TABLE fact_ev_market_annual (
    geo_key          INT NOT NULL REFERENCES dim_geography (geo_key),
    year             INT NOT NULL REFERENCES dim_year (year),
    scenario_key     INT NOT NULL REFERENCES dim_scenario (scenario_key),
    indicator_key    INT NOT NULL REFERENCES dim_indicator (indicator_key),
    value            DOUBLE PRECISION,
    is_suspect_value BOOLEAN NOT NULL,
    PRIMARY KEY (geo_key, year, scenario_key, indicator_key)
);

CREATE TABLE fact_charging_infrastructure (
    geo_key          INT NOT NULL REFERENCES dim_geography (geo_key),
    year             INT NOT NULL REFERENCES dim_year (year),
    scenario_key     INT NOT NULL REFERENCES dim_scenario (scenario_key),
    indicator_key    INT NOT NULL REFERENCES dim_indicator (indicator_key),
    value            DOUBLE PRECISION,
    is_suspect_value BOOLEAN NOT NULL,
    PRIMARY KEY (geo_key, year, scenario_key, indicator_key)
);

-- Electricity demand, battery deployment, oil displacement, average capacity per EV.
CREATE TABLE fact_ev_energy_annual (
    geo_key          INT NOT NULL REFERENCES dim_geography (geo_key),
    year             INT NOT NULL REFERENCES dim_year (year),
    scenario_key     INT NOT NULL REFERENCES dim_scenario (scenario_key),
    indicator_key    INT NOT NULL REFERENCES dim_indicator (indicator_key),
    value            DOUBLE PRECISION,
    is_suspect_value BOOLEAN NOT NULL,
    PRIMARY KEY (geo_key, year, scenario_key, indicator_key)
);

-- IEA vehicle price percentiles (2025 USD). geo_key is NULL for the rows the IEA file gives no country for.
CREATE TABLE fact_vehicle_prices (
    price_key        INT PRIMARY KEY,
    geo_key          INT REFERENCES dim_geography (geo_key),
    country_missing  BOOLEAN NOT NULL,
    vehicle_mode     TEXT    NOT NULL,
    powertrain       TEXT    NOT NULL,
    year             INT     NOT NULL REFERENCES dim_year (year),
    price_p0         DOUBLE PRECISION,
    price_p25        DOUBLE PRECISION,
    price_p50        DOUBLE PRECISION,
    price_p75        DOUBLE PRECISION,
    price_p95        DOUBLE PRECISION,
    price_p100       DOUBLE PRECISION,
    price_mean       DOUBLE PRECISION,
    currency         TEXT    NOT NULL
);

-- World Bank WDI, economies and aggregates. Grain: geography x year.
CREATE TABLE fact_economic_indicators (
    geo_key             INT NOT NULL REFERENCES dim_geography (geo_key),
    year                INT NOT NULL REFERENCES dim_year (year),
    gdp_per_capita_usd  DOUBLE PRECISION,
    gdp_growth_pct      DOUBLE PRECISION,
    population          BIGINT,
    urban_pop_pct       DOUBLE PRECISION,
    inflation_pct       DOUBLE PRECISION,
    has_core_indicators BOOLEAN NOT NULL,   -- GDP per capita, population and urban share all present
    PRIMARY KEY (geo_key, year)
);