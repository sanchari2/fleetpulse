# syntax=docker/dockerfile:1.7
# Multi-stage: dependencies are resolved once on the native build platform with
# a BuildKit pip cache, then only the runtime files are copied into the final
# image. Building linux/amd64 and linux/arm64 therefore costs one small layer
# per architecture, not a full pip install under emulation.
ARG PYTHON_VERSION=3.12

FROM --platform=$BUILDPLATFORM python:${PYTHON_VERSION}-slim AS builder
WORKDIR /build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore
COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --prefix=/install -r requirements.txt

FROM python:${PYTHON_VERSION}-slim AS runtime
ARG APP_VERSION=0.0.0-dev
ARG VCS_REF=unknown
ARG BUILD_DATE=unknown

LABEL org.opencontainers.image.title="fleetpulse" \
      org.opencontainers.image.description="Telemetry service for a simulated drone fleet" \
      org.opencontainers.image.source="https://github.com/OWNER/fleetpulse" \
      org.opencontainers.image.url="https://github.com/OWNER/fleetpulse" \
      org.opencontainers.image.documentation="https://github.com/OWNER/fleetpulse#readme" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    APP_VERSION=${APP_VERSION} \
    PORT=8000

# The python:3.12-slim tag is rebuilt only when upstream publishes it, so its
# Debian packages lag the point release. Pull the current security fixes in
# here; without this the Trivy gate fails on packages Debian has already
# patched (zlib1g was the first one to bite).
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get -y upgrade \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10001 fleetpulse \
 && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin fleetpulse

COPY --from=builder /install /usr/local
WORKDIR /app
COPY --chown=10001:10001 src ./src

# non-root, no shell, nothing writable outside /tmp
USER 10001:10001
EXPOSE 8000

# Kubernetes probes are authoritative; this keeps `docker run` users honest too.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"

CMD ["uvicorn", "fleetpulse.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-server-header"]
