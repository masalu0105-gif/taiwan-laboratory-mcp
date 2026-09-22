# 貢獻指南

歡迎醫檢師、工程師、資料維護者與講師參與。先從一個自己真的會查的問題開始，描述原本需要花哪些步驟，以及期待工具省下哪一步。

## 提出問題或需求

使用 [Issue templates](https://github.com/masalu0105-gif/taiwan-laboratory-mcp/issues/new/choose)。資料錯誤請附官方來源、版本、頁碼或欄位、實際結果及預期結果。請勿附病人資料、院內 SOP、帳密、API key 或未授權 catalog。

安全問題請依 [SECURITY.md](SECURITY.md) 處理，避免在公開 Issue 揭露可利用的細節。

## 修改前

1. 確認修改屬於 [P1 範圍](ROADMAP.md)。新資料源先說明使用場景與授權。
2. 優先沿用原骨架與標準函式庫；新依賴需解決現有具體問題。
3. 區分官方資料、人工整理、測試樣本；檢查 [資料契約](docs/architecture.md)。

原 V0.1 ZIP 已整合，來源與變更見 [bootstrap.md](docs/bootstrap.md)。在 repo 根目錄執行以下 PowerShell 指令；Python 環境建立方式見 README。

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe -m ruff format --check src tests scripts
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m build
$env:TAIWAN_LAB_ARTIFACT_DIR = (Resolve-Path .\dist).Path
.\.venv\Scripts\python.exe -m pytest tests\test_package_contents.py -q
Remove-Item Env:TAIWAN_LAB_ARTIFACT_DIR
```

archive 檢查只接受 `TAIWAN_LAB_ARTIFACT_DIR` 明確指定的 fresh build；缺 wheel／sdist 會直接失敗，避免把舊 `dist` 當成目前程式的交付物。CI 另外會從 wheel 安裝、離開 repo 後重跑測試，涵蓋實際 stdio subprocess、24 個工具呼叫，以及新舊協定協商模式。CI 全程使用 samples，不需 secrets 或官方網站連線。新增正式資料匯入時須另補官方欄位、日期與授權驗證；metadata schema 通過不代表內容經專業核准。

## Pull request 驗收

- 說明使用者實際看到的前後差異，附可重現步驟及測試結果。
- 資料轉換保留原值、來源、版本與更新時間；缺值不猜測。
- CDC 保留採檢條件；NHI 保留生效期間與點數單位；TFDA 保留許可證和法人角色。
- Sample fixtures 必須明示 `sample_only: true`；缺來源或未授權資料不得當正式資料合併。
- 說明限制與未驗證事項；維護者確認內容與授權後再合併。

不接受病人層級測試資料，即使投稿者宣稱已去識別化。P1 的測試使用合成資料或已確認可使用的公開資料。

## 授權

提交原創程式或文件表示同意依本專案 MIT License 供他人使用。外部資料須另附來源與適用授權；提交者不能透過本專案重新授權自己沒有權利散布的資料。
