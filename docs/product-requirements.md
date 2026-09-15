# Taiwan Laboratory MCP P1.1 產品需求文件（PRD-lite）

文件狀態：Draft for owner review

版本：0.3（Round 2 revisions）

依據核對日期：2026-09-13（Asia/Taipei）

適用版本：P1.1 正式公開資料查詢

## 1. 文件目的與證據標記

本文件定義 P1.1 要交付的使用者能力、可測驗收條件與發布門檻。技術資料契約與實作細節另見 `software-design.md`；測試案例應由本文件的 acceptance criteria 衍生，不得用實作方便性改寫產品邊界。

本文件使用下列標記：

| 標記 | 意義 | 產品處理 |
| --- | --- | --- |
| `VERIFIED` | 已由 2026-09-13 官方頁面、官方 metadata 或實際官方檔案核對 | 可作目前設計基線；新 snapshot 仍須重新驗證 |
| `INFERENCE` | 從資料分布推論，官方未明文定義 | 保留原值、明示推論，不轉成確定敘述 |
| `UNVERIFIED` | 尚無足夠一手證據 | 不作肯定回答；列為 owner／reviewer 待確認 |
| `RECOMMENDATION` | 本專案提出的產品或工程門檻 | 不宣稱為官方規定 |
| `OWNER GATE` | 需要產品 owner 明確決定或指定責任人 | gate 未完成前不得把受影響資料標成正式可用 |

## 2. 產品目的

Taiwan Laboratory MCP 讓醫檢相關使用者透過 AI Agent 查詢三個領域、四個公開資料集／查詢任務：CDC 採檢手冊、CDC 傳染病認可檢驗機構名冊、NHI 醫療服務給付項目，以及 TFDA 醫療器材許可資料。

P1.1 的核心價值是「縮短找到官方資料並核對原文的時間」。產品提供檢索、結構化呈現與來源定位，不提供診斷、個案申報判定、採購建議、產品等效性判定或主管機關背書。

## 3. 目標使用者與工作情境

| Persona | 主要工作（job） | 目前痛點 | P1.1 提供的結果 |
| --- | --- | --- | --- |
| 第一線醫檢師 | 查疾病的檢體、採檢時機、採檢量及規定、送驗方式、注意事項，以及官方欄位「應保存種類（應保存時間）」 | 官方手冊長、同疾病可有多目的與多檢體，且「應保存」容易被誤解為送驗前保存 | 依原始表格列分開呈現，附版本、頁碼與原文定位；明示「應保存」不是檢體送驗前保存條件 |
| 醫檢管理者／申報資料查詢者 | 查醫療服務項目代碼、點數、生效欄位與備註 | 名稱與代碼查找分散，容易把點數誤當金額或現行資料誤當歷史資料 | 回傳當前已驗證 snapshot 的完整原始欄位與範圍警示 |
| 醫檢、採購或 IVD 從業人員 | 查公開的產品許可／登錄資料、狀態與廠商角色 | 同字號可有多製造關係，效期與註銷狀態不能只看一欄 | 保留一對多製造關係、狀態分軌與 IVD 篩選依據 |
| 送驗規劃者 | 找可查核特定傳染病／方法的認可檢驗機構 | ODS 有合併儲存格與同證號多方法，人工篩選容易錯配 | 依證號、疾病、目的與方法列出候選機構及名冊定位 |
| Workshop 講師／參與者 | 示範如何用 AI 查公開醫檢資料並核對來源 | 容易把流暢回答誤當官方答案 | 看得到模式、版本、警示與來源，且可自行核對至少一筆 |

## 4. Jobs、user stories 與產品原則

1. 當我收到傳染病送驗需求時，我要依疾病、採檢項目與目的查看原始列，並能回到手冊原頁核對，避免把不同列拼在一起，也不把「應保存種類（應保存時間）」誤認為送驗前保存條件。
2. 當我查健保項目時，我要用代碼或中英文名稱找到現行 snapshot 中的候選列，看到點數、生效欄位、備註及資料能力限制。
3. 當我查 IVD 許可資料時，我要知道命中的許可／登錄字號、產品原文、註銷與效期欄位、申請商、所有製造關係及 IVD 分類依據。
4. 當我找認可檢驗機構時，我要依疾病與檢驗方法取得名冊候選，看到認可結束時間與能力試驗原值，並知道這不是收件可行性的保證。
5. 當資料尚未核准、更新失敗、過期或查無結果時，我要看到明確狀態與搜尋範圍，且不能收到悄悄混入的 sample 或推測答案。

所有場景共同遵守：原始值優先、查詢結果可追溯、不確定性可見、sample 與 official 不混查、查無資料不等於不存在。

## 5. P1.1 範圍

### 5.1 In scope

1. 建立並查詢三個領域、四個資料集的已驗證本機 snapshot：CDC 採檢手冊、CDC 認可機構 ODS、NHI 支付標準 CSV、TFDA 醫療器材許可證 CSV ZIP。
2. 支援 `sample` 與 `official_snapshot` 模式；每次查詢揭露資料模式、snapshot、來源、版本／官方時間、取得時間、驗證與 freshness 狀態。
3. 提供第 5.3 節 canonical operation matrix 所列 MCP tools，以及 `get_data_status` 的逐資料集狀態；既有 tool 只有在該矩陣明列相容行為時才保留。
4. 對 schema drift、下載／解析失敗、專業 review pending 與 stale 狀態採 fail-closed；可繼續服務上一個已核准 snapshot，但須明確警示。
5. 以 5–10 位醫檢相關使用者完成任務式測試，收集非病人、非機密的自願回饋。

### 5.2 Out of scope

1. 病人資料、病歷、院內資料清理、去識別化、Hospital Data Readiness、LIS／HIS 串接與院內正式部署。P1.1 僅適合本機離線公開資料查詢，不構成 hospital deployment readiness。
2. 診斷、治療或採檢個案決策；自動送出申報、判定個案可申報、把支付點數換算為實收金額。
3. 採購建議、產品可替代／臨床等效判定、販售狀態保證或主管機關推薦／核准聲明。
4. 完整歷史 NHI 點數資料庫、完整歷史 CDC 手冊庫，或對啟用同步前的歷史狀態作回推。
5. LOINC、FHIR、SNOMED、EQA、CAP 正式內容；P1.1 僅維持現有 adapter／status 保留介面。

### 5.3 Canonical operation matrix

本表是 P1.1 public MCP contract 的封閉 operation registry；公開集合必須與表中 22 個 exact names 完全相等。Machine-readable 真源目前已建立於 package resource `src/taiwan_lab_mcp/contracts/public-contract-v1.json`，內容同時包含 operation、request／response schemas、source payload／locator schemas、public enum、freshness、TFDA warning 與 safety registries；source／installed-wheel equality verification 已完成。SDD 可使用不同內部物件，但必須一對一 mapping，TDD 以 package resource 對 MCP `list_tools` 做集合、signature 與 response-schema equality，禁止 repo-relative fallback。

共同型別規則：`string` 必須是 trim 後非空字串；nullable string 只接受 `null` 或非空字串；`limit` 是 1–100 的 integer（搜尋類 operation `search_payment_items`、`search_reviewed_ivd`、`search_ivd_candidates`、`list_matching_license_records`、`find_manufacturer` 為 1–5、預設 5（owner 2026-09-15 先說「給20筆就很夠了」，同日改為「20筆好像還是有點太多，還是給5筆 有需要的話可以再進一步找」）；~~`find_authorized_lab` 同為 1–5、預設 5（owner 2026-09-15「A 加翻頁」，OD-13）~~ `find_authorized_lab` 為 1–20、預設 20（owner 2026-09-15「一次 20 筆」，OD-13）；`compare_products` 維持 1–100）；`offset` 是大於等於 0 的 integer。所有 data query operations 同時存在於 `sample` 與 `official_snapshot` mode；sample 只讀 synthetic fixtures 且固定警示，official 只讀該 source 的 serving build，source unavailable 不影響其他 source。所有可回多筆的 operation 都受 bounded-result contract 約束：有 `limit`／`offset` 參數者依 request；未公開分頁參數者固定 `limit=20, offset=0`。回應一律含 `total_matches`、`returned_count`、`limit`、`offset`、`truncated`，不得無界回傳或靜默截斷；compatibility alias 使用其 canonical operation 的 default page。

