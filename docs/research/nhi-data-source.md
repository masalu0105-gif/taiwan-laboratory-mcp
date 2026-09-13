# NHI 醫療服務給付項目資料源研究

文件狀態：Research complete; implementation governed by PRD/SDD

核對日期：2026-09-13（Asia/Taipei）

資料提供者：衛生福利部中央健康保險署
研究範圍：公開的「醫療服務給付項目及支付標準 CSV」及直接相關的一手入口；不含病人、申報或院內資料

## 1. 結論先行

這份 CSV 適合做 Taiwan Laboratory MCP 的第一條正式資料管線，因為下載端點可匿名取得、格式規則清楚、只有 7 欄，而且官方宣告每日更新。2026-09-13 實際下載得到 UTF-8 BOM CSV，6,173 筆資料、1,725,985 bytes，兩次下載的 SHA-256 相同。

不過產品範圍必須先修正兩個假設：

1. 官方描述明確寫的是「**現行給付項目**」。目前 6,173 筆的診療項目代碼全部唯一，並非同碼多歷史版本資料庫；因此它可回答目前 snapshot 中的代碼與點數，不能單靠此檔可靠回答任意歷史日期的舊點數。
2. CSV 是全部醫療服務項目，沒有「檢驗／實驗室」分類欄。不能只憑代碼前綴或名稱關鍵字，就宣稱得到完整 laboratory 子集；需要另外維護有官方章節或清單定位、且經領域 reviewer 核准的 scope mapping。

實作行為以 [PRD §5.3、§6.2](../product-requirements.md) 與 [SDD §10.1](../software-design.md) 為準：`search_payment_items` 永遠搜尋 serving snapshot 全表，依代碼、官方名稱與 approved alias 回傳候選，每筆明確回 `scope_status`；scope registry 只影響 scope／coverage 陳述，不得作為這個全表 operation 的過濾 gate。未核准前，不宣稱查詢已完整涵蓋所有健保檢驗項目。

## 2. 證據等級

- **VERIFIED—官方 metadata**：政府資料開放平臺頁面與 JSON、健保署資料開放平臺頁面與 JSON。
- **VERIFIED—實檔**：2026-09-13 00:55（Asia/Taipei）由官方 resource URL 下載並以標準 CSV parser 檢查。
- **INFERENCE**：根據實檔分布判讀、但官方欄位說明沒有明文定義的語意，例如所有 `29101231` 很可能是遠期／未定終止日 sentinel。
- **RECOMMENDATION**：本文件提出的清理與 schema drift 建議不是健保署官方規則；public status／freshness 行為只引用 PRD／SDD，不在研究文件另設第二套門檻。
- **UNVERIFIED**：尚未找到一份官方、機器可讀、完整且現行的 laboratory scope 分類表，也未以跨多日樣本實證「每日」實際更新是否含週末及國定假日。

## 3. 官方入口與實際下載端點

