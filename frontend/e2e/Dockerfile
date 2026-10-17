# syntax=docker/dockerfile:1
# The browser tests' runner: Playwright with its browsers, plus the Docker CLI so a
# test can kill or stop a container mid-reply (the socket is mounted by `make ui-e2e`;
# this image is for tests only and never published).
ARG PLAYWRIGHT_IMAGE=mcr.microsoft.com/playwright:v1.63.0-noble@sha256:eff16c30e6f3f4af0a03fa4b706120d5e9b0891c344a27d64559aff5900a4a27
ARG DOCKER_CLI_IMAGE=docker:29.8.1-cli@sha256:018edbc908e08fcc9dbf029c812c34251e9b4719e6f71ca0e5eae2a987d014ca

FROM ${DOCKER_CLI_IMAGE} AS docker

FROM ${PLAYWRIGHT_IMAGE}
COPY --from=docker /usr/local/bin/docker /usr/local/bin/docker
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0 CI=true
WORKDIR /e2e
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN --mount=type=cache,id=pnpm-store-e2e,target=/pnpm/store pnpm install --frozen-lockfile --store-dir /pnpm/store
COPY playwright.config.ts ./
COPY tests ./tests
ENTRYPOINT ["pnpm", "exec", "playwright", "test"]
