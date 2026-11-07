-- EVISION 360 data warehouse: schema.
-- Re-running this file wipes and recreates everything in the "evision" schema (full reload).
-- Run order: schema.sql -> dimensions.sql -> fact_tables.sql (load_warehouse.py does this for you).

DROP SCHEMA IF EXISTS evision CASCADE;
CREATE SCHEMA evision;
SET search_path TO evision;