# 原骨架來源

- 原始檔：`taiwan-laboratory-mcp-v0.1.zip`，由擁有者指定的 ChatGPT 對話產生，2026-09-12 自該帳號的檔案庫取回。
- SHA-256：`c55ab414259984c50817e7a45730bc74956a4f611368388a1b2ae01986ee6cf8`。
- 原骨架四個 adapter 測試在此次本機環境通過；未將 ZIP 內的 `__pycache__` 或 `.pytest_cache` 納入專案。
- 沿用套件名、15 個領域工具及 standards 狀態工具；新增資料狀態與 EQA 狀態工具、Protocol interfaces、來源欄位驗證、錯誤模式拒絕及 stdio 測試。
- 原 sample 的官方版號／頁面更新日已改為明確的 sample 版本及未知日期；未複核的採檢內容、示範點數 0 改為空值，避免被當成官方事實。

原始文件整合至小寫的 `docs/architecture.md`、`docs/data-sources.md` 及 `examples/prompts.md`。P1 保留公開資料查詢與教學定位，P2 僅列於 ROADMAP。這次沒有抓取 EQA／CAP catalog，也沒有匯入病人資料或正式政府資料集。
