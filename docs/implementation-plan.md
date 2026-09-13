# Taiwan Laboratory MCP P1.1 實作計畫書

文件狀態：Planning complete；implementation 尚未開始，public contract 以 PRD／SDD 為準
核對日期：2026-09-13（Asia/Taipei）
適用範圍：CDC 採檢送驗、NHI 檢驗支付、TFDA IVD 許可證公開資料

詳細來源調查：

- [NHI 資料來源調查](research/nhi-data-source.md)
- [TFDA 資料來源調查](research/tfda-data-source.md)
- [CDC 資料來源調查](research/cdc-data-source.md)

## 1. 計畫摘要

本階段要把現有 `sample_only` MCP 示範版，升級為可查詢、可追溯、可更新的台灣臨床檢驗公開資料工具。查詢服務採 **本機 snapshot 優先**：資料更新工作獨立下載官方來源、驗證、清理並產生版本化 snapshot；MCP runtime 只讀取最後一次通過驗證的資料，不在使用者查詢時臨時連網。

P1.1 先完成三個工作場景：

1. CDC：依第 2 章已確認的 8 個官方欄位查詢：傳染病名稱、採檢項目、採檢目的、採檢時間、採檢量及規定、送驗方式、應保存種類（應保存時間）、注意事項；複合欄保留原文，不另拆成容器、採法、感染性物質分類或送驗前保存指示。第 7 章送驗地點資料使用獨立 entity 與 schema。
2. NHI：查詢檢驗項目代碼、支付點數、生效期間及備註。
3. TFDA：查詢 IVD 相關許可證、有效日期、註銷狀態、申請商及製造商。

本階段不處理病人資料、LIS/HIS 串接、院內資料清理、診斷建議、申報自動送出或採購決策。LOINC、FHIR、SNOMED、EQA、CAP 維持現有保留介面，待授權及實際合作需求明確後再啟動。

## 2. 成功條件

- 三個來源皆能由可重跑的命令建立本機 snapshot，並保存來源 URL、取得時間、官方更新時間、授權及 SHA-256。
- 每筆 MCP 結果都能追溯至官方資料列，或 CDC 文件的版本與頁碼。
- 資料下載、解壓、欄位驗證或內容複核失敗時，不發布新 snapshot，也不靜默改回 sample。
- NHI 當期 snapshot 的代碼唯一性與非歷史查詢邊界、TFDA 許可證狀態與法人角色、CDC 同疾病不同檢驗方法的條件均不被錯誤合併。
- 由 5–10 位醫檢師完成指定任務測試，記錄任務完成率、來源核對成功率與推薦意願。

## 3. 官方資料來源

