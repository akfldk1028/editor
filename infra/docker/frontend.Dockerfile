FROM node:22-alpine AS build

WORKDIR /app
RUN npm install --global npm@11.6.2
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./frontend/
COPY infra/services/dwg/apps/workspace/package.json ./infra/services/dwg/apps/workspace/package.json
COPY infra/services/dwg/apps/workspace/src/ ./infra/services/dwg/apps/workspace/src/
COPY infra/services/dwg/packages/contracts/package.json ./infra/services/dwg/packages/contracts/package.json
COPY infra/services/dwg/packages/contracts/src/ ./infra/services/dwg/packages/contracts/src/
RUN npm --prefix frontend ci
COPY frontend/ ./frontend/
RUN npm --prefix frontend run build

FROM nginx:1.27-alpine
COPY infra/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/frontend/dist /usr/share/nginx/html

EXPOSE 80
