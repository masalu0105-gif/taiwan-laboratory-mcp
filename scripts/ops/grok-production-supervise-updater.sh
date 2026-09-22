#!/usr/bin/env bash
# Daily wake-up for the data update, run inside tmux.
#
# This host has no cron and no systemd (PID 1 is tini), so the schedule is a
# sleep loop kept alive by tmux, the same shape as the app supervisor next to it.
# grok-production-start.sh starts this session, and the boot self-heal hook calls
# that script, so the loop comes back after the machine restarts.
#
# 10:30 Asia/Taipei, one hour after the maintainer's own machine does its 09:30
# official-version check and publishes the release this script pulls.
set -uo pipefail

readonly base="${TAIWAN_LAB_PRODUCTION_BASE:-/home/box/taiwan-lab-mcp-production-20260922}"
readonly updater="${base}/grok-production-update-data.sh"
readonly log="${base}/update.log"
readonly run_at="${TAIWAN_LAB_UPDATE_AT:-10:30}"
readonly tz="${TAIWAN_LAB_UPDATE_TZ:-Asia/Taipei}"

note() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" >>"$log"; }

rotate_log() {
  if [ -f "$log" ] && [ "$(stat -c %s "$log")" -gt 10485760 ]; then
    tail -c 2097152 "$log" >"${log}.next"
    mv "${log}.next" "$log"
  fi
}

seconds_until_run() {
  local now target
  now="$(TZ="$tz" date +%s)"
  target="$(TZ="$tz" date -d "today ${run_at}" +%s 2>/dev/null)" || return 1
  if [ "$target" -le "$now" ]; then
    target="$(TZ="$tz" date -d "tomorrow ${run_at}" +%s)"
  fi
  echo $((target - now))
}

note "updater_loop_start run_at=${run_at} ${tz}"

while true; do
  rotate_log
  wait_for="$(seconds_until_run)" || wait_for=86400
  note "updater_sleeping seconds=${wait_for} next=$(TZ="$tz" date -d "@$(( $(date +%s) + wait_for ))" +'%F %T %Z')"
  sleep "$wait_for"

  if [ -x "$updater" ]; then
    note "updater_run_start"
    "$updater" >>"$log" 2>&1
    note "updater_run_exit=$?"
  else
    note "updater_missing path=${updater}"
  fi

  # Don't let a fast failure spin the loop back onto the same minute.
  sleep 90
done
