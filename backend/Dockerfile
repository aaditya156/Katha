FROM python:3.12-slim

WORKDIR /app

# Install system dependencies: build tools, libpq for Postgres, ffmpeg for audio stitching, curl for healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Setup audio cache and non-root application user
RUN mkdir -p /app/audio_cache && \
    chmod +x /app/entrypoint.sh && \
    adduser --disabled-password --gecos "" katha && \
    chown -R katha:katha /app

USER katha

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
