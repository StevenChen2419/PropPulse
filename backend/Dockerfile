FROM gcr.io/distroless/cc-debian13:nonroot@sha256:3ee00291cf386ec52a552e6a858d555debd74776eb4bfa53fa3df2cd6677515e AS runtime-base

FROM python:3.11-slim@sha256:b7a9e5f6a93d6d4a31f129bbd4bdee69efccb6ded0fb230d78aafaf37af98377 AS builder

WORKDIR /app

# Both stages use Debian 13; do not mix distro releases or copy glibc from elsewhere.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libgomp1 libstdc++6 && update-ca-certificates && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.lock.txt ./
RUN --mount=type=cache,target=/root/.cache/pip python -m pip install --upgrade pip==26.2.2 && python -m pip install --only-binary=:all: -r requirements.txt && python -m pip check && python -m pip uninstall -y setuptools wheel pip

COPY --from=runtime-base / /runtime-base/
COPY docker/assemble_runtime.py /assemble_runtime.py
# Official slim has no Tcl/Tk libraries; PropPulse has no GUI tooling/imports.
RUN rm -rf /usr/local/lib/python3.11/tkinter /usr/local/lib/python3.11/idlelib /usr/local/lib/python3.11/turtledemo /usr/local/lib/python3.11/turtle.py /usr/local/lib/python3.11/lib-dynload/_tkinter* && python /assemble_runtime.py && rm -rf /usr/local/include /usr/local/lib/python3.11/ensurepip /usr/local/lib/pkgconfig

FROM runtime-base AS runtime
ENV PATH="/usr/local/bin:/usr/bin:/bin" PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY --from=builder /usr/local /usr/local
COPY --from=builder /runtime-overlay/ /
COPY requirements.txt requirements.lock.txt alembic.ini ./
COPY app/ ./app/
COPY scripts/ ./scripts/
COPY alembic/ ./alembic/

USER 10001:10001
ENTRYPOINT []

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers", "--no-access-log"]
