#!/usr/bin/env bash
# Pull the newest published data release onto this host.
#
#   grok-production-update-data.sh            update the live data-root
#   grok-production-update-data.sh --dry-run  do the same work against a throwaway
#                                             copy of data-root and touch nothing live
#
# The dry run is not a shortcut that returns early. It downloads, verifies and
# installs exactly like the real run, just into a copy, so a failure that only
# shows up during install still shows up here.
#
# Nothing live is touched until every archive has been downloaded and its
# SHA-256 matched. If this script dies at any earlier point the running service
# keeps serving the data it already has.
set -uo pipefail

readonly base="${TAIWAN_LAB_PRODUCTION_BASE:-/home/box/taiwan-lab-mcp-production-20260922}"
readonly repo="masalu0105-gif/taiwan-laboratory-mcp"
readonly data_dir="${base}/data-root"
readonly venv_bin="${base}/.venv/bin"
readonly log="${base}/update.log"
readonly status_file="${base}/update-status.txt"
readonly lock_file="${base}/.update.lock"
readonly datasets="nhi_fee tfda_devices cdc_authorized_labs cdc_specimen_manual"

dry_run=0
[ "${1:-}" = "--dry-run" ] && dry_run=1

say() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" >>"$log"; echo "$*"; }

# First line of the status file is OK or 異常, so a glance is enough.
write_status() {
  {
    printf '%s\n' "$1"
    printf '時間：%s\n' "$(date +'%F %T %Z')"
    printf '模式：%s\n' "$([ "$dry_run" = 1 ] && echo '模擬（沒有動到正式資料）' || echo '正式')"
    shift
    printf '%s\n' "$@"
  } >"$status_file"
}

cleanup() {
  [ -n "${tmp_dir:-}" ] && [ -d "$tmp_dir" ] && rm -rf "$tmp_dir"
  [ -n "${copy_dir:-}" ] && [ -d "$copy_dir" ] && rm -rf "$copy_dir"
}
trap cleanup EXIT

exec 9>"$lock_file"
if ! flock -n 9; then
  echo "另一個更新還在跑，這次跳過"
  exit 0
fi

say "=== update_start dry_run=${dry_run} ==="

for cmd in curl jq unzip sha256sum; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    say "找不到指令 $cmd"
    write_status "異常：這台機器上找不到 $cmd" "更新沒有執行，服務中的資料沒有變動。"
    exit 1
  fi
done
if [ ! -x "${venv_bin}/taiwan-lab-data" ]; then
  say "找不到 ${venv_bin}/taiwan-lab-data"
  write_status "異常：找不到 taiwan-lab-data" "更新沒有執行，服務中的資料沒有變動。"
  exit 1
fi

# --- 1. 找出最新的資料版 ---------------------------------------------------
# Anonymous GitHub API calls share a 60/hour budget with every other machine on
# this egress IP, and we saw that budget run out. Prefer the logged-in gh, which
# gets 5000/hour, and keep the anonymous call only as a fallback.
fetch_releases() {
  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    gh api "repos/${repo}/releases?per_page=30" 2>>"$log" && return 0
  fi
  curl -fsSL -m 60 -H 'Accept: application/vnd.github+json' \
    "https://api.github.com/repos/${repo}/releases?per_page=30" 2>>"$log"
}

releases_json=""
for attempt in 1 2 3; do
  releases_json="$(fetch_releases)"
  [ -n "$releases_json" ] && break
  say "版本清單第 ${attempt} 次拿不到，等一下再試"
  sleep $((attempt * 20))
done
if [ -z "$releases_json" ]; then
  remaining="$(curl -s -m 15 https://api.github.com/rate_limit 2>/dev/null \
    | jq -r '.resources.core.remaining // "?"' 2>/dev/null)"
  say "GitHub API 三次都沒有回應 remaining=${remaining}"
  if [ "$remaining" = "0" ]; then
    write_status "異常：GitHub 查詢次數用完了，這次拿不到版本清單" \
      "更新沒有執行，服務中的資料沒有變動。下一輪會自己再試。"
  else
    write_status "異常：連不上 GitHub，拿不到版本清單" \
      "更新沒有執行，服務中的資料沒有變動。"
  fi
  exit 1
fi

tag="$(printf '%s' "$releases_json" \
  | jq -r '[.[] | select(.draft==false) | select(.tag_name | startswith("data-"))]
           | sort_by(.tag_name) | reverse | .[0].tag_name // empty')"
