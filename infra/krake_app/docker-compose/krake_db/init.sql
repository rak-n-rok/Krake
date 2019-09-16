-- Create DB
CREATE DATABASE krake;
USE krake;

-- Create tables
-- handled by SQLAlchemy, see krake_api/db_models.py

-- Create user
GRANT CREATE, SELECT, INSERT, UPDATE, DELETE, CREATE TEMPORARY TABLES, LOCK TABLES, EXECUTE ON krake.* TO krake@'%' IDENTIFIED BY 'tmp';

-- Create user to collect metrics
GRANT PROCESS, REPLICATION CLIENT, SELECT ON *.* TO exporter@'%' IDENTIFIED BY 'tmp';
