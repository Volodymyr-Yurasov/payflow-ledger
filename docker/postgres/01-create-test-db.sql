-- Runs once, on the first start of a fresh Postgres volume (as POSTGRES_USER, who
-- therefore owns it): the separate database the test suite uses.
CREATE DATABASE payflow_test;
