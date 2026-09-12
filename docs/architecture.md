# 架構與資料契約

目前為以原 V0.1 ZIP 整合的 0.1.1 開發／教學示範版。MCP 與 samples 已實作；正式資料同步與領域內容複核仍待完成。

## 最小架構

```text
MCP host / AI Agent
        │ stdio
        ▼
Python MCP server
        │
        ├── CDC 採檢送驗查詢
        ├── NHI 檢驗支付查詢
        └── TFDA IVD 查詢
                 │
                 ▼
       經驗證的資料與來源欄位
```

沿用原骨架的 `src/taiwan_lab_mcp/adapters/{cdc,nhi,tfda}.py` 與官方 MCP Python SDK。`server.py` 註冊 18 個工具；`adapters/base.py` 驗證環境模式並載入 package 內的 JSON samples；`models.py` 定義 metadata 契約。資料不依賴目前工作目錄。正式資料同步將獨立於工具呼叫；目前沒有雲端資料庫、向量資料庫或模型 API 呼叫。

官方 [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) 與 [PyPI](https://pypi.org/project/mcp/) 於 2026-09-12 核對為 v2 穩定系列，PyPI 版本 2.2.0。原骨架整合時仍須以實際 import、stdio 啟動和 client 呼叫驗證相容性。

## 查詢結果

查詢結果以 `status: sample_only` 或 `not_found` 標記是否命中，且兩者一律附 `data_mode: sample`、`sample_only: true` 及警示。`get_data_status` 回報 `official_data_loaded: false`。`not_found` 僅代表在本次資料範圍內未找到；不得衍生成「台灣沒有核准產品」「不能給付」或「沒有這種送驗方式」。

每筆紀錄保留 `provenance`、`source_url`、`version`、`updated_at`、`sample_only`。`DataRecord` 驗證頂層來源欄位與 provenance 一致；未提供更新時間時需附未知說明。正式紀錄的契約要求取得時間、授權與非合成的處理方式。這只驗證資料結構，尚未實作正式資料載入，也不等於來源、授權或醫學內容已核准。產品比較與空結果都保留來源、樣本狀態及限制。

### 三個領域的保真原則

| 領域 | 不可省略的關係 | 驗收重點 |
| --- | --- | --- |
| CDC | 疾病、檢驗方法、檢體、採檢時機、容器、保存與運送條件的對應 | 同一表格不同列不能合併成通用要求；每個實際值可回到文件頁碼 |
| NHI | 代碼、名稱、點數、生效起迄、備註 | 代碼保留字串；日期邊界明確；多版本不能任取一筆；點數維持點數單位 |
| TFDA | 許可證、有效日期、註銷資訊、效能、申請商及製造商角色 | 不能只看有效日期宣稱仍核准；產品比較不能推論臨床等效 |

中文／英文 alias 可以改善搜尋，不能抹掉方法、檢體或法人角色差異。缺值、未提供與不適用要可區分。來源欄位與原文保留；整理後值另行存放。

## Samples 與正式資料

所有 fixtures 都帶 `sample_only: true`，缺少此欄位或填入字串 `"true"` 都會被拒收。`TAIWAN_LAB_DATA_MODE` 只接受 `sample`，其他值使啟動失敗；正式模式尚未實作。此版不自動載入 `.env`，也沒有遠端抓取與網路回退。未來正式模式必須沿用資料契約，並另測查無資料與同步失敗的行為。

## Adapter 邊界

LOINC／FHIR／SNOMED 使用小型 interface 表達未來查詢契約；未設定 provider 時回報尚未啟用。EQA／CAP 同樣只留 interface 與授權 TODO。P1 不提供自動 mapping、FHIR 驗證、catalog 同步或隱藏的網路呼叫。

## 驗證範圍

1. 乾淨環境安裝 wheel，從 repo 以外的工作目錄啟動，確認 package data 隨安裝可用。
2. 透過真正的 MCP client 完成初始化、工具列舉及 CDC／NHI／TFDA 各一次呼叫。
3. 測試查無資料、空白／非法輸入、來源欄位保留及 sample 警示。
4. 驗證資料載入失敗不會回傳假成功、樣本或未驗證的官方值。
5. CI 與本機使用相同測試指令；結果引用實際 run 與 commit。
