FROM node:22-bookworm-slim AS node-runtime

FROM mcr.microsoft.com/dotnet/sdk:9.0-bookworm-slim AS application

COPY --from=node-runtime /usr/local/ /usr/local/

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fonts-noto-cjk python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

ENV npm_config_fetch_retries=5 \
    npm_config_fetch_retry_maxtimeout=120000 \
    npm_config_fetch_retry_mintimeout=20000

RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=cache,target=/root/.npm \
    python3 -m venv /opt/planm \
    && /opt/planm/bin/pip install . \
    && npm --prefix agents/runtimes/gitagent ci --prefer-offline --no-audit \
    && npm --prefix agents/runtimes/gitagent run build \
    && test -f agents/runtimes/gitagent/dist/exports.js \
    && npm --prefix external/dwg-intelligence ci --prefer-offline --no-audit \
    && npm --prefix external/dwg-intelligence run build:parser \
    && npm --prefix external/dwg-intelligence run build:cad-io-host

ENV PATH="/opt/planm/bin:${PATH}" \
    PLANM_REPOSITORY_ROOT=/app \
    PLANM_RUNS_ROOT=/data/planm-runs \
    PYTHONUNBUFFERED=1

RUN mkdir -p /data/planm-runs

EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
