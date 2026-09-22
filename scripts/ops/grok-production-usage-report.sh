#!/usr/bin/env bash
# Turn the raw usage log into something a person reads.
#
#   grok-production-usage-report.sh          今天
#   grok-production-usage-report.sh 7        最近 7 天
#   grok-production-usage-report.sh all      全部
#
# Writes to stdout and to usage-report.txt next to the log, so the answer is
# already sitting there when someone asks "有誰在用".
set -uo pipefail

readonly base="${TAIWAN_LAB_PRODUCTION_BASE:-/home/box/taiwan-lab-mcp-production-20260922}"
readonly usage_log="${base}/usage.jsonl"
readonly report_file="${base}/usage-report.txt"
readonly days="${1:-1}"

if [ ! -f "$usage_log" ]; then
  printf '還沒有任何使用紀錄。\n（紀錄檔 %s 還不存在，代表服務啟動後沒有人呼叫過，或還沒開啟記錄。）\n' \
    "$usage_log" | tee "$report_file"
  exit 0
fi

python3 - "$usage_log" "$days" <<'PY' | tee "$report_file"
import json, sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

path, window = sys.argv[1], sys.argv[2]
TAIPEI = timezone(timedelta(hours=8))

if window == "all":
    since, label = None, "全部紀錄"
else:
    n = int(window)
    since = datetime.now(timezone.utc) - timedelta(days=n)
    label = "今天到現在" if n == 1 else f"最近 {n} 天"

LOOPBACK = {"127.0.0.1", "::1", "localhost", "unknown"}

rows = []
with open(path, encoding="utf-8") as handle:
    for line in handle:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            row["_at"] = datetime.fromisoformat(row["at"])
        except (ValueError, KeyError):
            continue
        if since is None or row["_at"] >= since:
            rows.append(row)

print("=" * 52)
print(f"  公開網址使用情形（{label}）")
print(f"  產生時間 {datetime.now(TAIPEI):%Y-%m-%d %H:%M} 台北時間")
print("=" * 52)

if not rows:
    print("\n這段期間沒有人呼叫。")
    raise SystemExit

# The host checks itself over loopback after every restart. That is this
# machine talking to itself, not somebody using the service.
selfcheck = [r for r in rows if r.get("client") in LOOPBACK]
rows = [r for r in rows if r.get("client") not in LOOPBACK]

if not rows:
    print("\n這段期間沒有外部的人呼叫。")
    if selfcheck:
        print(f"（只有主機自己的例行檢查 {len(selfcheck)} 次。）")
    raise SystemExit

calls = [r for r in rows if not r.get("refused")]
refused = [r for r in rows if r.get("refused")]
people = {r.get("client", "?") for r in rows}

print(f"\n總共被呼叫 {len(calls)} 次，來自 {len(people)} 個不同的地方。")
print("（同一個人用手機和電腦連會算成兩個，數字看趨勢就好。）")
if refused:
    print(f"另有 {len(refused)} 次被擋下來（多半是同一個人短時間問太快）。")
if selfcheck:
    print(f"另外主機自己的例行檢查 {len(selfcheck)} 次，沒算進上面。")

first, last = min(r["_at"] for r in rows), max(r["_at"] for r in rows)
print(f"第一次 {first.astimezone(TAIPEI):%m-%d %H:%M}，最後一次 {last.astimezone(TAIPEI):%m-%d %H:%M}。")

tools = Counter(r["tool"] for r in calls if r.get("tool"))
if tools:
    print("\n【最常用的功能】")
    for name, count in tools.most_common(8):
        print(f"  {count:>4} 次   {name}")

print("\n【每個人用了多少】")
per_person = Counter(r.get("client", "?") for r in rows)
for who, count in per_person.most_common(10):
    blocked = sum(1 for r in refused if r.get("client") == who)
    extra = f"（其中 {blocked} 次被擋）" if blocked else ""
    print(f"  {count:>4} 次   {who}{extra}")

queries = defaultdict(Counter)
for r in calls:
    args = r.get("arguments") or ""
    if not args:
        continue
    try:
        parsed = json.loads(args.replace("…(截斷)", ""))
    except ValueError:
        continue
    for key in ("query", "disease", "code", "keyword", "name"):
        value = parsed.get(key)
        if isinstance(value, str) and value.strip():
            queries[r.get("tool", "?")][value.strip()] += 1
            break

if queries:
    print("\n【大家實際查了什麼】")
    for tool, counter in sorted(queries.items(), key=lambda kv: -sum(kv[1].values())):
        print(f"  {tool}")
        for term, count in counter.most_common(10):
            suffix = f" ×{count}" if count > 1 else ""
            print(f"      {term}{suffix}")

by_day = Counter(r["_at"].astimezone(TAIPEI).strftime("%m-%d") for r in rows)
if len(by_day) > 1:
    print("\n【每天幾次】")
    for day in sorted(by_day):
        print(f"  {day}  {'█' * min(40, by_day[day])} {by_day[day]}")
PY
