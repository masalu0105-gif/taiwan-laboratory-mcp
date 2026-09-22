# 架構與資料契約

> 目前實作仍以 package version `0.1.1` 發布，但已包含 P1.1 的雙模式 runtime、四組正式資料管線與 fail-closed 發布邊界。規範真源是 `docs/product-requirements.md`、`docs/software-design.md`、`docs/test-driven-development.md`；machine-readable 真源是 `src/taiwan_lab_mcp/contracts/public-contract-v1.json`。

<!-- public-contract-operations: 24 -->

MCP 目前公開 24 個工具。sample mode 使用 package 內合成資料；`official_snapshot` mode 只讀 repo 外已審核且完整性驗證通過的 snapshot。正式資料不存在、損壞或未通過 serving gate 時回報 unavailable／blocked，不會退回 sample。

## 最小架構

```text
MCP host / AI Agent
        │ stdio 或 streamable HTTP
        ▼
Python MCP server（同一份 24-tool registry）
        │
        ├── sample mode ─────── package 內合成 fixtures
        └── official_snapshot ─ repo 外 current manifest
                                      │
                                      ├── NHI 支付標準
                                      ├── TFDA 醫材許可證
                                      ├── CDC 認可檢驗機構
                                      └── CDC 採檢手冊
```

`server.py` 依 public contract 註冊 24 個工具；stdio 與 HTTP transport 共用同一個 server registry。`adapters/base.py` 驗證資料模式，`models.py` 驗證 public response 與 provenance，來源專屬 importer／store／autoupdate 模組負責建立與切換 snapshot。資料不依賴目前工作目錄，也沒有向量資料庫或模型 API 呼叫。

官方 [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) 與 [PyPI](https://pypi.org/project/mcp/) 於 2026-09-12 核對為 v2 穩定系列，PyPI 版本 2.2.0。原骨架整合時仍須以實際 import、stdio 啟動和 client 呼叫驗證相容性。

## 查詢結果

查詢結果明確帶 `data_mode`、`sample_only`、來源狀態與警示。sample 命中固定為 `sample_only: true`；正式命中固定為 `sample_only: false` 並綁定 snapshot identity、artifact hash、locator 與 provenance。`not_found` 只代表該 snapshot 與搜尋條件未命中；不得衍生成「台灣沒有核准產品」「不能給付」或「沒有這種送驗方式」。

每筆紀錄保留 `provenance`、`source_url`、`version`、`updated_at`、`sample_only`。正式資料另由 current manifest、immutable build identity 與 review evidence 控制 serving；結構驗證或自動測試通過仍不等於新的官方版本、臨床內容或發布已獲核准。產品比較維持停用，空結果保留來源、資料狀態及限制。

### 三個領域的保真原則

| 領域 | 不可省略的關係 | 驗收重點 |
| --- | --- | --- |
| CDC | 疾病、檢驗方法、檢體、採檢時機、容器、保存與運送條件的對應 | 同一表格不同列不能合併成通用要求；每個實際值可回到文件頁碼 |
| NHI | 代碼、名稱、點數、生效起迄、備註 | 代碼保留字串；日期邊界明確；多版本不能任取一筆；點數維持點數單位 |
| TFDA | 許可證、有效日期、註銷資訊、效能、申請商及製造商角色 | 不能只看有效日期宣稱仍核准；產品比較不能推論臨床等效 |

中文／英文 alias 可以改善搜尋，不能抹掉方法、檢體或法人角色差異。缺值、未提供與不適用要可區分。來源欄位與原文保留；整理後值另行存放。

## Samples 與正式資料

所有 fixtures 都帶 `sample_only: true`，缺少此欄位或填入字串 `"true"` 都會被拒收。`TAIWAN_LAB_DATA_MODE` 只接受 `sample` 或 `official_snapshot`；official mode 需要明確的 data root，runtime 只讀 current manifest 指向的 curated build。工具呼叫不會臨時下載官方資料，official unavailable 也不會網路回退或混用 sample。

正式同步走 raw → staged → curated／quarantine：下載與 schema 驗證失敗不改 current；新 candidate 未通過 review／publish gate 時維持上一個已核准 snapshot並揭露 stale／pending 狀態。原始檔、正式資料庫與 current pointer 都在 repo 外，package 只帶 contract、schema、rules、review protocols 與 sample fixtures。

## Adapter 邊界

LOINC／FHIR／SNOMED 使用小型 interface 表達未來查詢契約；未設定 provider 時回報尚未啟用。EQA／CAP 同樣只留 interface 與授權 TODO。P1 不提供自動 mapping、FHIR 驗證、catalog 同步或隱藏的網路呼叫。

## 驗證範圍

1. 乾淨環境安裝 wheel，從 repo 以外的工作目錄啟動，確認 package data 隨安裝可用。
2. 透過真正的 MCP client 完成初始化、工具列舉及 CDC／NHI／TFDA 各一次呼叫。
3. 測試查無資料、空白／非法輸入、來源欄位保留及 sample 警示。
4. 驗證資料載入失敗不會回傳假成功、樣本或未驗證的官方值。
5. CI 與本機使用相同測試指令；結果引用實際 run 與 commit。
