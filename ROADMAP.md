# Roadmap

## P1：台灣醫檢師願意使用與分享的免費 MCP

產品目的：以好用的公開資料查詢建立「醫檢 × AI」品牌，累積教學、Workshop 與醫院合作機會。優先看實際解決了哪些查詢問題，以及使用者是否願意推薦給同事。

### P1.0：原骨架整合與可重現示範

- [x] 取回並核對 `taiwan-laboratory-mcp-v0.1.zip`；記錄原始檔 SHA-256。
- [x] 整合 CDC／NHI／TFDA 工具、sample fixtures、Python package 與安裝說明。
- [x] 所有 fixtures 明示 `sample_only`；正式資料的 provenance 契約驗證不允許缺漏。
- [x] 在乾淨環境驗證安裝、MCP 啟動、工具列舉與三個場景的實際呼叫。
- [x] 建立 GitHub Actions 測試、建置與安裝包驗證；每次提交的結果以 [CI](https://github.com/masalu0105-gif/taiwan-laboratory-mcp/actions/workflows/test.yml) 為準。

### P1.1：正式公開資料查詢

- [x] CDC：採檢送驗內容逐欄對照官方版本、頁碼及條件。整本採檢手冊與認可檢驗機構名冊都已上線，逐字比對通過。
- [x] NHI：保留生效起迄、代碼與支付規範；當期 snapshot 若同碼重複則整批待審，`as_of` 歷史查詢明確拒絕。
- [x] TFDA：保留許可證效期、註銷狀態及廠商角色。10 萬多張全收錄；其中沒有分類代碼的那些依 2026-09-15 的決定維持「不確定」，所以涵蓋狀態固定是 `review_incomplete`。
- [x] 提供資料更新、失敗與過期狀態；更新失敗不會靜默改回 sample。
- [x] 發布到 PyPI，安裝縮成一行 `uv tool install taiwan-laboratory-mcp`（2026-09-22）。
- [x] 提供不用安裝的公開端點 `https://lab.masalulab.com/mcp`，資料每天自動對新版（2026-09-22）。
- ~~邀請 5–10 位醫檢師測試~~（2026-09-14 取消，改成直接公開上線、用 GitHub Issues 收回饋）

### P1.2：分享與教學

整理可重現的三段 Demo、安裝指引與 Workshop 練習。透過自願回饋了解使用痛點、分享意願及教學需求。

本專案任何路徑都不蒐集病人資料。至於使用者查詢紀錄：**本機安裝那條路不記錄任何東西**，套件預設也不記錄。維護者經營的那個公開端點有開使用紀錄，會記下查詢字句，用來知道大家在查什麼、哪些問法查不到；細節與關閉方式見 [SECURITY.md](SECURITY.md)。要完全不被記錄就裝在自己電腦上。

## 先留介面，依授權與合作條件啟動

| 項目 | 現階段邊界 | 啟動條件 |
| --- | --- | --- |
| LOINC | Adapter interface；不自行建立台灣 mapping | 已確認資料版本、授權及合作提供方式 |
| FHIR | Adapter interface；不宣稱符合 TW Core | 明確互通需求、profile 版本與驗證計畫 |
| SNOMED | Adapter interface；不內含術語資料 | 授權、地域與再散布條件確認 |
| EQA／CAP | Adapter／TODO；不抓 catalog | Provider 明確允許的取得方式與使用範圍 |

## P2：Hospital Data Readiness

當醫院提出具體需求，並確認資料責任、授權及合作範圍後，再評估 Data Cleaning、資料品質盤點、去識別化、LIS integration、地端部署與稽核。這些僅列於 roadmap，不加入 P1 功能、背景收集或依賴套件。

P2 的成功條件需與合作醫院另行訂定；P1 可用不代表已具備院內正式部署條件。