| Exact operation | Classification | Exact parameters（type/default） | Source | Mode | Canonical behavior |
| --- | --- | --- | --- | --- | --- |
| `get_data_status` | status | 無 | `all_sources` | sample + official | 逐一回四個資料集的第 7 節 public status/freshness，不合成單一健康狀態 |
| `search_disease` | active | `query: string` | `cdc_manual` | sample + official | 依疾病搜尋原始手冊列，回 matched rows 與 typed locator |
| `get_specimen_requirement` | active | `disease: string` | `cdc_manual` | sample + official | 回疾病匹配的完整第 2 章原始列，不跨列合併 |
| `get_collection_method` | compatibility alias | `disease: string` | `cdc_manual` | sample + official | alias 到 `get_specimen_requirement`；不合成來源沒有的獨立採檢方法欄 |
| `get_container` | compatibility alias | `disease: string` | `cdc_manual` | sample + official | alias 到 `get_specimen_requirement`；不從複合欄推導獨立容器值 |
| `get_transport_requirement` | compatibility alias | `disease: string` | `cdc_manual` | sample + official | alias 到 `get_specimen_requirement`；只保留送驗方式／注意事項原文，不推導 storage instruction |
| `get_submission_rule` | compatibility alias | `disease: string` | `cdc_manual` | sample + official | alias 到 `get_specimen_requirement`；回原始送驗相關欄位與定位 |
| `find_authorized_lab` | active | `query: string, city: string|null=null, limit: integer=20, offset: integer=0` | `cdc_recognized_labs` | sample + official | 依疾病／目的／方法／證號／機構與 optional city 回名冊候選，不保證收件；~~沒有翻頁參數，固定前 20 筆~~ ~~`limit` 1–5~~ `limit` 1–20，可用 `offset` 翻頁（owner 2026-09-15「A 加翻頁」「一次 20 筆」，OD-13）；`query` 以空格分成多個詞時每個詞都要命中，縣市詞改為縣市篩選（OD-14） |
| `get_lab_scope` | compatibility alias | `query: string` | `cdc_recognized_labs` | sample + official | 使用 `find_authorized_lab(query, city=null, limit=20, offset=0)` 的相同 matching 與 default page |
| `search_payment_items` | active | `query: string, limit: integer=5, offset: integer=0` | `nhi_fee` | sample + official | 查全表代碼／官方名稱／approved alias；回 total、分頁、scope、coverage、matched_by。每筆為摘要 record `nhi_fee_summary`：代碼、點數、起迄日、中英文名稱、scope_status、備註前 60 字與全文字數；`limit` 1–5（owner 2026-09-15：先定 1–50 避免超過 host 輸出上限，同日改為「給20筆就很夠了」，再改為「還是給5筆」）；完整備註與 scope 依據用 `get_points`／`get_payment_rule` |
| `search_lab_code` | compatibility alias | `query: string` | `nhi_fee` | sample + official | 使用 `search_payment_items(query, limit=5, offset=0)`；名稱不代表完整 laboratory scope |
| `get_points` | active | `code: string, as_of: string|null=null` | `nhi_fee` | sample + official | null 才做 current exact-code lookup；non-null 依下方 precedence 固定拒絕歷史查詢 |
| `get_payment_rule` | active | `query: string` | `nhi_fee` | sample + official | trim 後非空且按 exact code 查詢；wrong type／空字串回 `invalid_request`，合法非空但無 exact match 回 `not_found`；不套用未經來源證實的固定碼長 regex |
| `search_reviewed_ivd` | active | `query: string, manufacturer: string|null=null, limit: integer=5, offset: integer=0` | `tfda_device` | sample + official | 只回 approved `ivd_scope=included`；若只有 candidate 命中則 `candidate_matches_available`；每筆為摘要 record `tfda_device_summary`，`limit` 1–5（owner 2026-09-15），完整欄位用 `get_license` |
| `search_ivd_candidates` | active | `query: string, manufacturer: string|null=null, limit: integer=5, offset: integer=0` | `tfda_device` | sample + official | 回 `included|ambiguous|unknown` candidates、coverage、理由、總數與 truncation；每筆為摘要 record `tfda_device_summary`，`limit` 1–5（owner 2026-09-15） |
| `search_ivd` | compatibility alias | `query: string, manufacturer: string|null=null` | `tfda_device` | sample + official | 使用 `search_reviewed_ivd(query, manufacturer, limit=5, offset=0)`，description 明示 reviewed-only |
| `get_license` | active | `license_no: string` | `tfda_device` | sample + official | exact 許可／登錄字號，保留全部 source rows、角色、truth-table outputs；每列為完整 record `tfda_device`（34 個官方欄位原文、標籤與 truth-table 輸出） |
| `find_manufacturer` | active | `name: string, limit: integer=5, offset: integer=0` | `tfda_device` | sample + official | 依製造商名稱搜尋，保留同字號各 source row，不把申請商當製造商；每筆為摘要 record `tfda_device_summary`，~~固定前 20 筆~~ `limit` 1–5，可用 `offset` 翻頁（owner 2026-09-15） |
| `list_matching_license_records` | active | ~~`query: string, limit: integer=10`~~ `query: string, limit: integer=5, offset: integer=0, prefer_ivd: boolean=false, prefer_main_category: string|null=null, ivd_scope: string|null=null, main_category: string|null=null`（OD-06） | `tfda_device` | sample + official | ~~只按穩定非臨床順序並列原始欄位；不計分、不判等效、不作採購排序~~ 查全部許可證列（含已註銷），依 TFDA-06 命中程度排序並分頁；偏好只調順序、篩選只在明確指定時縮小範圍；並列原始欄位與標籤，不輸出品質分數、不判等效、不作採購排序；每筆為摘要 record `tfda_device_summary`（字號、中英文品名、申請商、製造商與國別、級數、許可證種類、主類別字母、分類代碼、`ivd_scope`、註銷與效期判斷、效能前 60 字與全文字數），完整欄位用 `get_license` |
| `compare_products` | deprecated | `query: string, limit: integer=10` | `tfda_device` | sample + official | 固定 `deprecated_unsupported`、0 items，指向 `list_matching_license_records` |
| `standards_status` | reserved status | 無 | `reserved_standards` | sample + official | 只回 LOINC／FHIR／SNOMED 尚未設定狀態，不查或內含術語資料 |
| `eqa_status` | reserved status | 無 | `reserved_eqa` | sample + official | 只回 EQA／CAP 未設定與授權待確認狀態，不抓 catalog |

NHI `get_points` validation precedence 固定如下：先驗證所有參數；`code` wrong type／空字串，或 `as_of` wrong type／空字串／不是嚴格 `YYYY-MM-DD`／不是有效 Gregorian calendar date，回 `invalid_request`、0 items。參數合法且 `as_of` 非 null 時，在 source availability 與 code lookup 前回 `historical_query_unsupported`、`historical_truth_supported=false`、0 items。只有 `as_of=null` 才依序處理 source availability，再做 exact-code lookup並回 `ok|not_found`。

NHI alias 只有在版本化 registry 中狀態為 `approved` 才能影響正式搜尋。每筆 alias 必須保存 alias 原文、對應 code、來源類型、來源 URL／locator、rule version、reviewer、reviewed_at 與 collision disposition；未核准 alias 不參與查詢。正規化僅採 Unicode NFKC、casefold、外圍 trim 與連續空白壓縮，原始名稱不被覆寫。排序固定為 exact code、exact official name／approved alias、prefix、substring，再依 code 與 `source_row_sha256`；回 `total_matches`、`returned_count`、`limit`、`offset` 與 `truncated`。

## 6. 功能需求與 acceptance criteria

以下條件使用 Given／When／Then，可直接轉為自動測試、golden case 或人工驗收。所有 official 結果另須通過第 8 節共同 release gates。

### 6.1 CDC 採檢送驗

| ID | Acceptance criteria |
| --- | --- |
| CDC-01 | Given 已核准的手冊 snapshot，When 以疾病名稱查詢，Then 結果依「傳染病名稱＋採檢項目＋採檢目的」的原始列分開呈現，不得把不同列的採檢時間、採檢量及規定、送驗方式或注意事項交叉合併。第 2 章沒有獨立「檢驗方法」欄。 |
| CDC-02 | Given 一筆命中結果，Then 至少回傳疾病、採檢項目、採檢目的、採檢時間、採檢量及規定、送驗方式、官方完整欄名 `應保存種類（應保存時間）` 與注意事項的原始值；P1.1 暫依研究解讀同列回 `not_pre_submission_storage=true`，不得抽成送驗前保存溫度／時間；此解讀須由 `CDC-R1-CONTENT` 獨立專業判讀，若不支持即不得核准並版本化修訂契約。來源未提供的欄位回 `null`。 |
| CDC-03 | Then 每筆 item 以 `artifact_id + locator + source_row_sha256` 定位到 snapshot 中具角色標記的手冊 artifact，並回 landing page、手冊版本、PDF 實體頁、印刷頁、表格／列定位；兩種頁碼不一致時都顯示。另回第 7.2 節的兩種可追溯狀態，不保證上游換版後舊 URL 仍可重現。 |
| CDC-04 | Given 官方發現新版但尚未完成 parser diff、人工校對及醫檢專業複核，When 查詢，Then 服務上一個 approved snapshot 時仍回 `result_status=ok|not_found`，並將 `latest_candidate_status=review_pending`、`stale=true` 與原因分欄呈現；沒有 serving snapshot 才回 `availability=data_unavailable`。 |
| CDC-05 | Given 查無疾病或資料不足，Then 回 `not_found` 或缺欄說明及實際搜尋的 snapshot／範圍，不推論 CDC 沒有規定；回應固定提醒使用者核對官方原文與機構流程。 |

