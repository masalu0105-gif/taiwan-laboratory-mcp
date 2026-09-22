# 資料來源與授權

核對日期：2026-09-18。四組來源已有 repo 外正式 snapshot 與查詢路徑；每次更新仍須重新發現／下載、驗證 provenance 與 schema，通過各來源 review／publish gate 才能切換 current。

<!-- official-source-ids: cdc_manual,cdc_recognized_labs,nhi_fee,tfda_device -->

## P1 官方來源

| Source ID | 官方入口與提供者 | 來源宣告 | 專案目前狀態 |
| --- | --- | --- | --- |
| `cdc_manual` | [傳染病檢體採檢手冊](https://www.cdc.gov.tw/Category/Page/WV_GRwCIYrWQsEVa8ctTWg)，衛生福利部疾病管制署 | 官方文件頁；每次同步重新發現附件並核對 PDF 版本 | 已建立整本手冊 snapshot、頁面 locator、完整性與 review gate；正式作業仍須核對原文 |
| `cdc_recognized_labs` | 疾管署認可傳染病檢驗機構名冊，衛生福利部疾病管制署 | 從官方 landing page 重新發現 ODS；頁面日期不能取代附件版本 | 已建立 ODS importer、正式 snapshot 與自動更新；不把機構列壓成單一證號列 |
| `nhi_fee` | [醫療服務給付項目及支付標準 CSV](https://data.gov.tw/dataset/174450)，衛生福利部中央健康保險署 | metadata license code `1`；政府資料開放授權條款第 1 版 | 已建立 7 欄 importer、正式 snapshot 與自動更新；點數不是金額，也不是歷史資料庫 |
| `tfda_device` | [醫療器材許可證資料集](https://data.gov.tw/dataset/9576)，衛生福利部食品藥物管理署 | 政府資料開放授權條款第 1 版；CSV endpoint 實際按 ZIP 驗證 | 已建立 34 欄 importer、正式 snapshot 與自動更新；全量醫材不能整份視為 IVD，涵蓋固定 `review_incomplete` |

更新頻率是來源宣告，不能當成最近一次成功同步的證據。資料入口頁的修改時間，也不等於每一筆紀錄或 PDF 的版本時間。

NHI 欄位包含診療項目代碼、健保支付點數、生效起迄、中英文名稱與備註。TFDA 欄位包含許可證字號、註銷資訊、有效日期、品名、效能、申請商、製造商及異動日期。匯入時需以實際檔案欄位再次驗證。

## 每筆正式資料需保留

| 欄位 | 意義 |
| --- | --- |
| `provenance` | 提供機關、資料集、取得方式、來源紀錄 ID／文件頁碼、原值與轉換說明 |
| `source_url` | 能讓使用者核對此筆內容的官方網址；下載資源 URL 另存於 provenance |
| `version` | 官方版本；來源未提供版本時，以明確標示的 snapshot SHA-256 識別，不捏造官方版號 |
| `updated_at` | 官方資料更新時間；來源未提供時保留 `null` 並說明未知 |
| `sample_only` | 正式資料為 `false`；合成資料及示範 fixture 為 `true` |

`provenance.retrieved_at` 另記取得時間與時區，不能填入 `updated_at` 充當官方更新時間。保留原始日期字串；民國日期轉換另記轉換方式。來源精確度僅到日期時，不自行添加時分秒。

## 授權與顯名

專案採 MIT；外部資料維持各自授權。NHI 與 TFDA 上述資料集宣告適用 [政府資料開放授權條款第 1 版](https://data.gov.tw/license)，使用及衍生資料需按條款顯名，不得暗示官方背書。

正式匯入時，依實際來源填入「提供機關、資料名稱、來源年份／版本、授權名稱與連結」的顯名資訊。若修改了欄位或整理方式，另外記錄本專案的處理。來源 URL 仍須與紀錄一起回傳。

CDC 個別文件與其中第三方素材的重製條件需逐份確認；在確認前，保留官方入口與示範介面。不得將其他政府資料集的授權自動套用到 CDC PDF。

## 示範資料

Fixtures 的唯一正本為 `src/taiwan_lab_mcp/data/*.sample.json`；`data/samples/README.md` 提供導覽，避免同時維護兩份 JSON。使用真實疾病或 analyte 名稱演示搜尋，也必須標記 `sample_only: true`。Sample 的 `source_url` 指向 repo 中的合成檔案；官方入口另外由 `get_data_status` 列出，避免把官方網址誤認為樣本數值的證據。

Sample 的警示須出現在 MCP 回傳內容中，不能只寫在 README。禁止在正式資料查詢失敗後靜默切換到 sample。

## 保留介面與未啟用來源

LOINC、FHIR、SNOMED 只保留 adapter interface，不內建 terminology 或台灣 mapping。EQA／CAP 僅保留 adapter／TODO；在確認 provider 授權、API 或允許的索引方式之前，不抓取 catalog、不重製題目與 program database，也不把公開可瀏覽視為重製授權。
