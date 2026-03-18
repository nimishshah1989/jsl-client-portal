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

# Next.js listens on 3000 inside container, mapped to 8007 externally
EXPOSE 3000

CMD ["./start.sh"]