### 6.2 NHI 醫療服務給付項目

| ID | Acceptance criteria |
| --- | --- |
| NHI-01 | Given 已核准的 NHI snapshot，When 以完整代碼查詢，Then 代碼以字串處理並保留前導零；回傳診療項目代碼、支付點數、起迄日、中英文名稱、備註及原始列 locator。 |
| NHI-02 | When 以代碼、中英文名稱或 approved alias 搜尋，Then 依第 5.3 節 deterministic matching、排序與分頁回傳候選、`total_matches`、`matched_by`、`scope_status`、scope／alias provenance 及 `coverage_status`。未核准 laboratory allowlist 時仍可查全表，但不宣稱結果完整涵蓋所有健保檢驗項目；未核准 alias 不影響搜尋。 |
| NHI-03 | Then 支付點數以「點」顯示，`0` 保留為有效值，不換算新臺幣；備註保留完整原文，不保證個案可申報。 |
| NHI-04 | Given `get_points` 的 optional `as_of` 是合法、非 null 的 ISO date，Then 回 `result_status=historical_query_unsupported`、`historical_truth_supported=false`、0 items，不比較 current row、不輸出指定日期點數；malformed／wrong type／空字串依第 5.3 節 precedence 回 `invalid_request`，`as_of=null` 才可查 serving snapshot 的現行來源列。 |
| NHI-05 | Given `生效迄日=29101231`，Then 在官方語意仍為 `UNVERIFIED` 時保留原始日期與 inference 標記，不顯示「永久有效」；查無結果只表示當前 snapshot 未命中，不推論「健保不給付」。 |

### 6.3 TFDA 醫療器材許可／登錄資料與 IVD 篩選

| ID | Acceptance criteria |
| --- | --- |
| TFDA-01 | Given 已核准的 TFDA snapshot，When 以許可／登錄字號查詢，Then 同字號所有 source rows 以 group 呈現，保留每個製造商、廠址、國別與製程；不得用字號去重後遺失製造關係。 |
| TFDA-02 | Then 分別呈現 `source_cancellation_status_raw`、註銷日期、註銷理由與 `valid_through`。不可把空白註銷欄稱為「未註銷」；查詢時才依明示的 `evaluated_as_of` 與 `Asia/Taipei` 計算 `within_validity_period_as_of=true|false|unknown`，並另列 `cancellation_recorded_in_source=true|false|unknown`，不得合成「有效許可」、仍在販售、可採購或獲 TFDA 推薦。 |
| TFDA-03 | Then 申請商與製造商使用不同欄位與標籤；中文品名、英文品名、效能、規格與限制項目保留原文，不從相似文字推論臨床能力或產品等效。 |
| TFDA-04 | Given `search_reviewed_ivd`，Then 只回 reviewed `included`，每筆帶官方次類別 code 與 rule version；沒有 included 但 `ambiguous`／`unknown` 候選存在時回 `candidate_matches_available`。Given `search_ivd_candidates`，Then 回 `included`／`ambiguous`／`unknown` 及 review coverage、舊制／缺碼筆數、總命中與 truncation，不得把 included-only 空結果說成「沒有相關 IVD」。 |
| TFDA-05 | Given code 同時命中衝突規則、缺次類別、舊制分類或未知 code，Then candidate search 回 `ambiguous`／`unknown` 與命中理由；關鍵字只能增加候選召回，不能升格為正式 IVD。未完成逐碼 reviewer 核准時 `coverage_status=review_incomplete`，不得稱完整 IVD 清單。 |
| TFDA-06 | Given 已核准的 TFDA snapshot，When 呼叫 `list_matching_license_records`，Then 搜尋全部 source rows（含官方已註銷、缺分類代碼、舊制分類），比對許可證字號、中文品名、英文品名、申請商名稱、製造商名稱、效能與主／次類別原文（正規化同 NHI）。每筆帶標籤：`ivd_scope`、主類別字母、醫療器材級數原文、許可證種類原文、`cancellation_recorded_in_source`，以及命中欄位 `matched_by`。預設排序依序為：命中程度（完全相同字號→完全相同中文或英文品名→品名開頭相同→品名包含→其他欄位包含）、官方註銷欄空白者在前、許可證字號、原始列號。`prefer_ivd=true` 或 `prefer_main_category` 只在同一命中程度內把符合者排前，不增減筆數；`ivd_scope`（`included`／`excluded`／`ambiguous`／`unknown`）或 `main_category`（A–P 單一字母）為篩選，只在使用者明確要求某一類時使用，非法值回 `invalid_request`。回 `total_matches`、`returned_count`、`limit`（1–5、預設 5；owner 2026-09-15 先說「給20筆就很夠了」，同日改為「還是給5筆」）、`offset` 與 `truncated`，可翻頁到最後一筆。不得輸出品質分數、相似度、優劣、可替代性或採購建議；「官方註銷欄空白」不得稱為有效許可。 |

#### 6.3.1 TFDA cancellation × date canonical truth table

Curated row 只保存來源 raw／parsed 欄位；以下兩個輸出只在 query time 依明示的 `evaluated_as_of` 計算。`evaluated_as_of` 預設為 `Asia/Taipei` 當日，結果必須同時回日期與時區。

| `source_cancellation_status_raw`（trim 後） | Parsed cancellation date | `cancellation_recorded_in_source` | Exact warning code |
| --- | --- | --- | --- |
| 空字串 | null | `false` | 無；語意僅是兩個來源欄都沒記錄，不等於「未註銷」 |
| 空字串 | valid date | `true` | `cancellation_date_without_status` |
| `已註銷` 或 `已廢止` | valid date | `true` | 無 consistency warning |
| `已註銷` 或 `已廢止` | null | `true` | `cancellation_status_without_date` |
| 其他非空字串 | valid date 或 null | `unknown` | `unknown_cancellation_status` |
| 任意 | invalid date | 不得出現在 serving result | Candidate validation rejected；不發布該 build |

`within_validity_period_as_of` 只比較 parsed `valid_through`：`evaluated_as_of <= valid_through` 為 `true`（有效日期當日採 inclusive）；`evaluated_as_of > valid_through` 為 `false`；missing／invalid 為 `unknown`。Official candidate 的 `valid_through` missing／invalid 會整批 rejected；`unknown` 只保留給 legacy sample／防禦性讀取。

| Cancellation output | Validity output | Additional exact warning code |
| --- | --- | --- |
| `true` | `true` | `cancellation_recorded_within_validity_window` |
| `true` | `false` | `cancellation_recorded_and_validity_period_elapsed` |
| `false` | `true` | 無；仍不得稱「有效許可」 |
| `false` | `false` | `validity_period_elapsed` |
| `unknown` | `true|false` | `cancellation_record_ambiguous`；若 validity 為 false 同時加 `validity_period_elapsed` |
| `unknown` | `unknown` | `cancellation_record_ambiguous` 與 `validity_date_unavailable` |
| `true|false` | `unknown` | `validity_date_unavailable` |

兩個輸出永遠分開，不得合成 `computed_temporal_state`、`not_cancelled_and_within_validity`、「有效許可」、上市、販售、採購或 TFDA 推薦結論。同一 raw／curated build 跨日查詢時只允許 `within_validity_period_as_of` 隨 injected clock 改變。

#### 6.3.2 TFDA IVD public enum

Public item 只允許 `ivd_scope=included|excluded|ambiguous|unknown`。Candidate operation 不回 `excluded`；reviewed-only operation只回 `included`。`review_pending` 是 review workflow，不是 `ivd_scope`；舊內部名稱 `not_ivd_by_reviewed_classification`、`ivd_unknown`、`ivd_candidate` 不得出現在 public result，必要時依序映射為 `excluded`、`unknown` 與 operation-level candidate membership。OD-03 已決定 `ambiguous`／`unknown` 可出現在 `search_ivd_candidates`；仍待 owner 指定的只有 registry reviewer。

### 6.4 CDC 傳染病認可檢驗機構

