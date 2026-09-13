# 第 1 輪獨立審查：產品需求與臨床誤導風險

審查日期：2026-09-13（Asia/Taipei）

審查角色：台灣醫檢使用者／產品需求／臨床誤導風險 reviewer

審查範圍：`README.md`、`ROADMAP.md`、`docs/product-requirements.md`、`docs/software-design.md`、`docs/test-driven-development.md`、`docs/implementation-plan.md`、`docs/research/*.md`

限制：本輪只審文件，不驗證程式實作或重新下載官方資料。以下判斷以文件內已標示的 2026-09-13 研究證據為準。

## 結論

**NEEDS REVISION。** 文件已正確守住 sample／official、provenance、現行資料不可冒充完整歷史、不同檢體／方法／製造關係不可錯接等主要邊界；但目前仍有 5 項 High 與 8 項 Medium finding。最需要先修的是 TFDA 效期狀態、IVD 候選搜尋、NHI `as_of`、CDC「保存」欄位語意，以及 `compare_products` 的產品名稱與行為。這些問題若只靠 disclaimer，仍可能讓 AI host 產生看似確定但超出來源能力的答案。

## Findings

### PCL-01 — TFDA 衍生狀態會隨時間失效，且把空白註銷欄推成「未註銷」

- **Severity：High**
- **檔案／行：** `docs/software-design.md:161`、`docs/software-design.md:392-395`、`docs/test-driven-development.md:111`、`docs/test-driven-development.md:160`、`docs/research/tfda-data-source.md:95-100`、`docs/research/tfda-data-source.md:161-172`
- **證據：** SDD 規定 raw hash 相同時不重建 curated snapshot，TFDA table/view 卻保存或輸出 `computed_temporal_state=not_cancelled_and_within_validity`。有效日期跨日後，即使官方檔案 hash 沒變，immutable snapshot 內的衍生狀態可能仍停在「期限內」。此外，來源的註銷狀態空白不是官方明文的「未註銷」布林值；研究只證明該欄空白，不能支持 `not_cancelled` 這個肯定語意。
- **建議修正：** 不在 immutable curated row 保存會隨今日日期改變的最終狀態；查詢時以明示的 `evaluated_as_of`、時區及 `valid_through` 計算。狀態名稱改為 `no_cancellation_recorded_in_source_and_within_validity_as_of`，或拆成 `cancellation_recorded`、`within_validity_period` 兩個欄位，禁止輸出「有效許可」「仍有效」。補有效日期前一日、當日、次日及官方 hash 未變的 injected-clock 測試。

### PCL-02 — IVD 搜尋的 PRD、SDD 與研究結論互相衝突，會造成高風險漏查

- **Severity：High**
- **檔案／行：** `docs/product-requirements.md:100-101`、`docs/software-design.md:410-418`、`docs/test-driven-development.md:68`、`docs/test-driven-development.md:162-165`、`docs/research/tfda-data-source.md:144-149`、`docs/research/tfda-data-source.md:218-223`
- **證據：** PRD 要求 IVD 搜尋回傳 `included`／`ambiguous`／`unknown`，SDD 卻規定 `search_ivd` 只回 `ivd_included`。研究又證明現行資料有 2,211 列屬 A／B／C 但無可解析現行次類別，另有 9,337 個舊制分類 cell；在舊制 crosswalk 未完成前，只回 included 會把大量 unknown 從候選結果完全隱藏。此時 `not_found` 很容易被 AI 或使用者誤讀成「沒有相關 IVD」。
- **建議修正：** 明確分成「reviewed included only」與「candidate recall」兩種查詢能力，tool 名稱、輸出狀態與警示都要區分。候選搜尋須能回 `ambiguous`／`unknown`，同時提供 `coverage_status`、本 snapshot 已 review code 比例、舊制／缺碼列數及 truncation。任何 completeness gate 未通過時，不得以空的 included-only 結果回答「有哪些相關 IVD」。

### PCL-03 — NHI `as_of` 是 PRD 必做、SDD 未來項目，且目前語意可能冒充歷史事實

