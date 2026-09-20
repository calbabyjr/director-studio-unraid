#!/usr/bin/env bash
set -euo pipefail

DATA="${DS_DATA_DIR:-/data}"
mkdir -p \
  "$DATA/jobs" \
  "$DATA/library" \
  "$DATA/projects" \
  "$DATA/logs" \
  "$DATA/harness-sessions" \
  "$DATA/workflow_profiles"

if [[ "${DS_DIRECTOR_AGENT_RUNTIME:-legacy}" == "harness" ]]; then
  export DS_HARNESS_MANAGED=false
  if [[ -z "${DS_HARNESS_INTERNAL_TOKEN:-}" ]]; then
    DS_HARNESS_INTERNAL_TOKEN="$(python -c 'import secrets; print(secrets.token_hex(32))')"
    export DS_HARNESS_INTERNAL_TOKEN
  fi
  export DS_HARNESS_BASE_URL="${DS_HARNESS_BASE_URL:-http://127.0.0.1:8791}"
  HARNESS_PORT="$(python - <<'PY'
from urllib.parse import urlsplit
import os
print(urlsplit(os.environ["DS_HARNESS_BASE_URL"]).port or 8791)
PY
)"
  echo "Starting Director Studio Harness sidecar on 127.0.0.1:${HARNESS_PORT}"
  DS_HARNESS_PORT="$HARNESS_PORT" \
  DS_HARNESS_INTERNAL_TOKEN="$DS_HARNESS_INTERNAL_TOKEN" \
  DS_HARNESS_SESSION_ROOT="$DATA/harness-sessions" \
  DS_HARNESS_PARENT_PID="$$" \
    node /app/harness/dist/server.js >>"$DATA/logs/harness-sidecar.log" 2>&1 &
fi

cd /app/backend
echo "Director Studio listening on ${DS_HOST:-0.0.0.0}:${DS_PORT:-8790}"
echo "ComfyUI: ${DS_COMFY_BASE_URL:-http://127.0.0.1:8188}"
echo "Ollama:  ${DS_OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
exec python -m uvicorn app.main:app \
  --host "${DS_HOST:-0.0.0.0}" \
  --port "${DS_PORT:-8790}" \
  --proxy-headers
