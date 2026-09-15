# ADR 0004：疾管署資料納入 GitHub Release 下載包

- 狀態：Accepted（owner 2026-09-16：「疾管署的資料也放進去」，transcript timestamp `2026-09-15T23:31:29.972Z`）。
- 範圍：`cdc_authorized_labs`（傳染病認可檢驗機構名冊，ODS）與 `cdc_specimen_manual`（傳染病檢體採檢手冊與修訂對照表，兩份 PDF）。
- 關聯：PRD OD-19、`docs/adr/0001-nhi-snapshot-release-bundle.md`、`docs/adr/0002-tfda-bundle-and-automatic-release.md`、SDD `D-007`、`D-023`。

## 背景

名冊 2026-09-15、手冊 2026-09-16 已在本機上線，但下載包只有健保與食藥署。名冊與手冊的審核規則第 1 版都寫著「GitHub Release 下載包不在這一版範圍，要 owner 另外決定」。owner 2026-09-16 決定放進去。

## 決定

1. `export-snapshot`／`install-snapshot` 與每日自動發布都支援這兩個來源，內容與檢查沿用 ADR 0001、0002：
   - 包內是該版本的 raw revision 整個資料夾、curated build（含 `audit/` 審核紀錄與驗收題）以及列出每個檔案大小與 SHA-256 的 bundle manifest。
   - 手冊的 raw revision 內含 `manual.pdf`、`revision.pdf` 與 `fetch.json`，三個都進包；資料庫的列只從 `manual.pdf` 讀出來。
   - 安裝時逐檔重算大小與 SHA-256，已存在但內容不同的檔案一律停手；current 指標照原本的 generation 檢查切換。
2. 兩個來源的審核規則各出第 2 版（`cdc-labs-r1-ai-review/2`、`cdc-labs-r1-auto-review/2`、`cdc-manual-r1-ai-review/2`、`cdc-manual-r1-auto-review/2`），`PUB-R1-OWNER` 的範圍改為「本機 MCP 服務與 GitHub Release 下載包」。本機建置要以第 2 版重建後才發布下載包。
3. 安裝端沿用發布者最後一次成功檢查的時間；兩個來源都是兩天沒有重新檢查就標「可能過期」（`cdc-labs-v1`、`cdc-manual-v1`），查詢照樣回答並帶警告。
4. 大小沿用 ADR 0002 的上限（壓縮後 128 MiB、解壓後 512 MiB）：名冊 ODS 約 1.4 MB，手冊 PDF 4.0 MB 加修訂對照表 0.8 MB，都遠低於上限。

## 取捨

- 疾管署官網資料依政府資料開放宣告可以再散布，條件是顯名；下載包的 manifest 與查詢結果都帶顯名與「非疾管署官方服務」說明。
- 包內沒有任何個資：名冊是機構與檢驗項目，手冊是採檢與送驗規定。

## 不做

- 手冊第 7 章與修訂對照表的資料（PRD OD-18，還在做）不在這一版包內。
- 不放 OCR 產生的資料。
