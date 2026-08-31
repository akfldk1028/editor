FROM node:22-bookworm-slim AS node-runtime

FROM mcr.microsoft.com/dotnet/sdk:9.0-bookworm-slim

COPY --from=node-runtime /usr/local/ /usr/local/

WORKDIR /dwg
COPY products/dwg/ ./

RUN npm ci --prefer-offline --no-audit \
    && npm run build:parser \
    && npm run build:cad-io-host

ENV DWG_WORKSPACE=/data/planm-runs \
    DWG_DRAWING_PATH=_seed/default.dwg \
    DWG_EXPORT_ROOT=/data/dwg-exports \
    DWG_GATEWAY_HOST=0.0.0.0 \
    DWG_GATEWAY_PORT=4317 \
    DWG_HOST_DIALOGS=off

# Keep the seed drawing outside DWG_WORKSPACE. A named volume mounted over that
# workspace is only populated from the image when the volume is empty, so a
# build-time copy into it silently disappears on every existing installation.
RUN mkdir -p /dwg/seed \
    && cp tests/fixtures/dwg/export_sample.dwg /dwg/seed/default.dwg

EXPOSE 4317

# Seed the workspace at start, after the volume is mounted, so the gateway always
# finds its default drawing regardless of the volume's prior contents.
CMD ["sh", "-c", "set -e; mkdir -p \"$DWG_EXPORT_ROOT\" \"$DWG_WORKSPACE/$(dirname \"$DWG_DRAWING_PATH\")\"; [ -f \"$DWG_WORKSPACE/$DWG_DRAWING_PATH\" ] || cp /dwg/seed/default.dwg \"$DWG_WORKSPACE/$DWG_DRAWING_PATH\"; exec npm run gateway"]