- **Severity：High**
- **檔案／行：** `docs/product-requirements.md:90`、`docs/software-design.md:376-379`、`docs/test-driven-development.md:64-65`、`docs/test-driven-development.md:143-145`、`docs/research/nhi-data-source.md:141-150`
- **證據：** PRD 的 `NHI-04` 把 `as_of` 寫成 P1.1 acceptance criterion；SDD 卻寫「若未來加入」，ToolResult／tool signature 也沒有 `as_of` 契約。更重要的是，目前 CSV 只有現行列；即使現行列的原始起迄欄位涵蓋某個過去日期，也不能證明該日期當時的點數就是現值。PRD 的「只判斷欄位是否涵蓋」仍可能被上層 AI 敘述成歷史有效性。
- **建議修正：** 二選一並同步三份文件：P1.1 移除 `as_of`；或正式定義 `as_of` request/response，對首次觀測 snapshot 以前的歷史事實一律 `historical_data_unavailable`。若保留單純欄位比較，欄位名應是 `current_row_date_fields_cover_query_date`，同時固定回 `historical_truth_supported=false`，不可只回布林命中。

### PCL-04 — 「保存」產品文案可能把 CDC 的留存欄位誤當檢體運送前保存條件

- **Severity：High**
- **檔案／行：** `README.md:15-17`、`README.md:23`、`docs/product-requirements.md:27`、`docs/product-requirements.md:35`、`docs/implementation-plan.md:19`、`docs/implementation-plan.md:169-174`、`docs/research/cdc-data-source.md:61-64`
- **證據：** README、PRD persona 與計畫摘要均承諾查「保存」，一般醫檢使用者會自然理解為檢體送驗前的保存溫度／時間；但來源研究已明確指出「應保存種類（應保存時間）」是疾管署保存材料／期間，不應改稱送驗前 storage。這是直接的臨床操作誤導風險。
- **建議修正：** 所有產品層文案改用官方完整欄名「應保存種類（應保存時間）」並就近標示「不是檢體送驗前保存條件」。真正運送溫度與時間只能保留在 `送驗方式`／注意事項原文，不抽成未被來源支持的 storage 欄。Golden case 與 pilot 必須加入一題，驗證使用者不會把兩者混淆。

### PCL-05 — `compare_products` 名稱和行為與「不做等效／採購判斷」的產品邊界衝突

- **Severity：High**
- **檔案／行：** `README.md:72`、`docs/product-requirements.md:29`、`docs/product-requirements.md:65`、`docs/software-design.md:489-494`、`docs/test-driven-development.md:164`
- **證據：** PRD 明確排除產品等效與採購建議；但公開 tool 仍叫 `compare_products`。SDD 已承認名稱需要修改，只因相容性而保留並加警示。MCP tool 名會直接影響 host 模型如何選工具及敘述結果，警示無法抵銷「compare」所誘發的比較、排序或可替代推論。
- **建議修正：** P1.1 將主工具改為 `list_matching_license_records` 或同等中性名稱；舊 `compare_products` 僅回 deprecated／unsupported boundary，不回可被模型整理成比較表的資料，或至少預設 disabled。加入 tool description contract 與 misuse prompt 測試，驗證不產出優劣、相似度、可替代性或採購排序。

### PCL-06 — `validation_status`／`review_status`／`status` 列舉不一致，無法建立單一可測對外契約

- **Severity：Medium**
- **檔案／行：** `docs/product-requirements.md:125-136`、`docs/software-design.md:232-244`、`docs/software-design.md:471-483`、`docs/software-design.md:485-487`
- **證據：** PRD 使用 `validation_status=approved|review_pending|rejected`，manifest 把機器驗證寫成 `passed`、人工 review 另為 `approved`，ToolResult 的 `validation_status` 又只有 `sample|passed|review_pending|unavailable`，沒有 `rejected`。同一新版被拒、但仍服務舊 approved snapshot 時，若沒有明確的 serving 與 candidate 雙狀態，caller 無法判定哪個狀態屬於哪個版本。
- **建議修正：** 建立一份 canonical status schema：至少拆成 `serving_validation_status`、`serving_review_status`、`candidate_status`、`availability`、`result_status`。列舉值與 JSON 欄位只定義一次，PRD／SDD／TDD 全部引用；補「candidate rejected + serving old approved」的序列化測試。

