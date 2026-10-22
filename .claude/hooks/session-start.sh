#!/bin/bash
set -euo pipefail

# Only needed in Claude Code cloud sessions: start Docker and build the test
# image. The embed image (local models, ~10 GB) is built on demand.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"
if ! docker info >/dev/null 2>&1; then
  (dockerd >/tmp/dockerd.log 2>&1 &)
  for _ in $(seq 30); do docker info >/dev/null 2>&1 && break; sleep 1; done
fi
# Build through buildx bake: since Compose v5.6 / buildx 0.38, `docker compose build`
# refuses the host network and CA secret that compose.cloud.yaml needs.
docker buildx bake -f compose.yaml -f .claude/compose.cloud.yaml \
  --allow=network.host --allow=fs.read=/root/.ccr/ca-bundle.crt --load test
