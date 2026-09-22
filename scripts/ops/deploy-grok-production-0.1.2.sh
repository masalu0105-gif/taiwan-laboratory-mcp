#!/usr/bin/env bash
set -euo pipefail

readonly base="/home/box/taiwan-lab-mcp-production-20260922"
readonly backup="/home/box/taiwan-lab-mcp-backups/20260922-pre-0.1.2"
readonly wheel="${base}/taiwan_laboratory_mcp-0.1.2-py3-none-any.whl"
readonly supervisor_next="${base}/grok-production-supervise-app.sh.next"

test -f "$wheel"
test -f "$supervisor_next"
chmod 700 "$supervisor_next"
bash -n "$supervisor_next"

/usr/local/bin/uv pip install \
  --python "${base}/.venv/bin/python" \
  --reinstall-package taiwan-laboratory-mcp \
  "$wheel"

mkdir -p "$backup"
cp -p \
  "${base}/grok-production-supervise-app.sh" \
  "${backup}/grok-production-supervise-app.sh.0.1.1"
mv "$supervisor_next" "${base}/grok-production-supervise-app.sh"
chmod 700 "${base}/grok-production-supervise-app.sh"

tmux kill-session -t taiwan-lab-production-app 2>/dev/null || true
tmux new-session -d -s taiwan-lab-production-app \
  "${base}/grok-production-supervise-app.sh"

if [ -d "${base}/candidates" ]; then
  mv "${base}/candidates" "$backup/candidates"
fi
if [ -f "${base}/box-selfheal-production.sh.candidate" ]; then
  mv "${base}/box-selfheal-production.sh.candidate" "$backup/"
fi
if [ -f "${base}/taiwan_laboratory_mcp-0.1.1-py3-none-any.whl" ]; then
  mv "${base}/taiwan_laboratory_mcp-0.1.1-py3-none-any.whl" "$backup/"
fi

sleep 4
"${base}/.venv/bin/python" -c \
  'import taiwan_lab_mcp; print(taiwan_lab_mcp.__version__)'
sha256sum "$wheel"
ss -ltnp | grep ':18083'
tmux has-session -t taiwan-lab-production-app
