#!/usr/bin/env bash
set -euo pipefail

readonly base="${TAIWAN_LAB_PRODUCTION_BASE:-/home/box/taiwan-lab-mcp-production-20260922}"
readonly log="${base}/app.log"

rotate_log() {
  if [ -f "$log" ] && [ "$(stat -c %s "$log")" -gt 20971520 ]; then
    tail -c 5242880 "$log" >"${log}.next"
    mv "${log}.next" "$log"
  fi
}

while true; do
  rotate_log
  printf '%s app_start\n' "$(date -u +%FT%TZ)" >>"$log"
  set +e
  env \
    PYTHONUNBUFFERED=1 \
    TAIWAN_LAB_DATA_MODE=official_snapshot \
    TAIWAN_LAB_DATA_DIR="${base}/data-root" \
    TAIWAN_LAB_HTTP_HOST=127.0.0.1 \
    TAIWAN_LAB_HTTP_PORT=18083 \
    TAIWAN_LAB_HTTP_PATH=/mcp \
    TAIWAN_LAB_HTTP_ALLOWED_HOSTS=grok-bot-box.tail6cbb55.ts.net,grok-bot-box.tail6cbb55.ts.net:443,127.0.0.1:18083,localhost:18083 \
    TAIWAN_LAB_HTTP_RATE_LIMIT_PER_MINUTE=240 \
    TAIWAN_LAB_HTTP_MAX_REQUEST_BYTES=262144 \
    "${base}/.venv/bin/taiwan-lab-mcp-http" >>"$log" 2>&1
  exit_code=$?
  set -e
  printf '%s app_exit=%s restart_in=3s\n' "$(date -u +%FT%TZ)" "$exit_code" >>"$log"
  sleep 3
done
