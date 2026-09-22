# 接下來要做的事

> 2026-09-22 更新。專案主要開發已經告一段落，這份只列「還沒做完」與「之後要接手的人要知道」的事。
> 已經做完的東西寫在 [實作紀錄](implementation-notes.md)，決定寫在 [PRD 第 9 節](product-requirements.md)。

## 現在的狀態（2026-09-22 實查）

- 四份官方資料都在服務：健保支付標準、食藥署醫材許可證、疾管署認可檢驗機構名冊（1150916）、疾管署傳染病檢體採檢手冊（1150826）。
- 24 個查詢工具，兩種接法：裝在自己電腦上（`taiwan-lab-mcp`）、連網址（`taiwan-lab-mcp-http`）。
- 公開正式網址 `https://grok-bot-box.tail6cbb55.ts.net/mcp`，跑在 Grok Bot VM，對外走 Tailscale Funnel；Windows 外部 MCP client 已完整驗證。
- 每天 09:30 自動檢查四個官方來源，通過就換版並自動發 GitHub Release。
- 程式版號 `0.1.2`；GitHub Actions run `35698168537` 在 Ubuntu、macOS、Windows 四組全綠。公開 Release 必須讓 tag、wheel、sdist 與四份資料資產維持同一組可安裝狀態。

## 待辦

### 1. VM 整機重建後的恢復驗證仍需供應商控制面

正式 app 由 `tmux` supervisor 監督，子程序崩潰與 SSH 斷線都已實測可恢復／持續。2026-09-22 已把 `~/.config/box-boot-selfheal.sh` 掛入 Grok 映像既有的 `/usr/local/bin/start-desktop.sh`，啟動時會呼叫 `~/.config/box-selfheal.sh`，復原 Tailscale、SSH、正式 app 與已核准的 Funnel；安裝程式、啟動程式與 vendor launcher 原檔備份都已保留。

boot hook 已人工執行成功，但 Grok 控制台沒有 Restart 操作，容器內對 PID 1／`pod-daemon` 發送 TERM／KILL 也不會重建容器。因此仍不能宣稱「整機重建後已實測自動恢復」或「永不斷線」。供應商真正重建容器後，需核對 `box-boot-selfheal.log` 新增一次 `boot_selfheal_ok`、公開 MCP verifier 通過；vendor image 更新也可能覆寫 launcher，狀態檢查要一併核對 hook marker。

### 2. Mac 實機驗證（owner 有 Mac 時）

程式與 `scripts/install-taiwan-lab-mcp.sh` 目前只有 GitHub 的自動測試驗過，**沒有人在真的 Mac 上走完一次安裝**。安裝說明的〈已知限制〉照實寫了這件事，驗過之後要一起改掉。

### 3. Grok Bot 雲端 VM（公開 production 已啟用；匿名端點的條款適用性未明）

2026-09-22 已在該 VM 做最小、可回復的實測：

1. Python HTTP server 放進 `tmux` 後中斷 SSH，重新連線仍可取得 HTTP 200；測完已停止，port 已釋放。
2. 安裝官方 `cloudflared` 2026.9.1 並核對 release SHA-256；臨時 Quick Tunnel 從外部 Windows 主機取得 HTTP 200，測完已停止，沒有改正式 DNS 或既有 tunnel。
3. 目前沒有 user systemd session；已改接既有 desktop launcher 並完成人工 boot hook 驗證，但平台控制面不提供 Restart，還沒證明整個容器重建後自動恢復。

同日已部署獨立的私人 pilot：`/home/box/taiwan-lab-mcp-pilot-20260922`，只聽 `127.0.0.1:18081`、固定 `sample` mode、使用獨立 venv 與 `tmux`，沒有正式資料。VM 內與 Windows 經 SSH tunnel 都以 MCP client 實測：24 個工具、`get_data_status.data_mode=sample`、0 個 official serving build，TFDA 新冠別名展開三個查詢詞。Windows 可用 `ssh -N -L 18082:127.0.0.1:18081 grok-box` 暫時取得 `http://127.0.0.1:18082/mcp`；關掉 SSH tunnel 就不再能從 Windows 存取。

owner 於 2026-09-22 明確要求改為公開正式主機。正式部署位於 `/home/box/taiwan-lab-mcp-production-20260922`，只聽 `127.0.0.1:18083`，使用 `official_snapshot` 與 Tailscale Funnel。外部驗證結果：24 tools、四個來源 available 且可追溯、TFDA 多關鍵字聯集 39 筆、NHI／CDC 查詢皆有 evidence-backed row。資料 396 個檔案、583,006,816 bytes，aggregate inventory SHA-256 為 `ffa1e13719808d178d4d06de62b667d263f5137cd37eaa5ba023c8eae72fae8c`。

資料庫、四來源資料更新排程與 MCP 查詢服務是 owner 自有工作流程，不是替第三方代管資料庫。Grok Bot 補充條款只明確寫 internal business purposes，沒有直接說明匿名公開 MCP 端點是否包含在內；因此只把這一點記為條款適用性未明，不據此判定違規、要求停站或阻擋既有資料排程。若未來用途改成替第三方保存非公開資料、收費代管或處理受限資料，需重新審查。

### 4. 公開服務 guard 已上線；匿名公開是 owner 既定範圍

