# ── Build stage ───────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

# Copy project config and package source directories
COPY pyproject.toml ./
COPY agent/ ./agent/
COPY ingest/ ./ingest/

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

# ── Runtime stage ─────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY . .

# Cloud Run sets PORT; default to 8080
ENV PORT=8080

EXPOSE ${PORT}

# Run with uvicorn — Cloud Run sends SIGTERM for graceful shutdown
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
