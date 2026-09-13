# TFDA 醫療器材許可證資料：來源、欄位與 IVD 匯入規劃

文件狀態：Research complete; implementation governed by PRD/SDD
核對日期：2026-09-13（Asia/Taipei）
資料集：政府資料開放平臺編號 9576／TFDA Open Data InfoId=68
研究範圍：官方與一手來源、實際下載檔案、欄位、更新節奏、IVD 篩選及正式 snapshot 門檻

## 1. 結論先行

1. **[VERIFIED]** 官方資料集每 7 日與藥證業務管理系統同步；政府資料開放平臺於本次核對時顯示詮釋資料更新時間為 2026-09-11 15:57。XML 內容另標示「最後更新日期 2026/09/10」，資料列中「異動日期」最大值也是 2026/09/10。這三種日期語義不同，manifest 必須分欄保存。
2. **[VERIFIED]** CSV、JSON、XML 三個下載 URL 目前都回傳 application/zip，不是 OAS 宣告的裸 CSV／JSON／XML。每個 ZIP 各含一個 UTF-8 資料檔；三種格式皆為 104,619 列、34 欄。
3. **[VERIFIED]** 「許可證字號」不是資料列唯一鍵：104,619 列只有 93,219 個不同字號，11,229 個字號出現多列，單一字號最多 4 列。實際重複多與不同製造商、製造廠址或製程有關，不能以字號去重。
4. **[VERIFIED]** 資料沒有「是否為 IVD」欄位。A／B／C 主類別也不能直接等同 IVD；現行官方分類附表的 B 類同時包含明確 IVD 品項與血液混合、血液成分處理等非 IVD 品項。
5. **[RECOMMENDED]** 正式版應使用 CSV ZIP 作主要匯入來源，建立「官方分類品項逐碼 IVD included／excluded／ambiguous／unknown 表」，再以「醫器次類別一～三」join。舊制數字類別、缺少次類別、未知代碼回 unknown；規則衝突回 ambiguous。review_pending 只屬內部 review workflow，不是 public ivd_scope。產品與 public contract 以 [PRD 第 6.3、7.1～7.3 節](../product-requirements.md)為準。

## 2. 官方入口與端點

| 項目 | 官方 URL | 本次核對結果 |
| --- | --- | --- |
| 政府資料開放平臺資料集頁 | https://data.gov.tw/dataset/9576 | **[VERIFIED]** 資料集名稱、34 個主要欄位、每 7 日、授權、免費、詮釋資料更新時間 |
| TFDA CSV | https://data.fda.gov.tw/data/opendata/export/68/csv | **[VERIFIED]** HTTP 200，application/zip，建議檔名 68_2.csv.zip |
| TFDA JSON | https://data.fda.gov.tw/data/opendata/export/68/json | **[VERIFIED]** HTTP 200，application/zip，建議檔名 68_5.json.zip |
| TFDA XML | https://data.fda.gov.tw/data/opendata/export/68/xml | **[VERIFIED]** HTTP 200，application/zip，建議檔名 68_1.xml.zip |
| Swagger discovery | https://data.fda.gov.tw/data/v3/api-docs/swagger-config | **[VERIFIED]** 可取得各分類 OAS URL；不要永久假設分類 UUID 不變 |
| 醫療器材 OAS | https://data.fda.gov.tw/data/dataset/oas/classification/5f602177-25c6-4e1a-ae15-75a216aad34a | **[VERIFIED]** 含 Dataset 68 的 34 欄 schema，但 MIME 與日期格式和實際下載不完全一致 |
| 現行分類分級修訂彙整 | https://www.fda.gov.tw/tc/siteContent.aspx?sid=11981 | **[VERIFIED]** 官網目前列最新修訂日期為 112-08-22，並提供第四條附表 |
| 第四條附表 PDF | https://www.fda.gov.tw/tc/includes/GetFile.ashx?id=f638327165592936924&type=4 | **[VERIFIED]** 163 頁，含品項代碼、中英文名稱、等級及鑑別範圍 |
| IVD 定義與申請資訊 | https://www.fda.gov.tw/TC/siteContent.aspx?sid=11638 | **[VERIFIED]** TFDA 說明第一至第三等級均可能含一般醫材與 IVD，IVD 另適用專門須知 |
| IVD 官方問答 | https://www.fda.gov.tw/TC/siteListContent.aspx?id=44389&sid=12727 | **[VERIFIED]** 2026-02-11 官方問答重述 IVD 定義，並要求按現行附表鑑別 |
| 開放資料授權 | https://data.gov.tw/license | **[VERIFIED]** 政府資料開放授權條款－第 1 版及顯名聲明 |

