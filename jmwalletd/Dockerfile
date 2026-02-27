# =============================================================================
# Global build args (must be before first FROM)
# Base image digests for reproducible builds
# Update with: ./scripts/update-base-images.sh
# =============================================================================
ARG PYTHON_VERSION=3.14
ARG PYTHON_SLIM_DIGEST=sha256:9006fc63e3eaedc00ebc81193c99528575a2f9b9e3fb36d95e94814c23f31f47

# JAM frontend version to pull from GitHub (used only by jam-ng target)
ARG JAM_VERSION=v2

# =============================================================================
# Stage 1: Build Python environment
# =============================================================================
FROM python:${PYTHON_VERSION}-slim@${PYTHON_SLIM_DIGEST} AS builder
WORKDIR /app

# build-essential + cmake + pkg-config needed to compile coincurve (no wheels for 3.14 yet)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    pkg-config \
    libffi-dev \
    libsodium-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY . /app/

RUN pip install --no-cache-dir \
    ./jmcore \
    ./jmwallet \
    ./maker \
    ./taker \
    ./orderbook_watcher \
    ./jmwalletd

# =============================================================================
# Stage 2: jmwalletd — standalone API daemon (default target)
# =============================================================================
FROM python:${PYTHON_VERSION}-slim@${PYTHON_SLIM_DIGEST} AS jmwalletd
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    tini \
    libsodium23 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN mkdir -p /root/.joinmarket-ng

ENV PYTHONUNBUFFERED=1
ENV JOINMARKET_DATA_DIR=/root/.joinmarket-ng
ENV JMWALLETD_HOST=0.0.0.0

EXPOSE 28183

ENTRYPOINT ["tini", "--"]
CMD ["jmwalletd", "--no-tls"]

# =============================================================================
# Stage 3: Build JAM frontend (cloned from GitHub, no submodule required)
# =============================================================================
FROM node:24-slim AS jam-builder
ARG JAM_VERSION

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 --branch ${JAM_VERSION} \
    https://github.com/joinmarket-webui/jam.git /app

WORKDIR /app
RUN npm ci && npm run build

# =============================================================================
# Stage 4: jam-ng — jmwalletd bundled with JAM frontend
# =============================================================================
FROM jmwalletd AS jam-ng

COPY --from=jam-builder /app/dist /usr/share/jmwalletd/jam
