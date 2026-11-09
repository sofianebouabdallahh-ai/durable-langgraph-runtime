# syntax=docker/dockerfile:1
# The web UI: built with Node, served by unprivileged nginx, which also proxies
# /api to the API replicas (one origin: no CORS). Base images pinned by digest.
ARG NODE_IMAGE=node:24.20.0-trixie-slim@sha256:50c3b2f6988dfc307b86e5301d69611af31f4789bdf232863b07d3b02fe55ae0
ARG NGINX_IMAGE=nginxinc/nginx-unprivileged:1.30.6-alpine3.24@sha256:782bb89768cc87b7f95c18b95baa1af250e5d451f26794f59363540161147c01

FROM ${NODE_IMAGE} AS build
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0 CI=true
WORKDIR /app
RUN corepack enable
# Dependencies first: a cached layer that changes only with the lockfile.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
RUN --mount=type=cache,id=pnpm-store,target=/pnpm/store \
    pnpm install --frozen-lockfile --store-dir /pnpm/store
COPY . .
RUN pnpm build

FROM ${NGINX_IMAGE}
# The base is pinned by digest; Alpine's security fixes published since are applied
# here (e.g. libexpat CVE-2026-77214), and the Trivy gate checks the result.
USER root
RUN apk upgrade --no-cache
USER 101
# Runs as nginx (UID 101); listens on 8080; temp files, the pid and the rendered
# config in /tmp (a tmpfs in Compose, an emptyDir in Kubernetes), so the root
# filesystem can be read-only. The config is a template (resolver, API address).
ENV NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1 \
    NGINX_ENVSUBST_OUTPUT_DIR=/tmp \
    NGINX_ENVSUBST_FILTER="^(NGINX_LOCAL_RESOLVERS|API_UPSTREAM|UI_HOSTNAMES)$" \
    API_UPSTREAM=api:8000 \
    UI_HOSTNAMES=""
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY nginx/include-rendered.conf /etc/nginx/conf.d/default.conf
COPY nginx/security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY nginx/api-proxy.conf /etc/nginx/snippets/api-proxy.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
