#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="finally"
CONTAINER_NAME="finally-app"
BUILD=false

if [[ "${1:-}" == "--build" ]]; then
  BUILD=true
fi

if [[ "$BUILD" == true ]] || ! docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
  docker build -t "$IMAGE_NAME" .
fi

if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
  docker rm -f "$CONTAINER_NAME" >/dev/null
fi

docker run -d \
  --name "$CONTAINER_NAME" \
  -p 8000:8000 \
  -v "$(pwd)/db:/app/db" \
  --env-file .env \
  "$IMAGE_NAME"

echo "FinAlly running at http://localhost:8000"
