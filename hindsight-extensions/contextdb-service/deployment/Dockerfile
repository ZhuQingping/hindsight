# BuildKit is required for dependency download cache mounts.
# Build from THIS repository, never assume an upstream image contains ContextDB.
# For a released build supply approved base digests and SOURCE_REVISION.
ARG NODE_IMAGE=node:24-bookworm-slim
FROM ${NODE_IMAGE} AS builder
ARG SOURCE_REVISION=unreleased
WORKDIR /app
RUN apt-get -o Acquire::http::Timeout=30 -o Acquire::Retries=2 update \
    && apt-get -o Acquire::http::Timeout=30 -o Acquire::Retries=2 install -y --no-install-recommends python3 python3-venv python3-dev gcc g++ ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/build-tools \
    && /opt/build-tools/bin/pip install --no-cache-dir uv==0.9.4
ENV PATH="/opt/build-tools/bin:/app/.venv/bin:${PATH}"
ENV UV_PROJECT_ENVIRONMENT=/app/.venv UV_PYTHON_DOWNLOADS=never HINDSIGHT_API_ENV_FILE=""
COPY pyproject.toml uv.lock package.json package-lock.json ./
COPY hindsight-all/pyproject.toml hindsight-all/README.md ./hindsight-all/
COPY hindsight-api/pyproject.toml hindsight-api/README.md ./hindsight-api/
COPY hindsight-all-slim/pyproject.toml hindsight-all-slim/README.md ./hindsight-all-slim/
COPY hindsight-dev/pyproject.toml hindsight-dev/README.md ./hindsight-dev/
COPY hindsight-clients/python/pyproject.toml hindsight-clients/python/README.md ./hindsight-clients/python/
COPY hindsight-embed/pyproject.toml hindsight-embed/README.md ./hindsight-embed/
COPY hindsight-api-slim ./hindsight-api-slim/
COPY hindsight-clients/typescript ./hindsight-clients/typescript/
COPY hindsight-control-plane ./hindsight-control-plane/
COPY hindsight-extensions/contextdb-service ./hindsight-extensions/contextdb-service/
COPY hindsight-docs/package.json ./hindsight-docs/
COPY hindsight-all-npm/package.json ./hindsight-all-npm/
COPY hindsight-tools/hindsight-agent-sdk/package.json ./hindsight-tools/hindsight-agent-sdk/
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=cache,target=/root/.npm \
    uv sync --frozen --package hindsight-api-slim --no-dev \
    && npm ci --ignore-scripts --include=optional --no-audit --no-fund \
    && npm run build -w @vectorize-io/hindsight-client
ENV PYTHONPATH=/app/hindsight-extensions/contextdb-service:/app/hindsight-api-slim
RUN /app/.venv/bin/python -m hindsight_ext_contextdb build-ui --source-root /app

ARG NODE_IMAGE=node:24-bookworm-slim
FROM ${NODE_IMAGE} AS runtime
ARG SOURCE_REVISION=unreleased
LABEL org.opencontainers.image.revision=${SOURCE_REVISION}
RUN apt-get -o Acquire::http::Timeout=30 -o Acquire::Retries=2 update \
    && apt-get -o Acquire::http::Timeout=30 -o Acquire::Retries=2 install -y --no-install-recommends python3 ca-certificates libgssapi-krb5-2 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home --shell /bin/bash contextdb
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/hindsight-api-slim /app/hindsight-api-slim
COPY --from=builder /app/hindsight-extensions/contextdb-service /app/hindsight-extensions/contextdb-service
COPY --from=builder /app/hindsight-control-plane/src /app/hindsight-control-plane/src
COPY --from=builder /app/hindsight-control-plane/standalone /app/hindsight-control-plane/standalone
COPY --from=builder /app/hindsight-control-plane/package.json /app/hindsight-control-plane/next.config.mjs /app/hindsight-control-plane/
COPY --from=builder /app/hindsight-clients/typescript/src /app/hindsight-clients/typescript/src
COPY --from=builder /app/hindsight-clients/typescript/package.json /app/hindsight-clients/typescript/
COPY --from=builder /app/package-lock.json /app/uv.lock /app/
RUN chmod +x /app/hindsight-extensions/contextdb-service/scripts/*.sh
ENV PATH="/app/.venv/bin:${PATH}" PYTHONUNBUFFERED=1 NODE_ENV=production HINDSIGHT_API_ENV_FILE=""
ENV PYTHONPATH=/app/hindsight-extensions/contextdb-service:/app/hindsight-api-slim
ENV CONTEXTDB_DEPLOY_DIR=/var/lib/contextdb
USER 10001:10001
EXPOSE 8888 9999
ENTRYPOINT ["/bin/bash", "/app/hindsight-extensions/contextdb-service/scripts/service.sh"]
CMD ["api"]
