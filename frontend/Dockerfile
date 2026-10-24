FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# unprivileged nginx (listens on 8080, runs as a non-root user). *.template files are rendered with the container's environment at start-up.
FROM nginxinc/nginx-unprivileged:1.27-alpine
ENV BACKEND_HOSTPORT=backend:8000 NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1 TRUSTED_PROXY_CIDR=127.0.0.1/32
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY proxy_common.conf /etc/nginx/proxy_common.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
