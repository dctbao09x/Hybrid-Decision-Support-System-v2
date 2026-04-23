#!/bin/bash
# deploy_server.sh
# =================
# Production deployment script for Linux
# Uses Gunicorn with UvicornWorker
#
# Usage:
#   ./scripts/deploy_server.sh [workers] [port]
#   ./scripts/deploy_server.sh 8 8000
#

set -e

WORKERS=${1:-8}
PORT=${2:-8000}
HOST=${3:-0.0.0.0}
TIMEOUT=${4:-30}

echo "============================================================"
echo "HDSS API SERVER DEPLOYMENT (Linux)"
echo "============================================================"

# Set environment
export ENVIRONMENT=production
export HTTP_MAX_CONNECTIONS=200
export HTTP_MAX_PER_HOST=50
export HTTP_KEEPALIVE=30
export DB_POOL_SIZE=20
export DB_MAX_OVERFLOW=30

echo ""
echo "[Config]"
echo "  Workers: $WORKERS"
echo "  Host: $HOST:$PORT"
echo "  Timeout: ${TIMEOUT}s"

# Check for gunicorn
if ! command -v gunicorn &> /dev/null; then
    echo "[Warning] Gunicorn not found, installing..."
    pip install gunicorn
fi

# Kill existing processes on port
echo ""
echo "[Cleanup] Stopping existing processes on port $PORT..."
fuser -k $PORT/tcp 2>/dev/null || true
sleep 2

# Change to project root
cd "$(dirname "$0")/.."

echo ""
echo "[Starting] Gunicorn with $WORKERS workers..."
echo ""

# Start with gunicorn config
exec gunicorn \
    --config config/gunicorn.conf.py \
    --bind "$HOST:$PORT" \
    --workers $WORKERS \
    --timeout $TIMEOUT \
    backend.run_api:app

# Alternative: Direct uvicorn multi-worker (if gunicorn fails)
# exec python -m uvicorn \
#     backend.run_api:app \
#     --host $HOST \
#     --port $PORT \
#     --workers $WORKERS \
#     --timeout-keep-alive $TIMEOUT \
#     --log-level info
