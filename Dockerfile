FROM node:22.19.0-bookworm-slim@sha256:4a4884e8a44826194dff92ba316264f392056cbe243dcc9fd3551e71cea02b90 AS frontend-builder

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run typecheck && npm run build && npm run test
RUN mkdir /static-next \
    && cp out/index.html out/api-docs.html /static-next/ \
    && cp -R out/_next /static-next/

# Build wheels separately so Node, compilers, and package indexes are absent from runtime.
FROM python:3.11.15-slim@sha256:90744cff8f32887f075c47d747a173ff333e9e98801667af93c357fa9f5e28ff AS builder

WORKDIR /build
COPY pyproject.toml requirements.lock ./
COPY src ./src
COPY --from=frontend-builder /static-next ./src/stock_probs/static/next
RUN python -m pip wheel \
    --wheel-dir /wheels \
    --constraint requirements.lock \
    .

FROM python:3.11.15-slim@sha256:90744cff8f32887f075c47d747a173ff333e9e98801667af93c357fa9f5e28ff

ENV HOME=/tmp \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STOCK_PROBS_DATA_DIR=/data

COPY --from=builder /wheels /wheels
RUN python -m pip install \
    --no-cache-dir \
    --no-index \
    --find-links=/wheels \
    stock-probs==0.1.0 \
    && rm -rf /wheels \
    && groupadd --system --gid 10001 stockprobs \
    && useradd --system --uid 10001 --gid stockprobs --home-dir /nonexistent \
        --shell /usr/sbin/nologin stockprobs \
    && install --directory --owner=stockprobs --group=stockprobs --mode=0700 /data

USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3).close()"]
# The broad in-container listener is reachable only through Compose's loopback-only publication.
CMD ["stock-probs", "serve", "--host", "0.0.0.0", "--port", "8000", "--allow-non-loopback"]