- `0.1.2` 已加每來源每分鐘 240 次的記憶體內 sliding-window 限流、256 KiB request body 上限、`Cache-Control: no-store`、`Referrer-Policy: no-referrer` 與 `nosniff`。
- Uvicorn 內建 access log 仍關閉；改由 `PublicHttpGuard` 自己記錄，格式受控且不含請求標頭。
- **owner 2026-09-22 裁決：公開端要記錄使用情形（等級 3，含查詢內容）。** 環境變數 `TAIWAN_LAB_HTTP_USAGE_LOG` 指定檔案才會開，套件預設關閉。每筆記時間、來源 IP、工具名稱、查詢參數、狀態碼；被拒絕的（429／413／401）另記 `refused` 代碼。參數超過 2000 字會截斷，檔案超過 50 MB 會輪替。寫入失敗不影響回應。
- README 原本寫「不記錄 HTTP access log」，已改寫成明講會記錄並看得到查詢內容。宣傳網站同步加註。
- 報表：`scripts/ops/grok-production-usage-report.sh`，產出給人讀的摘要（幾個人在用、最常用哪個工具、實際查了什麼字、誰被擋）。
- bearer token 驗證可選，設定只接受 SHA-256；目前公開 production 沒有開啟，維持 owner 要求的匿名公開。這是單機基本保護，不是 CDN／WAF 或分散式 DDoS 防護。

### 5. 主機端資料每日更新（2026-09-22 上線）

Grok VM 上沒有 cron 也沒有 systemd（PID 1 是 `tini`），排程沿用旁邊 app supervisor 的做法：tmux session `taiwan-lab-data-updater` 跑一個 sleep 迴圈，每天台北時間 10:30 叫 `grok-production-update-data.sh`。`grok-production-start.sh` 會起這個 session，boot self-heal hook 呼叫 start.sh，所以整機重開後會一起回來。`grok-production-status.sh` 多印 `data_updater=` 與 `data_update_last=`。

腳本正本在 repo 的 `scripts/ops/`，主機上另有一份在 production 目錄。`--dry-run` 不是提早 return，是對著 `cp -a` 出來的 data-root 複本走完同一段安裝程式。

2026-09-22 驗過的：

- 模擬跑：四份下載、SHA-256 相符、install-snapshot、讀取測試都過，正式資料沒被動到
- 真的換版：空目錄先裝 data-20260918 的名冊（`installed`、generation 1），再裝 data-20260922（`installed`、generation 2、snapshot id 換掉）
- 故意給錯的 `--sha256`：`BUNDLE_SHA256_MISMATCH`，rc=4
- GitHub API 匿名額度用完回 403：擋在動資料之前，rc=1。第一次模擬真的撞到，因此改走已登入的 `gh api`（5000/hr）並加三次重試
- 排程觸發：把 `TAIWAN_LAB_UPDATE_AT` 設成兩分鐘後，準時在該分鐘第 01 秒觸發並跑完
- 正式跑一次：四份都 `already_installed`，不重啟，`listener` 前後都在，公開網址 HTTP 200

還沒驗的：真的遇到「主機是舊版、Release 是新版」的那一天，走完換版加重啟那一整段。要等官方出新版，或人工把主機降版一次再跑。

## 之後接手的人要知道的兩件事

### TFDA 新冠別名會查三種來源寫法

owner 2026-09-22 核准多關鍵字聯集。`tfda-term-alias-v2` 會把「新冠」「新冠肺炎」「武漢肺炎」「嚴重特殊傳染性肺炎」展開成「新型冠狀病毒」「SARS-CoV-2」「COVID-19」三個查詢詞；同一來源列只回一次，排序使用所有變體的最佳 match tier，再沿用既有許可證字號與來源列順序。

### 建置後要明確驗證 fresh archives

source 測試不會自動讀取 repo 裡可能過期的 `dist/`。先執行 `python -m build`，再把 `TAIWAN_LAB_ARTIFACT_DIR` 指向該次輸出並單獨跑 `tests/test_package_contents.py`；缺 wheel、sdist 或必要 contract／review protocol／rule bundle 都會失敗。CI 也按這個順序執行，不能把 package test 的 skip 當成 archive gate 通過。

### 程式改完，記得把 owner 電腦上裝的那份一起更新

不然每天的自動發布會被擋，訊息長這樣（2026-09-17 真的發生過）：

```
"result":"blocked"
"reasons":["installed_program_differs_from_main:http_server.py"]
```

這個擋是刻意的：不讓「新資料包配舊程式」的組合流出去。更新方式：

```
uv build --wheel --out-dir <scratch>
uv pip install --python "C:/Users/User/AppData/Roaming/uv/tools/taiwan-laboratory-mcp/Scripts/python.exe" --reinstall-package taiwan-laboratory-mcp <scratch>/taiwan_laboratory_mcp-0.1.2-py3-none-any.whl "pypdfium2==5.13.0"
```

公開網址的 Grok VM 使用獨立 venv，部署精確的 `0.1.2` wheel；公開 Release 也應包含同版 wheel、sdist 與四份資料資產，避免 installer 從 latest release 取到舊程式。

### 食藥署的涵蓋狀態永遠是 `review_incomplete`，這不是待辦

104,619 張許可證裡有 17,606 張沒有分類代碼，依 owner 2026-09-15 的決定維持「不確定」。所以那個欄位不會變成 `complete`。這是那個決定的必然結果，不是漏做。

## 明文不做的（不用再想）

- 5 到 10 人的使用者試用（2026-09-14 取消，改公開上線收 GitHub Issues）
- LOINC、FHIR、SNOMED、EQA、CAP（保留介面，只回「尚未設定」）
- `compare_products` 維持停用
- 病人資料、LIS/HIS 串接、診斷建議、申報判斷、採購建議
