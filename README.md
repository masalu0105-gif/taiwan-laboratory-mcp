# Taiwan Laboratory MCP

[![CI](https://github.com/masalu0105-gif/taiwan-laboratory-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/masalu0105-gif/taiwan-laboratory-mcp/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/taiwan-laboratory-mcp)](https://pypi.org/project/taiwan-laboratory-mcp/)

讓 AI Agent 成為醫檢與法規人員的資料助理，直接查台灣三個最常翻的官方來源：**疾管署（CDC）採檢送驗、健保署（NHI）檢驗支付、食藥署（TFDA）IVD 許可證**。

過去要在三個網站之間切換、翻 PDF、對代碼；現在用自然語言問一句，Agent 就回你採檢條件、支付點數或許可證明細，並附上官方來源、資料版本與頁碼，方便直接核對。

**誰會用到**

- **醫檢師**：採檢前查檢體、容器與送驗規定；申報時查健保碼與點數。
- **法規／RA 人員**：查競品許可證、追蹤效期與註銷、比對申請商與製造商，做競品分析與許可證管控。
- **採購與業務**：確認產品是否有證、證在誰名下、對應哪些健保項目。
- **教學與訓練**：帶進醫院、學會與 Workshop，學生零安裝就能上手。

**為什麼能放心用**

- 四組資料全部來自政府開放資料與官方公告，不改寫、不推論。
- 每筆結果附 `provenance`、資料 snapshot 與原始位置，官方更新時自動比對換版。
- 24 個工具透過標準 MCP 協定提供，Claude、Cursor 等支援 MCP 的 host 都能接。
- 免費、開源（MIT），由 masalu.lab 發起與維護。

> **零安裝試用：把 MCP host 指向 `https://lab.masalulab.com/mcp`，立刻查四組正式資料。**

## 這些日常的痛，用問的就好

1. **特殊檢體不知道怎麼送**：以前翻疾管署手冊翻半天。現在問一句，檢體、容器、運送條件直接給你，附頁碼。
2. **院內做不了的傳染病項目，要送哪一家**：直接問哪些認可檢驗機構能做，名單跟範圍一次列出。
3. **健保申報要報哪個代碼、幾點**：某個項目或方法對應的代碼跟點數，不用再翻健保署那包檔案。
4. **申報條件搞不清楚**：這個項目多久能報一次、有什麼限制，直接問支付規範。
5. **競品調查**：某項目市場上有哪幾家廠商有證。以前查很久、驗證碼輸好幾次，現在一句話問完。
6. **業務拿來的許可證要確認**：證號查真偽、看在誰名下、有沒有註銷或快到期。
7. **自家證的效期盤點**：列出公司名下全部許可證，依效期排序，抓出半年內要展延的。
8. **新品送件前研究**：看同類產品的分類代碼與效能描述怎麼寫，找 predicate device。
9. **新供應商查核**：先查對方名下有幾張證、有沒有註銷紀錄，再決定要不要往下談。

## 你可以問什麼

| 你想問的問題 | 回答內容 | 官方入口 |
| --- | --- | --- |
| 「麻疹檢體怎麼採、怎麼送？」 | 檢體、時機、容器、保存、運送與送驗限制，附手冊版本及頁碼 | [CDC 採檢手冊](https://www.cdc.gov.tw/Category/Page/WV_GRwCIYrWQsEVa8ctTWg) |
| 「HbA1c 有哪些健保碼、支付幾點？」 | 代碼、名稱、支付點數、生效期間及相關規範 | [NHI 支付標準資料集](https://data.gov.tw/dataset/174450) |
| 「HPV DNA 有哪些相關 IVD 許可證？」 | 許可證、品名、效能、申請商、製造商、效期與註銷欄位 | [TFDA 許可證資料集](https://data.gov.tw/dataset/9576) |
| 「同類產品有哪幾家在賣、誰的證快到期？」 | 依品名或製造商列出競品許可證，含效期、註銷與申請商，適合法規人員做競品比較與許可證管控 | 同上 |

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

共 24 個工具，接上後呼叫 `get_data_status` 即可看到完整列表與各資料狀態。

| 模組 | 主要工具 |
| --- | --- |
| CDC | `search_disease`、`get_specimen_requirement`、`find_authorized_lab` |
| NHI | `search_payment_items`、`search_lab_code`、`get_points` |
| TFDA | `search_ivd`、`get_license`、`find_manufacturer`、`compare_products` |

搜尋類工具每次回 5 筆摘要，用 `offset` 翻頁；單筆完整欄位用 `get_*` 系列查。

## 文件與參與

- 上手：[使用場景](docs/use-cases.md)、[範例提問](examples/prompts.md)
- 深入：[資料來源與授權](docs/data-sources.md)、[架構與資料契約](docs/architecture.md)、[情境驗收](docs/persona-scenario-validation.md)
- 參與：[貢獻指南](CONTRIBUTING.md)、[Issues](https://github.com/masalu0105-gif/taiwan-laboratory-mcp/issues)、[接手事項](docs/next-steps.md)

## 範圍與路線

目前聚焦三個公開資料查詢場景。LOINC、FHIR、SNOMED、EQA／CAP 保留介面；院內資料與 LIS 整合見 [ROADMAP](ROADMAP.md)。歡迎透過 [Issue](https://github.com/masalu0105-gif/taiwan-laboratory-mcp/issues/new?template=feature_request.yml) 提出 Workshop 情境或需求。

## 使用建議

- 結果供查找與教學；採檢、申報、採購與醫療決策建議以官方原文為準。
- 公開端點會記錄查詢內容，建議不要輸入病人或院內資料；自架預設不記錄。
- `sample_only` 為示範資料；NHI 點數不宜直接換算金額，TFDA 比對不宜推論可互換。
- 本機資料不會自動更新；其餘見 [接手事項](docs/next-steps.md)。

## 授權

程式與原創文件採 [MIT License](LICENSE)。外部資料依各自來源授權使用，MIT 不替代政府或第三方資料的授權。本專案與 CDC、NHI、TFDA 無隸屬或官方背書關係。
