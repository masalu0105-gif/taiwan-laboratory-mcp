# Round 2 規格一致性稽核

稽核日期：2026-09-13（Asia/Taipei）

稽核範圍：`docs/product-requirements.md`、`docs/software-design.md`、`docs/test-driven-development.md`、`docs/implementation-plan.md`、`docs/research/*.md`、`docs/reviews/round1-*.md`

限制：本輪只做修訂後文件的機械與語義稽核；未修改 PRD、SDD、TDD、實作計畫或研究正文，未把任何 **PLANNED** 測試、CLI 或 official source qualification 視為已實作或已通過。

## 結論

**NEEDS REVISION。** 23 個 PRD acceptance IDs 都已各自出現在 TDD traceability matrix，且相對 Markdown 連結未發現斷鏈；但 canonical operation contract、4 個 SDD IDs、source gate namespace、NHI／TFDA 衍生語意、public safety flags 與數個 owner decision 尚未形成唯一真源。下列 P1 未修前，不宜把文件標成 implementation-ready，也不能把 official source 標為可發布。

機械檢查摘要：

| 檢查 | 結果 |
| --- | --- |
| PRD acceptance IDs | 23/23 各有一個 TDD matrix row |
| SDD IDs 在 TDD 的明確引用 | 10/14；缺 `SDD-FAIL-01`、`SDD-AUDIT-01`、`SDD-API-01`、`SDD-QUAL-01` |
| Canonical operation names 在 TDD discovery contract | 不完整；CDC tools 也未列成封閉清單 |
| Gate namespace | 主文件已改用 `REL-*`／`<SOURCE>-R1-*`，CDC research 仍使用裸 `G1`～`G5` |
| 相對 Markdown links | 在本輪檔案範圍內未發現不存在的本機 target |

## 殘留問題與最小修正

### R2-01 — P1 — Canonical operation matrix 仍不是完整、可機械驗證的 public contract

- Confidence：10/10
- 證據：`docs/product-requirements.md:75-87` 以「CDC `search_disease` 與採檢相關既有 tools」代表未封閉的集合，且 `find_authorized_lab`、`get_lab_scope`、`get_license`、`find_manufacturer` 沒有 exact parameter names/defaults；`docs/software-design.md:645-657` 延續相同模糊度；`docs/test-driven-development.md:436` 聲稱驗整張 operation matrix，實際只點名部分 NHI／TFDA tools，漏掉 `get_data_status`、`find_authorized_lab`、`get_lab_scope`、`get_license`、`find_manufacturer` 及 CDC 完整清單。
- 影響：不同實作者可保留不同 CDC legacy tools 或給相同 tool 不同 signature，TDD 仍可能通過局部 inventory。
- 最小修正：PRD 5.3 列出每一個 P1.1 tool 的 exact name、parameters、types、defaults、mode/source、deprecated policy；SDD 只引用該表並補 internal mapping；TDD 以同一份 operation fixture 對 `list_tools` 做集合相等與 signature equality，不再手寫不完整子集。

### R2-02 — P1 — 4 個 SDD requirements 沒有 TDD trace node 或明確 verification owner

- Confidence：10/10
- 證據：`docs/software-design.md:28`、`:37-39` 定義 `SDD-FAIL-01`、`SDD-AUDIT-01`、`SDD-API-01`、`SDD-QUAL-01`；機械搜尋在 `docs/test-driven-development.md` 的結果均為 0 次。TDD 雖有 fail-closed、audit、operation 與 CDC qualification 章節，但沒有以這四個 ID 綁到 canonical node/evidence。
- 影響：TDD 宣告的 bidirectional traceability 不能證明這四項 SDD requirement 由哪個 node 關閉，acceptance reporter 也無法判斷 coverage。
- 最小修正：在 TDD 增加 SDD verification matrix，逐 ID 指向 exact pytest node、qualification command/evidence path 與 gate；至少把四個缺漏 ID 綁到現有規劃中的 tests/CLI nodes。不要只把 ID 放進段落文字冒充可執行追蹤。

### R2-03 — P1 — Source gate namespace 尚未從 CDC research 完成遷移

