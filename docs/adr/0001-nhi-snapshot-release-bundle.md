# ADR 0001：NHI 審核版資料以 GitHub Release 下載包散布

- 狀態：Accepted（owner 決定，2026-09-14）
- 範圍：只限 `nhi_fee`。~~TFDA、~~CDC 手冊、CDC ODS 另案決定（TFDA 見 ADR 0002）。
- 關聯：PRD `OD-01`、`REL-G4`；SDD §6、§7.1、§8.2、§8.3、`D-007`；`docs/implementation-notes.md`「Owner 決定：過期處理、再散布、下一步與平台」。

## 背景

SDD §6 把「是否經 GitHub Release 再散布 curated artifact」列為 `OWNER GATE`，SDD §15 要求另立 ADR。PRD `OD-01` 預設只提供同步工具。

owner 在 2026-09-14 選擇把 owner 審核過的 NHI snapshot 放上 GitHub Release，並附上健保署原始 CSV；公開審核紀錄的 reviewer 不寫本名。

規格沒有定義使用者端怎麼取得與啟用散布的 snapshot。本 ADR 記錄本專案採用的做法。

## 決定

### 1. 下載包內容

一個 ZIP，檔名 `nhi_fee-snapshot-<curated build hash 前 12 碼>.zip`，另附同名 `.sha256`。ZIP 只含：

- `bundle-manifest.json`：snapshot／curated build／raw revision ID、curated manifest SHA-256、發布者最後一次成功 upstream check 時間、顯名、授權名稱與網址、非官方服務聲明，以及每個檔案的路徑、大小與 SHA-256。
- `raw/nhi_fee/<raw revision>/`：健保署原始 CSV 與 `fetch.json`。
- `curated/nhi_fee/<curated build>/`：SQLite、manifest、完整 `audit/`（validation、qualification candidate／certificate、三份 review record、evidence）。

不含：`manifests/current/`、`checks/`、`publish-events/`、`locks/`、`staged/`、`quarantine/` 與任何本機工具快取。

原始 CSV 可以散布的依據：2026-09-14 下載 `https://data.gov.tw/license`，「二、授與權利」允許不限目的、非專屬、免授權金進行重製、散布、公開傳輸，並得再轉授權；條件是顯名。每筆正式結果已帶顯名、授權網址與非官方聲明。

### 2. 匯出條件（發布者端）

`taiwan-lab-data export-snapshot nhi_fee` 只匯出目前正在服務、runtime 完整驗證通過、而且沒有任何 stale reason 的 build。有新版待審、上游檢查失敗或超過兩個宣告週期沒有成功檢查時，拒絕匯出（`EXPORT_SERVING_STALE`）。

同一份資料匯出的 ZIP bytes 固定：entry 順序固定、時間戳固定為 1980-01-01、manifest 為 canonical JSON。

### 3. 安裝（使用者端）

`taiwan-lab-data install-snapshot nhi_fee --bundle <zip> [--sha256 <hash>]` 在寫入任何檔案前依序檢查：

1. 整包 SHA-256（有提供時）、大小上限、ZIP magic bytes。
2. 每個 entry 的路徑安全（不得絕對路徑、drive、`..`、目錄、symlink、加密），entry 數上限。
3. `bundle-manifest.json` strict schema；ZIP 內檔案集合必須等於清單；每個路徑只能在該 snapshot 的 raw 與 curated 目錄內；每個檔案大小與 SHA-256 相符；必要檔案齊全；curated manifest hash 等於清單值。
4. data root 裡已存在的同路徑檔案必須 bytes 完全相同，否則拒絕（`BUNDLE_FILE_CONFLICT`），不覆寫。

寫入後重新驗證 raw revision 與 `fetch.json` 一致，再經既有 `publish_current_descriptor`（lock、generation CAS、target manifest／DB／audit 完整驗證、publish event）切換 current。已經在服務同一個 snapshot 時不產生新 generation。

### 4. 使用者端的 freshness

使用者電腦沒有自己檢查過上游。安裝時寫入的 check record 沿用下載包裡「發布者最後一次成功檢查這個原始檔」的時間，`check_id` 以 `nhi_fee-check-install-` 開頭，便於和本機上游檢查區分。

因此 runtime 會從發布者的檢查時間開始算：超過兩個宣告週期（48 小時）就顯示 `upstream_check_overdue`。使用者可以自行執行 `taiwan-lab-data check nhi_fee` 更新，或安裝較新的下載包。這個做法不宣稱使用者端做過任何上游核對。

### 5. Provenance

下載包含原始 CSV，安裝後 `local_artifact_available=true`，runtime 會逐次驗證原始檔 hash。`currently_reproducible_from_upstream` 維持 `false`（runtime 不連網）。

### 6. 發布節奏與審核人（2026-09-15 部分由 ADR 0002 §4 取代）

- ~~只有「上游有變、owner 審核通過並在本機發布」之後，才匯出新的下載包並建立新的 Release。~~ 改為本機自動換版成功後由排程發布（ADR 0002 §2）。
- 公開審核紀錄的 `reviewer_id` 使用「專案負責人」代號，`reviewer_role=project_owner`、`identity_assurance=local_asserted`。
- 建立 GitHub Release 屬對外公開動作；~~每一次都要把實際檔名、大小、SHA-256 交 owner 確認後才執行。~~ owner 2026-09-15 選擇自動發布（ADR 0002 §2）。

## 不做

- 不把 curated SQLite 或原始 CSV 放進 wheel／sdist（SDD §9）。
- 不自動下載 Release；使用者自行下載後用 `install-snapshot` 安裝。
- 不對下載包做數位簽章；完整性只靠 SHA-256 與 GitHub Release 的傳輸。能改寫使用者 data root 的人不在威脅模型內（SDD §13）。
