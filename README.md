# Taiwan Laboratory MCP

[![CI](https://github.com/masalu0105-gif/taiwan-laboratory-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/masalu0105-gif/taiwan-laboratory-mcp/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/taiwan-laboratory-mcp)](https://pypi.org/project/taiwan-laboratory-mcp/)

讓 AI Agent 直接查台灣醫檢工作最常用的三種公開資料：**CDC 採檢送驗、NHI 檢驗支付、TFDA IVD 許可證**。

免費、開源，由 masalu.lab 發起。目標是讓醫檢師第一次使用就少查一次資料，願意分享給同事，也能帶進醫院、學會與 Workshop 的教學現場。

> **零安裝試用：把 MCP host 指向 `https://lab.masalulab.com/mcp`，立刻查四組正式資料。**

## 你可以問什麼

| 你想問的問題 | 回答內容 | 官方入口 |
| --- | --- | --- |
| 「麻疹檢體怎麼採、怎麼送？」 | 檢體、時機、容器、保存、運送與送驗限制，附手冊版本及頁碼 | [CDC 採檢手冊](https://www.cdc.gov.tw/Category/Page/WV_GRwCIYrWQsEVa8ctTWg) |
| 「HbA1c 有哪些健保碼、支付幾點？」 | 代碼、名稱、支付點數、生效期間及相關規範 | [NHI 支付標準資料集](https://data.gov.tw/dataset/174450) |
| 「HPV DNA 有哪些相關 IVD 許可證？」 | 許可證、品名、效能、申請商、製造商、效期與註銷欄位 | [TFDA 許可證資料集](https://data.gov.tw/dataset/9576) |

更多情境見 [使用場景](docs/use-cases.md) 與 [範例提問](examples/prompts.md)。

## 四組正式資料

| 資料 | 內容 |
| --- | --- |
| 健保支付標準 | 全部檢驗支付項目，每筆附實驗室 scope 判定 |
| 食藥署醫療器材許可證 | 10 萬多筆全收錄，每筆標出是否屬體外診斷 |
| 疾管署認可檢驗機構名冊 | 傳染病認可檢驗機構與檢驗範圍 |
| 疾管署檢體採檢手冊 | 整本，含第 2 章採檢規定、第 7 章送驗地點與各章條文 |

官方有新版時，每日排程自動檢查、全部通過才換版，並自動發布新的 Release 下載包。

**每個結果都看得到根據。** 查詢結果保留 `provenance`、artifact hash、snapshot identity 與 locator；資料的發布時間、下載時間及查詢時間各自記錄，不知道的欄位明確標示未知。

## 最快的用法：連公開網址

把支援 Streamable HTTP 的 MCP host 指向：

`https://lab.masalulab.com/mcp`

遠端連線即可使用，適合上課、示範或先試試看。

這個端點在 2026-09-22 從外部以真正 MCP client 驗證過 24 個工具與四組可追溯的正式 snapshot。主機端有 supervisor 守著服務，異常會自動重啟；資料每天台北時間 10:30 自動比對最新 Release，每個檔案都核對 SHA-256，換版後自我檢查，服務不中斷。

匿名流量有每來源 IP 限流與 256 KiB 請求上限；private deployment 另可要求 bearer token。

## 裝在自己電腦（Windows／macOS）

需要離線查、或想自己掌握資料版本，照 **[安裝說明](docs/install.md)** 做。最快是用說明最前面的一鍵安裝腳本：下載四組資料、逐檔核對 SHA-256、裝進指定資料夾，並把設定加進 Claude 桌面版（先備份原檔）。

只裝程式、先看示範資料的話，一行就好：

```powershell
uv tool install taiwan-laboratory-mcp
```

沒有 uv 也可以用 pip（需 Python 3.10 以上）：

```powershell
python -m pip install taiwan-laboratory-mcp
$env:PYTHONIOENCODING = 'utf-8'
python -m taiwan_lab_mcp.demo
```

從原始碼跑：

```powershell
git clone https://github.com/masalu0105-gif/taiwan-laboratory-mcp.git
cd taiwan-laboratory-mcp
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
$env:PYTHONIOENCODING = 'utf-8'
.\.venv\Scripts\python.exe -m taiwan_lab_mcp.demo
```

Demo 會顯示 CDC 麻疹、NHI 糖化血色素及 TFDA HbA1c 的示範結果，包含 `sample_only: true`、來源及版本。macOS／Linux 用 `python3 -m venv .venv` 建環境，再以 `.venv/bin/python` 執行相同指令。

### 連接本機 stdio 的 MCP host

在 host 的 MCP 設定加入下列內容，`command` 改成剛建立環境的 Python 完整路徑：

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

連接後先請 host 呼叫 `get_data_status` 確認各 source 的狀態，再試「查詢 HbA1c 相關健保項目」。

本機執行，資料全在本地。`TAIWAN_LAB_DATA_MODE=sample` 使用合成 fixture；`official_snapshot` 搭配 `TAIWAN_LAB_DATA_DIR` 使用正式資料，來源不可用時 fail closed，不會退回 sample。沒裝的資料回 `data_unavailable`，不影響其他資料。

資料工作流程另提供 offline NHI candidate check（`taiwan-lab-data sync nhi_fee`），只讀取明確提供的 CSV、只產生 `review_pending` candidate，發布需獨立 review／publish gate。

## 工具清單

| 模組 | 工具 |
| --- | --- |
| 資料狀態 | `get_data_status` |
| CDC | `search_disease`、`get_specimen_requirement`、`get_collection_method`、`get_container`、`get_transport_requirement`、`get_submission_rule`、`find_authorized_lab`、`get_lab_scope` |
| NHI | `search_payment_items`、`search_lab_code`、`get_points`、`get_payment_rule` |
| TFDA | `search_reviewed_ivd`、`search_ivd_candidates`、`search_ivd`、`get_license`、`find_manufacturer`、`list_matching_license_records`、`compare_products` |
| 保留介面 | `standards_status`、`eqa_status` |

搜尋類工具一次回 5 筆摘要，用 `offset` 翻頁；完整欄位用 `get_payment_rule`、`get_points`、`get_license` 查單筆。`list_matching_license_records` 查全部許可證（含已註銷、舊制與沒有分類代碼的）。

## 文件與參與

1. [使用場景](docs/use-cases.md)、[範例提問](examples/prompts.md)
2. [資料來源與授權](docs/data-sources.md)、[架構與資料契約](docs/architecture.md)
3. [10 種角色、100 題 MCP 情境驗收](docs/persona-scenario-validation.md)
4. 想參與開發，先看 [貢獻指南](CONTRIBUTING.md)；資料問題請開 [Issue](https://github.com/masalu0105-gif/taiwan-laboratory-mcp/issues)
5. 接手前要知道的事：[接下來要做的事](docs/next-steps.md)

原始 ZIP 的 SHA-256 與整合說明見 [骨架來源](docs/bootstrap.md)。Fixtures 正本放在 `src/taiwan_lab_mcp/data/`，隨 package 安裝。

## 範圍與路線

P1 先把三個查詢場景做到容易使用、可查來源、適合現場示範。LOINC、FHIR、SNOMED 保留 adapter interface；EQA／CAP 保留 adapter 與授權 TODO。院內資料、去識別化及 LIS integration 的規劃見 [ROADMAP](ROADMAP.md)。P1 不需要病人資料，也不以收集使用者查詢內容換取免費使用。

歡迎分享使用經驗、提出 Workshop 情境，或透過 [教學／需求 Issue](https://github.com/masalu0105-gif/taiwan-laboratory-mcp/issues/new?template=feature_request.yml) 聯絡 masalu.lab。

## 使用建議

- **用途**：結果適合公開資料查找與教學示範；實際採檢、申報、採購或醫療決策，建議仍以官方原文與機構流程為準。
- **公開端點**：為了改善服務，端點會記錄查詢時間、來源 IP、工具名稱、查詢內容與回應狀態（不含請求標頭）。建議不要在公開端輸入病人資料、院內資料或帳號密碼；自架時套件預設不記錄，需設 `TAIWAN_LAB_HTTP_USAGE_LOG` 才會開。
- **示範資料**：`sample_only: true` 的結果只涵蓋麻疹、登革熱與各一筆示範項目，建議只用於熟悉工具，不建議據以決策。
- **資料解讀**：NHI 支付點數建議不要直接換算成新臺幣；TFDA 許可證比對建議不要推論產品可互換，也不建議作為廣告或效能宣傳素材。NHI 目前提供 current lookup，`as_of` 歷史查詢會明確回覆不支援。
- **更新機制**：Release 由專案負責人電腦上的每日排程產生，該機器未開機時當天不會有新版；本機安裝後的資料不會自動更新。其餘接手事項與條款待釐清處見 [接手事項](docs/next-steps.md)。

## 授權

程式與原創文件採 [MIT License](LICENSE)。外部資料依各自來源授權使用，MIT 不替代政府或第三方資料的授權。本專案與 CDC、NHI、TFDA 無隸屬或官方背書關係。
