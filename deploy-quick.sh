#!/bin/bash
# deploy-quick.sh — Fast deploy for code-only changes (no dependency changes)
# Usage:
#   ./deploy-quick.sh              Backend-only changes (~15 seconds)
#   ./deploy-quick.sh --frontend   Backend + frontend rebuild (~2-3 minutes)
#   ./deploy-quick.sh --full       Full Docker rebuild (~5 minutes, for dependency changes)

set -e

SERVER="ubuntu@13.206.34.214"
KEY="$HOME/.ssh/jsl-wealth-key.pem"
CONTAINER="client-portal"
APP_DIR="/home/ubuntu/apps/client-portal"
MODE="${1:---backend}"

echo "=== Pushing to git ==="
git push origin main 2>/dev/null || true

if [ "$MODE" = "--full" ]; then
  echo "=== FULL Docker rebuild ==="
  ssh -i "$KEY" "$SERVER" "
    cd $APP_DIR && git pull origin main &&
    docker build -t client-portal . &&
    docker rm -f $CONTAINER &&
    docker run -d --name $CONTAINER --env-file .env -p 8007:3000 --restart unless-stopped client-portal &&
    sleep 12 && curl -sf http://localhost:8007/api/health
  "
  echo "=== Full deploy complete ==="
  exit 0
fi

echo "=== Quick deploy ($MODE) ==="
ssh -i "$KEY" "$SERVER" "
  cd $APP_DIR && git pull origin main

  # Always copy backend into running container
  docker cp $APP_DIR/backend/. $CONTAINER:/app/backend/
  echo '[+] Backend copied'
"

if [ "$MODE" = "--frontend" ]; then
  echo "=== Rebuilding frontend inside container ==="
  ssh -i "$KEY" "$SERVER" "
    # Copy frontend source files
    docker cp $APP_DIR/frontend/src/. $CONTAINER:/app/frontend/src/
    docker cp $APP_DIR/frontend/public/. $CONTAINER:/app/frontend/public/

    # Rebuild Next.js inside the container
    docker exec $CONTAINER bash -c 'cd /app/frontend && npx next build' 2>&1 | tail -5
    echo '[+] Frontend rebuilt'
  "
fi

echo "=== Restarting container ==="
ssh -i "$KEY" "$SERVER" "
  docker restart $CONTAINER
  sleep 10
  curl -sf http://localhost:8007/api/health && echo ' [+] Healthy' || echo ' [-] Health check failed, waiting...'
  sleep 5
  curl -sf http://localhost:8007/api/health && echo ' [+] Healthy'
"
echo "=== Deploy complete ==="