| ID | Acceptance criteria |
| --- | --- |
| LAB-01 | Given 已核准的 ODS snapshot，When 依疾病、檢驗目的或方法查詢，Then 以「證號＋疾病＋目的＋方法」保存與回傳匹配列，不把同證號的多方法壓成單筆通用能力。 |
| LAB-02 | Then 回傳證號、縣市、機構、部門、疾病代碼／名稱、檢驗目的／方法、地址、電話、結束時間與最近一次年度能力試驗審查原值，以及 snapshot 與 source row locator。 |
| LAB-03 | Given ODS 垂直合併欄位，Then 只依 merge span 繼承 anchor 值；真正空白的能力試驗欄仍為空白，不 blanket forward-fill。 |
| LAB-04 | Given 能力試驗欄是日期、`無需能力試驗` 或空白，Then 三種原值分別保留；`結束時間` 不擴寫成官方未定義的「證書有效期限」。 |
| LAB-05 | Given 官方固定更新頻率尚為 `UNVERIFIED`，Then 介面只揭露本專案最後檢查時間、附件版本與 snapshot 狀態，不宣稱 CDC 每日／每月更新；結果只代表名冊命中，不保證當次收件或送驗可行。 |

### 6.5 Workshop 與可理解性

| ID | Acceptance criteria |
| --- | --- |
| UX-01 | 參與者開始查詢前能辨識目前為 `sample` 或 `official_snapshot`；sample 結果固定顯示不可用於實際採檢、申報或採購。 |
| UX-02 | 每位參與者可依具 item-level locator 的結果核對至少一筆值。只有當現行上游 artifact hash 相同，或能開啟合法保存且 hash 相符的 raw artifact，才算「官方值核對成功」；locator 有值但上游已換版時只算 `snapshot_traceable`，不算目前上游可重現。 |
| UX-03 | 測試流程只收集自願、非病人、非機密且符合第 8.3 節 schema 的回饋；不保存完整自由文字查詢、不以提供個資換取使用，並把 protocol／result hash 綁入 release evidence。 |

## 7. 狀態、警示與失敗語意

狀態必須拆開呈現，不能用一個「最新／有效」標籤混合 serving snapshot、candidate、來源時間與領域判斷。下列名稱與 enum 是 public contract；未列值不得對外輸出。

### 7.1 Canonical public enums

| 欄位 | Exact enum／型別 | 語意 |
| --- | --- | --- |
| `data_mode` | `sample`、`official_snapshot` | sample 固定 `sample_only=true`；official 固定 false，兩者不可同查 |
| `availability` | `available`、`data_unavailable` | 指定模式是否有可服務資料；沒有 official serving snapshot 時不得退回 sample |
| `serving_validation_status` | `not_applicable`、`passed` | 目前實際服務的 snapshot 是否通過自動驗證；失敗 candidate 永遠不成為 serving |
| `serving_review_status` | `not_applicable`、`approved` | 目前 serving snapshot 的必要人工／專業 review；pending／rejected 只屬 candidate |
| `latest_candidate_status` | `none`、`validating`、`review_pending`、`rejected`、`publishable` | 最新非 serving 候選的 pipeline 狀態，不改寫 serving 狀態 |
| `coverage_status` | `complete`、`review_incomplete`、`unknown` | 查詢所宣稱領域範圍的 coverage；P1.1 不允許丟 source row 後仍標 complete |
| `result_status` | `ok`、`not_found`、`data_unavailable`、`invalid_request`、`historical_query_unsupported`、`candidate_matches_available`、`deprecated_unsupported` | 本次 operation 結果；`not_found` 只代表揭露範圍內沒命中 |
| `stale` | boolean | 只描述 serving snapshot 的上游核對或已知新版狀態，不以資料列最大異動日推算 |
| `stale_reason_codes` | array of `upstream_check_overdue`、`upstream_verification_failed`、`newer_candidate_pending_review`、`newer_candidate_rejected`、`newer_candidate_awaiting_publish` | `stale=true` 時至少一個；可複數，不用自由文字取代 machine-readable code |
| `scope_status` | `in_scope`、`out_of_scope`、`review_pending` | NHI laboratory scope；每個候選 item 各自回傳 |
| `ivd_scope` | `included`、`excluded`、`ambiguous`、`unknown` | TFDA IVD 分類；reviewed 與 candidate operations 依第 5.3 節篩選 |

TFDA 的 `portal_metadata_modified_at`、`embedded_data_updated_on` 與 `max_record_changed_on` 都是 nullable evidence。若要提示內容年齡，使用下方獨立的 `content_age_status`，不得用不存在於 CSV 的 embedded date 或最大異動日直接把 serving snapshot 改為 stale。

### 7.2 Allowed combinations 與 provenance／locator

| 情境 | 必要組合 |
| --- | --- |
| sample 正常／無命中 | `data_mode=sample`、`availability=available`、兩個 serving status 均 `not_applicable`、`result_status=ok|not_found` |
| official serving 正常 | `official_snapshot`、`available`、serving validation `passed`、serving review `approved`、`result_status=ok|not_found` |
| 服務舊 approved、candidate pending／rejected／publishable | serving 組合維持正常；latest candidate 分別顯示；`stale=true` 並給相應 reason，不把 query result 改成 review pending |
| 沒有 serving snapshot | `availability=data_unavailable`、兩個 serving status 均 `not_applicable`、`result_status=data_unavailable`；candidate 狀態另列 |
| NHI `as_of` 非 null | 有 serving 時仍 `availability=available`，但 `result_status=historical_query_unsupported`、`historical_truth_supported=false` |
| deprecated `compare_products` | `result_status=deprecated_unsupported`、items 空陣列，提供 replacement operation 名稱 |

### 7.2.1 Closed public response schemas

以下是 `public-contract-v1` 的封閉 response family；每個 object 都是 `extra=forbid`，表列欄位全部 required，只有明列 `null` 者 nullable。`QueryResultV1` exact keys 為：`contract_version`（literal）、`operation`（第 5.3 節 exact name）、`query`（object）、`result_status`、`data_mode`、`sample_only`（boolean）、`availability`、`availability_reason_code`（string|null）、`source_status`（`SourceStatusV1`）、`coverage_status`、`coverage_detail`（`IvdCoverageDetailV1|null`）、`items`（`ItemEnvelopeV1[]`）、`total_matches`、`returned_count`、`limit`、`offset`（integer）、`truncated`（boolean）、`historical_truth_supported`（boolean|null；只在 NHI historical capability 適用，其他 operation 固定 null）、`evaluated_as_of`（ISO date|null）、`evaluated_timezone`（IANA timezone|null）、`replacement_operation`（第 5.3 節 exact name|null）、`provenance`（`ProvenanceV1|null`；無可服務資料時 null）、`snapshot_traceable`、`currently_reproducible_from_upstream`（boolean）、`warnings`（stable code array）、`notes`（string array）與 `safety`（第 7.4 節 exact object）。

`SourceStatusV1` exact keys 為 `serving_validation_status`、`serving_review_status`、`latest_candidate_status`、`stale`、`stale_reason_codes`。它與 `ProvenanceV1` 內重複的 `serving_review_status`、`stale`、`stale_reason_codes`，以及 top-level／provenance 的 `coverage_status` 必須逐值相等。`IvdCoverageDetailV1` exact keys 為 `reviewed_codes`、`total_codes`、`legacy_code_rows`、`missing_code_rows`、`unknown_code_rows`（皆為大於等於 0 的 integer）及 `rule_version`（non-empty string）；只允許 `search_ivd_candidates` 非 null。TFDA temporal operations 明確為 `search_reviewed_ivd`、`search_ivd_candidates`、`search_ivd`、`get_license`、`find_manufacturer`、`list_matching_license_records`：只有 `result_status=ok|not_found|candidate_matches_available` 時同時回非 null `evaluated_as_of` 與 `evaluated_timezone="Asia/Taipei"`；invalid／unavailable／deprecated 與其他 operations 兩者皆 null。只有 deprecated `compare_products` 的 `replacement_operation="list_matching_license_records"`，其他 operations 固定 null。

`query` 的 exact keys／type／nullable／default 直接使用第 5.3 節各 operation parameter schema；不得保存額外 host metadata。`OfficialContentDateV1` exact keys 為 `value_raw`（non-empty string）、`precision`（`day|month|year|unknown`）與 `timezone_known`（boolean）。`ItemEnvelopeV1` exact keys 為 `record`（依 operation 綁定的 source-specific strict payload）、`evidence`（非空 `EvidenceV1[]`）、`item_warnings`（stable code array）、`safety`（第 7.4 節 exact object）。`EvidenceV1` exact keys 為 `artifact_id`、`source_row_sha256`、`locator`（source-specific strict object）、`raw_value_available`（boolean）。`ProvenanceV1` exact keys 為 `source_id`、`source_name`、`provider`、`landing_url`、`resource_url`、`snapshot_id`（string|null）、`curated_build_id`（string|null）、`official_version_raw`（string|null）、`official_content_date`（`OfficialContentDateV1|null`）、`retrieved_at`、`artifacts`（`ArtifactReferenceV1[]`）、`parser_version`、`schema_version`、`rule_bundle_version`、`license_name`（string|null）、`license_url`（string|null）、`attribution`、`coverage_status`、`stale`、`stale_reason_codes`、`last_check_at`（datetime|null）與 `serving_review_status`。Sample provenance 必須保留 synthetic fixture 的來源與 evidence，但 `snapshot_id`、`curated_build_id`、`official_content_date` 固定 null；`retrieved_at` 使用 package build timestamp，`resource_url` 與 artifact `official_url` 指向官方 landing/resource URL但不得聲稱 fixture 值來自該頁，`parser_version` 使用 sample fixture schema version，artifact `storage_scope="package_resource"`。Official available 時兩個 IDs 必為 non-empty string。`ArtifactReferenceV1` exact keys 為 `artifact_id`、`role`、`storage_scope`、`data_root_relative_path`（string|null）、`official_url`、`sha256`、`local_artifact_available`（boolean）。Source-specific payload 與 locator 的 exact fields 以 package resource `public-contract-v1.json` 為唯一真源，必須逐 operation 完整列出 required／nullable/type，不允許 free-form `dict`；TDD 直接載入同一 resource 產生 schema tests。

