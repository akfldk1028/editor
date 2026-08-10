FROM node:22-alpine AS build

WORKDIR /app
RUN npm install --global npm@11.6.2
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./frontend/
COPY external/dwg-intelligence/apps/workspace/package.json ./external/dwg-intelligence/apps/workspace/package.json
COPY external/dwg-intelligence/apps/workspace/src/ ./external/dwg-intelligence/apps/workspace/src/
COPY external/dwg-intelligence/packages/contracts/package.json ./external/dwg-intelligence/packages/contracts/package.json
COPY external/dwg-intelligence/packages/contracts/src/ ./external/dwg-intelligence/packages/contracts/src/
RUN npm --prefix frontend ci
COPY frontend/ ./frontend/
RUN npm --prefix frontend run build

FROM nginx:1.27-alpine
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/frontend/dist /usr/share/nginx/html

EXPOSE 80
