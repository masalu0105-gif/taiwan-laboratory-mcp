# Taiwan Laboratory MCP

[![CI](https://github.com/masalu0105-gif/taiwan-laboratory-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/masalu0105-gif/taiwan-laboratory-mcp/actions/workflows/test.yml)

讓 AI Agent 查詢台灣醫檢工作常用的公開資料：**CDC 採檢送驗、NHI 檢驗支付、TFDA IVD 許可證**。

免費、開源，由 masalu.lab 發起。希望醫檢師第一次使用就能解決一個查資料的麻煩，願意分享給同事，也能帶進醫院、學會與 Workshop 的教學現場。

> **最快的試法：不用安裝，把 MCP host 指向 `https://grok-bot-box.tail6cbb55.ts.net/mcp` 就能查四組正式資料。**（往下看〈最快的用法〉一節，含限制說明。）

> **目前基準版本：0.1.2**，已發布在 [PyPI](https://pypi.org/project/taiwan-laboratory-mcp/)，`uv tool install taiwan-laboratory-mcp` 一行裝好程式。Package 提供 24 個工具與合成示範資料。四組正式資料都可以從 Releases 下載安裝（見[安裝說明](docs/install.md)，有一鍵安裝腳本）：健保支付標準（專案負責人審核；檢驗範圍由 AI 審核，[審核紀錄](docs/reviews/nhi-lab-scope-ai-review-2026-09-14.md)）、食藥署醫療器材許可證（10 萬多筆全收錄、每筆標出是否屬體外診斷等標籤，由 AI 代審，[審核紀錄](docs/reviews/tfda-ivd-ai-review-2026-09-14.md)）、疾管署傳染病認可檢驗機構名冊，以及疾管署傳染病檢體採檢手冊（整本，含第 2 章採檢規定、第 7 章送驗地點與各章條文）。官方有新版時，專案負責人電腦上的每日排程會自動檢查，全部通過才換版，並自動發布新的下載包。安裝後的程式不會自動下載新版資料。不可用於實際採檢、申報或採購。

## 三個先做好的問題

| 你想問的問題 | 預期取得的內容 | 官方入口 |
| --- | --- | --- |
| 「麻疹檢體怎麼採、怎麼送？」 | 檢體、時機、容器、保存、運送與送驗限制，附手冊版本及頁碼 | [CDC 採檢手冊](https://www.cdc.gov.tw/Category/Page/WV_GRwCIYrWQsEVa8ctTWg) |
| 「HbA1c 有哪些健保碼、支付幾點？」 | 代碼、名稱、支付點數、生效期間及相關規範 | [NHI 支付標準資料集](https://data.gov.tw/dataset/174450) |
| 「HPV DNA 有哪些相關 IVD 許可證？」 | 許可證、品名、效能、申請商、製造商、效期與註銷欄位 | [TFDA 許可證資料集](https://data.gov.tw/dataset/9576) |

## 使用時看得到資料根據

正式資料及查詢結果必須保留 `provenance`、artifact hash、snapshot identity 與 locator。資料的發布時間、下載時間及查詢時間各自記錄；不知道的欄位明確標示未知。示範資料必須帶 `sample_only: true`，不能用來決定採檢、申報或採購。

CDC 結果須保留條件與例外；NHI 支付點數不能直接當成新臺幣金額；TFDA 許可證比對不能推論產品可互換。查不到資料時，說明搜尋範圍及資料狀態。實際作業仍需核對官方原文與適用的機構流程。

## 最快的用法：連公開網址，什麼都不用下載

四份正式資料已經放在一台雲端主機上。把支援 Streamable HTTP 的 MCP host 指向這個網址就能查：

`https://grok-bot-box.tail6cbb55.ts.net/mcp`

你的電腦不用裝程式、不用下載 600 MB 資料、不用申請任何金鑰。適合上課發給學生、臨時在別人電腦上示範，或只是想先試試看。

這個端點在 2026-09-22 從 VM 外部以真正 MCP client 驗證過 24 個工具與四組可追溯的正式 snapshot。主機端有 supervisor 看著服務，程式異常結束會自動重啟，主機重開也會跑一次自癒腳本。**資料本身不會自動更新**：主機上是部署當下的 snapshot，換新版要重新部署（每日檢查官方新版的排程跑在專案負責人自己的電腦上，產出的是 GitHub 下載包）。

匿名流量有每來源 IP 限流、256 KiB 請求上限、不快取回應及不記錄 HTTP access log；private deployment 另可要求 bearer token。公開端仍不應接收病人資料、院內資料、帳號密碼或其他機密內容。結果僅供公開資料查找，不能代替採檢、申報、採購或醫療決策。資料庫、排程與 MCP 查詢服務是 owner 自有工作流程；Grok Bot 條款只明確寫 internal business purposes，因此目前保留的條款不確定性只針對匿名公開端點是否落在該用語內，不把它誤寫成「代管資料庫」或已知違規，詳見[接手事項](docs/next-steps.md)。

## 想裝在自己電腦（Windows／macOS）

需要離線查、或想自己掌握資料版本，照 **[安裝說明](docs/install.md)** 做。最快的做法是用那份說明最前面的一鍵安裝腳本：它會下載四組資料、逐檔核對 SHA-256、裝進你指定的資料夾，並把設定加進 Claude 桌面版（先備份原檔）。想一步一步自己來，同一份說明底下有完整的手動步驟。

只要裝程式不要資料的話，`uv tool install taiwan-laboratory-mcp` 一行就好，跑起來是合成示範資料。

沒有裝的資料會回 `data_unavailable`，不影響其他已裝好的資料。

## 五分鐘看示範資料（Windows PowerShell）

套件在 PyPI 上，裝程式只要一行（不含正式資料，跑起來是合成示範資料）：

```powershell
uv tool install taiwan-laboratory-mcp
```

沒有 uv 也可以用 pip，需先安裝 Python 3.10 以上：

```powershell
python -m pip install taiwan-laboratory-mcp
$env:PYTHONIOENCODING = 'utf-8'
python -m taiwan_lab_mcp.demo
```

想從原始碼跑（需要 Git）：

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

連接後先要求 host 呼叫 `get_data_status`，確認各 source 的 `availability`、`coverage_status` 與 serving identity；再試「查詢 HbA1c 相關健保項目」。也可透過 `.venv/Scripts/taiwan-lab-mcp.exe` 啟動 stdio server。它會等待 host 傳入 MCP 訊息，直接在終端機開啟時沒有一般互動選單。

不需 API key，也不會呼叫外部模型或自動抓取官方資料。程式讀取環境變數，不自動載入 `.env`。`TAIWAN_LAB_DATA_MODE=sample` 使用合成 fixture；`official_snapshot` 必須搭配既有、可驗證的 `TAIWAN_LAB_DATA_DIR`，來源不可用時會 fail closed，絕不退回 sample。

資料工作流程目前提供 offline NHI candidate check：`taiwan-lab-data sync nhi_fee --input <csv> --data-dir <path> --json` 只讀取呼叫端明確提供的 CSV，將 validation report 寫入 `staged/`，不會自動發布或連網。另有明確 opt-in 的 `--publisher-oid <oid>` upstream discovery／fetch path；它仍只產生 `review_pending` candidate，不自動發布，且正式 source／owner qualification 尚未完成。發布仍需獨立的 review／publish gate。

## 工具清單

| 模組 | 工具 |
| --- | --- |
| 資料狀態 | `get_data_status` |
| CDC | `search_disease`、`get_specimen_requirement`、`get_collection_method`、`get_container`、`get_transport_requirement`、`get_submission_rule`、`find_authorized_lab`、`get_lab_scope` |
| NHI | `search_payment_items`、`search_lab_code`、`get_points`、`get_payment_rule` |
| TFDA | `search_reviewed_ivd`、`search_ivd_candidates`、`search_ivd`、`get_license`、`find_manufacturer`、`list_matching_license_records`、`compare_products` |
| 保留介面 | `standards_status`、`eqa_status`；只回報尚未設定的狀態 |

CDC 的採檢、容器、運送等工具目前回傳同一完整疾病紀錄，保留原骨架的工具名稱與上下文。Sample 僅涵蓋麻疹、登革熱，以及示範用實驗室、HbA1c 健保項目和 IVD 各一筆。查 HPV DNA 會得到 `not_found` 與 sample 警示。NHI official serving snapshot 目前只支援 current exact lookup、搜尋與分頁；`as_of` 歷史查詢會明確拒絕。搜尋一次最多 5 筆（要看更多用 `offset` 翻頁），每筆只回摘要（備註前 60 字），完整備註用 `get_payment_rule` 或 `get_points` 查單筆。每筆結果帶實驗室 scope 判定；資料內仍有未判定代碼時標示 `coverage_status=review_incomplete`。TFDA 搜尋同樣一次最多 5 筆、每筆只回摘要，完整欄位用 `get_license`；`list_matching_license_records` 查全部許可證（含已註銷、舊制與沒有分類代碼的），預設不偏任何類別。查詢結果不可直接當作醫療器材廣告或效能宣傳素材。

## 文件與參與

1. 閱讀 [使用場景](docs/use-cases.md) 與 [範例提問](examples/prompts.md)。
2. 查看 [資料來源與授權](docs/data-sources.md) 及 [架構與資料契約](docs/architecture.md)。
3. 想參與開發，先看 [貢獻指南](CONTRIBUTING.md)；想回報資料問題，使用 [Issues](https://github.com/masalu0105-gif/taiwan-laboratory-mcp/issues)。
4. 目前還沒做完、以及接手前要知道的事，見 [接下來要做的事](docs/next-steps.md)。
5. 查看 [10 種角色、100 題 MCP 情境驗收](docs/persona-scenario-validation.md)與可重跑的測試矩陣。

原始 ZIP 的 SHA-256 與整合說明見 [骨架來源](docs/bootstrap.md)。Fixtures 的唯一正本放在 `src/taiwan_lab_mcp/data/`，會隨 Python package 安裝。

## P1 的範圍

先把上述三個查詢場景做到容易使用、可查來源、適合現場示範。LOINC、FHIR、SNOMED 僅保留 adapter interface；EQA／CAP 僅保留 adapter 與授權 TODO，未確認授權前不擷取 catalog。

院內資料、Data Cleaning、Hospital Data Readiness、去識別化及 LIS integration 的規劃見 [ROADMAP](ROADMAP.md)。P1 不需要病人資料，也不以收集使用者查詢內容或聯絡資料換取免費使用。

## 分享與教學合作

歡迎分享公開資料查詢的使用經驗、提出 Workshop 情境，或透過 [教學／需求 Issue](https://github.com/masalu0105-gif/taiwan-laboratory-mcp/issues/new?template=feature_request.yml) 聯絡 masalu.lab。請只提供適合公開的內容；Issue 為公開討論空間。

## 授權

專案程式與原創文件採 [MIT License](LICENSE)。外部資料依各自來源的授權使用，MIT 不替代政府資料或第三方資料的授權。本專案與 CDC、NHI、TFDA 無隸屬或官方背書關係。
