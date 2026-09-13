# Taiwan CDC 資料源深度調查：採檢手冊與認可檢驗機構

文件狀態：Research complete; implementation governed by PRD/SDD
核對日期：2026-09-13（Asia/Taipei）
證據範圍：衛生福利部疾病管制署與其官方資料站；未使用第三方整理資料
P1 用途：採檢送驗條件查詢、送驗地點查詢、傳染病認可檢驗機構查詢

## 1. 結論先行

| 結論 | 狀態 | 實測證據與影響 |
| --- | --- | --- |
| 現行採檢手冊是 `1150826` 版 | **VERIFIED** | [官方手冊頁](https://www.cdc.gov.tw/Category/Page/WV_GRwCIYrWQsEVa8ctTWg)目前列出手冊與修訂對照表 `1150826`；兩份文件內日期也是民國 115 年 8 月 26 日。原計畫書的 `1150508` 已不是現行版。 |
| 手冊沒有固定更新週期 | **VERIFIED** | 手冊封面明載「本手冊不定時更新，使用前請至疾管署全球資訊網，確認為最新資料」。因此不可設定「每年」或「每季」作為官方頻率。 |
| 網頁的「最後更新日期」不能代表附件版本 | **VERIFIED** | 手冊頁顯示 `2026/5/11`，但附件版次為 `1150826`；PDF HTTP `Last-Modified` 分別是 2026-08-26 與 2026-08-27。同步器必須監看附件名稱、URL 與檔案雜湊。 |
| 認可檢驗機構目前由 ODS 名冊提供 | **VERIFIED** | [官方認可機構頁](https://www.cdc.gov.tw/Category/Page/02d-tR1nzB8QuflX-NmM_w)目前附件為 `傳染病認可檢驗機構名冊1150909.ods`，而非 CDC Open Data Portal 的 CSV 資料集。 |
| 認可機構名冊沒有查到官方固定更新頻率 | **UNVERIFIED** | 頁面沒有頻率欄；頁面顯示最後更新 `2023/9/27`，附件檔名與 ODS metadata 卻是 2026-09-09。只能確認「持續換檔」，不能把單次間隔推成週期。 |

建議 CDC 來源每日檢查一次，但這是本專案的監控策略，不是 CDC 宣告的發布週期。正式查詢只讀最後一個通過驗證與專業複核的 snapshot。

## 2. 官方入口與下載方式

| 資料 | 官方入口 | 2026-09-13 實際附件 | 下載與識別方式 |
| --- | --- | --- | --- |
| 傳染病檢體採檢手冊 | [手冊頁](https://www.cdc.gov.tw/Category/Page/WV_GRwCIYrWQsEVa8ctTWg) | [1150826 手冊 viewer](https://www.cdc.gov.tw/File/Get/co-Lw-KlHBdl-j84lxzbig) | `File/Get` 對 PDF 回傳 HTML viewer；需再由 HTML 取得當期 `/Uploads/<uuid>.pdf`。不得把目前 UUID 永久寫死。 |
| 手冊修訂對照表 | 同上 | [1150826 修訂對照 viewer](https://www.cdc.gov.tw/File/Get/cBtNn3rYwlBFGthaclYfYg) | 與手冊同時下載，兩者版本／製表日期必須一致。 |
| 傳染病認可檢驗機構 | [認可機構頁](https://www.cdc.gov.tw/Category/Page/02d-tR1nzB8QuflX-NmM_w) | [1150909 ODS](https://www.cdc.gov.tw/File/Get/m53oC-FWJpk0kBK5lNmasA) | 此 `File/Get` 目前直接回傳 `application/octet-stream`；以 ZIP magic 與根目錄 `mimetype=application/vnd.oasis.opendocument.spreadsheet` 判定為 ODS。 |

同步器每次都應從官方入口重新發現附件，而不是直接請求上述當期 token。每次下載保存 landing URL、viewer URL、實際 binary URL、HTTP headers、取得時間、檔名、檔案大小與 SHA-256。

### 2.1 本次檔案指紋

| 檔案 | 大小 | SHA-256 | 狀態 |
| --- | ---: | --- | --- |
| 手冊 `1150826` PDF | 4,046,218 bytes | `988654C0E561630AD75E1145D2CA092EBDC6EB6A2A5CCCB9146BDA34B3DEAED7` | **VERIFIED** |
| 修訂對照表 `1150826` PDF | 780,660 bytes | `6732685204FCFD89A814A2180822A5429B77A23FD3AAC935596D29744A3B9EFF` | **VERIFIED** |
| 認可機構名冊 `1150909` ODS | 176,283 bytes | `ED8960B3921637548C7D5AC98FD002AE5793A80D99E995113FE9C9761244DED8` | **VERIFIED** |

原始檔只在本機暫存區解析，本次未加入 Git。歷史版本完整下載入口未在官方現行頁提供；搜尋仍可看到 `1150508` 的官方檔案頁索引，但舊 token 現已無法可靠取回，故歷史版本庫為 **UNVERIFIED / BLOCKED by upstream archive availability**。

## 3. PDF 結構與可抽取性實測

本次依專案規則使用本機 LiteParse 2.0.0，以 `--format json --no-ocr` 解析，並以 page screenshot 抽查表格版面。兩份 PDF 每一頁都有非空文字層；本次不需要 OCR。

P1.1 official publish 不接受任何 OCR-derived row。未來若必要頁缺少可靠文字層，OCR 只可產生 staged research candidate，不得進 approved build；即使完成 100% 人工核對也不能解除 P1.1 gate。要允許 OCR publish 必須先升版並修訂 [PRD §8.3](../product-requirements.md) 與 TDD，再定義 OCR engine／model version、options、output hash、bbox lineage 與 reviewer evidence。

| 文件 | PDF 實體頁數 | 文字層 | 版面特徵 | 主要風險 |
| --- | ---: | --- | --- | --- |
| 採檢手冊 `1150826` | 130 | **VERIFIED 可抽取** | 封面 1 頁、目錄 9 頁，正文印刷頁 1 從 PDF 第 11 頁開始；大量直式多欄合併儲存格表格 | PDF text order 會交錯欄位，疾病名稱與同一列可能跨頁；需用 bounding boxes 與表格線重建，不能只切純文字。 |
| 修訂對照 `1150826` | 29 | **VERIFIED 可抽取** | 橫式三欄：`修正規定`、`現行規定`、`說明`；三欄內又嵌套完整採檢表 | 三欄內容很長且跨頁，純文字抽取會把左右欄混在一起；必須依 x 座標分欄，並保留每頁重複表頭。 |

手冊最後一個 PDF 實體頁的印刷頁碼標成「第 120 頁／共 119 頁」。這是文件內部可見的不一致，表示 provenance 必須同時保存 `pdf_page=130` 與 `printed_page=120`，不能只用印刷頁碼當唯一定位鍵。

### 3.1 採檢規定表可可靠抽取的欄位

正文第 2 章「傳染病檢體採檢及運送規定總覽表」的穩定欄位如下：

| 原始欄名 | 建議 schema | 清理規則 |
| --- | --- | --- |
| 傳染病名稱 | `disease_name_raw` | 原文保留；另建 Unicode normalized 搜尋值，不自行合併同義疾病。 |
| 採檢項目 | `specimen_type_raw` | 同疾病可有多種檢體；每個檢體／方法組合作為獨立 record。 |
| 採檢目的 | `collection_purpose_raw` | 不把病原體檢測、抗體檢測、確認等文字轉成臨床判斷。 |
| 採檢時間 | `collection_timing_raw` | 保留「發病後 N 日內」等完整條件；P1.1 不另拆可被誤當臨床指示的結構化範圍。 |
| 採檢量及規定 | `volume_and_requirements_raw` | 數量、容器、採法常在同一格，不做有損拆分。 |
| 送驗方式 | `transport_raw` | 溫度、感染性物質分類與 P620/P650 關係不可拆散。 |
| 應保存種類（應保存時間） | `retention_raw` | 這是疾管署保存材料／期間，不應誤標為送驗前保存條件。 |
| 注意事項 | `notes_raw` | 全文保留，含交叉引用章節、前置聯絡要求與例外。 |

每筆 record 另加 `disease_class_section`、`manual_version`、`approved_date`、`pdf_page`、`printed_page`、`table_section`、`row_bbox`、`raw_cell_text` 與 `source_sha256`。本版第 2 章落在 PDF 第 13–68 頁；實作時應以章節標題及頁首版次定位，不硬寫固定頁數。

### 3.2 送驗地點與檢驗期間表

第 7 章從 PDF 第 93 頁開始，欄位為 `傳染病名稱`、`採檢單位`、`採檢項目`、`檢驗方法`、`檢驗期限`、`收件單位`、`實驗室生物安全等級(BSL)`、`備註`。這組資料應與第 2 章分成不同 entity，再以疾病與採檢項目建立可追溯關聯；不可在 PDF 抽取階段直接 join，避免同疾病多方法交叉配錯。

第 7.7 節欄名改為 `檢驗期間`，且表格結構不同；第 7.9 節是收件單位的電話、傳真與地址。兩者都要另建 schema，不能強塞進第 7 章主表。

## 4. 認可檢驗機構 ODS 結構

ODS 內有一個實際資料工作表 `1150909名冊`，另有兩個空白 sheet。以 OpenDocument XML 實測得到 12 個原始欄位、3,584 個非空資料列、344 個不同證號、29 組不同疾病代碼／名稱。

| 原始欄名 | 建議 schema | 重要規則 |
| --- | --- | --- |
| 證號、縣市別、機構名稱、部門別 | `certificate_no`, `city`, `institution_name_raw`, `department_raw` | 證號用字串；機構名尾端括號號碼可另建衍生欄，但不得覆蓋原名。 |
| 疾病代碼、疾病名稱 | `disease_code`, `disease_name_raw` | 代碼有英數與前導零，例如 `002a`、`19SC`，禁止轉數字。 |
| 檢驗目的、檢驗方法 | `test_purpose_raw`, `test_method_raw` | 同一疾病／目的可跨多列方法；方法代碼連同括號原文保存。 |
| 住址、連絡電話 | `address_raw`, `phone_raw` | 只提供機構查詢，不做個人聯絡人推論；電話分機保留。 |
| 結束時間 | `recognition_end_date` | 本次 3,584 列皆為 `YYYY/MM/DD`；欄名不是「證書有效期限」時仍需保留原始欄名與 snapshot。 |
| 最近一次年度能力試驗審查 | `latest_annual_pt_review_raw` | 本次有日期 3,513 列、`無需能力試驗` 40 列、空白 31 列；不可強制全部轉 date。 |

ODS 大量使用垂直合併儲存格：後續方法列會以 `covered-table-cell` 表示，解析時必須依 `number-rows-spanned` 繼承 anchor 值。禁止對任意空白欄做 blanket forward-fill，否則真正空白的能力試驗欄會被錯填。工作表也宣告到 16,384 欄，但第 13 欄後皆為重複空白；parser 應只讀已知 12 欄並限制 repeated-column expansion，避免記憶體浪費。

## 5. 更新偵測、schema drift 與 stale 規則

### 5.1 建議排程

| 來源 | 官方週期 | 專案檢查策略 | 發布策略 |
| --- | --- | --- | --- |
| 手冊＋修訂對照 | 不定時更新 | 每日重新讀 landing page；附件 token、title、binary SHA-256 任一變動即建立 staged snapshot | 新版本一律等完整變更列與醫檢專業複核，不自動覆蓋 current。 |
| 認可機構 ODS | **UNVERIFIED** | 每日檢查附件檔名、token、SHA-256 與 ODS metadata date | schema 穩定且差異驗證通過後仍先進 review queue；效期、方法或證號變更需人工核對。 |

Public status／freshness 完全引用 [PRD §7.1–7.3](../product-requirements.md) 與未來 package resource `public-contract-v1.json`；本研究不建立第二套欄位或 enum。CDC 兩個 source object 必須使用 canonical `source_id`、`availability`、`availability_reason_code`、`serving_*`、`latest_candidate_*`、`last_check_at`、`last_successful_check_at`、`last_successful_publish_at`、`latest_seen_version`、`stale`、`stale_reason_codes[]`、`content_age_*` 與 `freshness_policy_version`。

`stale` 只描述 available serving snapshot 的上游核對或已知新版狀態，不因手冊年齡直接宣稱過期。`validation_status`、`review_status`、`candidate_status`、singular `stale_reason`、`last_publish_at` 與 `official_data_loaded` 都是禁止進 public JSON 的 legacy keys。

### 5.2 fail-closed 條件

1. landing page 找不到手冊／修訂表其中一份，或兩份版本不一致。
2. viewer 抽出的 binary 不是 PDF、ODS mimetype 不符、下載截斷或 SHA-256 無法完成。
3. PDF 封面版次、核定日期、頁首版次、檔名互相不一致，或必要頁失去可靠文字層；OCR 可留 staged research evidence，但 P1.1 不得發布。
4. 第 2／7 章表頭或 ODS 12 欄發生增刪改名，合併儲存格關係無法重建。
5. 新 snapshot 尚未完成人工與醫檢專業複核。

任一條成立時不得發布該 candidate。若上一個 serving descriptor 及其 operational evidence 仍完整可驗證，runtime 依 PRD 保留舊 approved snapshot，並用 canonical `latest_candidate_status`、`stale=true` 與對應 `stale_reason_codes[]` 揭露候選狀態。若沒有 serving snapshot，或 current descriptor／operational status 缺失、毀損、hash／schema／source／generation 不符，該 source 必須回 `availability=data_unavailable`、對應 `availability_reason_code` 且 `stale=false`；不得降格成 stale、退回 sample、混查 staged 與 approved 資料。

## 6. 人工與醫檢專業複核

| 資料集 | Source gate ID | Reviewer／必查內容 | Hash-bound evidence | REL mapping |
| --- | --- | --- | --- | --- |
| CDC 手冊 | `CDC-R1-SOURCE` | 資料工程 reviewer：官方入口、附件配對、版次／日期、SHA-256、頁數與表頭 | fetch manifest、artifact pairing、schema-drift report | 支援 `REL-G2` |
| CDC 手冊 | `CDC-R1-LAYOUT` | 資料工程 reviewer：PDF screenshot、跨頁續列、雙頁碼、cell／header lineage 與欄位歸屬 | row-level diff、bbox locator、layout qualification | 支援 `REL-G2` |
| CDC 手冊 | `CDC-R1-CONTENT` | `medical_laboratory_professional`：疾病、檢體、目的、採檢時間、量與規定、送驗、應保存與注意事項仍屬同列 | signed content checklist、reviewer qualification basis | 支援 `REL-G3` |
| CDC ODS | `ODS-R1-SOURCE` | 資料工程 reviewer：landing、token、ODS mimetype、SHA-256、sheet 與 12 欄 | fetch manifest、archive／source verification | 支援 `REL-G2` |
| CDC ODS | `ODS-R1-STRUCTURE` | 資料工程 reviewer：merge spans、covered cells、repeat bounds、row locator 與空白保留 | structure qualification、row coverage／drift report | 支援 `REL-G2` |
| CDC ODS | `ODS-R1-CONTENT` | `recognition_program_reviewer`：證號、疾病、方法、結束時間、能力試驗狀態與不保證當次收件的安全語意 | signed content checklist、reviewer qualification basis | 支援 `REL-G3` |
| 發布／顯名 | `PUB-R1-OWNER` | owner：required source gates、授權 URL、顯名、非官方服務聲明與 archive policy | owner approval、publisher readback | 支援 `REL-G4`；不可替代 `REL-G5` |

每筆 accepted review record 必須依 [PRD §8.3](../product-requirements.md) 與 [SDD §7.3–7.4](../software-design.md) 綁定同一 `subject_digest`。Digest 涵蓋 ordered raw artifacts、curated DB、transform／rule hashes 與 review protocol version；publisher 必須重算 digest，並確認 required／completed source gate set 完全相等。Parser、schema、rule、raw artifact 或 curated build 任一變更，都要產生新 digest，舊簽核不得沿用。

第一個 CDC／ODS official build 將所有 rows 視為 changed 並逐列核對。後續版本全部 changed rows 必查；CDC 未變更列依 entity／疾病章節採固定 digest seed 分層抽樣，ODS 依疾病／機構分層抽樣，數量與 seed 完全依 SDD §10.3–10.4。CDC 與 ODS 都在任何 critical 或 unresolved major 時整批 rejected；已修正 major 必須產生新 build／`subject_digest` 再重審。修訂對照表只作變更導航，不能取代新舊 PDF diff；未列但實際有差異者標 `unlisted_change`。

`REL-G1` 是所有 official source 的共用資料安全前置，`REL-G5` 是獨立 pilot gate。`PUB-R1-OWNER` 只核准發布／顯名，不能取代 `CDC-R1-CONTENT` 的醫檢內容核准、`ODS-R1-CONTENT` 的認可制度核准或 `REL-G5` 使用者驗收。

## 7. 實作分解與驗收

1. `discover`：從兩個 landing pages 解析當期附件，保存 token、title、HTTP metadata 與來源頁快照雜湊。
2. `fetch/verify`：下載 binary、檢查 magic／mimetype／大小／SHA-256；viewer HTML 與附件 binary 分開保存 provenance。
3. `parse`：PDF 用版面座標重建第 2、7 章表；ODS 直接讀 OpenDocument XML 的前 12 欄與 merge span，不要求 Excel。
4. `review`：產生新舊版本 row diff、頁面截圖定位、quarantine 與專業 review checklist；所有 required gate evidence 綁定同一 `subject_digest`。
5. `publish`：只有 approved snapshot 可原子切換；MCP 每筆結果回傳版本、PDF 實體頁／印刷頁或 ODS snapshot＋原始列 locator。

驗收不能只看「文字有抽出來」。至少要用同疾病多檢體、跨頁續列、同證號多方法、能力試驗為文字／空白、以及最末頁 `120/119` 頁碼不一致做 golden cases，證明 parser 不會交叉污染或錯誤補值。

## 8. 授權與再利用邊界

[CDC 政府網站資料開放宣告](https://www.cdc.gov.tw/Category/FPage/TxkBIR9agw_IBRRmvn9TcQ)說明：網站資料與素材在可受著作權保護範圍內，以無償、非專屬、得再授權方式提供利用，且要求註明出處；同時排除專利、商標、機關標誌與特別聲明需另取得同意的內容，也不授予代表 CDC 建議、認可或贊同衍生產品的地位。**VERIFIED**。

[CDC 著作權聲明](https://www.cdc.gov.tw/Category/FPage/rvmij-b1qdDYyX_Olv67VQ)也要求合理利用時註明出處。兩份本次 PDF 的可抽取文字未發現附件專屬的禁止重製聲明，但這不等於法律意見；若要把完整 curated snapshot 隨 GitHub Release 再散布，仍應在發布前確認附件沒有第三方內容或另外標示。狀態：**UNVERIFIED legal review for bulk redistribution**。

MCP 最低要求是每筆結果註明「資料來源：衛生福利部疾病管制署」、官方 landing URL、文件／名冊版本、核對時間，且 UI／README 明示本專案不是 CDC 官方服務、未獲 CDC 推薦或認可。CDC logo 與機關標誌不納入資料包。

## 9. 限制與決策狀態

| 項目 | 狀態 | 處理方式 |
| --- | --- | --- |
| ODS 解析是否需要 LibreOffice | **RESOLVED / not required** | 本機雖未安裝 LibreOffice，本次已用 Python 標準函式庫直接讀 ODS XML 完成欄位驗證；SDD §10.4 已決定正式 importer 使用 `zipfile`＋`xml.etree.ElementTree.iterparse`，不依賴 LibreOffice。 |
| CDC 歷史版本完整下載庫 | **UNVERIFIED / BLOCKED upstream** | 現行頁只列最新版；不要承諾可重建所有歷史版本。從本專案啟用日起自行保留每次合法取得的 raw snapshot。 |
| 認可機構官方更新頻率 | **UNVERIFIED** | 以 daily polling 管理，不在文件或 MCP 中宣稱官方每日／每月更新。 |
| 批次再散布的最終法務判斷 | **UNVERIFIED** | 上線前由 owner 決定採「附官方下載器」或「發布 curated artifact」，後者先做授權複核。 |

研究證據已完成；實作與 production gate 以 PRD／SDD／TDD 為唯一規格來源。CDC adapter 必須完成上述 source review chain、hash-bound evidence 與相應 REL gates，不能以 PDF parser 測試通過取代專業複核。