- Confidence：10/10
- 證據：PRD 明定 `REL-G1`～`REL-G5` 不得充當 source review type（`docs/product-requirements.md:211-219`），SDD/TDD 使用 `CDC-R1-*`、`ODS-R1-*` 與 `PUB-R1-OWNER`；但 `docs/research/cdc-data-source.md:114-118` 仍把來源、版面、專業、ODS、owner publish 命名為裸 `G1`～`G5`。
- 影響：依研究文件實作的 review record 會被 TDD 規定判無效，且 `G5` 仍可能被誤解成 `REL-G5` pilot。
- 最小修正：把 CDC research 表改成兩條 source gate chain：`CDC-R1-SOURCE/LAYOUT/CONTENT` 與 `ODS-R1-SOURCE/STRUCTURE/CONTENT`，owner 用 `PUB-R1-OWNER`；另列 mapping 到 `REL-G2`～`REL-G4`，移除裸 `G1`～`G5`。

### R2-04 — P1 — NHI research／implementation plan 仍保留已被 canonical contract 否決的日期與查詢行為

- Confidence：10/10
- 證據：PRD/SDD/TDD 規定 strict Gregorian `YYYYMMDD`，任何 non-null `as_of` 一律 `historical_query_unsupported` 且不得比較 current row（`docs/product-requirements.md:80,114`、`docs/software-design.md:476,480`、`docs/test-driven-development.md:250`）。但 implementation plan 仍要求「民國／西元日期」轉 ISO（`docs/implementation-plan.md:122`）；NHI research 仍允許比較 current row 是否涵蓋指定日並回另一個 status `historical_data_unavailable`（`docs/research/nhi-data-source.md:146-150`）；其實作順序又說 scope 核准後「預設只回檢驗項目」（`:365`），與 `search_payment_items` 永遠查全表的 PRD contract 不同。實作計畫另持續以「同碼多版本」作 P1.1 測試目標（`docs/implementation-plan.md:30,214`），但本來源契約是當期重複 code 即 block。
- 影響：同一 NHI importer 可被寫成 ROC 猜測 parser、日期涵蓋 API 或 scope-filtered default，均與 acceptance tests 不相容。
- 最小修正：研究文件保留觀察證據，但在 implementation recommendation 明示已由 PRD v0.2 supersede；計畫改成 strict Gregorian、non-null `as_of` 固定 unsupported、`search_payment_items` 全表不變、duplicate current code 整批 block。歷史版本 ingestion 只留 P2/out-of-scope。

### R2-05 — P1 — TFDA cancellation／validity decision table 在三份文件仍互相衝突

- Confidence：10/10
- 證據：PRD/SDD 要求分開輸出 `cancellation_recorded_in_source` 與 `within_validity_period_as_of`，SDD 規定狀態與日期皆空時前者可為 `false`（`docs/product-requirements.md:122`、`docs/software-design.md:499`）。TDD 卻寫「來源狀態空白只能是 unknown」（`docs/test-driven-development.md:267`）；TFDA research 仍允許 `computed_temporal_state=not_cancelled_and_within_validity`（`docs/research/tfda-data-source.md:172`），正是 Round 1 要移除的肯定性合成狀態。
- 影響：空白註銷欄可能在不同 adapter 被序列化成 false、unknown 或「未註銷且有效」，後者可直接誘發採購／有效許可誤讀。
- 最小修正：在 PRD 建一張狀態×註銷日期×valid-through 的 canonical truth table，明定兩個輸出欄與 warning；TDD 逐列照表測；research 移除 `computed_temporal_state` 與 `not_cancelled_and_within_validity`，只保留 raw evidence。

### R2-06 — P1 — TFDA IVD public enum 與 owner decision 尚未收斂

- Confidence：10/10
- 證據：PRD public `ivd_scope` 只有 `included|excluded|ambiguous|unknown`，candidate tool 允許 ambiguous/unknown（`docs/product-requirements.md:162,255`）。TDD 與 TFDA research 仍使用未定義狀態 `review_pending`、`not_ivd_by_reviewed_classification`、`ivd_unknown`／`ivd_candidate`（`docs/test-driven-development.md:271`、`docs/research/tfda-data-source.md:213-215`）。同一 research 又把「ambiguous 是否可出現在候選搜尋結果」列為未決 owner gate（`:307`），但 PRD OD-03 已明確決定可出現。
- 影響：classifier、query filter 與 MCP schema 可能各採不同 enum；已決策行為仍被當作 blocker。
- 最小修正：research/TDD 全部改用 canonical `ivd_scope`，若需要 internal decision status，另列一對一 mapping且不得出現在 public result；把 ambiguous candidate gate 標為 **RESOLVED by PRD OD-03**，owner 只需指定 registry reviewer。