### 2.1 舊 API 說明網址的問題

資料集備註仍指向舊網址：

    https://data.fda.gov.tw/opendata/exportDataList.do?method=openDataApi&InfoId=68

**[VERIFIED]** 2026-09-13 實測該網址先由 HTTPS 301 導向 HTTP 首頁，再進 Swagger UI。正式同步器不應依賴這條不安全降級 redirect；應直接使用上表的 HTTPS Swagger discovery URL。

## 3. 更新頻率與版本時間

| 時間欄位 | 值 | 語義與使用方式 |
| --- | --- | --- |
| 官方更新頻率 | 每 7 日 | **[VERIFIED]** 資料集頁宣告；不是「固定星期幾」的 SLA |
| 資料集詮釋資料更新時間 | 2026-09-11 15:57 | **[VERIFIED]** 平臺頁面的 metadata 修改時間，不等於每筆許可證的異動日 |
| ZIP entry timestamp | CSV 2026-09-11 15:57:34+08:00；JSON 15:58:02；XML 15:57:20 | **[VERIFIED]** artifact metadata，不當作唯一版本號 |
| XML 內嵌最後更新日期 | 2026/09/10 | **[VERIFIED]** Information processing instruction；CSV／JSON 未見同等內嵌欄位 |
| 資料列最大異動日期 | 2026/09/10 | **[VERIFIED]** 本次 104,619 列的最大值；是記錄異動範圍，不等於下載時間 |
| HTTP Last-Modified／ETag | 未提供 | **[VERIFIED]** 三個下載端點本次 HEAD 皆未回傳；不可據此做 conditional GET |

建議每日檢查一次，下載後以 SHA-256 去重，不硬猜官方更新星期。manifest 同時保存 fetched_at、portal_metadata_modified_at、embedded_data_updated_on、max_record_changed_on、zip_entry_timestamp。內容日期年齡只能依 [PRD 第 7.1～7.3 節](../product-requirements.md)另列 content_age_status 與 content_age_evidence，不可由 embedded_data_updated_on 或 max_record_changed_on 直接把 serving snapshot 判為 stale。stale、stale_reason_codes 與所有 public status 欄位只引用該 PRD registry。

## 4. 實際下載與 ZIP 結構

核對時間：2026-09-13 00:56–01:00（Asia/Taipei）。下載只放在系統暫存區分析，未加入 repo。

| Endpoint | ZIP bytes | ZIP SHA-256 | ZIP entry | 解壓 bytes | 編碼／結構 |
| --- | ---: | --- | --- | ---: | --- |
| CSV | 16,265,433 | DE880620C56177E492806618F103FC7AC55B4F7302E7870C9992FACBA7F08292 | 68_2.csv | 70,554,601 | UTF-8 with BOM；104,619 data rows |
| JSON | 18,863,948 | 03C52A0B75846E1AF72BFABBC707FDCC18CD26A53C90FCBB9D79C434CC627ABA | 68_5.json | 136,452,182 | UTF-8；top-level array；104,619 objects |
| XML | 20,462,042 | ECBAFA63D7998556F5FA9FD3E50B9A52E1B7D746E91CCF312FC72602A709704F | 68_1.xml | 201,426,616 | UTF-8；dataList/rows；104,619 rows |

**[VERIFIED]** 三種格式欄位順序一致，都是 34 欄。將 JSON 的 null 正規化為空字串後，逐列逐欄與 CSV 比對為 0 個差異。XML 104,619 列的子元素欄位順序亦全部一致。

### 4.1 OAS 與實際回應不一致

| 項目 | OAS 宣告 | 2026-09-13 實際回應 | 實作結論 |
| --- | --- | --- | --- |
| CSV MIME | text/csv | application/zip | 先驗 ZIP magic bytes，不依副檔名或 MIME 直接當 CSV |
| JSON MIME | application/json | application/zip | 同上 |
| XML MIME | application/xml | application/zip | 同上 |
| 日期 | string, format=date-time | YYYY/MM/DD，無時間與時區 | 使用來源專用 strict date parser |
| nullable | OAS 未明確標 nullable／required | JSON 多欄為 null；CSV 同欄為空字串 | normalization 前保留原格式；curated 統一為 null |

