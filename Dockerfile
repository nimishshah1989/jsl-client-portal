# ============================================================
# JSL Client Portfolio Portal — Multi-stage Dockerfile
# Stage 1: Build Next.js frontend
# Stage 2: Python runtime with FastAPI + built frontend
# ============================================================

# --- Stage 1: Frontend build ---
FROM node:20-slim AS frontend

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --ignore-scripts
COPY frontend/ ./

# Cache-bust: changes on every commit to ensure fresh builds
ARG CACHEBUST=1
RUN npm run build

# --- Stage 2: Runtime ---
FROM python:3.11-slim

# Install Node.js for Next.js runtime
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Backend source
COPY backend/ ./backend/

# Frontend: copy entire build stage output (includes .next, node_modules, config)
COPY --from=frontend /app/frontend ./frontend/

# Scripts for data ingestion
COPY scripts/ ./scripts/

# Data directory (mount or copy data files here)
RUN mkdir -p /app/data

# Startup script
COPY start.sh ./
RUN chmod +x start.sh

# Download AWS RDS CA bundle for TLS verification (C2)
RUN apt-get update -q && apt-get install -y -q --no-install-recommends wget ca-certificates \
    && wget -q https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem \
         -O /app/rds-combined-ca-bundle.pem \
    && apt-get purge -y wget && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Non-root user (C16)
RUN useradd -r -s /bin/false -u 1001 appuser \
    && mkdir -p /app/data/uploads \
    && chown -R appuser:appuser /app
USER appuser

# Next.js on 3000 (frontend), FastAPI on 8000 (API)
# Nginx routes /api/* to 8000 directly, bypassing Next.js body size limit
EXPOSE 3000 8000

CMD ["./start.sh"]
