# 10 種角色、100 題 MCP 情境驗收

狀態日期：2026-09-22（Asia/Taipei）

## 結果

同一份 `persona-scenarios-v1` 矩陣已分別對下列兩條使用路徑執行：

- 從全新 wheel 安裝到乾淨 venv，離開原始碼目錄後以 stdio MCP 連接：100/100 通過。
- 公開 Streamable HTTP 端點 `https://grok-bot-box.tail6cbb55.ts.net/mcp`：100/100 通過。

這證明目前程式可以從安裝產物啟動，也可以透過公開端點呼叫 24 個 MCP 工具。它不代表官方資料永遠最新、VM 永遠在線、臨床驗證完成，或適合正式採檢、申報、採購與醫療決策。

## 使用情境

矩陣包含 10 種角色，每種 10 題：醫檢師、採檢護理師、外送檢驗協調員、公衛實驗室協調員、健保編碼查詢人員、IVD 法規人員、採購前資料覆核人員、醫檢教育講師、MCP 安裝整合人員、資料治理覆核人員。

每題都指定自然語言問題、MCP tool、參數與可機器判定的預期結果。除了正常命中，也驗證查無資料、空白查詢、錯誤分頁、NHI 歷史查詢不支援、產品比較停用，以及 LOINC／FHIR／SNOMED、EQA 保留介面維持未設定。測試不含病人資料。

真實查詢工具的回應另外強制檢查：

- `data_mode=official_snapshot` 且 `sample_only=false`；
- `snapshot_traceable=true`，並有 source provenance；
- `decision_support_only=true`；
- fail-closed 狀態符合每題預期。

## 基線發現與修補

公開端點基線為 97/100。三題失敗中，兩題是情境敘述與正式資料不一致：疾管署手冊確實有 malaria／瘧疾資料，手冊章名使用「外溢」而不是測試原先寫的「灑漏」。矩陣已依正式資料更正，沒有改程式迎合錯誤前提。

真正的查詢缺口是常見用語「糖化血色素」找不到健保代碼 `09006C`，因為官方名稱為「醣化血紅素」。已新增三個經審核的繁體中文用字別名，保留官方名稱與來源列不變，碰撞策略固定為回傳全部命中，不任選單一結果。

乾淨安裝驗收另發現 `mcp 2.2.0` 的 stdio client 需以 `stdio_client(...)` transport 建立。端到端測試與情境 runner 已改用現行介面，避免測試在 MCP server 啟動前就失敗。

## 重跑方式

公開端點：

```powershell
python scripts/run_persona_scenarios.py --url "https://grok-bot-box.tail6cbb55.ts.net/mcp"
```

安裝 wheel 後的本機 stdio（`<python>` 必須是裝有本套件的乾淨環境）：

```powershell
python scripts/run_persona_scenarios.py --stdio-python "<python>" --data-dir "<正式資料根目錄>" --stdio-cwd "<專案外空目錄>"
```

矩陣真源是 `tests/scenarios/persona-scenarios-v1.json`；結構與公開 tool contract 由 `tests/test_persona_scenarios.py` 驗證。摘要證據保存在 `reports/persona-scenarios/`，原始 JSON 執行紀錄預設不進 Git。

## 還沒有被這次驗證證明的事

- macOS 一鍵安裝尚未在實體 Mac 完整執行。
- 公開 VM 整機重啟後的無人值守恢復仍未證明；應用程式 child process 的自動恢復已驗證。
- TFDA 分類審核覆蓋仍標示 `review_incomplete`；unknown 不會被升格為 IVD。
- 本次沒有發布新 GitHub Release 或正式資料包；release 仍依既有 review／publish gate。