if [ -z "$tag" ]; then
  say "清單裡沒有 data- 開頭的版本"
  write_status "異常：GitHub 上找不到任何資料版" "更新沒有執行，服務中的資料沒有變動。"
  exit 1
fi
say "最新資料版：$tag"

assets_json="$(printf '%s' "$releases_json" | jq -r --arg t "$tag" \
  '.[] | select(.tag_name==$t) | .assets')"

# --- 2. 這一版跟已經裝好的一樣嗎 -------------------------------------------
installed_tag_file="${data_dir}/.installed-release-tag"
installed_tag="$(cat "$installed_tag_file" 2>/dev/null || echo '(未知)')"
say "目前裝的：$installed_tag"
if [ "$installed_tag" = "$tag" ] && [ "$dry_run" = 0 ]; then
  say "已經是最新版，不用動"
  write_status "OK：已經是最新版 $tag" "沒有下載，沒有重啟。"
  exit 0
fi

# --- 3. 下載並核對每一份 ---------------------------------------------------
tmp_dir="$(mktemp -d "${base}/.update-tmp.XXXXXX")"
planned=""
for ds in $datasets; do
  zip_url="$(printf '%s' "$assets_json" | jq -r --arg p "${ds}-snapshot-" \
    'map(select(.name | startswith($p)) | select(.name | endswith(".zip"))) | .[0].browser_download_url // empty')"
  sha_url="$(printf '%s' "$assets_json" | jq -r --arg p "${ds}-snapshot-" \
    'map(select(.name | startswith($p)) | select(.name | endswith(".zip.sha256"))) | .[0].browser_download_url // empty')"
  if [ -z "$zip_url" ] || [ -z "$sha_url" ]; then
    say "$ds：這一版沒有附這份資料，跳過"
    continue
  fi

  zip_path="${tmp_dir}/$(basename "$zip_url")"
  sha_path="${zip_path}.sha256"
  if ! curl -fsSL -m 900 -o "$zip_path" "$zip_url" 2>>"$log"; then
    say "$ds：下載失敗"
    write_status "異常：$ds 下載失敗" "還沒有動到正式資料，服務中的資料沒有變動。"
    exit 1
  fi
  if ! curl -fsSL -m 60 -o "$sha_path" "$sha_url" 2>>"$log"; then
    say "$ds：下載雜湊檔失敗"
    write_status "異常：$ds 的 SHA-256 檔下載失敗" "還沒有動到正式資料，服務中的資料沒有變動。"
    exit 1
  fi

  want="$(awk '{print $1; exit}' "$sha_path")"
  got="$(sha256sum "$zip_path" | awk '{print $1}')"
  if [ -z "$want" ] || [ "$want" != "$got" ]; then
    say "$ds：SHA-256 對不上 want=$want got=$got"
    write_status "異常：$ds 檔案雜湊對不上，可能下載壞了" "還沒有動到正式資料，服務中的資料沒有變動。"
    exit 1
  fi
  say "$ds：下載完成，雜湊相符"
  planned="${planned}${ds}|${zip_path}|${want}"$'\n'
done

if [ -z "$planned" ]; then
  say "沒有任何一份可以裝"
  write_status "異常：這一版 $tag 裡找不到任何一份資料" "更新沒有執行，服務中的資料沒有變動。"
  exit 1
fi

# --- 4. 決定裝到哪裡 -------------------------------------------------------
# 模擬模式對著複本做，走的是同一段安裝程式，不是提早 return。
target="$data_dir"
if [ "$dry_run" = 1 ]; then
  copy_dir="${base}/.data-root-dryrun.$$"
  say "模擬模式：複製一份 data-root 出來（$(du -sh "$data_dir" 2>/dev/null | cut -f1)）"
  if ! cp -a "$data_dir" "$copy_dir"; then
    say "複製失敗"
    write_status "異常：模擬用的複本建不起來" "正式資料沒有被動到。"
    exit 1
  fi
  target="$copy_dir"
fi

