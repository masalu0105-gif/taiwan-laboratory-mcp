#!/usr/bin/env bash
# 一鍵安裝 Taiwan Laboratory MCP（macOS）：裝查詢工具、下載官方資料包、設定 Claude 桌面版。
#
# 做的事跟 docs/install.md 的第 1 到 5 步一樣，只是不用自己打指令。重跑一次是安全的。
#
#   ./install-taiwan-lab-mcp.sh                                  四種資料全裝
#   ./install-taiwan-lab-mcp.sh --datasets nhi_fee,cdc_specimen_manual
#   ./install-taiwan-lab-mcp.sh --data-dir ~/lab --tag data-20260917
#   ./install-taiwan-lab-mcp.sh --skip-claude-config
#
# 注意：本專案的 macOS 支援目前只由 GitHub 的自動測試驗證過，這支腳本還沒有在實體 Mac 上
# 完整跑過。遇到問題請回報 https://github.com/masalu0105-gif/taiwan-laboratory-mcp/issues

set -euo pipefail

REPOSITORY='masalu0105-gif/taiwan-laboratory-mcp'
ACTOR='macos-installer'
ALL_DATASETS='nhi_fee tfda_devices cdc_authorized_labs cdc_specimen_manual'

DATA_DIR="$HOME/taiwan-lab-data"
CONFIG_PATH="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
DATASETS="$ALL_DATASETS"
TAG=''
SKIP_CLAUDE_CONFIG=0
SKIP_TOOL_INSTALL=0

dataset_name() {
    case "$1" in
        nhi_fee) printf '健保支付標準' ;;
        tfda_devices) printf '食藥署醫療器材許可證' ;;
        cdc_authorized_labs) printf '疾管署傳染病認可檢驗機構名冊' ;;
        cdc_specimen_manual) printf '疾管署傳染病檢體採檢手冊' ;;
        *) printf '%s' "$1" ;;
    esac
}

step() { printf '\n>> %s\n' "$1"; }
ok() { printf '   OK  %s\n' "$1"; }
info() { printf '       %s\n' "$1"; }

stop_with_advice() {
    printf '\n安裝停下來了：%s\n' "$1" >&2
    [ -n "${2:-}" ] && printf '怎麼辦：%s\n' "$2" >&2
    printf '還是不行的話，把上面整段訊息貼到 https://github.com/%s/issues 回報。\n' "$REPOSITORY" >&2
    exit 1
}

while [ $# -gt 0 ]; do
    case "$1" in
        --data-dir) DATA_DIR="$2"; shift 2 ;;
        --datasets) DATASETS="$(printf '%s' "$2" | tr ',' ' ')"; shift 2 ;;
        --tag) TAG="$2"; shift 2 ;;
        --config-path) CONFIG_PATH="$2"; shift 2 ;;
        --skip-claude-config) SKIP_CLAUDE_CONFIG=1; shift ;;
        --skip-tool-install) SKIP_TOOL_INSTALL=1; shift ;;
        -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
        *) stop_with_advice "不認得這個選項：$1" '用 --help 看可以填什麼。' ;;
    esac
done

for dataset in $DATASETS; do
    case " $ALL_DATASETS " in
        *" $dataset "*) ;;
        *) stop_with_advice "不認得這種資料：$dataset" "--datasets 只能填這四個名稱：$(printf '%s' "$ALL_DATASETS" | tr ' ' '、')。" ;;
    esac
done
[ -n "$DATASETS" ] || stop_with_advice '沒有指定要裝哪種資料' '把 --datasets 拿掉就會四種全裝。'

echo '=========================================================='
echo ' Taiwan Laboratory MCP 安裝程式'
echo ' 查健保支付標準、食藥署醫材許可證與疾管署檢驗資料'
echo '=========================================================='
echo '這不是健保署、食藥署或疾管署的官方服務，內容以三個機關的公告為準。'

# ------------------------------------------------------------------ 第 1 步：uv
step '第 1 步：檢查 uv（幫忙準備 Python 的小程式）'
find_uv() {
    if command -v uv >/dev/null 2>&1; then command -v uv; return; fi
    # uv 裝好後這個 session 的 PATH 還沒更新，所以直接找它的預設位置。
    [ -x "$HOME/.local/bin/uv" ] && printf '%s' "$HOME/.local/bin/uv"
}
UV="$(find_uv || true)"
if [ -n "$UV" ]; then
    ok "已經有 uv：$UV"
else
    info '沒有找到 uv，現在自動安裝（只裝在你的使用者資料夾，不需要管理員密碼）。'
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 \
        || stop_with_advice '自動安裝 uv 失敗' '開一個新的終端機視窗，貼上 curl -LsSf https://astral.sh/uv/install.sh | sh，裝完再跑一次這支腳本。'
    UV="$(find_uv || true)"
    [ -n "$UV" ] || stop_with_advice 'uv 裝完之後還是找不到' '關掉終端機重新開一個，再跑一次這支腳本。'
    ok "uv 裝好了：$UV"