| 領域 | 官方入口 | 下載方式 | 官方宣告更新頻率 | 本階段判定 |
| --- | --- | --- | --- | --- |
| NHI | [醫療服務給付項目及支付標準 CSV](https://data.gov.tw/dataset/174450) | 匿名 GET；2026-09-13 實測為 UTF-8 BOM CSV、7 欄、6,173 筆 | 官方宣告每日；週末／假日實際 cadence 尚待 30 天觀測 | 適合第一條正式 vertical slice，但只含現行給付項目，不能回答完整歷史點數 |
| TFDA | [醫療器材許可證資料集](https://data.gov.tw/dataset/9576) | CSV／JSON／XML endpoint 均實測回 ZIP；三種格式皆為 34 欄、104,619 列 | 官方宣告每 7 日，未承諾固定星期 | 可自動匯入；許可證字號不是 row unique key，且需逐碼 IVD 篩選 |
| CDC 手冊 | [傳染病檢體採檢手冊](https://www.cdc.gov.tw/Category/Page/WV_GRwCIYrWQsEVa8ctTWg) | 現行 `1150826`：手冊 130 PDF 頁、修訂對照 29 頁，皆有文字層 | 官方明示不定時更新 | 需版面座標解析、人工校對及醫檢專業複核 |
| CDC 認可機構 | [傳染病認可檢驗機構](https://www.cdc.gov.tw/Category/Page/02d-tR1nzB8QuflX-NmM_w) | 現行 `1150909` ODS：12 欄、3,584 資料列、344 個證號 | 官方固定頻率未查得 | 需解析 merge spans；頁面日期不可當附件新鮮度 |

NHI 與 TFDA 資料集目前標示為免費並採「政府資料開放授權條款－第 1 版」。依[授權條款](https://data.gov.tw/license)，利用或產生衍生資料時須明確顯名；官方資料也不構成主管機關對本 MCP 的推薦、許可或核准。CDC PDF 的重製與內容使用條件需依個別文件及 CDC 網站規定另行確認，不能直接套用 NHI／TFDA 的授權。

### 3.1 下載前的來源確認

每次同步先讀資料集頁面的 resource URL、更新頻率、授權與詮釋資料，不把目前觀察到的下載網址永久視為不變。下載器允許 resource URL 由設定檔提供，但正式發布前必須保存本次實際使用的 URL。

## 4. 資料處理架構

```text
官方資料入口
    │
    ▼
fetch：下載至暫存檔、記錄 HTTP 與取得時間
    │
    ▼
verify：檔案類型、大小、解壓安全、SHA-256、必要欄位
    │
    ▼
raw snapshot：原檔唯讀保存，不修改
    │
    ▼
parse：依來源解析 CSV／ZIP／PDF
    │
    ▼
normalize：保留原值，另產生標準化欄位
    │
    ▼
validate：schema、日期、唯一鍵、角色、跨欄位規則
    │
    ├── 不合格 → quarantine + 報告，不發布
    │
    ▼
publish：原子替換 current manifest
    │
    ▼
MCP runtime：唯讀查詢最後一次通過驗證的 snapshot
```

建議資料層：

| 層級 | 用途 | Git 策略 |
| --- | --- | --- |
| `data/raw/<source>/<snapshot-id>/` | 官方原始檔、下載 metadata、SHA-256 | 預設不進 Git；保留下載重建能力 |
| `data/staged/<source>/<snapshot-id>/` | 解析後、尚未通過領域驗證的資料 | 不進 Git |
| `data/curated/<source>/<snapshot-id>/` | 通過驗證、供 MCP 查詢的資料 | 先評估大小與再散布條件；必要時改為 release artifact |
| `data/quarantine/<source>/<snapshot-id>/` | 異常列與錯誤原因 | 不進 Git；不得被 runtime 載入 |
| `data/manifests/` | 版本、雜湊、列數、授權、驗證結果 | 可進 Git，但不得含秘密或個資 |

先以 Python standard library 處理 HTTP、CSV、ZIP、JSON、日期與 SHA-256。CDC PDF qualification 依 SDD 指定的 LiteParse 工具契約執行。P1.1 official publish 禁止使用 OCR-derived rows；文字層不足時只能產生 staged candidate，未來若要發布 OCR 結果，必須先修訂 PRD／TDD 並重新審查。

## 5. 共用 provenance 契約

每個 snapshot 至少保存：

- `source_id`、提供機關、資料集或文件名稱。
- 官方入口 URL、實際下載 URL、取得時間與時區。
- 官方版本或官方更新時間；未提供時明確標示未知。
- 原始檔 SHA-256、檔案大小、格式、列數或頁數。
- 授權名稱、授權 URL、顯名文字。
- parser 版本、schema 版本、清理規則版本。
- 驗證結果、異常列數、quarantine 位置與是否可發布。

每筆 curated record 另保存來源定位資訊，例如 NHI 原始代碼與列識別、TFDA 許可證字號、CDC 文件版本／頁碼／表格列。原始值不得被標準化值覆寫。

## 6. 各來源下載與清理計畫

### 6.1 NHI：第一優先

#### 下載

1. 從資料集頁 metadata 解析或確認當期 CSV resource URL；目前實測端點為 `https://info.nhi.gov.tw/api/iode0000s01/Dataset?rId=A21030000I-D20021-001`。
2. 下載至暫存檔，計算 SHA-256，再以內容判斷實際格式與編碼。
3. 檢查必要欄位：診療項目代碼、支付點數、生效起日、生效迄日、中文名稱、英文名稱、備註。
4. 必要欄位與前一版完全不相容時停止發布，產生 schema drift 報告。

#### 清理

- 代碼一律保留字串，禁止轉數字造成前導零遺失。
- 保存原始欄名與原始文字；另做 Unicode normalization、外圍空白清理及搜尋用 normalized text。
- 支付點數解析為整數或明確缺值，不加入貨幣符號，也不換算成新台幣。
- 本資料集目前日期欄按 strict Gregorian `YYYYMMDD` 驗證並保留原字串；P1.1 不自行猜測民國日期或其他格式，格式 drift 時整批停止發布。
- 現行已驗證 schema 的生效迄日必須是 strict `YYYYMMDD`；空白屬 schema drift，整批停止發布。未來若官方 schema 明確允許空白，須先改版契約；即使允許也只能表示來源未提供，不可自行填入永久有效。
- 此資料集官方描述為「現行給付項目」，本次 6,173 筆代碼全部唯一。不可把它包裝成歷史版本資料庫；未來若另取得歷史來源，才允許同一代碼保留多個有效期間。
- 本次所有 `生效迄日` 都是 `29101231`；在官方或 owner 確認其 sentinel 語意前，保存原值並標記 inference，不對外解釋為永久有效。
- 備註保留完整原文；搜尋 alias 另存，不改寫正式名稱。
- 官方 CSV 沒有章、節、類別或「是否臨床檢驗」欄位。檢驗 scope 必須另建有官方 locator、規則版本及醫檢 reviewer 的 allowlist；只靠名稱 keyword 或代碼前綴不可上正式模式。

#### 驗證

- 代碼非空、支付點數型別正確、起日不得晚於迄日。
- 當前 snapshot 若出現重複代碼，視為 schema／語義變更並 block pending review，不能自動去重。
- `get_points` 只有 `as_of=null` 才查詢現行 snapshot；合法非空日期固定回 `historical_query_unsupported`，錯誤型別、空字串、格式錯誤或無效日期回 `invalid_request`。
- 空結果只能表示本 snapshot 未命中，不能回覆「健保不給付」。

### 6.2 TFDA：第二優先

#### 下載

1. 第一版固定使用官方 CSV endpoint，但傳輸層必須按 ZIP 驗證；CSV、JSON、XML 三個 endpoint 在 2026-09-13 均實測回 `application/zip`。
2. 驗證 ZIP signature、限制解壓總大小與檔案數，拒絕絕對路徑及 `..` 路徑，避免 zip-slip。
3. 記錄壓縮檔與解壓後資料檔各自 SHA-256。
4. 對照完整 34 欄 exact schema；缺欄、重複欄或欄名異動即停止發布。OAS 只作 drift 輔助，不能取代實際 ZIP/header 驗證。

#### 清理

- 許可證字號只能作 group key，不能作 row key。本次 104,619 列只有 93,219 個不同字號，11,229 個字號具有多列，最多 4 列；row key 建議使用 canonical raw row SHA-256。
- 註銷狀態、註銷日期及有效日期分欄保存；不能只用有效日期判斷仍有效。
- 申請商、製造商、製造廠地址及國別分開，禁止合併成單一 company 欄位。
- 品名、效能、規格及類別保留原文，另做不具臨床推論的搜尋索引。
- IVD 篩選先產出可審查規則表，記錄命中理由；低信心或規則衝突者進 review queue，不直接納入正式 IVD 結果。
- 不由相似品名或效能文字推論兩項產品臨床等效。

#### IVD 篩選規則的核准門檻

第一版規則應以官方現行分類附表的品項碼為主，建立版本化 `included`／`excluded`／`ambiguous` registry；文字關鍵字只作召回輔助。A／B／C 是應用科別分類，不是 `ivd=true`。例如 B.9225 明確屬 IVD，但 B.9195 與 B.9245 是實際存在於資料中的反例，不能因同屬 B 類就納入。規則需抽樣檢查真陽性與假陽性，並由熟悉 IVD 許可證的人員核准後才能標記為正式。未核准前只提供「醫療器材候選結果」，不可宣稱已完整涵蓋台灣 IVD。

### 6.3 CDC：第三優先

#### 下載

1. 先抓官方手冊頁，辨識最新版手冊及修訂對照表連結；不能永久寫死 `File/Get` token 或底層 PDF UUID。
2. 同時保存頁面 metadata、PDF 原檔、版本字串、頁面更新時間及 SHA-256。
3. 新版 PDF 與前一版雜湊不同時先進 staged，不直接覆蓋 current。
4. 版本名稱、頁面更新時間與 PDF 內版本若不一致，停止自動發布並要求人工確認。

#### 清理

- 現行兩份 PDF 均有文字層，但純文字順序會混合欄位。應使用 bounding boxes 與表格線重建；文字層缺失時只可產生 OCR staged candidate，不得進 P1.1 approved build。
- 以表格列為最小語意單位，保存官方原欄位及其關係。不得自行拆出來源未提供的通用「容器」或「保存」欄；`應保存種類（應保存時間）` 原值必須保留，並附 `not_pre_submission_storage=true`。
- 跨頁表格需保留 header lineage；沒有可靠表頭的列進 quarantine。
- 不把同一疾病的不同檢驗方法、不同檢體或不同採檢時機合併成通用答案。
- 保存 PDF 頁碼、印刷頁碼、表格名稱、列號及原文片段，normalized 欄位只用於搜尋。現行手冊末頁可見「第 120 頁／共 119 頁」的不一致，因此兩種頁碼都不能省略。
- 修訂對照表用來標記新增、修改、刪除項目，不自行推論沒有列出的變更。

#### 人工與專業複核

CDC 每次新版本至少需完成：

1. parser 產出的結構化差異報告。
2. 人工核對所有變更列及抽樣未變更列。
3. 醫檢專業人員核對關鍵條件與頁碼。
4. reviewer、日期及決議寫入 manifest。

未完成專業複核的資料須回傳 `review_pending` 或維持上一個已核准 snapshot，不能標記為已確認的最新版。

#### CDC 認可檢驗機構 ODS

- 從官方 landing page 每次重新發現附件；頁面顯示日期與附件版本已證實可能脫鉤。
- 只讀實際工作表的已知 12 欄。ODS 雖宣告到 16,384 欄，第 13 欄後為重複空白，不得無限制展開。
- 依 `number-rows-spanned`／`covered-table-cell` 重建垂直合併內容，但禁止對所有空白欄 blanket forward-fill。
- 證號是機構 group key，方法／疾病／能力試驗等子列仍需保留；不可把 3,584 列錯誤壓成 344 列。
- 官方固定更新頻率仍為 UNVERIFIED；產品端每日 polling 是監控策略，不得寫成官方每日更新。

## 7. MCP 查詢層調整

現有程式與 wheel 仍是 `0.1.1` sample-only；下列能力全部為 **PLANNED**，沒有 executable official-mode evidence。Public operation、status、freshness 與 safety fields 的唯一真源是 `docs/product-requirements.md`，實作後的 machine-readable 真源為規劃中的 `src/taiwan_lab_mcp/contracts/public-contract-v1.json`：

- `data_mode` 支援 `sample` 與 `official_snapshot`。
- `sample_only` 依資料來源為 `true` 或 `false`，維持 strict boolean。
- 增加 PRD 定義的 `snapshot_id`、`retrieved_at`、`serving_validation_status`、`serving_review_status`、`latest_candidate_status`、`stale` 與 `stale_reason_codes[]`；禁止另建同義 public keys。
- `get_data_status` 回報每個來源最後成功同步、官方更新時間、目前 snapshot、驗證結果及同步錯誤。
- 查詢不得混合 sample 與 official records；若使用者明確進入 sample mode，所有結果繼續顯示示範警示。

若沒有通過驗證的 official snapshot，正式模式應明確失敗或回報 unavailable。下載失敗時可以繼續提供上一個已驗證 snapshot，但必須標記 stale，並顯示最後成功同步時間與失敗原因。

## 8. 測試與品質門檻

### 自動測試

- 下載：timeout、非預期 MIME、空檔、截斷檔、HTTP 錯誤與 URL 變更。
- 安全：ZIP 路徑穿越、解壓大小限制、檔案數限制及不支援格式。
- Schema：缺欄、改名、重複欄、編碼及日期錯誤。
- 領域：NHI 當期重複 code 整批 block、`as_of` 明確 unsupported；TFDA 註銷與效期依 PRD truth table 分欄；CDC 方法／檢體關係不可交叉污染。
- 發布：驗證失敗不改 current manifest；更新採原子替換；runtime 不讀 staged 或 quarantine。
- MCP：tool discovery、三領域正式查詢、空結果、stale 狀態及 provenance 完整性。

### 人工驗收

每個領域至少準備 10 個可從官方來源核對的 golden cases。CDC 第 2 章 golden cases 必須涵蓋同疾病多採檢項目或目的；NHI 涵蓋日期欄與 historical-query rejection 邊界；TFDA 涵蓋 validity period、註銷及法人角色差異。

## 9. 分期與預估

| 階段 | 內容 | 預估工作量 | 交付門檻 |
| --- | --- | --- | --- |
| A | 共用 snapshot、manifest、official mode、fail-closed publish | 2–3 個工作日 | 模擬同步失敗不污染 current；MCP 可回報資料狀態 |
| B | NHI 下載、7 欄 parser、scope allowlist 與測試 | 4–6 個工作日 | NHI golden cases 通過；scope 尚未核准時仍可服務，但 mapping 保留 locator 且固定 `coverage_status=review_incomplete` |
| C | TFDA ZIP、34 欄 schema、row identity、IVD registry 與複核 | 6–10 個工作日 | IVD registry 有抽樣報告及 owner 核准 |
| D | CDC PDF／ODS 解析、差異、雙頁碼與專業複核流程 | 9–15 個工作日 | PDF 與 ODS golden cases、專業複核完成 |
| E | MCP 整合、文件、Demo、5–10 人試用 | 3–5 個工作日，加受測者排程 | 任務、來源核對與推薦意願有紀錄 |

以上 24–39 個工作日只涵蓋工程實作粗估，不是 release commitment。另需預留 source qualification、第二人重算、out-of-tree wheel E2E、醫檢／IVD reviewer、owner gates、授權決策、修正與受測者排程；這些等待時間可能超過工程本身。建議每完成一個資料來源就發布明確標示範圍的測試版本，不等三個來源全部完成才第一次驗收。

## 10. 建議實作順序

1. 先寫一頁 snapshot／manifest schema，並將 `ToolResult` 從 sample-only 契約擴充為雙模式。
2. 用 NHI 建立第一條端到端管線，證明下載、raw、curated、publish、MCP 查詢及 stale handling。
3. 沿用同一套共用框架加入 TFDA，但將 ZIP 安全與 IVD 規則放在 TFDA adapter 內。
4. 最後加入 CDC PDF parser 與人工複核，不為了共用而扭曲三種來源差異。
5. 完成試用、修正高風險問題，再決定 0.2.0 發布。

## 11. 開始開發前需決定的事項

- Curated official snapshots 是否隨 GitHub Release 發布，或只提供同步工具讓使用者自行建立；此決定需依資料大小與再散布條件核對。
- NHI laboratory scope allowlist 的官方依據與 reviewer；未核准前只能查完整現行給付資料或維持候選模式。
- TFDA IVD 正式篩選規則由誰擔任 owner 與 reviewer。
- CDC 專業複核者、核准紀錄格式與更新時的 turnaround time。
- P1.1 是否只支援 Windows／本機 stdio，或同時承諾 macOS、Linux 與容器。

在上述事項尚未定案前，可以先完成共用資料契約與 NHI importer；這兩項不依賴 TFDA／CDC 的領域裁決。

## 12. 參考資料

- [政府資料開放平臺：醫療服務給付項目及支付標準 CSV](https://data.gov.tw/dataset/174450)
- [政府資料開放平臺：醫療器材許可證資料集](https://data.gov.tw/dataset/9576)
- [TFDA Open Data API 說明入口（InfoId 68）](https://data.fda.gov.tw/opendata/exportDataList.do?method=openDataApi&InfoId=68)
- [衛生福利部疾病管制署：傳染病檢體採檢手冊](https://www.cdc.gov.tw/Category/Page/WV_GRwCIYrWQsEVa8ctTWg)
- [政府資料開放授權條款－第 1 版](https://data.gov.tw/license)