# --- 5. 安裝 ---------------------------------------------------------------
installed=0; unchanged=0; failed=0; detail=""
while IFS='|' read -r ds zip_path want; do
  [ -z "$ds" ] && continue
  out="$("${venv_bin}/taiwan-lab-data" install-snapshot "$ds" \
          --bundle "$zip_path" --sha256 "$want" \
          --actor grok-scheduled-update --data-dir "$target" --json 2>&1)"
  rc=$?
  result="$(printf '%s' "$out" | jq -r '.result // empty' 2>/dev/null)"
  if [ "$rc" -ne 0 ] || [ -z "$result" ]; then
    say "$ds：安裝失敗 rc=$rc $out"
    detail="${detail}${ds}：失敗"$'\n'; failed=$((failed+1)); continue
  fi
  case "$result" in
    installed) say "$ds：已換新"; detail="${detail}${ds}：已換新"$'\n'; installed=$((installed+1)) ;;
    already_installed) say "$ds：本來就是這一版"; detail="${detail}${ds}：沒有變動"$'\n'; unchanged=$((unchanged+1)) ;;
    *) say "$ds：回傳 $result"; detail="${detail}${ds}：$result"$'\n'; failed=$((failed+1)) ;;
  esac
done <<<"$planned"

# --- 6. 裝完之後，資料讀得出來嗎 -------------------------------------------
probe="$(TAIWAN_LAB_DATA_MODE=official_snapshot TAIWAN_LAB_DATA_DIR="$target" \
  PYTHONIOENCODING=utf-8 "${venv_bin}/python" - <<'PY' 2>&1
import json, asyncio
from taiwan_lab_mcp import server
r = asyncio.run(server.mcp.call_tool("get_data_status", {}))
d = json.loads(r.content[0].text)
ok = [s["source_id"] for s in d["sources"] if s["availability"] == "available"]
bad = [s["source_id"] for s in d["sources"] if s["availability"] != "available"]
print("AVAILABLE=" + ",".join(ok))
print("UNAVAILABLE=" + ",".join(bad))
for s in d["sources"]:
    print("VER %s %s" % (s["source_id"], s["latest_seen_version"]))
PY
)"
say "讀取測試：$(printf '%s' "$probe" | tr '\n' ' ')"
if ! printf '%s' "$probe" | grep -q "^AVAILABLE="; then
  say "讀取測試沒有跑起來"
  if [ "$dry_run" = 1 ]; then
    write_status "異常：模擬安裝完之後讀不出資料" "正式資料沒有被動到。" "$probe"
  else
    write_status "異常：換版之後讀不出資料，請人工檢查" "服務沒有重啟，仍在跑舊的程式行程。" "$probe"
  fi
  exit 1
fi
if printf '%s' "$probe" | grep -q "^UNAVAILABLE=."; then
  say "有來源變成不可用"
  write_status "異常：換版之後有來源讀不到" "$(printf '%s' "$probe" | grep '^UNAVAILABLE=')"
  exit 1
fi

# --- 7. 模擬到此為止 -------------------------------------------------------
if [ "$dry_run" = 1 ]; then
  say "=== 模擬結束，正式資料完全沒有動到 ==="
  write_status "OK：模擬跑完，可以排上去" \
    "版本 $tag｜換新 ${installed}、沒變動 ${unchanged}、失敗 ${failed}" \
    "$detail" "$probe"
  exit 0
fi

printf '%s\n' "$tag" >"$installed_tag_file"

# --- 8. 真的換了才重啟 -----------------------------------------------------
if [ "$installed" -eq 0 ]; then
  say "沒有任何一份換新，不重啟"
  write_status "OK：$tag 沒有要換的東西" "$detail"
  exit 0
fi

say "重啟服務讓它讀到新資料"
pkill -f "${base}/.venv/bin/taiwan-lab-mcp-http" 2>/dev/null || true
ready=0
for _ in $(seq 1 60); do
  sleep 1
  if ss -ltnH 'sport = :18083' 2>/dev/null | grep -q '127.0.0.1:18083'; then ready=1; break; fi
done
if [ "$ready" -ne 1 ]; then
  say "重啟後 port 沒起來"
  write_status "異常：換版後服務沒起來，請人工檢查" "資料已換成 $tag。" "$(tail -n 20 "${base}/app.log")"
  exit 1
fi

code="$(curl -s -o /dev/null -w '%{http_code}' -m 20 \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"updater","version":"1"}}}' \
  http://127.0.0.1:18083/mcp)"
say "重啟後自我檢查 HTTP $code"
if [ "$code" != "200" ]; then
  write_status "異常：換版後服務回 HTTP $code" "資料已換成 $tag，請人工檢查。"
  exit 1
fi

say "=== update_done tag=$tag installed=$installed ==="
write_status "OK：已更新到 $tag" \
  "換新 ${installed}、沒變動 ${unchanged}、失敗 ${failed}｜服務已重啟，自我檢查 HTTP 200" \
  "$detail" "$probe"
exit 0
