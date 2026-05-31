FROM timescale/timescaledb-ha:pg16

# Bootstrap extensions on first run.
COPY init.sql /docker-entrypoint-initdb.d/00-extensions.sql
