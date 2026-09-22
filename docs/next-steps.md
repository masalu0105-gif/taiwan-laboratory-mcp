# 接下來要做的事

> 2026-09-22 更新。專案主要開發已經告一段落，這份只列「還沒做完」與「之後要接手的人要知道」的事。
> 已經做完的東西寫在 [實作紀錄](implementation-notes.md)，決定寫在 [PRD 第 9 節](product-requirements.md)。

## 現在的狀態（2026-09-22 實查）

- 四份官方資料都在服務：健保支付標準、食藥署醫材許可證、疾管署認可檢驗機構名冊（1150916）、疾管署傳染病檢體採檢手冊（1150826）。
- 24 個查詢工具，兩種接法：裝在自己電腦上（`taiwan-lab-mcp`）、連網址（`taiwan-lab-mcp-http`）。
- 公開正式網址 `https://grok-bot-box.tail6cbb55.ts.net/mcp`，跑在 Grok Bot VM，對外走 Tailscale Funnel；Windows 外部 MCP client 已完整驗證。
- 每天 09:30 自動檢查四個官方來源，通過就換版並自動發 GitHub Release。
- 功能基線 commit `2379656`；收尾文件 commit `d7088cf`。當時 CI 四個平台全綠。

## 待辦

### 1. VM 整機重開後的自動恢復仍待平台支援

正式 app 由 `tmux` supervisor 監督，子程序崩潰與 SSH 斷線都已實測可恢復／持續；Grok VM 的 PID 1 是 `tini`，沒有可用的 systemd boot hook。`~/.config/box-selfheal.sh` 已能復原 Tailscale、SSH、正式 app 與已核准的 Funnel，但 VM 更新或整機重開後仍要由 Grok 電腦內執行一次。舊 WSL unit 指令不再是正式主機方案。

不得據此宣稱 VM 永不斷線；平台級自動開機恢復仍是外部 blocker。

### 2. Mac 實機驗證（owner 有 Mac 時）

程式與 `scripts/install-taiwan-lab-mcp.sh` 目前只有 GitHub 的自動測試驗過，**沒有人在真的 Mac 上走完一次安裝**。安裝說明的〈已知限制〉照實寫了這件事，驗過之後要一起改掉。

### 3. Grok Bot 雲端 VM（公開 production 已啟用；供應商條款仍未確認）

2026-09-22 已在該 VM 做最小、可回復的實測：

1. Python HTTP server 放進 `tmux` 後中斷 SSH，重新連線仍可取得 HTTP 200；測完已停止，port 已釋放。
2. 安裝官方 `cloudflared` 2026.9.1 並核對 release SHA-256；臨時 Quick Tunnel 從外部 Windows 主機取得 HTTP 200，測完已停止，沒有改正式 DNS 或既有 tunnel。
3. 目前沒有 user systemd session，可證明的是「跨 SSH 斷線持續」，還沒證明 VM 重開後自動恢復。

同日已部署獨立的私人 pilot：`/home/box/taiwan-lab-mcp-pilot-20260922`，只聽 `127.0.0.1:18081`、固定 `sample` mode、使用獨立 venv 與 `tmux`，沒有正式資料。VM 內與 Windows 經 SSH tunnel 都以 MCP client 實測：24 個工具、`get_data_status.data_mode=sample`、0 個 official serving build，TFDA 新冠別名展開三個查詢詞。Windows 可用 `ssh -N -L 18082:127.0.0.1:18081 grok-box` 暫時取得 `http://127.0.0.1:18082/mcp`；關掉 SSH tunnel 就不再能從 Windows 存取。

owner 於 2026-09-22 明確要求改為公開正式主機。正式部署位於 `/home/box/taiwan-lab-mcp-production-20260922`，只聽 `127.0.0.1:18083`，使用 `official_snapshot` 與 Tailscale Funnel。外部驗證結果：24 tools、四個來源 available 且可追溯、TFDA 多關鍵字聯集 39 筆、NHI／CDC 查詢皆有 evidence-backed row。資料 396 個檔案、583,006,816 bytes，aggregate inventory SHA-256 為 `ffa1e13719808d178d4d06de62b667d263f5137cd37eaa5ba023c8eae72fae8c`。

條款風險沒有因技術上線而消失：Cursor 一般條款雖把 build／deploy／host 列入 Service，但 Grok Bot 補充條款限 internal business purposes，beta 功能只供 evaluation；production deployment 的 `Ask first` 文件也沒有授予公開代管權。供應商書面確認仍是未完成的 owner／production gate，不能把目前公開可連線解讀成供應商已核准。

### 4. 公開服務的規矩還沒定（owner 決定）

- **沒有身分驗證**：拿到網址的人都查得到。查的是公開政府資料，風險低，但網址發出去就收不回來。
- **架主機的人看得到查詢內容**：要不要留紀錄、隱私聲明怎麼寫，還沒決定。上課發給學生前建議先講一句。
- 也還沒有用量限制。

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
uv pip install --python "C:/Users/User/AppData/Roaming/uv/tools/taiwan-laboratory-mcp/Scripts/python.exe" --reinstall-package taiwan-laboratory-mcp <scratch>/taiwan_laboratory_mcp-0.1.1-py3-none-any.whl "pypdfium2==5.13.0"
```

公開網址那台（WSL）另外裝，目前是從 main 分支裝：
`uv tool install --force 'https://github.com/masalu0105-gif/taiwan-laboratory-mcp/archive/refs/heads/main.zip'`
（HTTP 那一層還沒進任何 Release，所以裝 tag 只會拿到 2 支執行檔。）

### 食藥署的涵蓋狀態永遠是 `review_incomplete`，這不是待辦

104,619 張許可證裡有 17,606 張沒有分類代碼，依 owner 2026-09-15 的決定維持「不確定」。所以那個欄位不會變成 `complete`。這是那個決定的必然結果，不是漏做。

## 明文不做的（不用再想）

- 5 到 10 人的使用者試用（2026-09-14 取消，改公開上線收 GitHub Issues）
- LOINC、FHIR、SNOMED、EQA、CAP（保留介面，只回「尚未設定」）
- `compare_products` 維持停用
- 病人資料、LIS/HIS 串接、診斷建議、申報判斷、採購建議