Importer 應以「ZIP → 單一預期 entry → 實際 header」作可信邊界；OAS 只用於 schema drift 的輔助比對，不作為實際傳輸格式的唯一真相。

### 4.2 ZIP 安全門檻

- entry path 正規化後不得為絕對路徑、UNC、drive path 或含父目錄跳脫。
- 此 adapter 要求恰好一個非目錄 entry，且副檔名與 endpoint 相符；變更即停止發布並人工審查。
- 建議上限：壓縮檔 64 MiB、單一解壓檔 256 MiB、總解壓 256 MiB、壓縮比 30；目前三份皆在範圍內。
- 不採用 server 提供的檔名直接寫檔；Content-Disposition 本次為非標準形式 filename*=UTF-8' '...，下載器應自行產生安全暫存檔名。
- 解壓、解析、雜湊與驗證完成前，不可改動 current availability descriptor；descriptor 欄位與切換方式由 SDD 第 8 節治理。

## 5. 完整欄位與樣本 header

本次 CSV header：

    "許可證字號","註銷狀態","註銷日期","註銷理由","有效日期","發證日期","許可證種類","舊證字號","醫療器材級數","通關簽審文件編號","中文品名","英文品名","效能","劑型","包裝","醫器主類別一","醫器次類別一","醫器主類別二","醫器次類別二","醫器主類別三","醫器次類別三","主成分略述","醫器規格","限制項目","申請商名稱","申請商地址","申請商統一編號","製造商名稱","製造廠廠址","製造廠公司地址","製造廠國別","製程","異動日期","製造許可登錄編號"

下表的 OAS 型別是官方 schema 宣告；空值數是 2026-09-13 CSV 實測。OAS 只提供型別與部分長度，沒有逐欄業務定義，因此欄位名稱以外的延伸解讀須保守。

| # | 欄位 | OAS 型別 | 空值數 | Curated 用法／注意事項 |
| ---: | --- | --- | ---: | --- |
| 1 | 許可證字號 | string ≤120 | 0 | 許可／登錄識別值；不是 row unique key，原值與搜尋正規化值並存 |
| 2 | 註銷狀態 | string ≤6 | 49,659 | 本次值為空、已註銷、已廢止；兩個非空值不可合併 |
| 3 | 註銷日期 | date-time | 49,543 | 實際為 nullable YYYY/MM/DD；與狀態獨立驗證 |
| 4 | 註銷理由 | string | 53,879 | 保留原文，不自行分類法律原因 |
| 5 | 有效日期 | date-time | 0 | 實際為 YYYY/MM/DD；不能單獨代表仍可上市或仍在販售 |
| 6 | 發證日期 | date-time | 0 | 實際為 YYYY/MM/DD |
| 7 | 許可證種類 | string ≤120 | 0 | 本次全為 09；**[UNVERIFIED]** OAS 未提供 codebook，不自行翻譯 |
| 8 | 舊證字號 | string ≤100 | 103,615 | 歷史連結候選；不可假設一對一或完整 |
| 9 | 醫療器材級數 | string ≤2 | 11,439 | 本次為空、1、2、3；空值不能推為第一級 |
| 10 | 通關簽審文件編號 | string ≤20 | 17,858 | 保存原值；不當作許可證字號替代鍵 |
| 11 | 中文品名 | string | 2 | 搜尋與顯示；原文保留，另建 Unicode/空白正規化欄位 |
| 12 | 英文品名 | string ≤4000 | 3 | 不得以相似品名推論產品等效 |
| 13 | 效能 | string ≤4000 | 10,823 | 只做檢索，不產生臨床效能比較結論 |
| 14 | 劑型 | string ≤200 | 104,619 | 本 snapshot 全空；保留 schema，不據此刪欄 |
| 15 | 包裝 | string | 104,432 | 高度稀疏；若未來開始填值，視為內容 drift |
| 16 | 醫器主類別一 | string ≤120 | 57 | 同時存在現行 A–P 名稱及舊制數字分類 |
| 17 | 醫器次類別一 | string ≤120 | 17,616 | 第一組品項 code＋名稱；IVD join 的主要來源之一 |
| 18 | 醫器主類別二 | string ≤120 | 102,172 | 第二組分類；不得覆蓋第一組 |
| 19 | 醫器次類別二 | string ≤120 | 102,178 | 第二組品項；以陣列建模 |
| 20 | 醫器主類別三 | string ≤120 | 103,825 | 第三組分類；不得覆蓋第一、二組 |
| 21 | 醫器次類別三 | string ≤120 | 103,830 | 第三組品項；以陣列建模 |
| 22 | 主成分略述 | string | 92,277 | 高度稀疏；只保留原文及檢索欄位 |
| 23 | 醫器規格 | string | 2,996 | 保留換行與原文；索引版另清理空白 |
| 24 | 限制項目 | string | 1,241 | 不自行推導販售或使用資格 |
| 25 | 申請商名稱 | string ≤300 | 1 | 與地址、統編同組；缺值列進 quarantine/review |
| 26 | 申請商地址 | string ≤300 | 6 | 正規化地址只能作搜尋輔助 |
| 27 | 申請商統一編號 | string ≤60 | 794 | 必須以字串保存；186 個非空值不是 8 位純數字 |
| 28 | 製造商名稱 | string ≤500 | 3 | 每列製造關係；同一字號可有多個製造商 |
| 29 | 製造廠廠址 | string ≤400 | 9 | 與製造商、國別、製程一起保存 |
| 30 | 製造廠公司地址 | string ≤400 | 104,348 | 與製造廠廠址不是同欄；不得自動互相補值 |
| 31 | 製造廠國別 | string ≤100 | 25 | 多為兩碼值；**[UNVERIFIED]** OAS 未宣告 ISO 標準 |
| 32 | 製程 | string ≤4000 | 86,675 | 可為全部製程、委託製造者、Manufactured by，亦有雙分號複合值 |
| 33 | 異動日期 | date-time | 0 | 實際為 YYYY/MM/DD；不取代 snapshot 更新時間 |
| 34 | 製造許可登錄編號 | string | 58,695 | 不在未核對另一官方資料集前推論其有效性 |

