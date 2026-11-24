#!/usr/bin/env bash
set -euo pipefail

smoke_log="$(mktemp)"
backend_pid=""
smoke_port="${MAGE_MED_SMOKE_PORT:-18000}"
smoke_url="http://127.0.0.1:${smoke_port}"

cleanup() {
  if [[ -n "${backend_pid}" ]]; then
    kill "${backend_pid}" 2>/dev/null || true
    wait "${backend_pid}" 2>/dev/null || true
  fi
  rm -f "${smoke_log}"
}
trap cleanup EXIT

uv run uvicorn mage_med_backend.main:app \
  --host 127.0.0.1 \
  --port "${smoke_port}" \
  --no-access-log >"${smoke_log}" 2>&1 &
backend_pid="$!"

backend_live=0
for _ in $(seq 1 30); do
  if curl --fail --silent "${smoke_url}/api/v1/health/live" >/dev/null; then
    backend_live=1
    break
  fi
  sleep 0.5
done

if [[ "${backend_live}" -ne 1 ]]; then
  echo "Backend failed to become live" >&2
  sed -n '1,120p' "${smoke_log}" >&2
  exit 1
fi

MAGE_MED_BACKEND_URL="${smoke_url}" \
  npm --workspace @mage-med/frontend run test:smoke

MAGE_MED_RUN_NEO4J_SMOKE=1 \
  uv run pytest -m neo4j_smoke \
    tests/smoke/test_backend_neo4j.py \
    services/knowledge_graph/tests/test_repository_live.py \
    apps/backend/tests/test_graph_sync_live.py