### PCL-07 — 「可回到官方原列核對」對 current-only 來源是過度承諾

- **Severity：Medium**
- **檔案／行：** `docs/product-requirements.md:29`、`docs/product-requirements.md:118`、`docs/software-design.md:284-292`、`docs/software-design.md:343`、`docs/research/nhi-data-source.md:141-150`、`docs/research/cdc-data-source.md:38`
- **證據：** UX-02 要求使用者憑 URL、版本與 locator 回查官方值，但 NHI／TFDA resource URL 主要提供當期檔，CDC 舊 token 也可能失效；source row number 加 hash 只能證明本地 snapshot 的定位，未必能在官方網站換版後重現。SDD 同時禁止把 official raw 打包進 wheel，且 curated artifact 是否再散布未決。
- **建議修正：** 把「可核對」拆成 `snapshot_traceable` 與 `currently_reproducible_from_upstream`。只有上游現檔 hash 與 snapshot 相同，或部署者能提供合法保存的 raw artifact，才把 UX-02 記為官方值回查成功；否則顯示上游已換版／舊檔不可取得。Pilot 不得只看 locator 有值就算成功。

### PCL-08 — P1.1 到底是三個還是四個正式場景，完成條件不一致

- **Severity：Medium**
- **檔案／行：** `README.md:5-17`、`ROADMAP.md:15-21`、`docs/implementation-plan.md:17-31`、`docs/product-requirements.md:55-59`、`docs/product-requirements.md:164`、`docs/product-requirements.md:191`
- **證據：** README、Roadmap 與實作計畫以 CDC／NHI／TFDA 三場景描述 P1.1；PRD 把 CDC 採檢手冊與 CDC 認可機構拆為四個正式查詢場景，並要求四者都通過才算 P1.1 完成。這會讓排程、pilot 任務、release 宣告與「三個來源」指標無法對齊。
- **建議修正：** 先決定 P1.1 是「三個領域、四個資料集／查詢任務」，或 ODS 延後到下一版。統一 README、Roadmap、PRD、工時表、G2/G3、golden case 分母與版本完成宣告。

### PCL-09 — NHI 名稱／alias 搜尋在 PRD 必做，但 SDD 可能整個阻擋，沒有可驗收行為

- **Severity：Medium**
- **檔案／行：** `docs/product-requirements.md:44`、`docs/product-requirements.md:88`、`docs/software-design.md:374-381`、`docs/research/nhi-data-source.md:17`、`docs/research/nhi-data-source.md:225`
- **證據：** PRD 要求名稱或 alias 搜尋回所有候選；來源研究建議未核准 scope 前仍可全表搜尋並回 `scope_status`。SDD 卻允許 `search_lab_code`／`get_payment_rule` 直接回 `scope_review_pending`，或把候選模式留給「未來新工具」。此外 alias 的來源、review 狀態與 schema 未定義，無法測試「所有符合候選」。
- **建議修正：** 定義本版唯一行為：全表名稱搜尋可以回候選，但每列必須帶 scope 狀態；或明確從 P1.1 移除名稱搜尋。若保留 alias，新增 `alias_raw`、來源、locator、rule version、review status 與 collision 行為，並把「所有符合」改為可測的 normalization／matching 規則與 truncation contract。

### PCL-10 — CDC 專業複核有 gate 名稱，但抽樣、資格與判退規則仍不可重現

- **Severity：Medium**
- **檔案／行：** `docs/product-requirements.md:160`、`docs/product-requirements.md:173`、`docs/software-design.md:450-452`、`docs/test-driven-development.md:181`、`docs/research/cdc-data-source.md:110-120`
- **證據：** 文件要求所有變更列全檢、未變更列跨疾病抽樣與醫檢 reviewer，但沒有定義抽樣分層／數量、關鍵欄位 checklist、reviewer 最低資格、衝突處理、任何一筆錯誤是否整批 rejected，以及修正後是否需要重新簽核。不同 reviewer 可在同一資料上做出不同 release 結論。
- **建議修正：** 在 G3 前定義 versioned review protocol：reviewer role/資格、必查欄位、全部變更列、未變更列抽樣算法與 seed、最小樣本、critical/major/minor 分級、判退門檻、修正後 re-review、簽核 scope 及 artifact/rule hash。`review.json` 保存這些欄位，不只 reviewer id 和時間。

