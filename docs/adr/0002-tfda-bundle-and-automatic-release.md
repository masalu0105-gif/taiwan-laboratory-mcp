# ADR 0002：食藥署下載包與自動發布

- 狀態：Accepted（owner 決定，2026-09-15）
- 範圍：`tfda_devices` 下載包；`nhi_fee` 與 `tfda_devices` 下載包的發布節奏。CDC 另案。
- 關聯：PRD `OD-10`、`OD-11`、`OD-12`；SDD `D-019`、`D-020`、`D-021`；ADR 0001（§6 部分由本 ADR 取代）；`docs/implementation-notes.md`「Owner 決定：下載包加入食藥署、自動發布、未審核代碼先算」。

## 背景

ADR 0001 只涵蓋健保，而且每次建立 Release 前都要 owner 確認檔名、大小與 SHA-256。

2026-09-15 健保與食藥署都改成本機自動更新之後，GitHub 下載包不會跟著換。owner 在 Claude Code 對話中說「好，那下載包也發一版新的」（transcript timestamp `2026-09-15T10:49:59.327Z`），接著回答三題（`2026-09-15T10:54:18.876Z`）：

- 新的下載包要放哪些資料：「健保＋食藥署 (Recommended)」
- 本機自動換版後下載包要不要自動發：「自動發 (Recommended)」
- 還沒審過的代碼怎麼標：「先當成「算」 (Recommended)」

## 決定

### 1. 食藥署下載包

- 檔名 `tfda_devices-snapshot-<curated build hash 前 12 碼>.zip`，另附同名 `.sha256`。
- 內容、匯出條件、安裝前檢查、寫入方式與使用者端 freshness 同 ADR 0001 §1–§5，路徑換成：
  - `raw/tfda_devices/<raw revision>/`：食藥署原始 ZIP 與 `fetch.json`。
  - `curated/tfda_devices/<curated build>/`：SQLite、manifest 與完整 `audit/`。
- 可以散布的依據同 ADR 0001：資料集 `https://data.gov.tw/dataset/9576` 的機器讀取資料 `license="1"`、網頁授權方式「政府資料開放授權條款-第1版」（2026-09-14 查證）；條件是顯名，每筆正式結果已帶顯名、授權網址與「非食藥署官方服務」說明。
- 大小：2026-09-15 上線版資料庫 166,920,192 bytes，壓縮後約 48.5 MB；原始 ZIP 16,265,433 bytes。兩個來源共用的上限改為壓縮後 128 MiB、解壓後 512 MiB。
- 匯出與安裝逐檔串流讀寫，不把整包放進記憶體。2026-09-14 這台電腦曾因可承諾記憶體不足，在解壓食藥署 ZIP 時當掉。
- 使用者端 freshness：食藥署宣告每 7 日更新，距發布者最後一次成功核對超過 14 天標 `upstream_check_overdue`，仍會回答。
- 公開審核紀錄：上線版 reviewer 為 `ai-reviewer:claude-opus-5`，自動更新版為 `automated-check:tfda-auto-update`，不寫成人工。

### 2. 自動發布

每日排程在健保、食藥署檢查之後，執行 repo 外腳本 `taiwan-lab-mcp-data\automation\publish_data_release.py`。

發布條件，全部成立才發：

1. 兩個來源都在服務，而且沒有 stale reason（沒有待審新版、上游檢查沒有失敗、沒有過期）。
2. GitHub 上最新的 Release 還沒有同名的兩個下載包。
3. 目標 commit 為 `origin/main`，而且：
   - `src/taiwan_lab_mcp` 每個檔案與本機安裝版逐檔相同（換行正規化後比對）；
   - 該 commit 的 GitHub CI 成功。

處理方式：

- 條件 1 或 2 不成立：不發，只寫紀錄，不算異常。
- 條件 3 不成立，或建立 Release 失敗：不發，STATUS 第一行標「異常」並寄信；同一個原因只寄一次。
- 發布後以 `gh release view` 比對 GitHub 回報的附件大小與 SHA-256。
- 標籤 `data-YYYYMMDD`（台北日期；同一天第二版起加 `-2`、`-3`）。

### 3. 審核範圍

- review protocol `tfda-r1-ai-review`、`tfda-r1-auto-review`、`nhi-r1-auto-review` 第 2 版的 `PUB-R1-OWNER` 範圍為 `local_mcp_serving_and_github_release_bundle`。
- 本機食藥署上線版以 `tfda-r1-ai-review` 第 2 版重建後才散布。
- 健保目前服務的 build 依 `nhi-r1-owner-review` 第 2 版審核，範圍已含下載包，不重建。

### 4. ADR 0001 §6 的變更

- 「只有上游有變、owner 審核通過並在本機發布之後，才匯出新的下載包」：改為本機自動換版成功後，由排程依本 ADR §2 發布。
- 「每一次都要把實際檔名、大小、SHA-256 交 owner 確認後才執行」：改為自動發布，發布結果寫入 STATUS 與紀錄檔。

## 不做

- 不對下載包做數位簽章（同 ADR 0001）。
- 不自動刪除舊 Release。
- 使用者端不自動下載新版。
