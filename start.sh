#!/bin/bash
# ============================================================
# JSL Client Portfolio Portal — Process Startup
# Runs Next.js (port 3000) and FastAPI (port 8000) in parallel.
# Next.js proxies /api/* requests to FastAPI internally.
# ============================================================

set -e

echo "[CPP] Starting FastAPI on port 8000..."
cd /app
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 2 &
FASTAPI_PID=$!

echo "[CPP] Starting Next.js on port 3000..."
cd /app/frontend
echo "[CPP] Frontend dir contents:"
ls -la /app/frontend/.next/ 2>/dev/null | head -10 || echo "[CPP] WARNING: .next directory NOT FOUND"
ls -la /app/frontend/.next/server/app/ 2>/dev/null | head -10 || echo "[CPP] WARNING: .next/server/app/ NOT FOUND"
npx next start -p 3000 &
NEXTJS_PID=$!

echo "[CPP] FastAPI PID: $FASTAPI_PID | Next.js PID: $NEXTJS_PID"

# Wait for either process to exit — if one dies, the container should stop
wait -n $FASTAPI_PID $NEXTJS_PID
EXIT_CODE=$?

echo "[CPP] A process exited with code $EXIT_CODE. Shutting down..."
kill $FASTAPI_PID $NEXTJS_PID 2>/dev/null || true
exit $EXIT_CODE
