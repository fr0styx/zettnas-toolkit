# =========================================================================
# Stage 1: Build modern offline-first frontend assets
# =========================================================================
# Base images are pinned by digest (OPS-19); Dependabot proposes updates.
# Node.js 26.12.1: the October 2026 security release (Brotli decoder CVE-2026-111497). Keep in step with .nvmrc.
FROM --platform=$BUILDPLATFORM node:26.12.1-alpine@sha256:40cd011b55415bc894e45b02fdd5a5dfde056921b7d23a64c74f80497af48797 AS frontend-builder

WORKDIR /build

COPY package.json package-lock.json ./
RUN npm ci

COPY frontend/ ./frontend/
COPY vite.config.mjs ./
RUN npm run build

# =========================================================================
# Stage 2: Production runtime image
# =========================================================================
FROM python:3.12-slim@sha256:cb33f7f771ecec2ef1225cf39b159591a040391bd73e4c01f00fdfc4c47611d2

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

LABEL org.opencontainers.image.source="https://github.com/fr0styx/zettnas-toolkit"
LABEL org.opencontainers.image.description="ZettNAS Toolkit: Hardware telemetry, custom fan curves, ARGB lightbar, and LCD dashboard"
LABEL net.unraid.docker.managed="dockerman"
LABEL net.unraid.docker.webui="http://[IP]:[PORT:8082]/"
LABEL net.unraid.docker.icon="https://raw.githubusercontent.com/fr0styx/zettnas-toolkit/main/static/img/icon.png"
LABEL net.unraid.docker.shell="bash"

# Core: disks, SMART, UPS, USB and cloud remotes (OPS-11)
RUN apt-get update && apt-get install -y --no-install-recommends \
    smartmontools \
    nvme-cli \
    apcupsd \
    udev \
    sg3-utils \
    usbutils \
    rclone \
    fuse3 \
    && rm -rf /var/lib/apt/lists/*

# Multi-arch Playwright support (linux/amd64 and linux/arm64)
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
ENV PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium

WORKDIR /app

COPY requirements.txt requirements.lock requirements-dev.txt ./
ARG DEV_BUILD=0
RUN --mount=type=cache,target=/root/.cache/pip pip install --require-hashes -r requirements.lock \
    && if [ "$DEV_BUILD" = "1" ]; then pip install -r requirements-dev.txt; fi

# Intel Quick Sync for converting videos browsers can't play (iPhone HEVC): the VA-API
# driver and the oneVPL GPU runtime. Used only when /dev/dri is passed to the container.
ARG TARGETARCH
RUN if [ "$TARGETARCH" = "amd64" ]; then \
      sed -i "s/^Components: main$/Components: main contrib non-free non-free-firmware/" /etc/apt/sources.list.d/debian.sources \
      && apt-get update && apt-get install -y --no-install-recommends intel-media-va-driver-non-free libmfx-gen1.2 libvpl2 \
      && rm -rf /var/lib/apt/lists/*; \
    fi

# Playwright (LCD renderer) ships its own Node.js, which lags behind security releases.
# Replace it with the patched official build so no vulnerable copy stays in the image.
COPY --from=node:26.12.1-trixie-slim@sha256:36793bcbb160a6a16cede1e62b93f84e26b78a972a8a4c0b879c1c12f22761ec /usr/local/bin/node /usr/local/lib/python3.12/site-packages/playwright/driver/node

# VARIANT=full (default) adds virtual machines (QEMU, OVMF, swtpm) and the front
# LCD renderer (headless Chromium and fonts). VARIANT=core leaves them out: a
# smaller image for servers without the LCD that don't run VMs. Published as
# the -core tags (latest-core, edge-core, …).
ARG VARIANT=full
ENV ZETTNAS_IMAGE_VARIANT=${VARIANT}
RUN if [ "$VARIANT" = "full" ]; then \
    apt-get update && apt-get install -y --no-install-recommends \
        qemu-system-x86 \
        qemu-system-arm \
        qemu-utils \
        ovmf \
        swtpm \
        qemu-system-modules-spice \
        qemu-system-modules-opengl \
        libslirp0 \
        chromium \
        chromium-sandbox \
        libnss3 \
        libnspr4 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libcups2 \
        libdrm2 \
        libxkbcommon0 \
        libxcomposite1 \
        libxdamage1 \
        libxfixes3 \
        libxrandr2 \
        libgbm1 \
        libpango-1.0-0 \
        libcairo2 \
        libasound2 \
        libgl1-mesa-dri \
        mesa-va-drivers \
        fonts-liberation \
        fonts-noto-cjk \
        fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*; \
    elif [ "$VARIANT" != "core" ]; then echo "VARIANT must be full or core" >&2; exit 1; fi

# Build metadata arguments injected by CI
ARG BUILD_COMMIT=""
ARG BUILD_DATE=""
ENV BUILD_COMMIT=${BUILD_COMMIT}
ENV BUILD_DATE=${BUILD_DATE}

# Copy Python backend application
COPY pyproject.toml .
COPY app.py .
COPY backend/ ./backend/
COPY static/ ./static/

# Persist build commit into filesystem for non-Docker-socket runtime inspection
RUN if [ -n "$BUILD_COMMIT" ]; then echo "$BUILD_COMMIT" > /app/.git_commit; fi

# Overlay freshly built frontend distribution
COPY --from=frontend-builder /build/static/ ./static/

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python3 -c 'import urllib.request, sys, os; port = os.environ.get("PORT", "8082"); sys.exit(0 if urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=4).getcode() == 200 else 1)'

CMD ["python3", "-m", "backend.main"]