fi

# --------------------------------------------------------- 第 2 步：找出要裝的版本
step '第 2 步：查 GitHub 上的版本'
if [ -n "$TAG" ]; then
    RELEASE_URI="https://api.github.com/repos/$REPOSITORY/releases/tags/$TAG"
else
    RELEASE_URI="https://api.github.com/repos/$REPOSITORY/releases/latest"
fi
RELEASE_JSON="$(curl -fsSL "$RELEASE_URI")" \
    || stop_with_advice '連不上 GitHub 或找不到版本' "確認網路正常；有指定 --tag 的話，到 https://github.com/$REPOSITORY/releases 確認標籤名稱拼對了。"
TAG="$(printf '%s' "$RELEASE_JSON" | grep '"tag_name"' | head -1 | cut -d'"' -f4)"
[ -n "$TAG" ] || stop_with_advice '讀不出版本編號' "到 https://github.com/$REPOSITORY/releases 看有沒有已發布的版本。"
ok "要裝的版本：$TAG"

# ------------------------------------------------------------- 第 3 步：裝查詢工具
step '第 3 步：安裝查詢工具'
if [ "$SKIP_TOOL_INSTALL" -eq 1 ]; then
    info '跳過（你指定了 --skip-tool-install）。'
else
    info '第一次安裝要下載 Python，可能要等一兩分鐘。'
    "$UV" tool install --force "https://github.com/$REPOSITORY/archive/refs/tags/$TAG.zip" \
        || stop_with_advice 'uv tool install 失敗（錯誤訊息在上面）' '網路不穩可以再跑一次；持續失敗就把上面的訊息回報。'
fi

# uv 通常把工具放在 ~/.local/bin，但使用者可以改，所以直接問它。
BIN_DIR="$("$UV" tool dir --bin 2>/dev/null | head -1 || true)"
[ -d "${BIN_DIR:-}" ] || BIN_DIR="$HOME/.local/bin"
MCP_EXE="$BIN_DIR/taiwan-lab-mcp"
DATA_EXE="$BIN_DIR/taiwan-lab-data"
[ -x "$DATA_EXE" ] || stop_with_advice "裝完卻找不到 $DATA_EXE" '關掉終端機重新開一個，再跑一次這支腳本。'
ok "查詢工具：$MCP_EXE"

# --------------------------------------------------------------- 第 4 步：下載資料
DATASET_COUNT="$(printf '%s' "$DATASETS" | wc -w | tr -d ' ')"
step "第 4 步：下載資料（$DATASET_COUNT 種）"
DOWNLOAD_DIR="${TMPDIR:-/tmp}/taiwan-lab-$TAG"
mkdir -p "$DOWNLOAD_DIR"
info "暫存在 $DOWNLOAD_DIR，裝完可以整個刪掉。"

ASSET_URLS="$(printf '%s' "$RELEASE_JSON" | grep '"browser_download_url"' | cut -d'"' -f4)"
for dataset in $DATASETS; do
    name="$(dataset_name "$dataset")"
    bundle_url="$(printf '%s\n' "$ASSET_URLS" | grep -E "/${dataset}-snapshot-[0-9a-f]+\.zip$" | head -1)"
    checksum_url="$(printf '%s\n' "$ASSET_URLS" | grep -E "/${dataset}-snapshot-[0-9a-f]+\.zip\.sha256$" | head -1)"
    [ -n "$bundle_url" ] && [ -n "$checksum_url" ] \
        || stop_with_advice "版本 $TAG 裡沒有 $name 的資料包" "到 https://github.com/$REPOSITORY/releases/tag/$TAG 看這一版有哪些檔案，用 --datasets 只挑有的。"

    bundle_path="$DOWNLOAD_DIR/$(basename "$bundle_url")"
    checksum_path="$DOWNLOAD_DIR/$(basename "$checksum_url")"
    info "下載 $name…"
    curl -fsSL "$bundle_url" -o "$bundle_path" || stop_with_advice "下載 $(basename "$bundle_url") 失敗" '網路斷了或逾時，再跑一次這支腳本就會接著下載。'
    curl -fsSL "$checksum_url" -o "$checksum_path" || stop_with_advice "下載核對碼失敗" '再跑一次這支腳本。'

    # .sha256 檔第一個欄位就是那串雜湊值。
    expected="$(awk '{print $1; exit}' "$checksum_path")"
    # macOS 有 shasum，多數 Linux 只有 sha256sum。
    if command -v shasum >/dev/null 2>&1; then
        actual="$(shasum -a 256 "$bundle_path" | awk '{print $1}')"
    elif command -v sha256sum >/dev/null 2>&1; then
        actual="$(sha256sum "$bundle_path" | awk '{print $1}')"
    else
        stop_with_advice '這台電腦沒有可以算 SHA-256 的指令' '裝了 shasum 或 sha256sum 再跑一次；沒核對過的檔案不應該安裝。'
    fi
    if [ "$(printf '%s' "$actual" | tr 'A-Z' 'a-z')" != "$(printf '%s' "$expected" | tr 'A-Z' 'a-z')" ]; then
        stop_with_advice "$(basename "$bundle_path") 下載到的內容跟發布時不一樣" "刪掉 $DOWNLOAD_DIR 整個資料夾再跑一次。持續不一樣就回報，不要繼續安裝。"
    fi
    ok "$name 下載完成，核對碼相符"

    printf '%s\t%s\t%s\n' "$dataset" "$bundle_path" "$expected" >> "$DOWNLOAD_DIR/plan.tsv"