| 用途 | URL | 2026-09-13 核對結果 |
| --- | --- | --- |
| 政府資料開放平臺資料集頁 | [醫療服務給付項目及支付標準(csv檔)](https://data.gov.tw/dataset/174450) | 顯示提供機關、7 欄、每 1 日、免費、政府資料開放授權條款第 1 版 |
| 政府資料機器可讀 metadata | [dataset 174450 JSON](https://data.gov.tw/api/v2/rest/dataset/174450) | `success=true`；identifier `A21030000I-D20021`；resource URL、UTF-8、CSV、更新時間均可讀 |
| 健保署資料開放平臺頁 | [dataset id 1381](https://info.nhi.gov.tw/IODE0000/IODE0000S09?id=1381) | 前端頁面本身由 JavaScript 載入資料 |
| 健保署 dataset detail JSON | [SQL009?datasetId=1381](https://info.nhi.gov.tw/api/iode0000s01/SQL009?datasetId=1381) | 顯示 `numberofdata=6173`、每日、UTF-8、resource id 與 `resourcemodified=2026年09月12日` |
| 實際 CSV resource | [A21030000I-D20021-001](https://info.nhi.gov.tw/api/iode0000s01/Dataset?rId=A21030000I-D20021-001) | 匿名 GET 成功；回傳附件 CSV，不是逐筆查詢 API |
| 健保署支付標準總入口 | [全民健康保險醫療服務給付項目及支付標準](https://www.nhi.gov.tw/ch/lp-3778-1.html) | 官方頁面將「醫療服務給付項目」導向上述資料開放平臺 |
| 人工查核介面 | [支付標準查詢](https://info.nhi.gov.tw/INAE5000/INAE5001S0) | 適合人工 spot check；本研究未把 UI 當自動同步來源 |
| 授權全文 | [政府資料開放授權條款－第 1 版](https://data.gov.tw/license) | 可利用與再授權，但必須顯名；不得暗示官方推薦、許可或核准 |

### 3.1 下載時不要寫死 resource URL

目前 URL 為：

```text
https://info.nhi.gov.tw/api/iode0000s01/Dataset?rId=A21030000I-D20021-001
```

同步器每次應先 GET `https://data.gov.tw/api/v2/rest/dataset/174450`，確認：

- `publisherOID`、`identifier`、`license` 與預期一致。
- `distribution` 中存在 `resourceFormat=CSV`。
- `resourceCharacterEncoding=UTF-8`。
- 從當次 metadata 取 `resourceDownloadUrl`，並把實際 URL 寫入 manifest。

resource id 或網域變更時先停止自動發布、產生 drift report；不可靜默改抓搜尋結果中的相似資料集。

## 4. 更新頻率與最近更新證據

2026-09-13 核對到的官方資訊：

| 證據 | 值 | 解讀限制 |
| --- | --- | --- |
| data.gov.tw `updateFrequency` | `regularupdate=1`, `Frequency=1`, `unittime=日` | 官方宣告「每 1 日」，不等於每一天內容一定變動 |
| data.gov.tw `modifiedDate` | `2026-09-12 07:06:04` | metadata 修改時間；頁面未標示時區 |
| data.gov.tw `notes` | `（檔案更新時間：2026-09-12 07:02:04）` | 官方檔案時間；頁面未標示時區 |
| 健保署 detail JSON `modified` | `2026-09-12 07:02:04` | 與中文 notes 一致 |
| 健保署 detail JSON `resourcemodified` | `2026年09月12日` | 精確度只有日期 |
| HTTP response `Date` | `Sat, 12 Sep 2026 16:55:42 GMT` | 只證明回應時間，不是資料內容更新時間 |

資料集頁於核對時顯示「每 1 日」，而最近檔案更新日期為前一日。這足以支持 daily polling 規劃，還不足以證明週末、假日及無內容變更日的實際行為。應在 importer 上線後保存至少 30 天 metadata 與 SHA-256，才有實測 cadence。

目前 CSV 回應沒有觀察到 `Last-Modified` 或 `ETag`，不能依賴 conditional GET。應使用官方 `modifiedDate`／`notes` 加上檔案 SHA-256 判定是否產生新 snapshot。

另有一項 metadata 不一致：data.gov.tw JSON 的中文 `notes` 是 2026-09-12，但 `en.notes` 仍寫 2025-08-11。同步時應把兩者都保存為 evidence，以頂層 `modifiedDate`／中文 `notes` 作本來源官方更新證據，差異寫入 validation report；對外 freshness 結果仍依 PRD §7 的 canonical contract 計算與命名。

## 5. 實際 HTTP 與檔案證據

2026-09-13 00:55（Asia/Taipei）匿名 GET 結果：

```text
HTTP/1.1 200 OK
Content-Length: 1725985
Content-Type: application/csv
Content-Disposition: attachment; filename=A21030000I-D20021-001.csv
```

- 檔案大小：`1,725,985 bytes`
- SHA-256：`624e8d0ace8f7e0d5c3ed3102069df94ee25f05e2b39a0d60822e7f1a51ca271`
- 編碼：UTF-8，含 BOM `EF BB BF`
- 同一時段第二次下載：大小與 SHA-256 相同
- 解析結果：1 個 header + 6,173 個 data records；每筆皆為 7 欄
- 換行：主要 record separator 為 LF，但部分 quoted cell 內含 CRLF；不得用單純 `splitlines()` 當 record parser

以上 hash 只識別這一次 snapshot，不能寫成未來固定測試值。

## 6. 完整欄位清單與樣本 header

官方 metadata 與實檔 header 完全一致，順序如下：

```csv
診療項目代碼,健保支付點數,生效起日,生效迄日,英文項目名稱,中文項目名稱,備註
```

| 原始欄位 | 當次觀察 | 建議 curated 型別 | 驗證／清理重點 |
| --- | --- | --- | --- |
| `診療項目代碼` | 6,173/6,173 非空；當次全唯一 | string | 不可轉數字；保留前導零；格式不只 6 碼 |
| `健保支付點數` | 全部為非負整數字串；含 0 | integer + raw string | 0 是有效觀察值，不可當 missing；單位為點，不換算成新台幣 |
| `生效起日` | 全部 8 碼 Gregorian `YYYYMMDD` | ISO date + raw string | 嚴格日曆驗證；不要套民國年轉換 |
| `生效迄日` | 6,173 筆全部為 `29101231` | ISO date + raw string + sentinel flag | 保留原值；sentinel 語意尚需官方／owner 確認 |
| `英文項目名稱` | 1,832 筆空白（29.7%） | nullable string | 空白合法；不得由中文自動翻譯後冒充官方名稱 |
| `中文項目名稱` | 全部非空；7 筆含內嵌換行 | string | 以 CSV parser 解析；搜尋版可正規化空白，但原值需保存 |
| `備註` | 2,567 筆空白（41.6%） | nullable string | 空白合法；備註可能含申報限制，不能截斷或只做摘要 |

### 6.1 欄位分布快照

- `診療項目代碼` 長度為 2–7；743 筆有前導零。
- 4,752 筆符合 5 digits + 1 uppercase letter；另有純數字、英文字母開頭、較短代碼與 7 碼代碼。
- 因此不能用 `^[0-9]{5}[A-Z]$` 當全表 hard validation。
- `健保支付點數` 最小 0、最大 1,266,499；262 筆為 0；未觀察到負數或小數。
- `生效起日` 最早 `19950301`、最晚 `20260901`；全部可解析為 Gregorian date。
- `生效迄日` 當次全部是 `29101231`。
- 英文名稱有 7 筆外圍空白；中文名稱／備註可見全形空格與少量 tab。原始值不可被覆寫，搜尋欄位可另做 normalization。

### 6.2 可重現的 golden row

當次 snapshot 中：

```text
診療項目代碼: 09006C
健保支付點數: 200
生效起日: 20120101
生效迄日: 29101231
英文項目名稱: HbA1c (Hemoglobin A1c)
中文項目名稱: 醣化血紅素
```

這筆可作 parser 與 exact-code lookup 的 golden case；點數與日期仍必須以每次新 snapshot 重核，不能把 200 永久寫死為產品規則。

## 7. 重要語意與資料品質風險

### 7.1 這是現行清單，不是歷史版本庫

資料集官方 description 是「現行給付項目」。當次代碼全唯一，所有迄日相同，沒有同碼多版本。故：

- `get_points(code, as_of=null)` 可回傳 serving snapshot 的現行來源列。
- **Superseded research draft**：不得再以 non-null `as_of` 比較 current row 的起迄日，也不得回傳舊草案名稱 `historical_data_unavailable`。
- Canonical 行為依 PRD §5.3／NHI-04：先驗證參數；合法且 non-null 的 `as_of` 一律回 `result_status=historical_query_unsupported`、`historical_truth_supported=false`、0 items，不讀 code lookup、不回 current points，也不回日期涵蓋布林。
- `as_of` 只接受嚴格 Gregorian `YYYY-MM-DD` 且必須是有效日曆日期；wrong type、空字串、格式錯誤或無效日期回 `invalid_request`、0 items。
- 來源欄 `生效起日`／`生效迄日` 則只接受嚴格 Gregorian `YYYYMMDD`；不得猜測或轉換民國年。
- 被替換／刪除的舊列不在當前 CSV。每日留存 snapshot 只能形成首次收集後的觀察歷史；歷史版本 ingestion 屬 P2／P1.1 out of scope，不能用來擴張本版 public contract。

### 7.2 沒有 laboratory 分類欄

7 欄中沒有章、節、類別、檢驗專科或是否屬檢驗的旗標。名稱 keyword 會漏掉縮寫項目，也可能誤納處置、方案或打包費；代碼前綴也不是已驗證的完整分類規則。

建議另建 `nhi_lab_scope` mapping：

| 欄位 | 用途 |
| --- | --- |
| `code` | 對應原始診療項目代碼 |
| `scope_status` | `in_scope` / `out_of_scope` / `review_pending` |
| `basis_type` | 官方支付標準章節、官方檢驗結果上傳清單、人工領域審查等 |
| `basis_url`、`basis_locator` | 官方 URL 與頁／章／表定位 |
| `rule_version` | scope 規則版本 |
| `reviewer`、`reviewed_at` | 核准者與時間 |

健保署公開的檢驗結果上傳項目清單可作 golden seed，但它代表特定上傳方案的項目，不足以當「全部健保檢驗」母集合。正式 completeness 宣告需要另外完成官方章節對照及醫檢 reviewer 核准。

### 7.3 日期 sentinel 未有欄位級官方定義

當次 6,173 筆 `生效迄日` 都是 `29101231`，高度符合遠期 sentinel 的型態，但資料集欄位說明沒有明文說「代表無期限」。第一版應：

- 保存 `effective_end_raw="29101231"`。
- 可另加 `possible_open_end_sentinel=true`，標示為 inference。
- 在取得官方定義或 owner 決議前，不把原值刪除，也不對外說「永久有效」。

### 7.4 metadata 不能替代 record validation

- metadata 的 `coverageStartedDate=2025-06-05` 是資料集 coverage，不是資料列最早生效日；實檔最早是 1995-03-01。
- metadata 中兩個日期欄位的 `uri` 指向其他業務語意，不宜拿來生成醫療 schema。
- 健保署 detail JSON 的 temporal coverage 顯示成在地化字串，與 data.gov.tw 頂層 ISO 值不易直接對照。
- 所以 importer 應以 exact header 與 record-level validation 為準，metadata 只作來源與更新證據。

## 8. 建議 raw → staged → curated 流程

### 8.1 fetch／raw

1. 先取得 data.gov.tw metadata，保存完整 JSON、取得時間與 SHA-256。
2. 從 metadata 解析 resource URL；下載到同檔案系統的暫存檔。
3. 驗證 HTTP 200、非空、允許的 host、Content-Type、Content-Disposition 與最大檔案大小。
4. 計算原始檔 SHA-256，再以 atomic rename 放入 immutable raw snapshot。
5. 保存 response headers；不要因目前缺少 ETag／Last-Modified 就自行捏造。

### 8.2 parse／staged

- 以 UTF-8-sig 解碼；沒有 BOM 但仍是合法 UTF-8時可列 warning，解碼失敗則阻擋發布。
- 使用 RFC 4180-aware CSV parser，開檔時保留 `newline=""`；不可手動按實體行切割。
- header 先移除 BOM，再做 exact schema 比對。
- 為每列保存 `source_row_number`、原始 7 欄與 canonical row hash。
- CSV malformed、欄數不等於 7、NUL byte 或重複 header 時進 quarantine 並阻擋整個 snapshot。

### 8.3 normalize／curated

原始欄位完整保留，另產生：

```text
code_raw                  -> 原始診療項目代碼
code_normalized           -> trim + ASCII uppercase；不得轉數字
points_raw                -> 原始支付點數
points                    -> base-10 integer
effective_start_raw       -> 原始 YYYYMMDD
effective_start           -> ISO date
effective_end_raw         -> 原始 YYYYMMDD
effective_end             -> ISO date
possible_open_end_sentinel
name_zh_raw / name_zh_search
name_en_raw / name_en_search
note_raw / note_search
scope_status
source_row_number
source_row_sha256
snapshot_id
```

搜尋欄位可用 Unicode NFKC、casefold、外圍 trim、連續 whitespace 壓成單一空格；正式顯示、證據與差異比較一律使用 raw value。不要自動更正官方用字，例如「醣化／糖化」差異；alias 必須另存並標來源。

### 8.4 validate／publish

- `code_raw`、points、起日、迄日、中文名稱不得空白。
- points 必須為非負 base-10 integer；0 合法。
- 日期必須為 8 位數且通過 Gregorian calendar；起日不得晚於迄日。
- 完全重複列應報錯；當期 candidate 只要出現重複 current code，就必須整批 **BLOCK**，保留 raw/staged evidence 並停止發布。不得 last-write-wins、去重後 partial publish，或只把重複列送 review 後繼續發布。
- curated row count、唯一 code count、空值率、日期分布與前一個已發布 snapshot 做差異報告。
- 所有阻擋條件通過後，才用 atomic pointer／manifest 切換 `current`。

## 9. Schema drift、status／freshness 與 fail-closed

### 9.1 Schema drift 規則

| 事件 | 動作 |
| --- | --- |
| 必要欄位缺少、改名或重複 | **BLOCK**；保留 raw、產生 drift report、不更新 current |
| 新增未知欄位 | staged 保留；**BLOCK pending review**，避免忽略可能具重要語意的新欄 |
| 欄位只改順序 | parser 可依名稱讀取，但此次 snapshot 仍需 review 後才能發布 |
| 編碼不再是 UTF-8 | **BLOCK**；不要猜 Big5 或以 replacement character 繼續 |
| row count 為 0 或解析錯誤 | **BLOCK** |
| row count 或唯一 code count 大幅變動 | block pending review；建議先用相對前版 ±10% 作啟動門檻，待 30 天基線後再調整 |
| English／note 空值率變動 | warning + diff；這兩欄本來可空，不能單憑空值阻擋 |
| 代碼出現新格式 | 不刪列；送 review，更新 schema version 後發布 |

±10% 是工程啟動值，不是官方門檻。當累積足夠 snapshot 後，應改用來源本身的歷史波動基線。

### 9.2 Status／freshness 契約

本研究只提供來源頻率與更新時間 evidence，不另定排程時間、stale 週期、hard-stop 天數或 public 欄位。實作一律引用 [PRD §7.1～§7.3](../product-requirements.md) 的 canonical public enums／status／freshness registry，以及 [SDD §7.5～§7.6](../software-design.md) 的 availability descriptor 與 operational status 更新協定。

對本來源仍成立的 fail-closed 原則是：同一 SHA-256 可記錄 successful upstream check 而不重建相同 curated build；下載、解碼、schema、重複 current code 或其他 batch validation 失敗時不得切換 serving current，也不得 fallback sample。能否繼續服務上一個 approved build，以及 `availability`、`stale`、`stale_reason_codes[]`、candidate 與 serving 欄位的 exact 組合，只能依上述 PRD／SDD truth table 決定。

### 9.3 MCP provenance 與 status 邊界

```text
source_name
provider = 衛生福利部中央健康保險署
dataset_id = 174450
identifier = A21030000I-D20021
resource_id = A21030000I-D20021-001
landing_url
resource_url
official_modified_at
retrieved_at (含時區)
raw_sha256
snapshot_id
schema_version
parser_version
license_name
license_url
source_row_number
source_row_sha256
scope_status / scope_basis
```

Public status／freshness 欄位不得由這份清單另生 schema；直接使用 PRD §7.3 的 exact registry。特別禁止 singular `stale_reason`、泛稱 `validation_status`、`review_status`、`candidate_status`、`last_publish_at` 等 legacy keys。

## 10. 授權、顯名與產品聲明

資料集標示「免費」及「政府資料開放授權條款－第 1 版」。條款允許不限目的、時間及地域利用、修改、散布與再授權，但要求對原資料與衍生物明確顯名；條款也明定資料不構成提供機關推薦、同意、許可或核准。

建議每個 release manifest 與 MCP provenance 顯示：

```text
資料提供機關：衛生福利部中央健康保險署
資料集：醫療服務給付項目及支付標準(csv檔)
來源資料時間：<official modifiedDate；若未標時區則照原精確度保存>
本地 snapshot：<retrieved_at + SHA-256>
授權：政府資料開放授權條款－第 1 版
授權網址：https://data.gov.tw/license
處理說明：Taiwan Laboratory MCP 進行格式解析、搜尋正規化與範圍標記
```

若官方未提供版號，`snapshot_id` 不得假裝成官方版本；應明確稱「本地 snapshot 識別碼」。產品介面不得使用「健保署認證／核准本 MCP」等文字。

## 11. 可重跑驗證方法

### 11.1 最小下載證據

```powershell
$metadataUrl = 'https://data.gov.tw/api/v2/rest/dataset/174450'
$metadata = Invoke-RestMethod -Uri $metadataUrl -Method Get
$resourceUrl = $metadata.result.distribution |
  Where-Object { $_.resourceFormat -eq 'CSV' } |
  Select-Object -First 1 -ExpandProperty resourceDownloadUrl

curl.exe -L --fail --connect-timeout 20 --max-time 120 `
  -D response-headers.txt -o nhi.csv $resourceUrl
Get-FileHash -Algorithm SHA256 -LiteralPath .\nhi.csv
```

正式程式需再加入允許網域、最大檔案大小、暫存路徑與 atomic publish；上例只供人工重現。

### 11.2 每次同步應輸出的機器可讀報告

```json
{
  "http_status": 200,
  "content_type": "application/csv",
  "bytes": 1725985,
  "sha256": "<current hash>",
  "encoding": "utf-8-sig",
  "header": ["診療項目代碼", "健保支付點數", "生效起日", "生效迄日", "英文項目名稱", "中文項目名稱", "備註"],
  "row_count": 6173,
  "unique_code_count": 6173,
  "invalid_row_count": 0,
  "blocking_errors": [],
  "warnings": []
}
```

數字是 2026-09-13 snapshot 的預期輸出範例；正式驗證應與前一版比較，不把 row count 或 hash 永久寫死。

### 11.3 最小驗收案例

1. `09006C` exact lookup 可回傳一筆，並附原始列與 snapshot provenance。
2. `0` 點項目能正常保留，不被當作 null。
3. 含內嵌 CRLF 的中文名稱仍只產生一筆 record。
4. 人為刪除 `備註` header 時，snapshot 不得發布。
5. 合法 non-null `as_of` 固定回 `historical_query_unsupported`、`historical_truth_supported=false`、0 items；不得比較 current row。malformed `as_of` 則回 `invalid_request`。
6. 人為加入第二筆相同 current code 時整批 block，serving current 不變。
7. 下載失敗或新檔驗證失敗時，serving current 不變；public status 依 PRD §7 truth table 呈現，絕不混入 sample。

## 12. 未驗證項目與 owner 決策

| 項目 | 狀態 | 建議下一步 |
| --- | --- | --- |
| `29101231` 的官方明文語意 | UNVERIFIED | 向資料提供聯絡人確認；確認前保存原值並標 inference |
| 完整 laboratory scope 分類 | UNVERIFIED | 以現行支付標準章節／表格建立 allowlist，交醫檢 reviewer 核准 |
| 每日更新是否含週末／假日 | UNVERIFIED | 保存至少 30 天 metadata + hash，建立實測 cadence |
| 任意歷史日期的舊點數 | NOT SUPPORTED BY THIS CSV | 另規劃歷年官方支付標準文件 ingestion；不可由現行列倒推 |
| status／freshness policy | GOVERNED | 直接引用 PRD §7.1～§7.3 與 SDD §7.5～§7.6；本文件不另定 threshold 或 public 欄名 |
| curated snapshot 是否再散布 | OWNER DECISION | 授權允許利用但仍需完成顯名、release 大小與更新責任設計 |

## 13. 實作優先順序

1. 建立 metadata resolver、immutable raw snapshot、manifest 與上述 7 欄 exact parser。
2. 完成 code／points／date 型別、quoted newline、provenance 與 fail-closed 測試。
3. 依 PRD 實作 `search_payment_items` 全表候選搜尋；每筆回 `scope_status`、scope provenance、`coverage_status` 與 deterministic pagination。`search_lab_code` 只作相同行為的 compatibility wrapper，名稱不得被解讀為已過濾的完整 laboratory 清單。
4. 建立 laboratory scope mapping 與官方 locator；reviewer 核准可提升 scope／coverage 陳述，但不得改變 `search_payment_items` 搜尋全表的 canonical 行為。
5. 從首次正式同步起保留每日 hash/diff；歷史點數 ingestion 留在 P2／P1.1 out of scope，P1.1 對任何合法 non-null `as_of` 固定 unsupported。

## 14. 本次研究方法

- 讀取 3 個官方 landing／metadata 入口與 1 份授權全文。
- 直接匿名下載官方 CSV 兩次，比對大小與 SHA-256。
- 使用 Python standard library `csv` 以 UTF-8-sig 解析，檢查 header、欄數、列數、空值、代碼形態、points、日期、換行與搜尋正規化風險。
- 另檢視健保署同頁提供的 TXT resource。它在當次為約 22 MB、UTF-8 BOM、固定寬度／caret 分隔且無 header，並存在內嵌換行；CSV 更適合作主資料源，TXT 可作人工 cross-check，不建議作第一版 importer。
- 所有引用均為 `data.gov.tw`、`nhi.gov.tw` 或 `info.nhi.gov.tw` 一手來源；未用第三方資料決定 schema。
