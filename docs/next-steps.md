# 接下來要做的事

> 2026-09-18 收尾時整理。專案主要開發已經告一段落，這份只列「還沒做完」與「之後要接手的人要知道」的事。
> 已經做完的東西寫在 [實作紀錄](implementation-notes.md)，決定寫在 [PRD 第 9 節](product-requirements.md)。

## 現在的狀態（2026-09-18 實查）

- 四份官方資料都在服務：健保支付標準、食藥署醫材許可證、疾管署認可檢驗機構名冊（1150916）、疾管署傳染病檢體採檢手冊（1150826）。
- 24 個查詢工具，兩種接法：裝在自己電腦上（`taiwan-lab-mcp`）、連網址（`taiwan-lab-mcp-http`）。
- 公開網址 `https://lab.masalulab.com/mcp`，跑在 owner 電腦的 WSL 裡，對外走既有的 Cloudflare Tunnel。
- 每天 09:30 自動檢查四個官方來源，通過就換版並自動發 GitHub Release。
- 程式最新 commit `2379656`，CI 四個平台全綠。

## 待辦

### 1. 把公開網址的服務裝成開機自動啟動（owner 執行，需要密碼）

現在服務是手動起的，WSL 一重開公開網址就會斷。unit 檔已經寫好放在 `/home/flumox/taiwan-lab-mcp-http/taiwan-lab-mcp-http.service`。

```
wsl -e sudo cp /home/flumox/taiwan-lab-mcp-http/taiwan-lab-mcp-http.service /etc/systemd/system/
wsl -e sudo systemctl enable --now taiwan-lab-mcp-http
```

### 2. Mac 實機驗證（owner 有 Mac 時）

程式與 `scripts/install-taiwan-lab-mcp.sh` 目前只有 GitHub 的自動測試驗過，**沒有人在真的 Mac 上走完一次安裝**。安裝說明的〈已知限制〉照實寫了這件事，驗過之後要一起改掉。

### 3. Grok Bot 雲端 VM（owner 2026-09-17 決定暫緩，等他建置起來再做）

owner 原話：「目前還沒有用 GrokBot，所以列為之後要讓他去上傳、去做、去測試的事情。」2026-09-18 再次確認：「等我把 Growbook 那個部分建置起來，我們再來進行。」

搬過去之前要在**那台機器上實測**這三件，不能用推論的（官方公告頁沒寫）：

1. 能不能跑一直開著的常駐程式並聽 port。最小測法：
   `python3 -m http.server 8080 &` 然後 `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080`，回 200 才算過。
2. 能不能裝 cloudflared 並讓 tunnel 一直連著。
3. 拿它當對外服務的主機，合不合 xAI／Cursor 的使用條款。

三項都過就照 `docs/install.md` 的〈進階：一台主機服務多個人〉搬：在 VM 上裝同一個工具、跑同一支啟動腳本、把 `lab.masalulab.com` 改指到那邊的 cloudflared。**使用者手上的網址不用換。**

### 4. 新冠相關的查詢只覆蓋一部分（要不要做由 owner 決定）

一個別名只能換成一個字。新冠的許可證分散在「新型冠狀病毒」「SARS-CoV-2」「COVID-19」三種寫法，聯集 30 列，目前單一替換覆蓋 25 列。要全覆蓋得讓一個別名對到多個字再把結果合併，會動到食藥署搜尋的排序（10 萬筆那張表），風險比較高，暫不做。

### 5. 公開服務的規矩還沒定（owner 決定）

- **沒有身分驗證**：拿到網址的人都查得到。查的是公開政府資料，風險低，但網址發出去就收不回來。
- **架主機的人看得到查詢內容**：要不要留紀錄、隱私聲明怎麼寫，還沒決定。上課發給學生前建議先講一句。
- 也還沒有用量限制。

## 之後接手的人要知道的兩件事

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