### R2-07 — P1 — TFDA research 的 row quarantine 流程仍可被解讀成 partial publish

- Confidence：9/10
- 證據：SDD/TDD 規定 `quarantined_rows > 0` 整批 block、published `input_rows == curated_rows`（`docs/software-design.md:396-413`、`docs/test-driven-development.md:183-187`）。TFDA research 卻把空字號、日期、狀態衝突與角色缺值列為 `Row quarantine`，流程圖在 `row quarantine + batch quality report` 後繼續 join/build/publish（`docs/research/tfda-data-source.md:243-252,263-276`），沒有寫明任何 row quarantine 都 block P1.1 publish。
- 影響：依研究文件實作時可能丟棄 source rows 後仍產生看似 `coverage_status=complete` 的 snapshot。
- 最小修正：把 research 的 `Row quarantine` 改名為 diagnostic row disposition，逐項標「保留 raw/staged evidence＋整批 block」；分類未知則原列完整進 curated、`ivd_scope=unknown`，不得 quarantine。流程在 quarantine count 非零處直接終止 publish。

### R2-08 — P1 — Operational status integrity 在同一 SDD 有兩種 public mapping

- Confidence：10/10
- 證據：`docs/software-design.md:358` 規定 status 缺失／毀損／與 current 不一致時回 `availability=data_unavailable`、`result_status=data_unavailable`、`OPERATIONAL_STATUS_INTEGRITY`；但 threat model 在 `:726` 說同一情況「一律 stale」。TDD internal mapping只列 pointer／manifest／DB／audit failure，沒有 operational-status integrity node（`docs/test-driven-development.md:124-140`）。
- 影響：runtime 可在 status tamper 時繼續服務並標 stale，也可完全 unavailable；兩者的可用性與安全行為不同。
- 最小修正：選一個 mapping。依目前 public enum 最小改動是保留 7.6 的 `data_unavailable`，把 14.1 改成相同語意；TDD 增加 status missing/hash/schema/source/snapshot mismatch nodes，逐一 assert source unavailable、current 不變且不 fallback sample。

### R2-09 — P2 — Public safety flags 有三組不同欄名

- Confidence：10/10
- 證據：PRD 使用 `not_a_specimen_storage_instruction` 與 item-level `not_pre_submission_storage`（`docs/product-requirements.md:91,102`）；SDD entity table 改成 `not_pre_submission_specimen_storage`，operation contract 又改回前者，並新增 ODS `not_a_receiving_guarantee`（`docs/software-design.md:571,661`）；TDD 對 ODS 使用另一名稱 `does_not_confirm_current_acceptance`，另新增 PRD 未列的 `not_validated_for_hospital_deployment`（`docs/test-driven-development.md:27,438`）。
- 影響：tool description、ItemEnvelope 與 contract tests可能對不同 key 做斷言，host 也無法依穩定欄位顯示警示。
- 最小修正：在 PRD 增加 exact safety-field registry，明定每個 field 的層級、適用 tools、型別與必填條件；SDD/TDD只引用同一名稱。最小命名選擇是保留已進 acceptance criterion 的 `not_pre_submission_storage`，ODS 在 `not_a_receiving_guarantee` 與 `does_not_confirm_current_acceptance` 二選一；hospital deployment flag若要成為 contract，先加入 PRD。

### R2-10 — P2 — P1.1 OCR publish 邊界在 PRD、SDD/TDD 與 implementation plan 仍可讀成不同政策

- Confidence：9/10
- 證據：SDD/TDD 明定 P1.1 official publish 禁止 OCR，只可產生 staged candidate（`docs/software-design.md:565`、`docs/test-driven-development.md:285`）。PRD 先說 P1.1 OCR 只可 staged，接著又列「若要發布含 OCR」的 review 條件而未明說必須升版（`docs/product-requirements.md:239`）；implementation plan 仍寫成文字層缺失時直接啟用 OCR（`docs/implementation-plan.md:90,169`）。
- 影響：實作者可能把 100% review 當成本版 OCR publish 的合法路徑，也可能只產 staged research output。
- 最小修正：PRD 明寫「P1.1 official publish 不接受 OCR；以下條件只供未來版本，需先修 PRD/TDD」；implementation plan 同步寫成「只產 staged candidate，不進 approved build」。

### R2-11 — P2 — PLANNED／VERIFIED／OWNER GATE 標記仍有過期或遺漏

