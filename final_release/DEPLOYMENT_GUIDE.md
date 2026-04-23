# Deployment Guide
## Hybrid Decision Support System - Production Deployment

**Version:** 1.2.0  
**Generated:** 2026-01-15  
**Status:** Production Ready

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Environment Setup](#environment-setup)
3. [Configuration](#configuration)
4. [Deployment Steps](#deployment-steps)
5. [Verification](#verification)
6. [Rollback](#rollback)
7. [Monitoring](#monitoring)

---

## Prerequisites

### System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| Python | 3.11+ | 3.12 |
| RAM | 8 GB | 16 GB |
| CPU | 4 cores | 8 cores |
| Storage | 50 GB | 100 GB SSD |
| OS | Ubuntu 22.04 / Windows Server 2022 | Ubuntu 22.04 LTS |

### Dependencies

```bash
# Python packages
pip install -r requirements.txt
pip install -r requirements_data_pipeline.txt

# Optional: ML dependencies
pip install -r backend/requirements_api.txt
```

---

## Environment Setup

### 1. Clone Repository

```bash
git clone <repository-url>
cd "Hybrid Decision Support System"
```

### 2. Virtual Environment

```bash
# Create virtual environment
python -m venv venv

# Activate (Linux/Mac)
source venv/bin/activate

# Activate (Windows)
.\venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

---

## Configuration

### Environment Variables

Create `.env` file in project root:

```bash
# Server Configuration
HOST=0.0.0.0
PORT=8000
DEBUG=false
LOG_LEVEL=INFO

# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/hdss

# Redis Cache
REDIS_URL=redis://localhost:6379/0

# Authentication
JWT_SECRET_KEY=<your-secret-key>
JWT_ALGORITHM=HS256
JWT_EXPIRATION=3600

# ML Models
MODEL_PATH=./models
MODEL_VERSION=latest

# Feature Flags
ENABLE_KILLSWITCH=true
ENABLE_MARKET_INTEL=true
ENABLE_XAI=true
```

### Configuration Files

| File | Purpose |
|------|---------|
| `config/settings.yaml` | Main application settings |
| `config/auth_config.yaml` | Authentication configuration |
| `config/services.yaml` | Service registry configuration |
| `config/logging.yaml` | Logging configuration |

---

## Deployment Steps

### Step 1: Pre-Deployment Checks

```bash
# Run controller enforcement tests
python tests/test_controller_enforcement.py

# Verify all routers registered
python -c "from backend.api.router_registry import get_all_routers; print(len(get_all_routers()))"

# Expected: 20+ routers
```

### Step 2: Database Migration

```bash
# Run migrations
alembic upgrade head

# Verify migrations
alembic current
```

### Step 3: Cache Warmup

```bash
# Warm up caches
python scripts/warmup_caches.py
```

### Step 4: Start Application

#### Development
```bash
uvicorn backend.run_api:app --host 0.0.0.0 --port 8000 --reload
```

#### Production (Gunicorn + Uvicorn)
```bash
gunicorn backend.run_api:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
```

#### Docker
```bash
docker-compose up -d
```

### Step 5: Post-Deployment Verification

```bash
# Health check
curl http://localhost:8000/api/v1/health

# API docs
curl http://localhost:8000/docs
```

---

## Verification

### Health Endpoints

| Endpoint | Expected Response |
|----------|-------------------|
| `GET /api/v1/health` | `{"status": "healthy"}` |
| `GET /api/v1/health/ready` | `{"ready": true}` |
| `GET /api/v1/health/live` | `{"live": true}` |

### Smoke Tests

```bash
# Run smoke tests
pytest tests/smoke/ -v

# Check route count
curl http://localhost:8000/api/v1/ops/routes | jq '.total_routes'
# Expected: 190+
```

### Route Validation

```bash
# Verify all routers loaded
curl -s http://localhost:8000/openapi.json | jq '.paths | keys | length'
# Expected: 50+
```

---

## Rollback

### Quick Rollback

```bash
# Stop current deployment
docker-compose down

# Roll back to previous version
git checkout <previous-tag>

# Restart
docker-compose up -d
```

### Database Rollback

```bash
# Roll back last migration
alembic downgrade -1

# Roll back to specific revision
alembic downgrade <revision-id>
```

---

## Monitoring

### Metrics Endpoints

| Endpoint | Description |
|----------|-------------|
| `/api/v1/ops/metrics` | Prometheus metrics |
| `/api/v1/ops/health` | Detailed health |
| `/api/v1/ops/config` | Runtime config |

### Key Metrics

| Metric | Alert Threshold |
|--------|-----------------|
| `request_latency_p99` | > 500ms |
| `error_rate_5m` | > 1% |
| `memory_usage` | > 80% |
| `cpu_usage` | > 70% |

### Logging

```bash
# View application logs
tail -f logs/app.log

# View error logs
tail -f logs/error.log

# JSON logs for aggregation
tail -f logs/json.log | jq .
```

---

## Scaling

### Horizontal Scaling

```yaml
# docker-compose.scale.yml
services:
  api:
    image: hdss:latest
    deploy:
      replicas: 4
      resources:
        limits:
          cpus: '2'
          memory: 4G
```

### Load Balancer Configuration

```nginx
upstream hdss_api {
    least_conn;
    server api1:8000;
    server api2:8000;
    server api3:8000;
    server api4:8000;
}

server {
    listen 80;
    location / {
        proxy_pass http://hdss_api;
    }
}
```

---

## Security Checklist

- [ ] JWT_SECRET_KEY is unique and secure
- [ ] DEBUG=false in production
- [ ] HTTPS enabled
- [ ] Rate limiting configured
- [ ] CORS properly restricted
- [ ] Admin routes protected
- [ ] Kill-switch accessible only to admins
- [ ] Audit logging enabled

---

## Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| Router not found | Check router_registry.py imports |
| 401 Unauthorized | Verify JWT configuration |
| 500 on dispatch | Check MainController handlers |
| Slow startup | Reduce eager imports |

### Debug Mode

```bash
# Enable debug logging
LOG_LEVEL=DEBUG uvicorn backend.run_api:app --reload
```

---

*Deployment documentation maintained by DevOps Team*
