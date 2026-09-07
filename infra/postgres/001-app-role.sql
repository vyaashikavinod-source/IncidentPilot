-- Executed only when PostgreSQL initializes a fresh named volume.
\getenv app_password INCIDENTPILOT_DB_PASSWORD
SELECT format('CREATE ROLE incidentpilot LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L', :'app_password') \gexec
ALTER DATABASE incidentpilot OWNER TO incidentpilot;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO incidentpilot;
