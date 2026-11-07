SET search_path TO evision;

-- Surrogate keys are assigned by the loader (deterministic order), so plain INT primary keys are used.

-- One row per year (annual facts join here). Covers observed years and IEA projection years.
CREATE TABLE dim_year (
    year               INT PRIMARY KEY,
    decade             INT      NOT NULL,
    is_partial_year    BOOLEAN  NOT NULL,   -- latest year in the Ember file (2026 stops before December)
    is_projection_year BOOLEAN  NOT NULL    -- later than the latest observed year
);

-- One row per month (monthly facts join here).
CREATE TABLE dim_date (
    month_start        DATE PRIMARY KEY,    -- first day of the month
    year               INT      NOT NULL REFERENCES dim_year (year),
    quarter            SMALLINT NOT NULL CHECK (quarter BETWEEN 1 AND 4),
    month              SMALLINT NOT NULL CHECK (month BETWEEN 1 AND 12),
    month_name         TEXT     NOT NULL,
    year_month         TEXT     NOT NULL,   -- e.g. '2024-05' (sorts correctly as text)
    is_complete_period BOOLEAN  NOT NULL    -- month is not later than the last month most countries have reported
);

-- Countries AND aggregates (World, EU, IEA regions) in one dimension.
-- Always filter geo_type = 'country' when summing across geographies, otherwise totals double count.
-- geo_code: ISO3 for countries; WLD / EUU for World / European Union (shared by all sources);
--           IEA_<NAME> for IEA-only regions; World Bank codes for World Bank aggregates.
CREATE TABLE dim_geography (
    geo_key       INT PRIMARY KEY,
    geo_code      VARCHAR(40) NOT NULL UNIQUE,
    geo_name      TEXT        NOT NULL,
    geo_type      VARCHAR(10) NOT NULL CHECK (geo_type IN ('country', 'aggregate')),
    iso3          CHAR(3)     UNIQUE,       -- NULL for aggregates
    continent     TEXT,                     -- from Ember; NULL for countries Ember does not cover
    ember_region  TEXT,
    is_eu         BOOLEAN,
    is_oecd       BOOLEAN,
    is_g20        BOOLEAN,
    is_g7         BOOLEAN,
    is_asean      BOOLEAN,
    in_ember      BOOLEAN     NOT NULL,
    in_iea        BOOLEAN     NOT NULL,
    in_worldbank  BOOLEAN     NOT NULL,
    has_ev_data   BOOLEAN     NOT NULL      -- in Ember or IEA (Sri Lanka, for example, is FALSE)
);

CREATE TABLE dim_scenario (
    scenario_key   INT PRIMARY KEY,
    scenario_code  VARCHAR(20) NOT NULL UNIQUE,   -- Historical / STEPS / CPS
    scenario_name  TEXT        NOT NULL,
    is_projection  BOOLEAN     NOT NULL,
    description    TEXT
);

-- Ember drivetrain categories. Aggregate rows (EV_TOTAL, ALL) overlap with the component rows:
-- never sum across all drivetrains; filter on is_aggregate or pick a single drivetrain.
CREATE TABLE dim_drivetrain (
    drivetrain_key   INT PRIMARY KEY,
    drivetrain_code  VARCHAR(20) NOT NULL UNIQUE,
    drivetrain_name  TEXT        NOT NULL,
    drivetrain_group TEXT        NOT NULL,        -- EV / Hybrid / ICE / Other / Aggregate
    is_aggregate     BOOLEAN     NOT NULL
);

-- IEA indicators: one row per (parameter, vehicle mode, powertrain, unit).
CREATE TABLE dim_indicator (
    indicator_key      INT PRIMARY KEY,
    indicator_category VARCHAR(10) NOT NULL CHECK (indicator_category IN ('market', 'charging', 'energy')),
    parameter_code     TEXT NOT NULL,             -- e.g. ev_sales, ev_stock, charging_points
    vehicle_mode       TEXT NOT NULL,             -- Cars, Vans, Buses, ...
    powertrain         TEXT NOT NULL,             -- EV, BEV, PHEV, FCEV, Fast, Slow, ...
    unit               TEXT NOT NULL,
    UNIQUE (parameter_code, vehicle_mode, powertrain, unit)
);