`ReservedStatusResultV1` 適用 `standards_status`／`eqa_status`，exact keys 為 `contract_version`、`operation`、`configured`（literal `false`）、`result_status`（literal `data_unavailable`）、`availability_reason_code`（literal `no_serving_snapshot`）、`capabilities`（standards 固定 `LOINC|FHIR|SNOMED`，EQA 固定 `EQA|CAP` 的 enum array）、`warnings`（stable code array）與 `notes`（string array）；不得包含術語、catalog 或 data-query `items`。`get_data_status` 使用第 7.3 節獨立 exact schema。

P1.1 新增 operation 在 sample mode 上線前，必須有對應 source-specific synthetic payload、locator 與至少一個 meaningful fixture；任一 operation 缺 fixture 時，整個 22-tool `public-contract-v1` 不得發布，也不得以 19～21 個 tools 或空殼結果假裝支援。這是 `REL-G1` 的 contract migration gate；現行 v0.1.1 的 18-tool baseline 不因此被描述為已完成 22-tool contract。

每個 official result 的 snapshot 層依上述 `ProvenanceV1` 完整回傳。每個 item／TFDA manufacturing child 必須各自包含 `artifact_id`、`source_row_sha256` 與 typed locator；不能只靠 top-level provenance 推定來源列。

Artifact reference 必須包含 `artifact_id`、`role`、`storage_scope`、data-root-relative path（若有）、官方 URL、SHA-256 與 `local_artifact_available`。所有結果另回：

- `snapshot_traceable=true|false`：manifest、artifact／curated build hash 與 item locator 是否足以重現本 snapshot 內的值。
- `currently_reproducible_from_upstream=true|false`：目前上游 artifact 是否仍與 snapshot hash 相同；上游換版或舊 token 失效時為 false。

只有上游同 hash，或可開啟合法保存且同 hash 的 raw artifact，才可宣稱值能回查官方 artifact。若 release 沒有散布 raw，必須回 `local_artifact_available=false`。未知欄位使用 `null` 或明確 unknown，不捏造值。

### 7.3 Canonical status／freshness field registry

PRD 第 7.1～7.3 節與 `public-contract-v1.json` 是唯一 public status／freshness registry。`get_data_status` top-level exact keys 為 `contract_version="public-contract-v1"`、`data_mode`、`sources`；`sources` 必須含下列四個 strict source objects。模型採 `extra=forbid`；其他文件中的舊名只可標 legacy／superseded，不得進 public JSON。

| Exact field | Type／enum | Required semantics |
| --- | --- | --- |
| `source_id` | `cdc_manual|cdc_recognized_labs|nhi_fee|tfda_device` | 四個 source object 各出現一次 |
| `availability` | 第 7.1 節 enum | 是否有完整、可驗證的 serving source |
| `availability_reason_code` | `null|no_serving_snapshot|serving_integrity_failure|operational_status_integrity_failure` | `QueryResultV1` 與 status object 共用此 exact enum；available 時必為 null，unavailable 時必填 |
| `serving_snapshot_id` | string 或 null | official available 時必填；sample 與 unavailable 時 null，禁止製造 official ID |
| `serving_curated_build_id` | string 或 null | official available 時必填並綁定 parser／schema／rule bundle；sample 與 unavailable 時 null |
| `serving_validation_status` | 第 7.1 節 enum | 只描述 serving build |
| `serving_review_status` | 第 7.1 節 enum | 只描述 serving build |
| `latest_candidate_id` | string 或 null | `latest_candidate_status=none` 時為 null，其他狀態必填 |
| `latest_candidate_status` | 第 7.1 節 enum | 只描述最新非 serving candidate |
| `coverage_status` | 第 7.1 節 enum | 來源／規則所能宣稱的查詢 coverage |
| `last_check_at` | RFC 3339 datetime 或 null | 最近一次 upstream check 嘗試時間 |
| `last_successful_check_at` | RFC 3339 datetime 或 null | 最近一次完成來源、artifact 與 schema 核對的時間 |
| `last_successful_publish_at` | RFC 3339 datetime 或 null | 最近一次成功切換 serving descriptor 的時間；唯一 public publish timestamp |
| `official_content_date` | object 或 null | 保存來源原值、precision 與 `timezone_known`；不可拿 response time 代填 |
| `latest_seen_version` | string 或 null | 最近一次 upstream discovery 看見的官方版本／附件名；不可把 local snapshot ID 冒充官方版號 |
| `stale` | boolean | available source 的 freshness 結果；unavailable 時固定 false |
| `stale_reason_codes` | 第 7.1 節 enum array | stale false 時空陣列；stale true 時至少一個且去重 |
| `content_age_status` | `not_applicable|within_threshold|warning|critical|unknown` | 與 stale 分開；threshold version與 evidence另附，不代替 upstream check |
| `freshness_policy_version` | non-empty string | 產生 stale 與 content-age 判斷的產品規則版本 |
| `content_age_evidence` | object 或 null | 若非 null，含 `basis_field`、`basis_value_raw`、`age_days`、`threshold_version`；不得從無對應 evidence 的來源捏造 |

禁止 public legacy keys：`validation_status`、`review_status`、`candidate_status`、singular `stale_reason`、`last_publish_at`、`official_data_loaded`、`content_age_warning`。完整性錯誤固定映射：descriptor 不存在且沒有 publish event，或 descriptor 完整但沒有 serving build，皆為 `no_serving_snapshot`；前者固定 candidate none／ID null，後者可依完整 descriptor 揭露候選狀態。Descriptor 遺失但已有 publish event，或 descriptor/pointer、serving manifest、audit、DB 缺失／損壞／hash mismatch 為 `serving_integrity_failure`；descriptor 中 candidate/check operational section 的 schema、hash、source 或 generation mismatch 為 `operational_status_integrity_failure`。兩種 integrity failure 固定 `latest_candidate_status=none`、`latest_candidate_id=null`，不揭露候選狀態，不可捏造或掃 staged。它們都令 query `result_status=data_unavailable`、`stale=false`，不得 fallback sample。Serving descriptor 與 operational fields 必須作為同一可驗證、原子切換單位，避免兩檔切換窗口。

### 7.4 Exact safety-field registry

下列是全部 public structured safety keys；型別一律 strict boolean，適用時值固定 `true`，不適用時省略，禁止輸出同義 key。每個適用 operation 的 MCP tool description 必須含 exact `key=true` token；ToolResult top-level `safety` 與每個 ItemEnvelope 的 `safety` 都要重複適用 keys。0 items 時仍須保留 top-level safety。

| Exact safety field | 適用 operations | Required meaning |
| --- | --- | --- |
| `decision_support_only` | 全部 19 個 data query operations | 結果只協助查找公開資料，不是診斷、申報、採購、收件或臨床作業決策 |
| `verify_current_official_source` | 全部 19 個 data query operations | 使用前仍須核對當期官方來源與機構流程 |
| `not_validated_for_hospital_deployment` | 全部 19 個 data query operations | P1.1 未驗證院內部署、host log、傳輸、權限或 retention |
| `not_for_claim_determination` | `search_payment_items`、`search_lab_code`、`get_points`、`get_payment_rule` | 不判定個案可申報，不把點數當金額 |
| `not_for_procurement_or_equivalence` | `search_reviewed_ivd`、`search_ivd_candidates`、`search_ivd`、`get_license`、`find_manufacturer`、`list_matching_license_records`、`compare_products` | 不作採購、產品等效、可替代、上市或販售判定 |
| `not_pre_submission_storage` | `search_disease`、`get_specimen_requirement`、`get_collection_method`、`get_container`、`get_transport_requirement`、`get_submission_rule` | 官方「應保存種類（應保存時間）」不是檢體送驗前 storage instruction |
| `does_not_confirm_current_acceptance` | `find_authorized_lab`、`get_lab_scope` | 名冊命中不保證當次收件、送驗資格或服務可用性 |

