# syntax=docker/dockerfile:1.7
# =============================================================================
# Ollama Web Search - Single Container Build
# =============================================================================
# Builds frontend and backend into a single container for simplified deployment.
# Usage:
#   docker build -t ollama-web-search .
#   docker run -p 8080:8080 ollama-web-search
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1: Build Frontend
# -----------------------------------------------------------------------------
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend_rebuild

# Copy package files first for better layer caching
COPY frontend_rebuild/package*.json ./
RUN npm ci

# Copy frontend source and build
COPY frontend_rebuild/ ./
ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN npm run build

# -----------------------------------------------------------------------------
# Stage 2: Backend with Static Files
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/requirements.txt

# Copy backend application
COPY backend/main.py /app/main.py

# Copy frontend build output
COPY --from=frontend-builder /app/frontend_rebuild/dist /app/static

# Create data directory for persistence
RUN mkdir -p /data

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=20s --timeout=5s --retries=5 --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)" || exit 1

# Run the server
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