done

# ----------------------------------------------------------- 第 5 步：把資料裝進去
step "第 5 步：安裝資料到 $DATA_DIR"
mkdir -p "$DATA_DIR"
INSTALLED=''
while IFS="$(printf '\t')" read -r dataset bundle_path expected; do
    [ -n "$dataset" ] || continue
    name="$(dataset_name "$dataset")"
    info "安裝 $name…"
    output="$("$DATA_EXE" install-snapshot "$dataset" --bundle "$bundle_path" --sha256 "$expected" --actor "$ACTOR" --data-dir "$DATA_DIR" --json 2>&1 || true)"
    case "$output" in
        *'"result":"installed"'*) ok "$name 安裝完成" ;;
        *'"result":"already_installed"'*) ok "$name 本來就裝好了，沒有變動" ;;
        *)
            printf '%s\n' "$output"
            stop_with_advice "安裝 $name 失敗" "上面那行 error_code 的意思，查 https://github.com/$REPOSITORY/blob/main/docs/install.md 的錯誤對照表。"
            ;;
    esac
    INSTALLED="$INSTALLED$name、"
done < "$DOWNLOAD_DIR/plan.tsv"
rm -f "$DOWNLOAD_DIR/plan.tsv"

# ------------------------------------------------------- 第 6 步：設定 Claude 桌面版
if [ "$SKIP_CLAUDE_CONFIG" -eq 1 ]; then
    step '第 6 步：跳過（你指定了 --skip-claude-config）'
else
    step '第 6 步：把工具加進 Claude 桌面版'
    mkdir -p "$(dirname "$CONFIG_PATH")"
    if [ -f "$CONFIG_PATH" ]; then
        backup="$CONFIG_PATH.bak-$(date +%Y%m%d-%H%M%S)"
        cp "$CONFIG_PATH" "$backup"
        info "原本的設定檔已備份到 $backup"
    fi
    command -v python3 >/dev/null 2>&1 \
        || stop_with_advice '找不到 python3，沒辦法安全地改設定檔' "先跑一次 xcode-select --install，或改用 --skip-claude-config 並照 docs/install.md 第 5 步手動貼設定。"
    MCP_EXE="$MCP_EXE" DATA_DIR="$DATA_DIR" CONFIG_PATH="$CONFIG_PATH" python3 - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["CONFIG_PATH"])
config = {}
if path.exists() and path.read_text(encoding="utf-8").strip():
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise SystemExit(f"現有的 {path} 不是合法的 JSON，不敢動它。備份還在，請先自己修好再跑一次。")
config.setdefault("mcpServers", {})["taiwan-laboratory"] = {
    "command": os.environ["MCP_EXE"],
    "env": {
        "TAIWAN_LAB_DATA_MODE": "official_snapshot",
        "TAIWAN_LAB_DATA_DIR": os.environ["DATA_DIR"],
        "PYTHONIOENCODING": "utf-8",
    },
}
path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
    ok "設定檔寫好了：$CONFIG_PATH"
fi

echo
echo '=========================================================='
echo ' 裝好了'
echo '=========================================================='
echo "版本：$TAG"
echo "資料夾：$DATA_DIR"
echo "已裝的資料：${INSTALLED%、}"
echo
echo '接下來你要做的：'
echo '  1. 完全關掉 Claude 桌面版（Cmd+Q，不是只關視窗），再重新打開。'
echo '  2. 對 Claude 說：「請呼叫 get_data_status，告訴我資料狀態」。'
echo '  3. 再問一句：「登革熱要採什麼檢體、怎麼送驗？」'
echo
echo "暫存的下載檔可以刪掉：$DOWNLOAD_DIR"