建議把三組主／次類別轉成 classifications 陣列，把同字號多列轉成 manufacturing_sites 陣列，但每列原始值與 source_row_id 都要保留。MCP 對外顯示名稱宜用「許可／登錄字號」，因實際字號中包含「登」類記錄。

## 6. 資料量與品質基線

| 指標 | 2026-09-13 實測 |
| --- | ---: |
| 資料列 | 104,619 |
| 欄位 | 34 |
| 欄寬不符列 | 0 |
| 不同許可／登錄字號 | 93,219 |
| 出現多列的字號 | 11,229 |
| 單一字號最大列數 | 4 |
| 完全相同的重複列 | 0 |
| 同字號申請商三欄互相衝突 | 0 |
| 任一主類別為現行 A／B／C 的列 | 19,794 |
| 上述不同字號 | 17,477 |
| A／B／C 主類別但沒有可解析 A/B/C 次類別 code 的列 | 2,211 |
| 本次不同 A/B/C 次類別 code | 399 |

三個主類別欄合計有 98,131 格為現行 A–P 格式、9,337 格為舊制四位數字格式、206,054 格空白，另有 335 格其他格式。Parser 必須保留原始值並版本化 parse 規則，不能把未匹配資料丟掉。

## 7. 許可狀態、效期與法人角色

### 7.1 狀態與日期要分軌

| 註銷狀態 | 列數 |
| --- | ---: |
| 空白 | 49,659 |
| 已註銷 | 53,731 |
| 已廢止 | 1,229 |

以 2026-09-13 比對有效日期：

| 組合 | 列數 |
| --- | ---: |
| 狀態空白＋有效日期尚未到期 | 43,661 |
| 狀態空白＋有效日期已過 | 5,998 |
| 已註銷＋有效日期已過 | 53,531 |
| 已註銷＋有效日期尚未到期 | 200 |
| 已廢止＋有效日期已過 | 771 |
| 已廢止＋有效日期尚未到期 | 458 |

另有 116 列「註銷狀態空白但註銷日期有值」，不可自動判為有效。Immutable raw／curated row 只保留 source_cancellation_status_raw、註銷日期、註銷理由與 valid_through 等來源證據；不得保存會隨日期改變的合成狀態。