### PCL-11 — Pilot 的 80% 指標沒有固定任務與計分規則，無法比較兩輪修改是否真的改善

- **Severity：Medium**
- **檔案／行：** `docs/product-requirements.md:144-152`、`docs/product-requirements.md:162`、`docs/test-driven-development.md:299-305`
- **證據：** 5–10 人樣本下，80% 會因分母小而大幅跳動；文件沒有固定題目、受測者背景分層、allowed help、超時、部分完成、警示理解題目或 critical safety issue 定義。若 participant 沒碰到 stale／unknown／not_found，就不能用訪談自然發生的結果驗證警示理解。
- **建議修正：** 建立固定 pilot protocol，至少強制四類正常任務及 sample、stale、not_found、IVD unknown、NHI historical unavailable 等安全情境；定義逐題 rubric、時間、可用協助、分母與 critical issue taxonomy。結果以人數與比例並列，不把 4/5 與 8/10 視為同等證據。

### PCL-12 — 安全警示只在 result notes／人工文案抽查，未覆蓋 MCP host 的工具選擇與二次敘述

- **Severity：Medium**
- **檔案／行：** `docs/product-requirements.md:29`、`docs/product-requirements.md:64-65`、`docs/software-design.md:107`、`docs/software-design.md:483`、`docs/test-driven-development.md:61`、`docs/test-driven-development.md:67`
- **證據：** 產品透過 AI Agent 使用，但現有驗收多半只檢查 ToolResult 或「文案抽查」。MCP host 可能忽略 notes，把點數說成可申報、把許可資料說成可採購，或把 CDC 候選機構說成可收件。文件未要求 tool description 本身包含邊界，也未定義對常見越界問法的契約測試。
- **建議修正：** 將邊界做成結構化欄位，例如 `decision_support_only`、`not_for_claim_determination`、`not_for_procurement_or_equivalence`、`verify_current_official_source`，並同步放入 tool description。新增 MCP discovery contract 與 misuse-query cases；測試至少保證 tool 不回肯定性判定，並在每筆高風險結果旁顯示對應警示，而非只放在尾端 notes。

### PCL-13 — P1 文件暗示「符合醫院部署」，與 P2 gate 及 PHI 邊界不一致

- **Severity：Medium**
- **檔案／行：** `docs/product-requirements.md:63`、`docs/software-design.md:78`、`docs/software-design.md:619`、`ROADMAP.md:36-40`
- **證據：** PRD 與 Roadmap 明確把院內正式部署、資料責任、去識別化、LIS/HIS 與稽核放到 P2；SDD 卻以「確保醫院端 runtime」及「符合本機/醫院部署」描述 D-001。離線唯讀只是降低網路依賴，不能證明已具醫院部署所需的存取控制、端點治理、host log／retention、變更管理與院方核准。
- **建議修正：** 將文字改為「適合本機離線查詢；不構成院內部署 readiness」。P1 release notes 明示若由醫院環境使用，仍不得輸入病人資料，且 MCP host／LLM 的查詢記錄、傳輸與權限不在本專案已驗證範圍；院內正式導入需走 P2 gate。

## 已確認沒有發現的越界

- 在已審文件中，沒有看到 P1.1 要 ingest 病人資料、病歷、LIS/HIS 或院內資料清理。
- LOINC、FHIR、SNOMED、EQA、CAP 仍維持未啟用／授權 gate，沒有被偷渡成 P1.1 正式內容。
- 文件有明確禁止把 NHI 點數當金額、TFDA 許可資料當採購／等效結論，以及把查無結果當官方不存在；上述 finding 是要求把這些界線落成一致、可測且不易被 AI host 稀釋的契約。

## 建議第 1 次修訂優先序

1. 先修 PCL-01～PCL-05，因為直接影響臨床／申報／IVD 判讀。
2. 統一狀態與三／四場景範圍（PCL-06、PCL-08、PCL-09）。
3. 將 provenance、review、pilot 與警示改成可重現契約（PCL-07、PCL-10～PCL-12）。
4. 收斂院內部署措辭（PCL-13），維持 P1/P2 邊界。
