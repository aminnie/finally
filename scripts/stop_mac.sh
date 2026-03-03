#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="finally-app"
if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
  docker rm -f "$CONTAINER_NAME" >/dev/null
  echo "Stopped $CONTAINER_NAME"
else
  echo "$CONTAINER_NAME not running"
fi
