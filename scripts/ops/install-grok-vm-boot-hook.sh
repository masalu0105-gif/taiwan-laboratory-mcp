#!/usr/bin/env bash
set -euo pipefail

readonly source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly hook_source="${source_dir}/grok-vm-boot-selfheal.sh"
readonly hook_target="$HOME/.config/box-boot-selfheal.sh"
readonly vendor_launcher="/usr/local/bin/start-desktop.sh"
readonly recovery_dir="$HOME/.config/box-recovery"
readonly begin_marker="# >>> taiwan-laboratory-mcp boot self-heal >>>"
readonly end_marker="# <<< taiwan-laboratory-mcp boot self-heal <<<"

test -r "$hook_source"
test -f "$vendor_launcher"
mkdir -p "$recovery_dir"
chmod 700 "$recovery_dir"
install -m 700 "$hook_source" "$hook_target"

if ! sudo grep -Fq "$begin_marker" "$vendor_launcher"; then
  backup="${recovery_dir}/start-desktop.sh.before-taiwan-lab"
  if [ ! -f "$backup" ]; then
    sudo cp "$vendor_launcher" "$backup"
    sudo chown "$(id -u):$(id -g)" "$backup"
    chmod 600 "$backup"
  fi

  patch_file="$(mktemp)"
  trap 'rm -f "$patch_file"' EXIT
  awk -v begin="$begin_marker" -v end="$end_marker" '
    /^tail -f \/dev\/null$/ && !inserted {
      print begin
      print "if [ \"${DISPLAY:-:1}\" = \":1\" ] && [ -x \"$HOME/.config/box-boot-selfheal.sh\" ]; then"
      print "\tsetsid nohup \"$HOME/.config/box-boot-selfheal.sh\" >/dev/null 2>&1 &"
      print "fi"
      print end
      print ""
      inserted=1
    }
    { print }
    END { if (!inserted) exit 42 }
  ' "$vendor_launcher" >"$patch_file"
  sudo install -o root -g root -m 755 "$patch_file" "$vendor_launcher"
fi

sudo grep -Fq "$end_marker" "$vendor_launcher"
test -x "$hook_target"
echo "boot_hook=installed"
echo "hook=$hook_target"
echo "launcher=$vendor_launcher"
