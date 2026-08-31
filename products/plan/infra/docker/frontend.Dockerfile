FROM node:22-alpine AS build

WORKDIR /app
RUN npm install --global npm@11.6.2
COPY products/plan/frontend/package.json products/plan/frontend/package-lock.json products/plan/frontend/.npmrc ./products/plan/frontend/
COPY products/dwg/apps/workspace/package.json ./products/dwg/apps/workspace/package.json
COPY products/dwg/apps/workspace/src/ ./products/dwg/apps/workspace/src/
COPY products/dwg/packages/contracts/package.json ./products/dwg/packages/contracts/package.json
COPY products/dwg/packages/contracts/src/ ./products/dwg/packages/contracts/src/
RUN npm --prefix products/plan/frontend ci
COPY products/plan/frontend/ ./products/plan/frontend/
RUN npm --prefix products/plan/frontend run build

FROM nginx:1.27-alpine
COPY infra/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/products/plan/frontend/dist /usr/share/nginx/html

EXPOSE 80