Query time 才依明示的 evaluated_as_of（預設 Asia/Taipei 當日）分開產生 cancellation_recorded_in_source=true|false|unknown 與 within_validity_period_as_of=true|false|unknown，並套用 [PRD 第 6.3.1 節 canonical truth table](../product-requirements.md)。兩個輸出永遠不可合成 computed_temporal_state、not_cancelled_and_within_validity、「有效許可」、上市、販售、採購或 TFDA 推薦結論。

### 7.2 申請商與製造商不可混合

**[VERIFIED]** 同一許可／登錄字號的多列，常對應不同製造商、製造廠址或製程；可同時有台灣包裝廠、海外製造廠及委託製造者。

- 申請商只標示為來源欄位的 applicant，不改稱品牌商、進口商、經銷商或目前持證商，除非有其他官方欄位支持。
- 製造商與製造廠是一對多關係；以 source row 保存，不任意合併。
- 字號是 group key，不是 row key。建議 source_row_id 為 canonical raw row 的 SHA-256。
- manufacturer_site_id 可由製造商＋廠址＋國別＋製程原值產生 hash，但不宣稱是 TFDA 官方 ID。

## 8. IVD 識別：可行範圍與不確定性

### 8.1 官方定義

TFDA 2026-02-11 官方問答與「醫療器材許可證核發與登錄及年度申報準則」所用定義一致：IVD 是蒐集、處理或檢查取自人體的檢體，供診斷疾病、決定健康狀態或其他狀況使用的試劑、儀器、軟體或系統。TFDA 並指向「醫療器材分類分級管理辦法」第四條附表作品項鑑別。

### 8.2 為什麼不能只取 A／B／C

- **[VERIFIED]** A／B／C 是應用科別分類，不是 ivd=true 標記。
- **[VERIFIED]** B.9225「體外診斷用的細胞冷凍設備及反應劑」明確屬 IVD 用途。
- **[VERIFIED]** 同一 B 類的 B.9195「血液混合器及血液重量分析裝置」只描述混合／稱重；B.9245「自動血球細胞分離器」描述供血者血液成分分離後輸回或供輸血／血品製備。依官方 IVD 定義，不能因主類別為 B 就自動標 IVD。
- **[VERIFIED]** 本次資料實際含 B.9195 26 列、B.9245 105 列、B.9225 26 列，false positive 不是純理論問題。
- **[UNVERIFIED]** 官方資料集與 OAS 都沒有完整、機器可讀的「是否 IVD」codebook；附表也未對每一品項放一致的 IVD 標籤。

### 8.3 建議的可稽核規則

建立版本化表 tfda_device_classification_ivd_review，至少包含：

| 欄位 | 說明 |
| --- | --- |
| classification_code | 例如 A.1345；從官方附表抽取 |
| zh_name, en_name, risk_class, identification_text | 官方原文，不改寫 |
| regulation_version, effective_from, source_page, source_sha256 | 法規版本與定位 |
| ivd_scope | public 值只接受 included／excluded／ambiguous／unknown |
| decision_basis | 引用 IVD 定義與該品項鑑別文字 |
| reviewer, reviewed_at, rule_version | 專業 reviewer 與版本 |

許可證 join 邏輯：

1. 解析「醫器次類別一～三」的正式代碼，不用主類別名稱作最終判斷。
2. Approved included code 且沒有衝突時，public ivd_scope 為 included；included 與 excluded／ambiguous 規則同時命中時為 ambiguous。
3. 全部已 review codes 都是 excluded 時，public ivd_scope 才為 excluded。
4. 次類別缺失、舊制數字格式、未知 code 或法規版本不明，一律 public ivd_scope=unknown，不可當成非 IVD。
5. search_ivd_candidates 只回 included／ambiguous／unknown；search_reviewed_ivd 只回 approved included。品名、效能、規格關鍵字只能增加 candidate operation 的召回，不能覆蓋 registry decision。

Legacy/internal 名稱若需要讀取舊資料，只能在明示 migration 中映射：not_ivd_by_reviewed_classification → excluded、ivd_unknown → unknown；ivd_candidate 代表 operation-level candidate membership，不是 ivd_scope。review_pending 只屬 review workflow。這些舊名稱均不得出現在 public result；唯一 public enum 以 [PRD 第 6.3.2 與 7.1 節](../product-requirements.md)為準。

### 8.4 正式上線前的 owner gate 與已決議事項

