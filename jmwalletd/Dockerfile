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
# Always built for amd64: the output is static JS that runs in the browser,
# so the build platform doesn't matter. node:24-slim has no linux/arm/v7 image.
# =============================================================================
FROM --platform=linux/amd64 node:24-slim AS jam-builder
ARG JAM_VERSION

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 --branch ${JAM_VERSION} \
    https://github.com/joinmarket-webui/jam.git /app

WORKDIR /app
RUN npm ci && npm run build

# =============================================================================
# Stage 4: jam-ng — self-contained: jmwalletd + JAM frontend + Tor + obwatcher
# Managed by s6-overlay for multi-process supervision
# =============================================================================
FROM jmwalletd AS jam-ng

# s6-overlay version (pinned for reproducibility)
ARG S6_OVERLAY_VERSION=3.2.0.2

# Install xz-utils (for extracting s6-overlay), wget (for downloading s6-overlay), and Tor daemon
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    xz-utils \
    tor \
    && rm -rf /var/lib/apt/lists/*

# Install s6-overlay (noarch + arch-specific, checksums pinned)
# noarch tarball is the same for all platforms
ADD --checksum=sha256:6dbcde158a3e78b9bb141d7bcb5ccb421e563523babbe2c64470e76f4fd02dae \
    https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-noarch.tar.xz /tmp
# Arch-specific tarball: select based on TARGETARCH/TARGETVARIANT at build time
ARG TARGETARCH
ARG TARGETVARIANT
RUN set -eux; \
    case "${TARGETARCH}/${TARGETVARIANT:-}" in \
        amd64/)   S6_ARCH=x86_64;  S6_SHA256=59289456ab1761e277bd456a95e737c06b03ede99158beb24f12b165a904f478 ;; \
        arm64/)   S6_ARCH=aarch64; S6_SHA256=8b22a2eaca4bf0b27a43d36e65c89d2701738f628d1abd0cea5569619f66f785 ;; \
        arm/v7)   S6_ARCH=armhf;   S6_SHA256=c8b8532fe4ec432898960e9ec9c903926454ce73588d4c94ad0e023f0b34fe39 ;; \
        *) echo "Unsupported platform: ${TARGETARCH}/${TARGETVARIANT:-}" >&2; exit 1 ;; \
    esac; \
    wget -qO /tmp/s6-overlay-arch.tar.xz \
        "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-${S6_ARCH}.tar.xz"; \
    echo "${S6_SHA256}  /tmp/s6-overlay-arch.tar.xz" | sha256sum -c -; \
    tar -C / -Jxpf /tmp/s6-overlay-noarch.tar.xz; \
    tar -C / -Jxpf /tmp/s6-overlay-arch.tar.xz; \
    rm -f /tmp/s6-overlay-*.tar.xz

# Copy s6 service definitions and torrc
COPY jmwalletd/rootfs/ /

# Ensure run scripts are executable
RUN chmod +x /etc/s6-overlay/s6-rc.d/tor/run \
    && chmod +x /etc/s6-overlay/s6-rc.d/tor-ready/up \
    && chmod +x /etc/s6-overlay/s6-rc.d/obwatcher/run \
    && chmod +x /etc/s6-overlay/s6-rc.d/jmwalletd-svc/run

# Tor data directory (writable at runtime)
RUN mkdir -p /var/lib/tor && chown root:root /var/lib/tor && chmod 700 /var/lib/tor

# Copy JAM frontend
COPY --from=jam-builder /app/dist /usr/share/jmwalletd/jam

# Default env: point services at the local Tor and obwatcher
ENV TOR__SOCKS_HOST=127.0.0.1
ENV TOR__SOCKS_PORT=9050
ENV TOR__CONTROL_HOST=127.0.0.1
ENV TOR__CONTROL_PORT=9051
ENV OBWATCH_URL=http://127.0.0.1:8000

# s6-overlay init replaces tini as PID 1
ENTRYPOINT ["/init"]
# No CMD — s6-overlay starts all services via s6-rc
