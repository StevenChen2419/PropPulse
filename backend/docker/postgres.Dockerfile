# PostgreSQL 15, official binaries/entrypoint; only direct non-root startup supported.
FROM postgres:15-alpine@sha256:a8e042598834300dfaa17a54f695b87b7f25d3490433bbbe2ef3bffbb9747f24
RUN rm /usr/local/bin/gosu
# Provision PGDATA/socket mounts for UID70 before startup. Root volume ownership
# repair is intentionally unsupported and fails closed without the removed helper.
USER 70:70