- 399 個本次出現的現行 A/B/C 次類別 code 必須逐碼 review；不能只抽樣後宣稱完整。
- 舊制數字分類要另找 TFDA 官方歷史附表或明確 crosswalk。TFDA 2025 年 FAQ只確認新舊主類別名稱對應，未提供所有次類別 code crosswalk。
- 每個決策保存官方鑑別原文與頁碼；法規更新時，只重新審查新增、刪除、修改或生效日改變的 code。
- Review 完成前，MCP 對外只能稱「IVD 候選」，不可稱「台灣完整 IVD 清單」。
- **[RESOLVED by PRD OD-03]** ambiguous／unknown 可出現在 search_ivd_candidates，但不得標成正式 IVD；仍待 owner 決定的只有 registry reviewer。

## 9. 清理、驗證與 quarantine

### 9.1 Raw → staged

- 保存 ZIP 原檔、URL、HTTP status/MIME、取得時間、ZIP/entry SHA-256、entry 清單與大小。
- CSV 以 utf-8-sig 開啟；所有欄位先以字串接收，禁止自動把字號、統編或級數轉數字。
- 保留原始換行、全形／半形、引號與空白；另產生搜尋用 NFKC、trim、collapsed-whitespace 欄位。
- 日期只接受空值或 YYYY/MM/DD。原字串與 ISO YYYY-MM-DD 並存。

### 9.2 Staged 驗證與 diagnostic row disposition

P1.1 不允許 partial publish。Quarantine 是診斷證據區，不是排除壞列後繼續發布的資料層；只要 quarantined_rows > 0，整個 candidate build 必須 block，current descriptor 維持不變。Published snapshot 必須滿足 input_rows == curated_rows 且 quarantined_rows == 0。Canonical disposition 以 [SDD 第 8.1 節](../software-design.md)及 [PRD coverage/status 契約](../product-requirements.md)為準。

整批 hard fail：

- ZIP magic、entry 數、路徑、大小或壓縮比不合規。
- 缺少或重複任一既有 34 欄、CSV row width 不一致、檔案無法完整解析。
- 資料列為 0、任一 source row 無法 round-trip、任一核心識別或必要日期無法解析、日期格式全面改變、字元解碼失敗。
- 官方 schema／實際 header 出現未審核 breaking change。

Diagnostic quarantine evidence；任一項出現均整批 block：

- 許可證字號空白。
- 必要日期不可解析或發證日期晚於有效日期。
- 註銷日期非空但無法依核准格式解析。
- 欄位／原值無法 round-trip，或 source row identity 無法建立。

完整保留於 curated 的 semantic warning，不可 quarantine 或隱藏原列：

- 同字號申請商資料不一致、相同 source row hash 重複、製造關係大量變動。
- 註銷狀態不在已知集合、狀態／日期組合不一致、角色欄缺值：保留 raw evidence，查詢依 PRD 第 6.3.1 節 truth table 回對應 warning／unknown。
- 醫療器材級數空白、主類別為舊制數字、次類別 missing/unknown：原列完整進 curated，public ivd_scope=unknown；一般許可查詢仍可用，reviewed-only IVD 不得納入。
- 空白註銷狀態但有效日期已過、非空註銷狀態但有效日期仍在未來：保留兩軌證據，不合成最終有效性。

### 9.3 Schema drift 與資料量 drift

- 保存 ordered_header_sha256、header_set_sha256、OAS schema hash、row count、distinct permit count、status distribution、分類格式分布、各欄 null rate。
- 欄位刪除／改名／重複：hard fail。
- 新增欄位：先 staged，更新 schema 與測試並人工核准後才發布；不能默默丟棄。
- Row count 相對上一版變化超過 10%、任一關鍵欄 null rate 增加超過 2 個百分點、未知 status/code 出現：停止自動發布並產生 diff report。
- OAS 與 payload 不一致是目前已知例外，應固定 regression test；若未來改回裸格式，也視為 transport drift。

## 10. Fail-closed 發布流程

    download to unique temp file
      → verify HTTPS response + ZIP magic + safe entries
      → hash ZIP and entry
      → parse all rows as strings
      → validate exact approved schema
      → normalize without overwriting raw values
      → write diagnostic quarantine evidence and batch quality report
          ├─ quarantined_rows > 0 → block candidate; current unchanged
          └─ quarantined_rows = 0 → continue
      → preserve unknown classifications in curated with ivd_scope=unknown
      → join versioned IVD classification review table
      → run golden cases and distribution drift checks
      → write immutable snapshot
      → atomically replace current availability descriptor

