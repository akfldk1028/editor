FROM node:22-alpine AS build

WORKDIR /app
RUN npm install --global npm@11.6.2
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./frontend/
COPY agents/dwg/apps/workspace/package.json ./agents/dwg/apps/workspace/package.json
COPY agents/dwg/apps/workspace/src/ ./agents/dwg/apps/workspace/src/
COPY agents/dwg/packages/contracts/package.json ./agents/dwg/packages/contracts/package.json
COPY agents/dwg/packages/contracts/src/ ./agents/dwg/packages/contracts/src/
RUN npm --prefix frontend ci
COPY frontend/ ./frontend/
RUN npm --prefix frontend run build

FROM nginx:1.27-alpine
COPY infra/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/frontend/dist /usr/share/nginx/html

EXPOSE 80
