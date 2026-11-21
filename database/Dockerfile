FROM postgres:15.3-alpine

# Scripts d'initialisation SQL
COPY ./database/init.sql /docker-entrypoint-initdb.d/init.sql

EXPOSE 5432