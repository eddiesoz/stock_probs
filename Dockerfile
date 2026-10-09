ARG SOURCE_DATE_EPOCH=1757894400
# Legacy `docker build` lacks BuildKit's automatic platform args; BuildKit overrides these
# defaults and production builds use the requested target architecture.
ARG BUILDPLATFORM=linux/amd64
ARG TARGETARCH=amd64
ARG BUILDARCH=amd64

FROM --platform=linux/amd64 ghcr.io/anomalyco/opencode:2.0.7@sha256:d2c7ddda8142b47942426972fcee07f56ecde762ac7f528c5e53c2f957aabc05 AS opencode-amd64
FROM --platform=linux/arm64 ghcr.io/anomalyco/opencode:2.0.7@sha256:396bd94fe43d392fd7b12e3ec83d80c0e527715936bfcf6f9120a4385e541e42 AS opencode-arm64

# These source stages contain no RUN commands, so cross-arch extraction never executes foreign code.
FROM --platform=$BUILDPLATFORM python:3.11.15-slim@sha256:90744cff8f32887f075c47d747a173ff333e9e98801667af93c357fa9f5e28ff AS opencode-assets
ARG TARGETARCH
RUN mkdir -p /assets/amd64/lib /assets/amd64/usr/lib \
    /assets/arm64/lib /assets/arm64/usr/lib
COPY --from=opencode-amd64 /lib/ld-musl-x86_64.so.1 /assets/amd64/lib/ld-musl-x86_64.so.1
COPY --from=opencode-amd64 /lib/libc.musl-x86_64.so.1 /assets/amd64/lib/libc.musl-x86_64.so.1
COPY --from=opencode-amd64 /usr/lib/libgcc_s.so.1 /assets/amd64/usr/lib/libgcc_s.so.1
COPY --from=opencode-amd64 /usr/lib/libstdc++.so.6 /assets/amd64/usr/lib/libstdc++.so.6
COPY --from=opencode-amd64 /usr/lib/libstdc++.so.6.0.34 /assets/amd64/usr/lib/libstdc++.so.6.0.34
COPY --from=opencode-arm64 /lib/ld-musl-aarch64.so.1 /assets/arm64/lib/ld-musl-aarch64.so.1
COPY --from=opencode-arm64 /lib/libc.musl-aarch64.so.1 /assets/arm64/lib/libc.musl-aarch64.so.1
COPY --from=opencode-arm64 /usr/lib/libgcc_s.so.1 /assets/arm64/usr/lib/libgcc_s.so.1
COPY --from=opencode-arm64 /usr/lib/libstdc++.so.6 /assets/arm64/usr/lib/libstdc++.so.6
COPY --from=opencode-arm64 /usr/lib/libstdc++.so.6.0.34 /assets/arm64/usr/lib/libstdc++.so.6.0.34
RUN mkdir -p /out && case "$TARGETARCH" in \
      amd64) cp -a /assets/amd64/. /out/ ;; \
      arm64) cp -a /assets/arm64/. /out/ ;; \
      *) echo "unsupported target architecture" >&2; exit 1 ;; \
    esac

# Compile the fixed, checksum-pinned V2.0.7 source patch outside the runtime image.
FROM --platform=$BUILDPLATFORM python:3.11.15-slim@sha256:90744cff8f32887f075c47d747a173ff333e9e98801667af93c357fa9f5e28ff AS opencode-patched-builder
ARG TARGETARCH
ARG BUILDARCH
WORKDIR /build
COPY tools/opencode-v2-security-patch/ /patch/
RUN install --directory --owner=0 --group=0 --mode=0700 /build-tmp
ENV TMPDIR=/build-tmp
RUN python /patch/build_native.py \
    --target-arch "$TARGETARCH" \
    --build-arch "$BUILDARCH" \
    --output /out

