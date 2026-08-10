FROM node:22-bookworm-slim AS node-runtime

FROM mcr.microsoft.com/dotnet/sdk:9.0-bookworm-slim

COPY --from=node-runtime /usr/local/ /usr/local/

WORKDIR /dwg
COPY agents/dwg/ ./

RUN npm ci --prefer-offline --no-audit \
    && npm run build:parser \
    && npm run build:cad-io-host

ENV DWG_WORKSPACE=/data/planm-runs \
    DWG_DRAWING_PATH=_seed/default.dwg \
    DWG_EXPORT_ROOT=/data/dwg-exports \
    DWG_GATEWAY_HOST=0.0.0.0 \
    DWG_GATEWAY_PORT=4317 \
    DWG_HOST_DIALOGS=off

RUN mkdir -p /data/planm-runs/_seed /data/dwg-exports \
    && cp tests/fixtures/dwg/export_sample.dwg /data/planm-runs/_seed/default.dwg

EXPOSE 4317
CMD ["npm", "run", "gateway"]