19 個 data query operations 是第 5.3 節除 `get_data_status`、`standards_status`、`eqa_status` 外的全部 operations。禁止 legacy／synonym keys：`not_a_specimen_storage_instruction`、`not_pre_submission_specimen_storage`、`not_a_receiving_guarantee`。Tool description 另須明示不得輸入病人資料；misuse contract tests 不得只檢查 top-level notes。

## 8. 成功指標與 release gates

### 8.1 成功指標

| 指標 | 計算方式 | P1.1 目標 |
| --- | --- | --- |
| Golden-case correctness | 四個資料集各自通過第 8.3 節可計數條件的 official golden cases 中，內容與 locator 均通過的案例／全部案例 | 100%；每資料集至少 10 例 |
| Provenance completeness | official 結果含全部必填 provenance 的筆數／抽查 official 結果 | 100% |
| Critical semantic contamination | 發生跨方法、跨檢體、跨製造關係、sample/official 混查或現行冒充歷史的案例數 | 0 |
| Pilot task completion | 5–10 位受測者中，在不由主持人代操作下完成指定查詢的人數／參與人數 | 至少 80% |
| Source verification success | 受測者能依 locator 開啟同 hash 的現行上游或合法保存 raw artifact，並核對至少一筆值的人數／參與人數 | 至少 80%；人數與比例並列 |
| Warning comprehension | 能正確說明 sample、stale、not_found 或候選狀態限制的人數／被問到的人數 | 至少 80% |
| Recommendation signal | 回答「願意推薦給同事」的分布與理由 | 記錄基線，不作醫療正確性替代指標；P1.1 不預設硬門檻 |

### 8.2 Release gates

| Gate | 通過條件 | 未通過時 |
| --- | --- | --- |
| `REL-G1` 共用資料安全 | Raw revision 與包含 parser／schema／normalization／rule bundle 的 curated build identity 分離；hash-bound audit evidence、完整 source-row coverage、並行安全 publish、唯讀 runtime、sample/official 隔離及第 7 節狀態都有可重跑測試；任何 source row 被丟棄即 block 整批；安裝 wheel 後可在 repo 外解析 hash-bound rule bundle | 不得啟用任何 official source |
| `REL-G2` 來源契約 | 該資料集 importer、欄位規則、drift 測試、item-level provenance 與至少 10 個 countable official golden cases 全數通過 | 該資料集維持 data_unavailable；不阻止其他已核准資料集獨立發布 |
| `REL-G3` 領域複核 | CDC 手冊、CDC ODS、NHI scope、TFDA IVD 分別通過第 8.3 節 protocol 與對應 source review records | 受影響內容只可標候選／review incomplete，不能宣稱正式範圍完整 |
| `REL-G4` 授權與發布 | 每資料集完成顯名、授權 URL、非官方服務聲明、archive 內容檢查及 `PUB-R1-OWNER`；若散布 curated artifact，另完成再散布確認 | 只提供部署者自行同步，或暫不發布該 artifact |
| ~~`REL-G5` 使用者驗收~~ | ~~5–10 人依第 8.4 節固定 pilot protocol 完成，量化 UX 指標達標，所有 critical safety issue 歸零，protocol/result hashes 綁入 release evidence~~ | ~~修正並重測；不得宣稱 P1.1 完成~~ |
| `REL-G5` 公開上線與市場回饋（owner 2026-09-14 決定取代 pilot） | 已通過 `REL-G1`～`REL-G4` 的資料集直接以公開 Release 上線；安裝說明、GitHub Issues 回報入口與已知限制在 README／Release 頁可見；使用者回報的 critical safety issue 以 Issue 追蹤並在修正版本中關閉 | 發現 critical safety issue 時暫停該資料集的新 Release，修正後再發 |

`REL-G1`～`REL-G5` 只代表 release-level gates，不得寫入 source review record 充當審查類型。Source qualification gate 使用下列 namespace：

| 資料集 | Source gate IDs | 對應 release gate |
| --- | --- | --- |
| NHI | `NHI-R1-SOURCE`、`NHI-R1-SCHEMA`、`NHI-R1-SCOPE` | 前兩者支援 `REL-G2`；scope 支援 `REL-G3` |
| TFDA | `TFDA-R1-SOURCE`、`TFDA-R1-SCHEMA`、`TFDA-R1-IVD` | 前兩者支援 `REL-G2`；IVD 支援 `REL-G3` |
| CDC 手冊 | `CDC-R1-SOURCE`、`CDC-R1-LAYOUT`、`CDC-R1-CONTENT` | source/layout 支援 `REL-G2`；content 支援 `REL-G3` |
| CDC ODS | `ODS-R1-SOURCE`、`ODS-R1-STRUCTURE`、`ODS-R1-CONTENT` | source/structure 支援 `REL-G2`；content 支援 `REL-G3` |
| 發布授權 | `PUB-R1-OWNER` | 支援 `REL-G4`；不能代替 `REL-G5` pilot |

允許依 NHI → TFDA → CDC 的順序逐資料集啟用 official mode；每個未完成資料集必須顯示 `data_unavailable`。只有三個領域、四個資料集／查詢任務都通過相應 gates，才可將整體版本標為「P1.1 完成」。

### 8.3 Golden case 與 review evidence protocol

可計入 `REL-G2` 的 official golden case 必須使用 versioned schema，逐案保存 `case_id`、`source_id`、task／acceptance ID、官方 raw artifact SHA-256、curated build／parser／schema／normalization／rule bundle versions、輸入、expected fields、typed locator、reviewer、reviewed_at、decision 及 evidence path。Synthetic fixture 只能產生 `synthetic_ci_passed`；只有上述欄位完整且 decision 為 approved 才能產生 `official_qualification_approved`。兩者不得合併計數。

所有 accepted validation report 與 review record 必須進 immutable、content-addressed audit bundle。每筆 review 的 `subject_digest` 綁定 ordered raw artifacts、curated DB、transform／rule hashes與 review protocol version；publisher 必須重新計算並確認 required／completed source gate set 完全相等。Reviewer identity 預設只是本機稽核聲明；若有密碼學簽章，必須另列 assurance level，不得混稱。

CDC 與 ODS 的 versioned review protocol 至少規定：

1. Reviewer role 與資格；CDC content reviewer 為具傳染病檢體處理經驗的醫檢專業人員，ODS content reviewer 為熟悉認可制度的人員，實際姓名由 OD-04 指定。
2. 新舊版全部變更列必查；未變更列以固定 seed 分層抽樣，涵蓋所有疾病類別且總數至少 20 列。手冊另必含跨頁續列、同疾病多採檢項目與「應保存」語意案例。
3. Checklist 必查原始欄位關係、跨頁／merge lineage、版本、雙頁碼或 ODS row locator，以及安全警示；不能只核對抽取文字存在。`CDC-R1-CONTENT` reviewer 必須依欄名、章節上下文與疾管署原文獨立判讀「應保存種類（應保存時間）」語意，不得由預填的 `not_pre_submission_storage` 提示答案；判讀不支持目前解讀時 gate 不得核准並須改版 contract。
4. `critical` 為可能導致採檢／送驗條件錯接、來源錯配或錯誤肯定決策；`major` 為值或 locator 不正確；`minor` 為不影響語意的呈現問題。任何 critical 或 unresolved major 都整批 rejected；已修正 major 必須產生新 build／subject digest 並重審，不能在原 review record 直接標已處置。
5. Parser、schema、rule、raw artifact 或 curated build 任一變更，以及修正 critical／major 後，都要對受影響 scope 重新 review 並產生新 subject digest；舊簽核不得沿用。

NHI scope 與 TFDA IVD review 同樣必須使用 hash-bound、versioned protocol；未核准規則只能產生 `review_incomplete`／candidate 結果。

P1.1 official publish 永不接受 OCR-derived rows；OCR 只能產生 staged research candidate。任何必要頁缺少可靠文字層，該 candidate 即不得成為 P1.1 approved build，即使完成 100% 人工核對也不能解除本版 gate。未來版本若要允許 OCR publish，必須先修訂 PRD 與 TDD、提高版本、重新審查 release gate，再定義 OCR engine／model version、options、output hash、bbox lineage、100% cell review 與 reviewer evidence；不得只改 SDD 或實作。完整官方 PDF 留在 ignored raw data root，不得以 CI synthetic layout fixture 冒充 official qualification。

### 8.4 Versioned pilot protocol

> **2026-09-14 owner 決定取消本節 pilot**：不找 5–10 位受測者，改為通過 `REL-G1`～`REL-G4` 後直接公開上線，由使用者回報（GitHub Issues）收集回饋。以下原文保留作歷史，不再是發布條件；第 8.1 節量化 UX 指標因此沒有受測資料，不得宣稱已達標。

