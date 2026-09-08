FROM node:22-alpine AS build

WORKDIR /app
RUN npm install --global npm@11.6.2
COPY frontend/app/planm/package.json frontend/app/planm/package-lock.json frontend/app/planm/.npmrc ./frontend/
COPY infra/services/dwg/apps/workspace/package.json ./infra/services/dwg/apps/workspace/package.json
COPY infra/services/dwg/apps/workspace/src/ ./infra/services/dwg/apps/workspace/src/
COPY infra/services/dwg/packages/contracts/package.json ./infra/services/dwg/packages/contracts/package.json
COPY infra/services/dwg/packages/contracts/src/ ./infra/services/dwg/packages/contracts/src/
RUN npm --prefix frontend ci
COPY frontend/app/planm/ ./frontend/
RUN npm --prefix frontend run build

FROM nginx:1.27-alpine
COPY infra/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/frontend/dist /usr/share/nginx/html

EXPOSE 80