FROM node:22.19.0-bookworm-slim@sha256:4a4884e8a44826194dff92ba316264f392056cbe243dcc9fd3551e71cea02b90 AS frontend-builder
ARG SOURCE_DATE_EPOCH

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
ENV NODE_OPTIONS=--max-old-space-size=512
COPY frontend/ ./
# Frontend contract tests inspect the legacy dashboard and shared theme initializer.
COPY src/stock_probs/static/app.js src/stock_probs/static/theme.js /build/src/stock_probs/static/
RUN npm run typecheck && npm run build && npm run test -- --test-concurrency=1
RUN mkdir -p /static-next/tools \
    && cp out/index.html out/api-docs.html out/overview.html out/research.html out/tools.html \
       out/sign-in.html out/invite.html out/passkey.html out/authenticator.html out/account.html out/admin.html /static-next/ \
    && cp out/tools/forecast.html out/tools/live-trading.html out/tools/markets.html /static-next/tools/ \
    && cp -R out/_next /static-next/

# Build wheels separately so Node, compilers, and package indexes are absent from runtime.
FROM python:3.11.15-slim@sha256:90744cff8f32887f075c47d747a173ff333e9e98801667af93c357fa9f5e28ff AS builder
ARG SOURCE_DATE_EPOCH

WORKDIR /build
COPY pyproject.toml requirements.lock ./
COPY src ./src
COPY --from=frontend-builder /static-next ./src/stock_probs/static/next
RUN python -m pip wheel \
    --wheel-dir /wheels \
    --constraint requirements.lock \
    . \
    && python -m pip install \
        --root /install \
        --prefix /usr/local \
        --no-cache-dir \
        --no-compile \
        --no-index \
        --find-links=/wheels \
        stock-probs==0.1.0 \
    && find /install -exec touch --no-dereference --date="@${SOURCE_DATE_EPOCH}" {} +

FROM python:3.11.15-slim@sha256:90744cff8f32887f075c47d747a173ff333e9e98801667af93c357fa9f5e28ff
ARG SOURCE_DATE_EPOCH
ARG REVISION

LABEL org.opencontainers.image.source="https://github.com/eddiesoz/stock_probs" \
      org.opencontainers.image.revision="${REVISION}"

ENV HOME=/tmp \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STOCK_PROBS_DATA_DIR=/data

# Runtime does not install packages; remove base-image package managers and build tooling.
RUN python -m pip uninstall --yes setuptools wheel pip
COPY --from=builder /install /
# Debian's /lib is a /usr/lib symlink, so merge both asset trees into the real directory.
COPY --from=opencode-assets /out/lib/ /usr/lib/
COPY --from=opencode-assets /out/usr/lib/ /usr/lib/
RUN install --directory --owner=10001 --group=10001 --mode=0700 /data \
    && install --directory --mode=0755 /usr/local/share/stock-probs \
    && install --directory --owner=10002 --group=10002 --mode=0700 /run/assistant-worker-home \
    && touch --date="@${SOURCE_DATE_EPOCH}" / /data
COPY --from=opencode-patched-builder /out/opencode /usr/local/bin/opencode
COPY --from=opencode-patched-builder /out/build.json /usr/local/share/stock-probs/opencode-build.json
COPY --from=opencode-patched-builder /out/opencode-LICENSE /usr/local/share/stock-probs/opencode-LICENSE
RUN chown root:root /usr/local/bin/opencode /usr/local/share/stock-probs/opencode-build.json \
        /usr/local/share/stock-probs/opencode-LICENSE \
    && chmod 0755 /usr/local/bin/opencode \
    && chmod 0444 /usr/local/share/stock-probs/opencode-build.json \
        /usr/local/share/stock-probs/opencode-LICENSE

USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3).close()"]
# The broad in-container listener is reachable only through Compose's loopback-only publication.
ENTRYPOINT ["python", "-m", "stock_probs.container_supervisor"]
# Non-root local/dev runs bypass PID 1 supervision; production Compose supplies root with only
# SETUID/SETGID so the fixed supervisor can drop the two child identities.
CMD ["serve", "--host", "0.0.0.0", "--port", "8000", "--allow-non-loopback"]
