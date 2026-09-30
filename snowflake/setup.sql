-- One-time Snowflake setup for the project.
-- Run as ACCOUNTADMIN in a Snowsight worksheet.
--
-- Layout:
--   RAW   data as loaded by the Python scripts, never edited by hand
--   DEV   dbt tables built while models are being changed or tested
--   PROD  dbt tables built from the approved models; Power BI reads from here

USE ROLE ACCOUNTADMIN;

-- Smallest warehouse, suspended after 60 seconds idle to save trial credits.
CREATE WAREHOUSE IF NOT EXISTS FINN_WH
  WAREHOUSE_SIZE = 'XSMALL'
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE;

CREATE DATABASE IF NOT EXISTS RAW;
CREATE DATABASE IF NOT EXISTS DEV;
CREATE DATABASE IF NOT EXISTS PROD;

CREATE SCHEMA IF NOT EXISTS RAW.FINN_SLATES;   -- real FINN data
CREATE SCHEMA IF NOT EXISTS RAW.SIMULATION;    -- simulated contacts, deals and experiment assignment

-- Create a project role and grant it to my user.
-- Everything else in the project runs with this role instead of ACCOUNTADMIN.
CREATE ROLE IF NOT EXISTS FINN_ROLE;
GRANT USAGE ON WAREHOUSE FINN_WH TO ROLE FINN_ROLE;
GRANT ALL ON DATABASE RAW  TO ROLE FINN_ROLE;
GRANT ALL ON DATABASE DEV  TO ROLE FINN_ROLE;
GRANT ALL ON DATABASE PROD TO ROLE FINN_ROLE;
GRANT ALL ON ALL SCHEMAS IN DATABASE RAW TO ROLE FINN_ROLE;
GRANT ALL ON FUTURE SCHEMAS IN DATABASE RAW TO ROLE FINN_ROLE;

SET my_user = '"' || CURRENT_USER() || '"';
GRANT ROLE FINN_ROLE TO USER IDENTIFIER($my_user);

-- Later, for GitHub Actions: a service user with key-pair authentication.
-- CREATE USER IF NOT EXISTS FINN_CI
--   TYPE = SERVICE
--   DEFAULT_ROLE = FINN_ROLE
--   DEFAULT_WAREHOUSE = FINN_WH
--   RSA_PUBLIC_KEY = '<public key>';
-- GRANT ROLE FINN_ROLE TO USER FINN_CI;
