#!/usr/bin/env bash
set -u

# Grok Bot containers use tini/pod-daemon instead of systemd. The vendor desktop launcher starts
# on every container boot, and calls this small user-owned hook. flock keeps the primary and any
# extra desktop from racing each other.
readonly lock_file="$HOME/.config/box-boot-selfheal.lock"
readonly log_file="$HOME/.config/box-boot-selfheal.log"
readonly selfheal="$HOME/.config/box-selfheal.sh"

mkdir -p "$HOME/.config"
exec 9>"$lock_file"
flock -n 9 || exit 0

printf '%s boot_selfheal_start\n' "$(date -u +%FT%TZ)" >>"$log_file"
sleep 10

for attempt in 1 2 3 4 5 6; do
  if [ -x "$selfheal" ] && "$selfheal" >>"$log_file" 2>&1; then
    printf '%s boot_selfheal_ok attempt=%s\n' "$(date -u +%FT%TZ)" "$attempt" >>"$log_file"
    exit 0
  fi
  printf '%s boot_selfheal_retry attempt=%s\n' "$(date -u +%FT%TZ)" "$attempt" >>"$log_file"
  sleep 10
done

printf '%s boot_selfheal_failed\n' "$(date -u +%FT%TZ)" >>"$log_file"
exit 1
