-- Creates the database used by the integration test suite.
-- Runs once, on first container start, via docker-entrypoint-initdb.d.
--
-- The test database is separate because the harness truncates it between runs;
-- pointing tests at the development database would silently destroy local data.
CREATE DATABASE ssa_test OWNER ssa;
