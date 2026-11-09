# Katha Studio: Production Deployment Guide

> **Operations Runbook for Docker Compose, AWS, GCP, and Cloud Platforms**

---

## 1. Quickstart: Local & On-Premise Docker Compose

### Prerequisites
- Docker Engine $\ge 24.0$ & Docker Compose v2.
- At least 4GB of available RAM and 10GB of disk space.

### Steps
1. **Clone and Configure**:
   ```bash
   git clone https://github.com/your-username/katha-studio.git
   cd katha-studio
   cp .env.example .env
   ```
2. **Set Security Keys & Credentials**:
   ```bash
   # Generate secure JWT secret key
   openssl rand -hex 32
   ```
   Edit `.env` and paste into `SECRET_KEY`. Set `LLM_DEFAULT_PROVIDER` (`gemini`, `groq`, or `mock`) and your respective API keys.

3. **Start the Complete Stack**:
   ```bash
   make docker-up
   # Or directly:
   docker compose up -d --build
   ```

4. **Verify Container Health**:
   ```bash
   docker compose ps
   ```
   - **Frontend UI**: [http://localhost:5173](http://localhost:5173)
   - **Backend API & Swagger Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
   - **Health Endpoint**: [http://localhost:8000/health](http://localhost:8000/health)

---

## 2. Production Docker Compose (`docker-compose.prod.yml`)

For dedicated Linux VM deployments (e.g. Ubuntu 22.04 LTS on AWS EC2, GCP Compute Engine, or DigitalOcean):

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

### Production Optimizations Applied:
- **Internal Database Isolation**: PostgreSQL and Redis ports are not exposed to the host; communication occurs strictly across internal Docker overlay networks.
- **Persistent Volume Mounts**: PostgreSQL data (`pgdata`), Redis data (`redisdata`), and Audio Master MP3 cache (`audio_cache_data`) survive container rebuilds.
- **Hardened Nginx**: Implements gzip compression, asset caching headers, and `proxy_buffering off` for uninterrupted Server-Sent Events (SSE).
- **Non-Root Containers**: Backend runs under unprivileged `katha` user (`uid 1000`).

---

## 3. Cloud Native Deployment Architecture

### A. Google Cloud Platform (Recommended for Gemini Integration)
- **Frontend & Backend**: Deployed as serverless containers on **Cloud Run** (with execution timeouts set to $300\text{s}$ for audio stitching).
- **Database**: **Cloud SQL for PostgreSQL 16** with the `pgvector` database flag enabled.
- **Cache & Event Bus**: **Memorystore for Redis**.
- **Audio Storage**: Google Cloud Storage (GCS) mounted via Cloud Run volume or S3-compatible client.
- **Secrets**: Managed via **GCP Secret Manager**.

### B. Amazon Web Services (AWS)
- **Compute**: **AWS ECS Fargate** behind an Application Load Balancer (ALB).
- **Database**: **Amazon RDS for PostgreSQL 16** with `CREATE EXTENSION IF NOT EXISTS vector;`.
- **Cache**: **Amazon ElastiCache for Redis**.
- **Audio Assets**: **Amazon S3** with **CloudFront** CDN distribution for high-speed master audio streaming.

---

## 4. Production Security Checklist

- [ ] **Secret Key**: Unique 256-bit random string generated via `openssl rand -hex 32`.
- [ ] **Database Credentials**: Strong random database password; no default `katha_secret`.
- [ ] **TLS / HTTPS**: Configured via Let's Encrypt / Certbot or Cloud Load Balancer SSL termination.
- [ ] **CORS Settings**: Restrict `allow_origins` in `app/main.py` to production domain.
- [ ] **Rate Limiting**: Nginx or API Gateway rate-limiting applied to `/api/v1/generation/*` and `/api/v1/auth/*`.
- [ ] **Data Loss Prevention**: Automated daily snapshots of PostgreSQL database.