`REL-G5` 使用固定 protocol version，5–10 位參與者逐人完成九個 scenario IDs：四個正常任務（CDC 手冊、NHI、TFDA、ODS）及五個安全情境（sample、stale、not_found、IVD unknown、NHI historical query unsupported）。正常任務每題上限 10 分鐘，安全情境每題上限 5 分鐘；可使用公開安裝說明與 tool help，不可由主持人提供答案或代操作。需要答案提示者標 `assisted=true`，不計入 unassisted task completion。

每題 rubric 固定為：找到正確 operation、取得符合 acceptance criterion 的結果、辨識限制／警示、完成 artifact 核對；每項 0／1，四項全數通過才算該題完成。Critical safety issue 包含：把 sample 當 official、把 current NHI 值當歷史或個案可申報、把 TFDA 結果作採購／等效／「有效許可」判定、把 CDC「應保存」當送驗前保存、把 ODS 命中當收件保證、跨列錯接，或高風險 item 缺少結構化警示。

Pilot result schema 只保存 participant pseudonymous ID、角色類型、scenario ID、開始／結束時間、assisted、四項分數、critical issue code 與可選的去識別短註記；不得保存原始自由文字 query、病人資料或機密內容。報告必須同時列人數與比例，例如 `4/5 (80%)`，不得只報百分比；protocol hash、result hash、facilitator 與 owner approval record 綁入 release evidence。

## 9. Owner decisions

| ID | 需決定事項 | 建議預設 | 影響／期限 | SDD mapping |
| --- | --- | --- | --- | --- |
| OD-01 | Official curated snapshots 是否隨 GitHub Release 再散布 | 先提供同步工具；完成各來源授權與 artifact 大小審查後再開放再散布 | `REL-G4` 前 | `D-007` |
| OD-02 | NHI laboratory scope reviewer、allowlist 依據及 `29101231` 對外語意 | scope 未核准前全表可查並顯示 `review_incomplete`；sentinel 只顯示原值＋inference | `NHI-R1-SCOPE` 前 | `D-009`、`D-014` |
| OD-03 | TFDA IVD registry owner／reviewer | `ambiguous`／`unknown` 可出現在 candidate operation 但不得標正式 IVD；逐碼 review 完成才解除 coverage gate | `TFDA-R1-IVD` 前 | `D-010` |
| OD-04 | CDC 手冊與認可機構 reviewer 身分，以及新版本 turnaround time | 簽核格式已由第 8.3 節鎖定；分開指定醫檢內容 reviewer 與認可制度 reviewer | `CDC-R1-CONTENT`／`ODS-R1-CONTENT` 前 | `D-011` |
| OD-05 | 各資料集 stale warning／hard-stop 門檻與 P1.1 支援平台 | 先依來源研究建立可設定門檻；首版以 Windows 本機 stdio 為必測，其他平台不承諾至通過相同驗證 | `REL-G1`／公開安裝文件前 | `D-008`、`D-012` |

**Owner 已決定（2026-09-14，在 Claude Code 對話中回覆；上表保留原始建議作歷史）：**