- Confidence：9/10
- 證據：TFDA research 標題狀態是 `implementation ready`（`docs/research/tfda-data-source.md:3`），但同文件仍有 owner gates且多個實作建議已被 PRD/SDD supersede；CDC research 把 LibreOffice 未安裝標為 `BLOCKED locally`，同一列又證明 stdlib ODS parser 可行且不需要 LibreOffice（`docs/research/cdc-data-source.md:144`）。PRD OD-02 同時要求決定 NHI scope與 `29101231` 對外語意（`docs/product-requirements.md:254`），SDD decision log 的 D-009 只保留 scope owner，未追蹤 sentinel 決議（`docs/software-design.md:821`）。TFDA research 的 ambiguous owner gate則已被 PRD OD-03 解決。
- 影響：owner checklist會漏掉 sentinel 決議、保留已解決 gate，並讓 research evidence被誤認為完整實作規格。
- 最小修正：研究文件狀態改成「Research complete; implementation governed by PRD/SDD」；CDC LibreOffice項改 `RESOLVED / not required`；建立 OD-01～OD-05 到 SDD D-* 的一對一 mapping，新增 sentinel decision row並將已決策項標 resolved。

### R2-12 — P2 — Qualifier package resource 路徑有一處拼錯，canonical command 無法依單一路徑實作

- Confidence：10/10
- 證據：SDD 目錄與模組規劃、TDD 都使用 `src/taiwan_lab_mcp/qualifier_specs/liteparse-2.0.0.json`／`qualifier_specs/liteparse-2.0.0.json`（`docs/software-design.md:159,760`、`docs/test-driven-development.md:310,421`），但 CDC qualification 流程寫成 package resource `qualifiers/liteparse-2.0.0.json`（`docs/software-design.md:561`）。
- 影響：repo 外 wheel qualification 可能讀不到 spec，或有人為了通過而加入未規範的 fallback path。
- 最小修正：把 `docs/software-design.md:561` 改為 `qualifier_specs/liteparse-2.0.0.json`，並在 out-of-tree wheel node assert exact `importlib.resources` package/path，禁止 repo-relative fallback。

### R2-13 — P2 — `get_points.as_of` 的 invalid-input precedence 尚未定義

- Confidence：8/10
- 證據：PRD operation matrix稱 `as_of` 為 optional ISO date，同時 NHI-04 說「任何 non-null」都回 `historical_query_unsupported`（`docs/product-requirements.md:80,114`）。TDD allowed combinations同時規定 non-null `as_of` 回 unsupported、參數不合法回 `invalid_request`（`docs/test-driven-development.md:116-119`），沒有定義 malformed date、空字串、非字串的優先順序。
- 影響：相同 request 可因 validator先後順序得到兩種 `result_status`，stdio compatibility test無法唯一斷言。
- 最小修正：明定 validation precedence。建議「合法 ISO date但 non-null → `historical_query_unsupported`；malformed／wrong type／空字串 → `invalid_request`」，並加入四個 exact stdio cases；若真要所有 non-null 都 unsupported，就移除「ISO date」型別承諾。

### R2-14 — P2 — Status／freshness 欄位名仍有第二套寫法

- Confidence：9/10
- 證據：implementation plan 仍規劃 `validation_status` 與 singular `stale_reason`（`docs/implementation-plan.md:201`），NHI／CDC research 也使用 singular `stale_reason`（`docs/research/nhi-data-source.md:281`、`docs/research/cdc-data-source.md:98`）；PRD canonical contract 已改為 serving/candidate 分欄與 `stale_reason_codes[]`。SDD 對同一發布時間又同時使用 `last_successful_publish_at` 與 `last_publish_at`（`docs/software-design.md:437,639`）。
- 影響：status JSON、manifest與ToolResult可能保留舊欄，形成第二套 public schema。
- 最小修正：指定 PRD 7.1/7.2 為唯一 public field registry；plan/research 的實作建議全部改成 canonical names或明標「legacy/superseded」。在 PRD/SDD 二選一固定 `last_publish_at` 或 `last_successful_publish_at`，TDD 加 `extra=forbid` 與 legacy-key rejection。

## Round 2 exit condition

只有在 R2-01～R2-08 完成、R2-09～R2-14 至少收斂成單一 machine-readable contract，且再次跑相同機械檢查後，文件才適合標記為 implementation-ready。正文修正時應以 PRD 作產品／public contract 真源、SDD作 internal architecture 真源、TDD只引用 exact IDs/nodes；research 與 implementation plan 保留證據和排程，不再另定 public enum、gate 或 tool semantics。
