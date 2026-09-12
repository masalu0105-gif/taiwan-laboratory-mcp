# Taiwan Laboratory MCP

[![CI](https://github.com/masalu0105-gif/taiwan-laboratory-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/masalu0105-gif/taiwan-laboratory-mcp/actions/workflows/test.yml)

讓 AI Agent 查詢台灣醫檢工作常用的公開資料：**CDC 採檢送驗、NHI 檢驗支付、TFDA IVD 許可證**。

免費、開源，由 masalu.lab 發起。希望醫檢師第一次使用就能解決一個查資料的麻煩，願意分享給同事，也能帶進醫院、學會與 Workshop 的教學現場。

> **目前版本：0.1.1，P1 開發／教學示範版。** 已沿用原始 V0.1 ZIP 整合可安裝的 MCP server，內含 18 個工具與四組合成示範資料。**正式 CDC／NHI／TFDA 資料同步尚未實作**；目前所有查詢都會明示 `sample_only`，不可用於實際採檢、申報或採購。

## 三個先做好的問題

| 你想問的問題 | 預期取得的內容 | 官方入口 |
| --- | --- | --- |
| 「麻疹檢體怎麼採、怎麼送？」 | 檢體、時機、容器、保存、運送與送驗限制，附手冊版本及頁碼 | [CDC 採檢手冊](https://www.cdc.gov.tw/Category/Page/WV_GRwCIYrWQsEVa8ctTWg) |
| 「HbA1c 有哪些健保碼、支付幾點？」 | 代碼、名稱、支付點數、生效期間及相關規範 | [NHI 支付標準資料集](https://data.gov.tw/dataset/174450) |
| 「HPV DNA 有哪些相關 IVD 許可證？」 | 許可證、品名、效能、申請商、製造商、效期與註銷欄位 | [TFDA 許可證資料集](https://data.gov.tw/dataset/9576) |

## 使用時看得到資料根據

正式資料及查詢結果必須保留 `provenance`、`source_url`、`version`、`updated_at`。資料的發布時間、下載時間及查詢時間各自記錄；不知道的欄位明確標示未知。示範資料必須帶 `sample_only: true`，不能用來決定採檢、申報或採購。

CDC 結果須保留條件與例外；NHI 支付點數不能直接當成新臺幣金額；TFDA 許可證比對不能推論產品可互換。查不到資料時，說明搜尋範圍及資料狀態。實際作業仍需核對官方原文與適用的機構流程。

## 五分鐘開始（Windows PowerShell）

需先安裝 Python 3.10 以上與 Git。本專案尚未發布到 PyPI，請從此 repo 安裝。

```powershell
git clone https://github.com/masalu0105-gif/taiwan-laboratory-mcp.git
cd taiwan-laboratory-mcp
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
$env:PYTHONIOENCODING = 'utf-8'
.\.venv\Scripts\python.exe -m taiwan_lab_mcp.demo
```

Demo 應顯示 CDC 麻疹、NHI 糖化血色素及 TFDA HbA1c 的**示範**結果，包含 `sample_only: true`、來源及版本。尚未匯入的採檢條件與支付點數保留 `null`，不填入猜測值。

macOS／Linux 可用 `python3 -m venv .venv` 建立環境，再以 `.venv/bin/python` 執行相同安裝與 Demo 指令。

### 連接支援本機 stdio 的 MCP host

在 host 的 MCP 設定中加入下列內容，將 `command` 改成剛建立環境的 Python **完整路徑**。設定格式依各 host 而異；這裡提供常見的 `mcpServers` 範例，不會代替你修改 host 設定。

```json
{
  "mcpServers": {
    "taiwan-laboratory": {
      "command": "C:\\path\\to\\taiwan-laboratory-mcp\\.venv\\Scripts\\python.exe",
      "args": ["-m", "taiwan_lab_mcp.server"],
      "env": {
        "TAIWAN_LAB_DATA_MODE": "sample",
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

連接後先要求 host 呼叫 `get_data_status`，確認 `official_data_loaded: false`；再試「查詢 HbA1c 相關健保項目」。也可透過 `.venv/Scripts/taiwan-lab-mcp.exe` 啟動 stdio server。它會等待 host 傳入 MCP 訊息，直接在終端機開啟時沒有一般互動選單。

不需 API key，也不會呼叫外部模型或抓取官方資料。程式讀取環境變數，不自動載入 `.env`；此版只接受 `sample` 模式，其他值會停止啟動，避免誤以為已啟用正式資料。

## 工具清單

| 模組 | 工具 |
| --- | --- |
| 資料狀態 | `get_data_status` |
| CDC | `search_disease`、`get_specimen_requirement`、`get_collection_method`、`get_container`、`get_transport_requirement`、`get_submission_rule`、`find_authorized_lab`、`get_lab_scope` |
| NHI | `search_lab_code`、`get_points`、`get_payment_rule` |
| TFDA | `search_ivd`、`get_license`、`find_manufacturer`、`compare_products` |
| 保留介面 | `standards_status`、`eqa_status`；只回報尚未設定的狀態 |

CDC 的採檢、容器、運送等工具目前回傳同一完整疾病紀錄，保留原骨架的工具名稱與上下文。Sample 僅涵蓋麻疹、登革熱，以及示範用實驗室、HbA1c 健保項目和 IVD 各一筆。查 HPV DNA 會得到 `not_found` 與 sample 警示。

## 文件與參與

1. 閱讀 [使用場景](docs/use-cases.md) 與 [範例提問](examples/prompts.md)。
2. 查看 [資料來源與授權](docs/data-sources.md) 及 [架構與資料契約](docs/architecture.md)。
3. 想參與開發，先看 [貢獻指南](CONTRIBUTING.md)；想回報資料問題，使用 [Issues](https://github.com/masalu0105-gif/taiwan-laboratory-mcp/issues)。

原始 ZIP 的 SHA-256 與整合說明見 [骨架來源](docs/bootstrap.md)。Fixtures 的唯一正本放在 `src/taiwan_lab_mcp/data/`，會隨 Python package 安裝。

## P1 的範圍

先把上述三個查詢場景做到容易使用、可查來源、適合現場示範。LOINC、FHIR、SNOMED 僅保留 adapter interface；EQA／CAP 僅保留 adapter 與授權 TODO，未確認授權前不擷取 catalog。

院內資料、Data Cleaning、Hospital Data Readiness、去識別化及 LIS integration 的規劃見 [ROADMAP](ROADMAP.md)。P1 不需要病人資料，也不以收集使用者查詢內容或聯絡資料換取免費使用。

## 分享與教學合作

歡迎分享公開資料查詢的使用經驗、提出 Workshop 情境，或透過 [教學／需求 Issue](https://github.com/masalu0105-gif/taiwan-laboratory-mcp/issues/new?template=feature_request.yml) 聯絡 masalu.lab。請只提供適合公開的內容；Issue 為公開討論空間。

## 授權

專案程式與原創文件採 [MIT License](LICENSE)。外部資料依各自來源的授權使用，MIT 不替代政府資料或第三方資料的授權。本專案與 CDC、NHI、TFDA 無隸屬或官方背書關係。
