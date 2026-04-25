-- Enable PostGIS extensions on first container init.
-- Source of truth: NYC_Agent_Data_Sources_API_SQL.md §6
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;