- 任一步失敗都保留上一個已驗證 snapshot；不得改用 sample 資料偽裝成功。
- 若繼續提供上一版，MCP 依 [PRD 第 7.1～7.3 節](../product-requirements.md)回傳 serving/candidate 分離狀態、stale、stale_reason_codes 與時間證據；本研究文件不另定 public status enum。
- Runtime 只讀 current availability descriptor 指向的 immutable snapshot，不讀 raw、staged 或 quarantine。
- 查詢結果的 public status 欄、provenance 與 locator 只引用 [PRD 第 7 節 canonical registry](../product-requirements.md)；TFDA item 另保留 source row id、許可／登錄字號與 IVD 規則版本。

## 11. 授權與顯名

**[VERIFIED]** 資料集頁指定「政府資料開放授權條款－第 1 版」，免費。條款允許不限目的、時間與地域利用及再授權，但使用開放資料與衍生物時必須明確顯名；未盡顯名義務視為自始未取得授權。條款也明定資料提供不構成機關推薦、同意、許可或核准。

建議顯名文字：

> 衛生福利部食品藥物管理署（2026），醫療器材許可證資料集（snapshot：〔snapshot-id〕）。資料依政府資料開放授權條款－第 1 版釋出：https://data.gov.tw/license。本 MCP 為衍生應用，不代表 TFDA 推薦、同意、許可或核准。

年份與 snapshot id 應由實際 manifest 產生，不寫死在程式碼。

## 12. 實作切片與驗收門檻

1. **下載與 schema（1–2 日）**：先做 CSV ZIP、安全下載、SHA-256、34 欄 strict parser、manifest 與資料量基線。驗收須涵蓋惡意 ZIP、缺欄、裸 HTML、MIME 錯置。
2. **狀態與製造關係（1–2 日）**：狀態／效期分軌，字號 group 與 manufacturing rows 一對多。Golden cases 涵蓋已註銷但未到有效日、空白狀態但已過期、多製造廠。
3. **IVD classification registry（3–5 日＋reviewer）**：從官方附表建立逐碼 registry；399 個現有 A/B/C code 完成 review。B.9195、B.9245 不可誤入，B.9225 應正確命中，舊制／缺 code 回 unknown。
4. **MCP 與運維（1–2 日）**：依 PRD 第 7.1～7.3 節加入 canonical provenance、serving/candidate status、stale_reason_codes、rule version 與 get_data_status。下載失敗不得污染 current；無 official snapshot 時 availability=data_unavailable。

## 13. 尚未驗證／需 owner 決定

- **[UNVERIFIED]** 許可證種類 09 的官方 codebook 尚未在本次一手 schema 中出現；先原值輸出。
- **[UNVERIFIED]** 製造廠國別是否保證 ISO 3166-1 alpha-2；本次值看似兩碼，但 OAS 只標 string。
- **[UNVERIFIED]** 異動日期的精確業務觸發條件；只稱來源異動日期。
- **[UNVERIFIED]** 舊制四位數字次分類到現行 A–P 品項的完整官方 crosswalk。
- **[OWNER GATE]** 指定 IVD classification registry reviewer。
- **[RESOLVED by PRD OD-03]** ambiguous／unknown 可出現在 search_ivd_candidates，但不得標成正式 IVD。
- **[OWNER GATE]** Curated snapshot 是隨 GitHub Release 再散布，或只提供工具讓部署者自行下載。

## 14. 研究方法與可重跑證據

- 官方頁面、Swagger/OAS 與法規附件於 2026-09-13 即時核對。
- 三個公開端點實際下載到系統暫存區，以 ZIP metadata、SHA-256、UTF-8 解碼、CSV/JSON/XML 全量 parse 驗證。
- JSON null 正規化後與 CSV 全量逐欄比對；XML 以 streaming parse 核對列數與欄位順序。
- 現行 163 頁分類附表以本機 LiteParse 2.0.0、no-OCR 解析文字層，並回到 TFDA 官方 PDF 核對品項與頁碼。
- 未下載或提交任何限制資料、個資或院內資料；本次 raw artifact 不進 Git。
