# =========================================================================
# Stage 1: Build modern offline-first frontend assets
# =========================================================================
FROM node:20-alpine AS frontend-builder

WORKDIR /build

COPY package.json package-lock.json ./
RUN npm ci

COPY frontend/ ./frontend/
COPY vite.config.mjs ./
RUN npm run build

# =========================================================================
# Stage 2: Production runtime image
# =========================================================================
FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

LABEL org.opencontainers.image.source="https://github.com/fr0styx/zettnas-toolkit"
LABEL org.opencontainers.image.description="ZettNAS Toolkit: Hardware telemetry, custom fan curves, ARGB lightbar, and LCD dashboard"
LABEL net.unraid.docker.managed="dockerman"
LABEL net.unraid.docker.webui="http://[IP]:[PORT:8082]/"
LABEL net.unraid.docker.icon="https://raw.githubusercontent.com/fr0styx/zettnas-toolkit/main/static/img/icon.png"
LABEL net.unraid.docker.shell="bash"

RUN apt-get update && apt-get install -y --no-install-recommends \
    smartmontools \
    apcupsd \
    udev \
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
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt
RUN playwright install chromium

# Copy Python backend application
COPY app.py .
COPY backend/ ./backend/
COPY static/ ./static/

# Overlay freshly built frontend distribution
COPY --from=frontend-builder /build/static/ ./static/

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python3 -c 'import urllib.request, sys, os; port = os.environ.get("PORT", "8082"); sys.exit(0 if urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=4).getcode() == 200 else 1)'

CMD ["python3", "-m", "backend.main"]