| ID | 決定 | 落地要求 |
| --- | --- | --- |
| OD-01 | NHI curated snapshot 以 GitHub Release 下載包公開散布，附原始 CSV；公開審核紀錄的 reviewer 寫「專案負責人」代號。~~TFDA／CDC 另案決定~~（TFDA 見 OD-10；CDC 仍另案） | `docs/adr/0001-nhi-snapshot-release-bundle.md`；review protocol `nhi-r1-owner-review` 第 2 版；~~每次建立 Release 前 owner 確認檔名、大小、SHA-256~~（2026-09-15 OD-11 改為自動發布） |
| OD-02 | scope reviewer 由 AI 擔任；allowlist 依據必須是健保署支付標準官方文件原文（章節／項目標題與代碼範圍，附 locator）。`29101231` 維持只顯示原值並標「可能表示未設定結束日」 | review record 的 reviewer 必須標明為 AI（不得寫成人工 reviewer）；~~AI 判斷不確定的代碼維持 `review_pending`~~（2026-09-14 owner 決定：「你找不出來的，或者是你不知道要判到底是不是的，你就給他放進去。我們寧可錯殺一百，也不要放過一個。」不確定的代碼一律 `in_scope`，判定依據須寫明是依此決定）。~~每筆正式結果的 notes 必須揭露「檢驗範圍由 AI 審核，未經人工複核」~~（2026-09-14 owner 決定：檢驗範圍結果不需要加這段備註） |
| OD-03 | TFDA IVD registry reviewer 由 AI 擔任，依官方醫療器材分類分級附表原文逐碼判斷 | 同 OD-02 的揭露要求；~~不確定者維持 `ambiguous`／`unknown`，不得升格為 `included`~~（2026-09-14 owner 決定同 OD-02：附表逐碼判不出來或附表查無的 A/B/C 代碼一律 `included`，判定依據須寫明是依此決定；沒有 A–P 分類代碼或舊制編號的許可證列不在此決定範圍，仍為 `unknown`） |
| OD-04 | CDC 採檢手冊內容與認可檢驗機構名單由 AI 全程代審；正式結果不加「未經人工複核」備註（owner 2026-09-15 回答：「Ai全程代審 不用特別備注未經人工審核」） | review record 的 reviewer 必須標明為 AI，不得寫成人工或「專案負責人」；~~新版處理時間（turnaround）尚未決定~~ 官方改版後照健保、食藥署自動檢查、全部通過就換上（owner 2026-09-15：「A 開始做疾管署」，A 為「跟健保、食藥署一樣自動檢查、通過就換」）；實作前另立 CDC review protocol |
| OD-05 | NHI 超過兩個宣告週期沒有成功檢查時標 `upstream_check_overdue`，不 hard-stop，持續回答並揭露；P1.1 支援 Windows 與 macOS | macOS 以 CI macos-latest 驗證；實機安裝流程尚未驗證前不得宣稱實機已驗證 |
| OD-06 | TFDA 許可證資料 104,619 筆（含已註銷、缺分類代碼、舊制分類）全部收錄、全部查得到，服務 IVD 以外產業的使用者（例如競品研究）。每筆掛官方欄位與審核結果的標籤；預設依命中程度排序、不偏任何類別；使用者的語意由 host AI 判斷，再指定偏好（只調順序）或篩選（使用者明確要求時）。缺分類代碼的 17,606 列維持 `ivd_scope=unknown`（owner 2026-09-15：「A 這樣才有做 data 清理的意義在啊」；2026-09-14「舊制那些維持現狀」） | TFDA-06；`list_matching_license_records` 新增分頁、偏好與篩選參數；可並排原始欄位供使用者自行比較，系統不判優劣、等效或可替代，`compare_products` 維持 deprecated；TFDA 下載包大小上限另行調整 |
| OD-07 | TFDA 上線審核（`TFDA-R1-SOURCE`、`TFDA-R1-SCHEMA`、`PUB-R1-OWNER` 與正式驗收題）由 AI 代審；附表 A/B/C 以外大類的代碼維持 `ivd_scope=unknown`；搜尋一頁 20 筆的摘要內容暫不再減（同日稍後 owner 把一頁改為 5 筆，見 §5.3 共同型別規則；owner 2026-09-15：「1.a 2.a 3.z你直接幫我審核」） | review protocol `tfda-r1-ai-review` 第 1 版（`status=owner_delegated`）；審核紀錄與驗收題的 reviewer 寫 `ai-reviewer:claude-opus-5`、role `ai_reviewer_delegated_by_owner`，不得寫成人工或「專案負責人」；~~範圍只限本機 MCP 服務，不含 GitHub Release 下載包~~（2026-09-15 OD-10 起含下載包，protocol 第 2 版）；每日排程改跑 `check tfda_devices`，~~官方新版仍需再審才發布~~（同日 OD-08 改為自動更新） |
| OD-08 | 食藥署官方每週新版改為自動更新：自動檢查全部通過就換上，沒過就保留目前版本並寄信（owner 2026-09-15：「A變成成自動化 我不想花太多心力維護」） | review protocol `tfda-r1-auto-review` 第 1 版（OD-10～12 後為第 2 版）；reviewer 寫 `automated-check:tfda-auto-update`，不得寫成人工或 AI 逐版審核；擋下條件：資料列數或許可證字號數變動超過 10%、主要欄位空白比例上升超過 2 個百分點、出現新的註銷狀態值、驗收題不通過、換版前全表逐列比對不符；~~只限本機 MCP 服務~~ 只由正式安裝版執行（OD-11 起也自動發布下載包）；同一個被擋下的新版只寄一次信；~~健保新版仍需 owner 審核~~（同日 OD-09 改為自動更新）；通知信列出內容有改的許可證字號與欄位，另算有效日期往後延（通常是展延）的字號數；本機只留最近 3 版，更舊的建置與原始檔由每日排程移到資源回收筒（owner 2026-09-15 選 A，並問「展延…總筆數沒有異動的話，系統也偵測得到嗎？」） |
| OD-09 | 健保支付標準新版也改為自動更新：自動檢查全部通過就換上，沒過就保留目前版本並寄信（owner 2026-09-15：「好，那健保新版也改成自動更新」） | review protocol `nhi-r1-auto-review` 第 1 版（OD-10～12 後為第 2 版）；reviewer 寫 `automated-check:nhi-auto-update`，不得寫成人工或專案負責人；擋下條件：資料列數或代碼數變動超過 10%、英文名稱空白比例上升超過 2 個百分點、驗收題不通過、換版前全表逐列比對不符；新版多出、還沒有檢驗範圍判定的代碼~~維持 `review_pending`~~ 先算 `in_scope`（OD-12）並列在通知信；只由正式安裝版執行，~~GitHub Release 下載包不跟著換~~（OD-11 改為自動發布）；手動審核流程（`prepare-review`／`publish`）保留 |
| OD-10 | GitHub Release 下載包同時放健保與食藥署：食藥署許可證全表、原始 ZIP 與審核紀錄一起公開散布（owner 2026-09-15：「好，那下載包也發一版新的」，並選「健保＋食藥署」） | `docs/adr/0002-tfda-bundle-and-automatic-release.md`；review protocol `tfda-r1-ai-review` 第 2 版（範圍含下載包），本機食藥署建置以第 2 版重建；安裝前逐檔驗大小與 SHA-256，與 ADR 0001 相同；公開審核紀錄的 reviewer 為 AI 或自動檢查身分，不寫人工 |
| OD-11 | 本機自動換版成功後，每日排程自動發布新的 GitHub Release，不逐次請 owner 確認（owner 2026-09-15 選「自動發」） | 只發布本機正在服務、沒有待審新版或檢查失敗的 build；Release 標籤指向的程式 commit 必須和本機安裝版程式檔案相同、且 CI 通過，否則不發並寄信；最新 Release 已含同一組 build 就不重發；review protocol `nhi-r1-auto-review`、`tfda-r1-auto-review` 第 2 版 |
| OD-12 | 官方新版出現還沒審過的代碼時先當成「算」：健保算檢驗項目（`in_scope`），食藥署附表 A/B/C 類算體外診斷（`included`）；通知信列出這些代碼，之後補審（owner 2026-09-15 選「先當成「算」」） | 健保只套用在正式建置，判定依據寫「尚未審核的代碼：依專案負責人 2026-09-15 決定先算檢驗，之後補審」，查詢結果不因未審代碼整份標 `review_incomplete`；食藥署 D–P 類與沒有分類代碼的列維持 `unknown`；離線合成建置的健保未審代碼維持 `review_pending` |
| OD-13 | 疾管署認可檢驗機構查詢加翻頁：`find_authorized_lab` 新增 `limit`（~~1–5，預設 5~~ 1–20，預設 20）與 `offset`，可翻到最後一筆（owner 2026-09-15 回答翻頁 A／B 選項：「A 加翻頁」，transcript timestamp `2026-09-15T14:43:28.643Z`；同日看過模擬結果後回「一次 20 筆」，`2026-09-15T15:34:05.386Z`） | ~~一頁筆數沿用健保、食藥署搜尋的 5 筆（OD-07 同日「還是給5筆 有需要的話可以再進一步找」）~~ 一頁 20 筆：名冊一家機構的每個檢驗方法各佔一筆，模擬「在台南能做傷寒的有哪幾間醫院」時一次 5 筆只看到 10 家中的 3 家、要查 8 次，一次 20 筆第一次就看到 10 家；`get_lab_scope` 固定回第一頁 20 筆；翻過最後一筆時仍回總筆數；public contract 名稱維持 `public-contract-v1`（專案仍在 0.1.x） |
| OD-14 | 認可檢驗機構查詢把空格分開的詞拆開查：縣市詞當縣市篩選，其他詞每個都要命中（owner 2026-09-15 選 A「整句查不到的話回 A」，transcript timestamp `2026-09-15T15:34:05.386Z`） | 起因：模擬時「台南 傷寒」「傷寒 台南市」「台中 梅毒」都回 `not_found`，實際分別有 40、40、58 筆；縣市詞為 22 個縣市名稱或去掉「市／縣」的簡稱（「新竹」「嘉義」同時涵蓋市與縣）；只有一個詞時規則不變；全部都是縣市詞時照一般詞查；沒有空格的整句（「台南能做傷寒的醫院」）不拆，仍回 `not_found`；MCP 工具說明寫明兩種查法 |
| OD-15 | 採檢手冊格內換行選 B：被格子寬度折斷的行接成一行，「1.」「2.」編號前才換行；原文另存（owner 2026-09-15「我選 B」，transcript timestamp `2026-09-15T15:57:15.191Z`） | 例子（1150826 第 16 頁採檢目的）：「病原體檢↵測；血清↵型別鑑定」顯示為「病原體檢測；血清型別鑑定」；英數字兩邊補空格（「3↵mL 血清」→「3 mL 血清」）；出處查核與 row hash 用原文。~~只有編號前換行~~ Claude 同日補充、待 owner 確認：放得下卻換行的當成作者自己換的行保留（「傷寒↵副傷寒」）；是否折斷由字元位置推測（ADR 0003），1150826 少數「2-8oC↵(B 類感染性物質…」兩種讀法都說得通 |
| REL-G5 | 取消 5–10 人 pilot，改為公開上線並由使用者回報收集回饋 | 見第 8.2 節修訂列與第 8.4 節註記 |

## 10. 風險、假設與緩解

| 風險／假設 | 目前狀態 | 影響 | P1.1 緩解 |
| --- | --- | --- | --- |
| 官方 resource URL、傳輸格式或 schema 變動 | 已知可能；TFDA OAS 與實際 ZIP 已有差異 | 抓錯檔、解析錯欄或靜默產生壞資料 | 每次由官方入口發現、驗 magic/header/hash；drift 一律 staged + review |
| NHI CSV 是現行清單且無 laboratory 分類 | `VERIFIED`；完整 scope `UNVERIFIED` | 誤答歷史點數或假稱完整檢驗子集 | 現行／歷史能力分開；scope 狀態、locator 與 reviewer gate |
| `29101231` 代表 open-ended | `INFERENCE` | 誤稱永久有效 | 原值保留並標推論，待官方或 owner 決議 |
| TFDA IVD 無單一官方布林欄位，舊制 crosswalk 不完整 | `VERIFIED`／部分 `UNVERIFIED` | 非 IVD 誤納、真正 IVD 漏失 | 次類別逐碼 registry；ambiguous/unknown 不升格；關鍵字只作候選 |
| CDC PDF 表格跨頁、雙頁碼且附件版次可與頁面日期脫鉤 | `VERIFIED` | 條件錯接或定位失敗 | 版面解析、雙 locator、diff、人工與專業複核 |
| CDC 認可機構官方固定更新頻率 | `UNVERIFIED` | 把本專案 polling 誤稱官方 cadence | 分開顯示官方頻率 unknown 與本專案 last check |
| 上游暫時失敗或新版本尚未核准 | 預期情境 | 舊資料被誤認為最新，或系統偷退 sample | 保留上一 approved snapshot、強制 stale/review warning、無前版則 `data_unavailable` |
| 5–10 人 pilot 足以證明全面臨床適用 | 不成立；pilot 僅驗證早期 usability | 過度解讀小樣本 | 回報分母、情境與限制；不以推薦意願替代內容正確性 |

## 11. P1.1 完成定義

P1.1 只有在下列事項全部成立時才算完成：三個領域、四個資料集／查詢任務均使用各自已核准的 official snapshot；`REL-G1`～`REL-G5` 全數通過；狀態及 provenance 可由 MCP 使用者看見；沒有未解決的 critical semantic contamination 或 sample/official 混查問題。~~pilot 指標達標~~（2026-09-14 owner 取消 pilot，改由公開上線後的使用者回報收集回饋；見第 8.2、8.4 節）。

完成 P1.1 只代表適合本機離線公開資料查詢，不構成院內部署 readiness，也不代表 CDC、NHI、TFDA 對本產品的認證、核准或背書。即使在醫院環境試用，仍不得輸入病人資料；MCP host／LLM 的查詢記錄、資料傳輸、權限、retention 與院方核准不在 P1.1 已驗證範圍。院內正式導入須另走 P2 的資料責任、存取控制、端點治理、稽核與變更管理 gate。實際採檢、申報、送驗與採購仍須核對當期官方原文及使用者所屬機構流程。

## 12. 依據文件

- [P1.1 實作計畫書](implementation-plan.md)
- [P1 使用場景](use-cases.md)
- [NHI 資料源研究](research/nhi-data-source.md)
- [TFDA 資料源研究](research/tfda-data-source.md)
- [CDC 資料源研究](research/cdc-data-source.md)
- [Roadmap](../ROADMAP.md)
