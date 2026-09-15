# Taiwan Laboratory MCP P1.1 測試驅動開發計畫

文件狀態：Round 2 revised draft；official publish 仍受 `REL-G1`～`REL-G5` 約束

核對日期：2026-09-14（Asia/Taipei）

適用範圍：三個領域、四個資料集／查詢任務（NHI、TFDA、CDC PDF、CDC ODS）、共用 snapshot 與 MCP stdio

## 1. 目的與測試承諾

本文件把產品需求與軟體設計轉成可執行的測試順序。測試不追求每個小函式都有一個案例，而是優先證明資料不會被錯接、錯算、錯誤發布或失去來源。每個正式資料切片都要先出現一個能說明風險的失敗測試，再做最小實作使其通過，最後才整理共用程式。

P1.1 的五項測試承諾如下：

1. `sample` 與 `official_snapshot` 永不混查；正式資料不可用 sample 偽裝成功。
2. 只有完整驗證且通過必要人工 gate 的 immutable snapshot 能成為 `current`。
3. 原始值、標準化值與 provenance 分開保存，任何 MCP 結果都能回到原列或文件頁面。
4. NHI、TFDA、CDC／ODS 的領域關係維持各自語意，不為了共用而合併成錯誤模型。
5. 上游失敗、schema drift 或資料過舊時，系統明確回報 stale／unavailable，且上一個已核准 snapshot 保持不變。

## 2. 現況基線與刻意不測的範圍

文件撰寫時的 `src/taiwan_lab_mcp` 只實作 sample mode；那段 `53 passed` 是 v0.1.1 baseline。現在 worktree 已完成第一輪雙模式共用層與 NHI vertical slice，canonical NHI／MCP boundary tests 與 migrated baseline 共同回歸；最新完整 suite 為 155 passed。這不代表 canonical matrix 的所有 planned nodes、正式 source qualification 或整體 P1.1 release gates 已關閉。

本階段不測病人資料、LIS／HIS、申報送出、診斷建議、採購建議、LOINC／FHIR／SNOMED 實作或 EQA／CAP catalog。也不為單純 getter、薄 wrapper、常數或標準函式庫已保證的行為逐一寫測試；只有當它們承載資料信任邊界或曾發生回歸，才補案例。

Official suite 最多證明「適合本機離線公開資料查詢」，不構成院內部署 readiness。測試不涵蓋 MCP host／LLM 的 log retention、院方 access control、變更管理或 PHI governance；P1.1 tool description 必須標 `not_validated_for_hospital_deployment=true` 與「不得輸入病人資料」，院內正式導入留在 P2。

外部網站是否在線、當天列數或當天 SHA-256 不放進一般 CI。一般測試全部離線、可重跑；live source probe 是同步作業的獨立檢查，結果保存為 report，不能取代 parser 與發布測試。

## 3. 測試層級與責任

| 層級 | 要證明的事情 | 主要做法 | 不負責的事情 |
| --- | --- | --- | --- |
| Unit | 日期、字串、row identity、分類狀態、merge span 等高風險純規則正確 | 小型 table-driven fixture、`pytest.mark.parametrize` | 不測網路與完整 MCP server |
| Contract | manifest、record、provenance、各來源 header 與狀態列舉符合已核准 schema | 直接驗證 model／parser 輸入輸出與錯誤類型 | 不以 Pydantic 通過代表資料語意正確 |
| Integration | fetch artifact 經 verify → parse → validate → publish 後，runtime 只讀 `current` | `tmp_path` 建立完整目錄與故障注入，網路以固定 response fixture 取代 | 不依賴當下官方網站 |
| MCP stdio | 安裝後 server 可被 host discovery，sample／official／stale／unavailable 均能正確序列化 | 延續 `tests/test_mcp_stdio.py` 的 subprocess，從 repo 外 cwd 執行 | 不把直接呼叫 Python adapter 當 stdio 驗證 |
| Golden | 查詢結果的關鍵值與來源定位可由 reviewer 回到官方證據 | 每來源至少 10 個 owner-approved cases；比對語意欄位及 provenance | 不把整份 JSON snapshot 當脆弱的 golden blob |
| Security | 下載、ZIP、路徑、大小、格式與 host allowlist 不可跨越 trust boundary | 惡意 bytes／entry name／redirect／截斷檔 fixture | 不用破壞 current 或真實目錄做測試 |
| Property-like regression | 大量邊界組合仍維持 invariant | 標準函式庫固定 seed 或明列 case matrix，不新增 Hypothesis | 不做無法重現的隨機 fuzzing |

必要的人工 gate 不是自動測試的替代品。CDC 內容複核、TFDA IVD registry 核准與 NHI laboratory scope 核准，都要在 manifest 留下 reviewer、時間、規則版本與決議；自動測試只驗證「未核准時不能正式發布或不能宣稱完整」。

## 4. Red–Green–Refactor 工作方式

每個切片使用同一節奏：

1. **Red**：先新增一個最小失敗案例，測試名稱直接描述醫療／資料風險；先確認它因缺少目標行為失敗，而非 fixture、import 或環境錯誤。
2. **Green**：只實作讓該案例與既有 suite 通過的最小程式；不順便加入下一來源、抽象 framework 或新依賴。
3. **Refactor**：全部 green 後才移除重複，且測試輸出與 public contract 不變；共用層只抽出三個來源確實共享的 immutable snapshot、manifest、provenance 與 publish 行為。
4. **Record**：在追蹤矩陣標記對應 requirement／SDD ID／測試檔與 release gate；若需求變更，先改 acceptance test，再改程式。

一個 Red 應只卡住一個決策。例如「缺少 NHI `備註` 欄會阻擋發布」與「支付點數 0 不可變 null」分成兩個測試；不要用單一端到端案例同時承擔所有失敗原因。

## 5. 需求到測試追蹤矩陣

以下 node IDs 是 P1.1 的 canonical planned layout。尚未建立的檔案標為 **PLANNED**，必須在對應 Red 切片先建立後才可執行；不能把不存在的 node 或 `53 deselected` 當通過。每次跑完由 acceptance reporter 寫入 `reports/acceptance/<release-id>/<PRD-ID>.json`，包含 node ID、exit code、測試輸出 hash、golden qualification hash 與 source review evidence hash。

目前已將第一輪可執行 slice 拆到 `tests/test_nhi_importer.py`、`tests/test_official_adapters.py`、`tests/test_mcp_stdio.py`、`tests/test_snapshot_publish.py`、`tests/test_freshness.py`、`tests/test_security_boundaries.py` 與 `tests/test_models.py`；其中 `SDD-API-01`、`SDD-ISO-01`、`SDD-PUB-01`、`SDD-FAIL-01`、`SDD-FRESH-01`、`SDD-PROV-01`、`SDD-SEC-01`、`SDD-OBS-01`、`SDD-AUDIT-01`、`SDD-NHI-01` 與 `NHI-01..05` 已登錄為 executable，其餘 canonical node 仍為 PLANNED。Acceptance registry 與 reporter 只承認實際登錄且可執行的 node，不把相近測試名稱或集中式 suite 映射成已關閉的 canonical node。

| PRD ID | SDD | Canonical pytest node ID | 必要證據／gate |
| --- | --- | --- | --- |
| `CDC-01` | `SDD-CDC-01` | `tests/test_cdc_pdf_importer.py::test_cdc_01_methods_and_specimens_do_not_cross_join` | `CDC-G-001..010`；`CDC-R1-LAYOUT`、`CDC-R1-CONTENT` |
| `CDC-02` | `SDD-CDC-01` | `tests/test_cdc_pdf_importer.py::test_cdc_02_raw_fields_are_complete_or_explicit_null` | CDC golden qualification |
| `CDC-03` | `SDD-CDC-01`、`SDD-PROV-01` | `tests/test_cdc_pdf_importer.py::test_cdc_03_locator_keeps_artifact_and_both_page_numbers` | immutable audit bundle＋locator readback |
| `CDC-04` | `SDD-PUB-01`、`SDD-FRESH-01` | `tests/test_official_adapters.py::test_cdc_04_pending_candidate_keeps_serving_approved_build` | 三個 `CDC-R1-*` gates |
| `CDC-05` | `SDD-OBS-01` | `tests/test_mcp_stdio.py::test_cdc_05_not_found_keeps_scope_and_verification_boundary` | stdio JSON＋tool description inventory |
| `NHI-01` | `SDD-NHI-01`、`SDD-PROV-01` | `tests/test_nhi_importer.py::test_nhi_01_exact_code_preserves_raw_fields_and_locator` | `NHI-G-001..010`；`NHI-R1-SOURCE`、`NHI-R1-SCHEMA` |
| `NHI-02` | `SDD-NHI-01` | `tests/test_official_adapters.py::test_nhi_02_name_and_reviewed_alias_search_returns_scoped_candidates` | alias／scope bundle hash；`NHI-R1-SCOPE` |
| `NHI-03` | `SDD-NHI-01` | `tests/test_nhi_importer.py::test_nhi_03_zero_points_and_full_note_are_preserved` | NHI golden qualification |
| `NHI-04` | `SDD-NHI-01` | `tests/test_mcp_stdio.py::test_nhi_04_as_of_is_explicitly_unsupported_in_p1_1` | `result_status=historical_query_unsupported`、0 items |
| `NHI-05` | `SDD-NHI-01` | `tests/test_nhi_importer.py::test_nhi_05_sentinel_stays_raw_inference_and_not_permanent` | sentinel golden＋`NHI-R1-SOURCE` |
| `TFDA-01` | `SDD-TFDA-01`、`SDD-PROV-01` | `tests/test_tfda_importer.py::test_tfda_01_permit_group_preserves_every_source_row` | `TFDA-G-001..010`；`TFDA-R1-SOURCE`、`TFDA-R1-SCHEMA` |
| `TFDA-02` | `SDD-TFDA-01` | `tests/test_official_adapters.py::test_tfda_02_temporal_fields_are_evaluated_without_validity_claim` | injected-clock matrix＋evaluated_as_of |
| `TFDA-03` | `SDD-TFDA-01` | `tests/test_tfda_importer.py::test_tfda_03_applicant_and_manufacturing_roles_never_merge` | TFDA golden qualification |
| `TFDA-04` | `SDD-TFDA-01` | `tests/test_official_adapters.py::test_tfda_04_reviewed_and_candidate_searches_have_distinct_scopes` | `TFDA-R1-IVD`＋coverage report |
| `TFDA-05` | `SDD-TFDA-01` | `tests/test_official_adapters.py::test_tfda_05_conflict_missing_and_legacy_codes_remain_candidates` | ambiguous／unknown golden cases |
| `LAB-01` | `SDD-ODS-01` | `tests/test_cdc_ods_importer.py::test_lab_01_certificate_disease_purpose_method_rows_remain_distinct` | `ODS-G-001..010`；`ODS-R1-STRUCTURE` |
| `LAB-02` | `SDD-ODS-01`、`SDD-PROV-01` | `tests/test_cdc_ods_importer.py::test_lab_02_raw_twelve_fields_and_row_locator_are_returned` | ODS golden qualification |
| `LAB-03` | `SDD-ODS-01` | `tests/test_cdc_ods_importer.py::test_lab_03_only_declared_merge_spans_inherit_anchor_values` | `ODS-R1-STRUCTURE` |
| `LAB-04` | `SDD-ODS-01` | `tests/test_cdc_ods_importer.py::test_lab_04_pt_review_date_text_and_blank_round_trip` | `ODS-R1-CONTENT` |
| `LAB-05` | `SDD-FRESH-01`、`SDD-OBS-01` | `tests/test_mcp_stdio.py::test_lab_05_unknown_official_cadence_is_not_reported_as_daily` | ODS status JSON＋tool boundary |
| `UX-01` | `SDD-ISO-01` | `tests/test_mcp_stdio.py::test_ux_01_data_mode_and_sample_warning_are_visible` | sample／official stdio transcripts |
| `UX-02` | `SDD-PROV-01` | `tests/test_models.py::test_ux_02_traceability_distinguishes_snapshot_from_upstream_reproducibility` | pilot task `PILOT-TRACE-01`＋artifact availability evidence |
| `UX-03` | `SDD-OBS-01` | `tests/test_models.py::test_ux_03_protocol_collects_no_patient_or_secret_fields` | versioned pilot protocol/result hashes；`REL-G5` |

`SDD-SEC-01` 的 trust-boundary tests 與 `SDD-PUB-01` 的 atomic/concurrency tests 是所有 official acceptance 的 `REL-G1` 前置證據。一項需求只有在 node 通過、其 JSON evidence 存在且 hash 可重算、golden／review gate 完整及 MCP 回傳通過時才可關閉；單獨 parser green 不算完成。

### 5.1 SDD verification matrix（14／14）

下列是 14 個 SDD ID 的 canonical verification interfaces；目前已執行的 node 由 acceptance registry 標為 executable，其餘仍為 **PLANNED**。每個 SDD ID 只能由表內 node 與 evidence 關閉，不能因相關章節已寫完就視為通過。

| SDD ID | Canonical verification node／command | 必要 evidence／gate |
| --- | --- | --- |
| `SDD-ISO-01` | `tests/test_mcp_stdio.py::test_sdd_iso_01_official_never_falls_back_to_sample` | sample／official stdio transcript；`REL-G1` |
| `SDD-PUB-01` | `tests/test_snapshot_publish.py::test_sdd_pub_01_availability_descriptor_is_atomic_under_concurrency` | generation／parent snapshot／two-process trace；`REL-G1` |
| `SDD-FAIL-01` | `tests/test_freshness.py::test_sdd_fail_01_operational_integrity_is_data_unavailable` | fail-closed report／unchanged current hash；`REL-G1` |
| `SDD-PROV-01` | `tests/test_models.py::test_sdd_prov_01_every_item_and_child_has_typed_row_evidence` | manifest／item locator readback；`REL-G1`／`REL-G2` |
| `SDD-FRESH-01` | `tests/test_freshness.py::test_sdd_fresh_01_internal_states_map_to_prd_freshness` | operational status fixture／public mapping report；`REL-G1` |
| `SDD-NHI-01` | `tests/test_nhi_importer.py::test_sdd_nhi_01_contract_bundle` | NHI qualification certificate；`NHI-R1-SOURCE`／`NHI-R1-SCHEMA` |
| `SDD-TFDA-01` | `tests/test_tfda_importer.py::test_sdd_tfda_01_contract_bundle` | TFDA truth-table report／registry hash；`TFDA-R1-IVD` |
| `SDD-CDC-01` | `tests/test_cdc_pdf_importer.py::test_sdd_cdc_01_contract_bundle` | CDC official qualification certificate；`CDC-R1-LAYOUT`／`CDC-R1-CONTENT` |
| `SDD-ODS-01` | `tests/test_cdc_ods_importer.py::test_sdd_ods_01_contract_bundle` | ODS qualification certificate；`ODS-R1-STRUCTURE`／`ODS-R1-CONTENT` |
| `SDD-SEC-01` | `tests/test_security_boundaries.py::test_sdd_sec_01_trust_boundary_matrix` | bounded-stream／path containment report；`REL-G1` |
| `SDD-OBS-01` | `tests/test_models.py::test_sdd_obs_01_status_and_logs_exclude_query_content` | redacted sync／status report hash；`REL-G1`／`REL-G5` |
| `SDD-AUDIT-01` | `tests/test_snapshot_publish.py::test_sdd_audit_01_subject_digest_binds_all_evidence` | immutable audit paths／hash readback；source gates |
| `SDD-API-01` | `tests/test_mcp_stdio.py::test_sdd_api_01_public_contract_resource_matches_discovery` | `public-contract-v1.json` hash／list_tools transcript；`REL-G1` |
| `SDD-QUAL-01` | `tests/test_cdc_pdf_importer.py::test_sdd_qual_01_liteparse_identity_and_resource_resolution` ＋第 9.2 節 CLI | out-of-tree wheel／missing／mismatch／success preflight；`CDC-R1-LAYOUT` |

Acceptance reporter 必須對 14 個 SDD ID 輸出 `reports/acceptance/<release-id>/<SDD-ID>.json`，內含 collected node count、exit code、evidence path／hash 與 gate disposition。Node 不存在、0 collected、skip、xfail、**PLANNED** 或只有文件審查，一律不得記為 passed。

## 6. 共用 snapshot、stale 與發布測試

### 6.1 Public status contract

Public MCP JSON 以 PRD 為唯一真源；SDD 的 internal pipeline enum 必須透過一張 versioned mapping table轉成下列欄位，禁止直接把 internal value 序列化出去：

```text
data_mode = sample | official_snapshot
availability = available | data_unavailable
serving_validation_status = not_applicable | passed
serving_review_status = not_applicable | approved
latest_candidate_status = none | validating | review_pending | rejected | publishable
result_status = ok | not_found | data_unavailable | invalid_request |
                historical_query_unsupported | candidate_matches_available |
                deprecated_unsupported
stale = strict boolean
stale_reason_codes[] = upstream_check_overdue | upstream_verification_failed |
                       newer_candidate_pending_review | newer_candidate_rejected |
                       newer_candidate_awaiting_publish
coverage_status = complete | review_incomplete | unknown
```

`tests/test_models.py` 必須從 package resource `src/taiwan_lab_mcp/contracts/public-contract-v1.json` 讀取 public enums，以 `extra=forbid` model 與全組合參數化測下列 matrix；任何未列組合拒絕序列化：

| 情境 | availability／serving | candidate／stale | 合法 result |
| --- | --- | --- | --- |
| sample 有／無命中 | `available`、`not_applicable`／`not_applicable` | `none`、`false`、空 reasons | `ok`／`not_found`，另有 `sample_only=true` |
| official serving 正常 | `available`、`passed`／`approved` | `none`、`stale=false`、空 reasons | `ok`／`not_found` |
| official 舊版服務且新版待審／被拒／待發布／上游失敗 | `available`、`passed`／`approved` | 對應 candidate；`stale=true` 且至少一個對應 reason | `ok`／`not_found`／candidate tool 的 `candidate_matches_available` |
| official 無 serving build | `data_unavailable`、`not_applicable`／`not_applicable` | candidate 可揭露；`stale=false`、空 reasons | `data_unavailable` |
| NHI 帶非 null `as_of` | 依目前 serving 狀態 | candidate 欄不變 | `historical_query_unsupported`、0 items、`historical_truth_supported=false` |
| `compare_products` | 任何 mode | 不改來源狀態 | `deprecated_unsupported`、0 items |
| 參數不合法 | 任何 mode | 不改來源狀態 | `invalid_request`、0 items |

特別測 `candidate rejected + serving old approved`：result 仍是 `ok`／`not_found`，`serving_*` 仍指舊版，`latest_candidate_status=rejected`，`stale_reason_codes` 含 `newer_candidate_rejected`。無 serving build 時不能稱 stale，因為根本沒有正在服務的過舊資料。

Internal-to-public mapping fixture 必須鍵定 SDD 的 deterministic table：

| Internal state | Public mapping |
| --- | --- |
| serving 不存在或 sample | serving validation／review 均 `not_applicable` |
| serving manifest automated validation passed 且 required reviews approved | `passed`／`approved`；其他組合不得 serve |
| 無 non-serving candidate | `latest_candidate_status=none` |
| discovered／fetched／raw_verified／parsed／validated | `latest_candidate_status=validating` |
| internal review pending | `latest_candidate_status=review_pending` |
| approved 但尚未切 current | `latest_candidate_status=publishable`，並含 `newer_candidate_awaiting_publish` |
| validation failed／review rejected／build failed 且為 latest candidate | `latest_candidate_status=rejected` |
| store ready／sample | `availability=available` |
| current availability descriptor／manifest／DB／audit 失效或無 serving | `availability=data_unavailable` |

每個 internal state 只能有一組 public 輸出；一對多、未映射值或直接外洩 internal enum 都讓 contract test 失敗。

舊 `status` 欄已不屬於 public contract，必須由 `extra=forbid` 拒絕，不能保留第二套 enum。`stale=false` 必須有空 reason array；`stale=true` 必須至少一個合法 reason。所有錯誤 response 固定 error code／安全 note，不得帶 traceback、absolute local path 或 candidate 暫存內容。

Public ToolResult、status、safety 與 item models 全部 `extra=forbid`。Contract mutation tests 逐一加入 legacy／同義 key：`status`、`validation_status`、`review_status`、`candidate_status`、`stale_reason`、`last_publish_at`、`official_data_loaded`、`not_a_specimen_storage_instruction`、`not_pre_submission_specimen_storage`、`not_a_receiving_guarantee`；也測未列 enum 值與不明 extra key。這些 case 必須 schema validation fail，不得忽略、改名或帶入 public JSON。僅能經由明示 versioned migration 讀取舊檔，migration 輸出仍必須通過 current public contract。

同一 mutation suite 也必須拒絕 legacy `content_age_warning`。`QueryResultV1` 對 `source_status`、`coverage_detail`、`evaluated_as_of`／`evaluated_timezone`、`replacement_operation` 與 sample nullable provenance IDs 做 exact-key／allowed-combination tests；source-specific record／locator schemas 直接由 packaged `public-contract-v1.json` 參數化，不在測試另手抄一份。

`get_data_status` 另作 exact-key equality：top-level 只有 `contract_version="public-contract-v1"`、`data_mode`、`sources`，四個 source IDs 各出現一次；每個 source object 的 required／nullable fields、`availability_reason_code`、`last_check_at`、`last_successful_check_at`、唯一 publish timestamp `last_successful_publish_at`、content-age 欄位與 allowed combinations 全部由同一 fixture 參數化。少一欄、多一欄、重複 source 或 unavailable 卻 `stale=true` 都失敗。sample case 必須 assert `availability=available`、兩個 serving ID 均為 null、兩個 serving status 均為 `not_applicable` 且含 synthetic warning。

### 6.2 Identity、artifact 與 row provenance

至少涵蓋下列案例：

- `raw_revision_id` 由 ordered artifact hashes 與 discovery metadata hash 計算；`curated_build_id` 由 raw revision、application、parser、schema、normalization、rule bundle 及 extractor output hashes 的 canonical fingerprint 計算。
- `tests/test_snapshot_publish.py::test_build_identity_canonical_vectors_are_second_person_reproducible` 用版本化 `RawRevisionFingerprintV1`／`CuratedBuildFingerprintV1` vectors 驗證 project-owned `canonical_json_bytes_v1`：只接受 object／array／UTF-8 string／integer／boolean／null，key 依 Unicode code point 排序，array 維持 schema order，無 BOM／換行／Unicode normalization，float／NaN／Infinity 拒絕。第二個 process 從 repo 外 wheel 重算的 canonical bytes 與 hash 必須相同。
- Raw revision mutation matrix 證明 artifacts 依 `(role, artifact_id)` 排序，URL 只做已核准的 scheme／host／fragment 處理且不重排 query；`fetched_at`、HTTP Date、ETag／Last-Modified、run ID、retry／redirect trace 與本機路徑改變不影響 identity，但 source、授權、official version 或 artifact role／URL／bytes／hash 改變必須改 ID。
- `application_build_sha256` 固定為已安裝 `taiwan-laboratory-mcp` distribution inventory hash，不是版本字串、Git tree 或 wheel archive hash。Out-of-tree wheel case 先驗 RECORD hash／size，再 hash 所有 `taiwan_lab_mcp/**` 及 dist-info `METADATA`／`WHEEL`／`entry_points.txt` 實際 bytes 的 sorted canonical inventory；排除 RECORD、`direct_url.json`、INSTALLER、REQUESTED、`__pycache__`／`.pyc`。RECORD mismatch、缺 package resource、editable 或 direct-directory install 一律 `APPLICATION_BUILD_IDENTITY_MISSING`，只可建 development staged attempt，不得產生 reviewable／approved build。
- 只有完整 fingerprint 相同、final build 已通過 readback 且 audit evidence 齊全才可 skip。same raw／different rule、same raw／parser fix、same raw／different extractor output 都必須產生新 immutable curated build；failed attempt 使用不同 `build_attempt_id`，修正後可重跑相同目標 fingerprint。
- official record 必須有 `curated_build_id`、來源入口與實際下載 URL、含時區的 `retrieved_at`、artifact SHA-256、schema／parser／rule version、license、source locator 與 serving status。
- 每個 artifact reference 必須有 `artifact_id`、role、`storage_scope`、data-root-relative path、URL、SHA-256 與 `local_artifact_available`。publish/readback 測試要拒絕絕對路徑、root escape、hash mismatch 與重複 artifact id。
- publisher date 未提供時保留 `null` 並附原因，不得填入下載日期；record 的 build／來源欄位必須與 manifest 一致。
- typed item envelope 中每個 source row 或 child row 都要有 `artifact_id + source_row_sha256 + locator`。TFDA grouped manufacturing child、CDC manual row 與 ODS method row 逐一驗證，top-level provenance 不能取代 row provenance。
- raw value 與 normalized value 並存；normalize 後再算 source row hash 的實作應失敗，row identity 必須由定義好的 canonical raw row 產生。
- `sample_only` 必須是 strict boolean；`sample` record 只能是 synthetic provenance，official record 不能是 synthetic。
- 查無資料表示「此 snapshot 未命中」，不能推成官方不存在、不給付、不認可或非 IVD。
- Traceability 分成 `snapshot_traceable` 與 `currently_reproducible_from_upstream`。只有本機合法保存 raw 且 hash 通過，或當期上游 artifact hash 相同時，後者才可為 true；只有 locator 不算官方現站可重現。

### 6.3 Schema drift

各來源都使用同一組 drift 行為測試，但 header 本身留在來源 adapter：

| 變化 | 預期結果 |
| --- | --- |
| 缺欄、改名、重複欄 | block；產生 drift report；current 不變 |
| 新增未知欄 | staged 保留但 block pending review，不得默默忽略 |
| 只改欄位順序 | 可依名稱解析，但未核准前不發布 |
| 解碼錯誤、NUL、malformed record、0 rows | block |
| row count 相對前版超過啟動門檻 | review pending；門檻是產品設定，不標成官方規則 |
| nullable 欄正常波動 | report warning；除非跨越已核准門檻，不直接 hard fail |

測試以「前一個 fixture baseline」做相對比較，不把 2026-09-13 的 6,173、104,619 或任何一次 SHA-256 永久寫成未來資料必須相同。

### 6.4 Stale、content age 與 fail-closed

使用 injected clock，不 monkeypatch 全域系統時間。測試至少包含：

- 同 raw hash 且完整 curated fingerprint 也相同時，只更新成功 check；rule、parser、schema、normalization、application 或 extractor output hash 任一改變時必須重建。
- NHI 超過兩個宣告週期未成功核對時標 stale；是否超過 7 日 hard stop 依 owner 設定測兩種 policy。
- TFDA `stale` 只依最後完整成功 upstream verification 與已知新版待審判斷。CSV 沒有 embedded date；`portal_metadata_modified_at`、nullable `embedded_data_updated_on` 與 `max_record_changed_on` 只作證據。若產品顯示 10／14 日內容年齡，欄位必須是獨立的 `content_age_status`，不得改寫 stale 或稱為官方 SLA；mutation test 拒絕 legacy `content_age_warning`。
- CDC stale 依「多久未成功核對」及「已看到新版但尚未核准」判斷，不依 PDF 年齡自行宣稱內容過期。
- 新檔失敗時可繼續服務舊的 approved snapshot，但 public 只回最後成功時間與固定 reason code；具體失敗階段留在 immutable check evidence。沒有舊 snapshot 時回 `availability=data_unavailable`。
- 任一錯誤路徑都不得讀 sample、staged 或 quarantine 資料。
- `CurrentAvailabilityV1` 將 serving pointer 與 operational status 置於同一 descriptor，在同一 per-source lock／CAS 內單次 replace；runtime 每個 operation 只讀一次 descriptor。完整性使用封閉參數化 matrix：descriptor 不存在且 publish-event index 無成功事件，或 descriptor 完整但無 serving build → `no_serving_snapshot`；前者固定 candidate none，後者可揭露完整 descriptor 的 candidate。Descriptor 不存在但已有成功 publish event、serving manifest、audit 或 DB 缺失／損壞／hash mismatch → `serving_integrity_failure`＋internal `CURRENT_POINTER_INTEGRITY`；candidate/check operational section schema、hash、source 或 generation mismatch → `operational_status_integrity_failure`＋internal `OPERATIONAL_STATUS_INTEGRITY`。兩種 integrity failure 固定 `latest_candidate_status=none`、`latest_candidate_id=null`。全部回 `availability=data_unavailable`、`result_status=data_unavailable`；每案 assert descriptor bytes／generation 不變、`stale=false`、不 fallback sample，也不以 stale 代替 integrity failure；其他來源仍可獨立服務。

### 6.5 Quarantine 與 coverage

P1.1 預設不允許 partial publish。任何會移除 source row、截斷 TFDA 一對多製造關係、破壞 CDC 列關係或錯填 ODS merge span 的 row error 都 block 整批；`quarantined_row_count > 0` 時 publisher 必須拒絕，current 不變。TFDA 分類 code 無法解析時保留完整一般許可列，將 IVD state 設為 unknown，不可 quarantine 原列。

使用每來源「單一壞列夾在合法列中」fixture，assert 不會產生看似 `coverage_status=complete` 的 snapshot。P1.1 只允許 `complete`、`review_incomplete`、`unknown`；partial publish 不在契約內。未來若 owner 另開 partial publish，必須新增 PRD acceptance、逐 query 警示、排除列數／原因與 source-specific gate，不能只放寬測試。

### 6.6 Immutable validation、review 與 golden evidence

Final evidence 固定放在：

```text
curated/<source>/<curated-build-id>/audit/validation.json
curated/<source>/<curated-build-id>/audit/qualification-candidate.json
curated/<source>/<curated-build-id>/audit/reviews/<gate-id>.json
curated/<source>/<curated-build-id>/audit/golden-qualification.json
```

Manifest 以 data-root-relative path＋SHA-256 引用每檔。Review schema v1 採 `extra=forbid`，至少含 `gate_id`、decision、`subject_digest`、reviewer id、`identity_assurance`、reviewed_at（含時區）、protocol name/version 與 evidence refs。Pre-review `QualificationCandidateV1` 保存 case IDs、逐案結果、`automated_status`與`synthetic_ci_status`；`subject_digest` 綁定 ordered artifacts、raw revision、curated DB、application／parser／schema／normalization／extractor／rule hashes、validation hash 與 qualification candidate hash。每份 review 都必須綁定同一 `subject_digest`。Reviews 完成後，publisher 才產生 final `QualificationCertificateV1` 到 `golden-qualification.json`，其中引用 subject digest、candidate report hash 與所有 accepted review hashes，並設 `official_qualification_status=approved`。Final certificate 與 review hashes 不得再回饋 subject digest，以免形成 hash 循環。

Publisher 在 lock 內重新計算 subject digest，要求 manifest 的 `required_gates == completed_gates`，且每個 completed record decision=approved；未完成的 domain capability 放在獨立 `capability_reviews`，狀態必須反映 coverage／feature 未核准。缺 serving gate、未知或未宣告 gate、digest 不符、evidence path 逃逸、evidence hash 被換掉或 reviewer protocol 過期都拒絕。`identity_assurance` 只接受 `local_asserted`或`cryptographically_signed`；`reviewer_id` 若只是本機稽核名稱必須用 `local_asserted`，不可被 UI 稱為密碼學簽章。

Source gates固定為：NHI 的 `NHI-R1-SOURCE`、`NHI-R1-SCHEMA`、`NHI-R1-SCOPE`；TFDA 的 `TFDA-R1-SOURCE`、`TFDA-R1-SCHEMA`、`TFDA-R1-IVD`；CDC 手冊的 `CDC-R1-SOURCE`、`CDC-R1-LAYOUT`、`CDC-R1-CONTENT`；ODS 的 `ODS-R1-SOURCE`、`ODS-R1-STRUCTURE`、`ODS-R1-CONTENT`。共同發布授權記錄用 `PUB-R1-OWNER`。PRD release gate 只用 `REL-G1`～`REL-G5`，publisher 不接受裸 `G1`／`G5` 字串。

| Source evidence | 對應 release gate |
| --- | --- |
| 各來源的 `R1-SOURCE`＋`R1-SCHEMA`／`R1-LAYOUT`／`R1-STRUCTURE` | `REL-G2` source contract／qualification |
| `NHI-R1-SCOPE`、`TFDA-R1-IVD`、`CDC-R1-CONTENT`、`ODS-R1-CONTENT` | `REL-G3` domain review |
| `PUB-R1-OWNER` | `REL-G4` attribution／distribution authorization；不能代替 `REL-G5` pilot |

Serving／feature gate matrix 也要做 contract test：NHI 全表 current lookup 需 `NHI-R1-SOURCE + NHI-R1-SCHEMA + PUB-R1-OWNER`，缺 `NHI-R1-SCOPE` 仍可服務但 `coverage_status=review_incomplete`；TFDA 一般許可、candidate search與已逐碼核准的 included rows 需 `TFDA-R1-SOURCE + TFDA-R1-SCHEMA + PUB-R1-OWNER`，`TFDA-R1-IVD` 未完整時 `search_reviewed_ivd` 只能回已核准列且 coverage 為 review incomplete；CDC PDF 需三個 CDC gates＋`PUB-R1-OWNER`；ODS 需三個 ODS gates＋`PUB-R1-OWNER`。`REL-G3` 要宣告整體 P1.1 完成時，仍要求所有 domain gates通過。

### 6.7 Read-only SQLite runtime

Builder 測試要求 transaction 完整 commit／checkpoint／close，固定 journal policy，關閉後沒有 `-wal`、`-shm` 或 `-journal`，再 hash `data.sqlite3`。Runtime 使用安全建構的 SQLite URI `mode=ro`；只有 hash readback 通過且 DB 已永久 immutable 時才加 `immutable=1`，並設定 `PRAGMA query_only=ON`、停用 extension loading、支援時 `trusted_schema=OFF`，所有 query 參數化。

`tests/test_snapshot_publish.py` 至少包含：INSERT／DDL／ATTACH write denied、旁檔不存在、DB／schema tamper 被拒絕、extension 無法載入、惡意 query 字串只作參數，以及 runtime 已開啟 build A 時 current 切到 B 仍完成讀 A、新連線才讀 B。這些測試證明 read-only 與一致性，不宣稱相鄰 hash 能防止有 data-root write 權限的惡意本機使用者；部署 evidence 另驗 runtime principal 唯讀、publisher principal 可寫。

### 6.8 Atomic、concurrent publish 與 recovery

在 `tmp_path` 預先建立 approved snapshot A 與 current `CurrentAvailabilityV1`，再對 download、verify、parse、normalize、validate、golden、review、write、descriptor replace 每一階段注入例外。每個案例都 assert：

1. current availability descriptor 的原始 bytes、hash 與 generation 未改；
2. runtime 仍只讀 A，或在無 A 時 unavailable；
3. 失敗 artifact 只出現在 temp／staged／quarantine；
4. sync report 記錄 stage、error code、時間與候選 snapshot，不含秘密或不必要的絕對暫存路徑。

成功案例 assert 新 build B 先完整落盤且驗證，再單次切換同時含 serving identity、`last_successful_publish_at` 與 operational state 的 descriptor；runtime 在切換前後只能看到完整 A 或完整 B，不能看到 pointer=B／status=A 或部分 B。每來源 publish 使用 exclusive lock；descriptor 含單調 `generation` 與 `parent_snapshot_id`，lock 內重新 read current 並做 compare-and-swap。current 已變時舊候選必須拒絕，不可 late publish 造成倒退。

Concurrency suite 以兩個 process＋barrier 重現 A／B 同時準備、B 先切換、A 晚到；assert 最終 generation 單調、A 收到 conflict、current 仍是 B。另測 lock timeout、process 在 descriptor temp fsync 前後崩潰、replace 完成但 readback 前崩潰、殘留 temp／lock recovery。POSIX qualification 驗 parent directory fsync；Windows qualification驗實際採用的 replace primitive、重新開檔 readback 與啟動 recovery，不宣稱超出實測的斷電 durability。

Rollback 走獨立 command，必填 target approved build、expected generation、reason、actor 與時間；測試證明它產生新的 generation／audit record 並原子切換新 descriptor，不可偽裝成一般 publish或改寫舊 manifest。

## 7. NHI 測試案例

### 7.1 Parser 與型別

- exact 7-column UTF-8 BOM CSV 可解析；合法 UTF-8 無 BOM 只產生 warning；非 UTF-8、replacement character 或重複 header 阻擋發布。
- 以標準 `csv` parser 處理 quoted CRLF；含換行的中文名稱仍是一筆 record。
- code 永遠是字串，`09006C` 與其他前導零代碼往返不變；不可用單一六碼 regex 拒絕 2–7 碼合法來源值。
- points `0` 是整數 0，不是 null；負數、小數、貨幣符號、空白或無法解析值依契約 quarantine／block。
- `YYYYMMDD` 使用 Gregorian strict parser；2 月 29 日、月底、無效月份及 start > end 都有 table-driven case。
- `29101231` 同時保存 raw date、parsed date 與 `possible_open_end_sentinel=true`；測試禁止將它輸出成「永久有效」。

### 7.2 查詢語意

- `09006C` fixture 可 exact lookup，結果含原 code、points、日期、source row number／hash 與 snapshot provenance；fixture 內的數值是測試 snapshot 證據，不是跨版本產品常數。
- 同一 code 若在當期檔出現兩列，整批進 review pending，不做 last-write-wins。P1.1 不建立歷史版本邏輯，也不以目前列的日期區間推論過去真實點數。
- `get_points(code, as_of=null)` 是 current serving snapshot 的 exact lookup。Request validation 順序固定先驗所有參數：`as_of` 的 wrong type、空字串、malformed 或不存在的 ISO calendar date 一律 `invalid_request`、0 items；只有合法 ISO date 的非 null 值回 `historical_query_unsupported`、`historical_truth_supported=false`、0 items，且不查 code 或 source availability；null 才繼續依 availability 與 exact code lookup。Stdio 固定四案：`"2026-09-13"`、`""`、`"2026-02-30"` 與 integer；不得比較 current row 日期、附上現行 points 冒充參考，或因查詢日期落在原始欄位內就回答歷史值。
- `search_payment_items` 對全表代碼、中文、英文與已核准 alias 回候選，每列帶 `matched_by`、`scope_status` 與 basis。`scope_status` 只接受 `in_scope`／`out_of_scope`／`review_pending`；`NHI-R1-SCOPE` 未完成時 `coverage_status=review_incomplete`，不得宣稱 laboratory completeness。搜尋結果每列為 `nhi_fee_summary` 摘要（備註前 60 字、全文字數、是否截斷），`limit=6` 回 `invalid_request`；exact-code 查詢仍回完整 `NHIRecord`（`tests/test_nhi_search_summary.py`）。舊 `search_lab_code` 是相同搜尋的 wrapper；`get_payment_rule(query)` 的 wrong type／trim 後空字串回 `invalid_request`，合法非空但沒有 exact code 回 `not_found`，不套固定碼長 regex；命中時只回備註原文與 locator，皆由 stdio contract 鎖定。
- Alias bundle 每筆必須含 alias raw、code、來源、locator、rule version、review status 與 canonical hash；未核准 alias 不參與查詢。相同 normalized alias 命中多 code 時全部回傳，排序固定為 exact code、exact official name／approved alias、prefix、substring，再依 code 與 `source_row_sha256`；回 `total_matches`、`limit`、`offset`、`returned_count`、`truncated`，不能任意取第一筆。
- 中文／英文名稱的搜尋 normalization 不覆寫官方名稱；英文空白不能自動翻譯補值；備註不得截斷。

## 8. TFDA 測試案例

### 8.1 ZIP、schema 與 raw row

- 即使 MIME 宣告 CSV，payload 為 ZIP 時依 magic bytes 正確處理；HTML 錯誤頁、截斷 ZIP、非 ZIP payload 均 block。
- ZIP 只允許一個預期副檔名的非目錄 entry；拒絕 `..`、絕對路徑、UNC、drive path、symlink-like entry、多 entry、超過 64 MiB 壓縮檔、256 MiB 單一／總 actual streamed uncompressed bytes 或壓縮比 30。Declared size 欺騙與剛好等於上限的合法 stream 都要測；不得為測試提交 256 MiB fixture，可用限制注入的 bounded stream stub。
- exact 34-column header 才能進 validate；OAS 宣告 MIME／date-time 與實際 ZIP／`YYYY/MM/DD` 的已知差異固定成 regression case。
- 所有欄先以字串讀入；許可／登錄字號、統編與級數不得自動轉數字；CSV raw 與 canonical row hash 可重現。
- 同字號多列全部保留，group lookup 回多個 manufacturing rows；source row hash 才是 row identity，許可證字號不是 unique key。

### 8.2 狀態、角色與 IVD registry

- Immutable row 只保存 `source_cancellation_status_raw`、cancellation date、valid through，不保存會隨今日失效的最終 temporal state。查詢時用 injected clock 產生 `evaluated_as_of`（Asia/Taipei）與分開的 `cancellation_recorded_in_source`／`within_validity_period_as_of`，永不合成 final state、「未註銷」、「有效許可」、販售或採購結論。`tests/test_official_adapters.py::test_tfda_02_temporal_fields_are_evaluated_without_validity_claim` 必須逐列參數化下列 cancellation truth table（status 先 trim）：

| Raw status | Parsed cancellation date | `cancellation_recorded_in_source` | Consistency warning |
| --- | --- | --- | --- |
| 空字串 | null | `false` | 無 cancellation warning；只表示來源沒有記錄 |
| 空字串 | valid date | `true` | `cancellation_date_without_status` |
| `已註銷`／`已廢止` | valid date | `true` | 無 consistency warning |
| `已註銷`／`已廢止` | null | `true` | `cancellation_status_without_date` |
| 其他非空 status | valid date 或 null | `unknown` | `unknown_cancellation_status` |
| 任何 status | invalid date | 不得 serve | candidate rejected，current 不變 |

Validity table 也逐列測：`evaluated_as_of <= valid_through` 為 `true`（到期日 inclusive），次日起為 `false`，missing／invalid 為 `unknown`；official invalid candidate 仍整批 rejected，`unknown` 僅保留給 legacy／sample 防禦。交叉 warnings 固定為：

| cancellation／validity | Required warning |
| --- | --- |
| `true`／`true` | `cancellation_recorded_within_validity_window` |
| `true`／`false` | `cancellation_recorded_and_validity_period_elapsed` |
| `false`／`false` | `validity_period_elapsed` |
| `unknown`／`true` | `cancellation_record_ambiguous` |
| `unknown`／`false` | `cancellation_record_ambiguous` 與 `validity_period_elapsed` |
| `unknown`／`unknown` | `cancellation_record_ambiguous` 與 `validity_date_unavailable` |
| 任何值／`unknown` | `validity_date_unavailable` |

相同 raw／curated build 跨日查詢會改變 `within_validity_period_as_of`，但原始列與 build id 不變。
- applicant、manufacturer、factory address、company address、country、process 保持不同欄位；manufacturer filter 不可命中只出現在 applicant 的字串，同字號多製造廠不能被壓成一筆法人。
- B.9225 在 approved registry 為 included；B.9195 與 B.9245 為 excluded。主類別 A／B／C 本身不得讓資料變成 IVD。
- Public `ivd_scope` 只接受 `included`、`excluded`、`ambiguous`、`unknown`：approved included 與 excluded／ambiguous 同時命中時為 `ambiguous`；全部 reviewed codes 皆 excluded 時為 `excluded`；缺次類別、舊制四碼、未知 code 或規則版本不明均為 `unknown`。Internal review state 可分開保存，但 `review_pending`、`not_ivd_by_reviewed_classification`、`ivd_unknown`、`ivd_candidate` 都不得出現在 public `ivd_scope`；contract mutation tests 逐一拒絕。
- `search_reviewed_ivd` 只回逐碼 approved included；相容名稱 `search_ivd` alias 到此行為。若沒有 included 但 candidate tool 可命中，回 `candidate_matches_available`，不可用空結果暗示沒有 IVD。
- `search_ivd_candidates` 回 included／ambiguous／unknown，並強制回 `coverage_status`、reviewed code 比例、舊制／缺碼列數、`total_matches`、`returned_count` 與 `truncated`；candidate 不得混進 reviewed-only 結果。名稱／效能／規格關鍵字只能召回 candidate，不能覆蓋 registry decision。
- Bounded-result contract 對 `search_disease`、`get_specimen_requirement`、`find_authorized_lab`、`get_license`、~~`find_manufacturer`~~ 各測 0、20、21 筆：無公開分頁參數時固定 `limit=20, offset=0`，第 21 筆令 `total_matches=21`、`returned_count=20`、`truncated=true`；不得無界回傳或靜默截斷。`get_lab_scope` 及其他 alias 另驗 canonical default page。~~`list_matching_license_records` 固定 `offset=0` 並依 request `limit`，P1.1 不提供下一頁。~~ `list_matching_license_records`、`find_manufacturer` 與其他搜尋 operation 依 request `limit`（1–5、預設 5，owner 2026-09-15）與 `offset` 分頁（OD-06），測 0、limit、limit+1 與最後一頁。
- ~~`list_matching_license_records` 只並列來源欄位並採穩定、非臨床排序。~~ `list_matching_license_records`（PRD TFDA-06）測：
  - 已註銷、缺分類代碼、舊制分類列都能命中。
  - 五級命中程度排序與 tie-break 固定。
  - `prefer_ivd`／`prefer_main_category` 只改順序、`total_matches` 不變。
  - `ivd_scope`／`main_category` 篩選與非法值 `invalid_request`。
  - 每列標籤與 `matched_by`。
  - 輸出不含 score／similarity 欄位。

  舊 `compare_products` 固定 `deprecated_unsupported`、0 items，不輸出比較表、相似度、優劣、可替代性或採購排序。
- 實作測試（2026-09-15）：
  - `tests/test_tfda_ivd_registry.py`：packaged registry 版本、551 碼、AI reviewer、B.9225／B.9195／B.9245、缺 reviewer 或版本不一致拒絕、重複代碼、代碼只取大寫 A–P、主類別字母、join 規則、引號與臺台正規化。
  - `tests/test_tfda_publish.py`：AI 代審的正式 build 成功並寫入 protocol `tfda-r1-ai-review`、開發安裝拒絕、reviewer 不是 protocol 指定身分拒絕、驗收題少於 10 題／比對失敗／reviewer 不符拒絕且不寫任何 curated 檔；每日檢查同檔成功、新檔保留舊版並寫差異、下載失敗標 stale、沒有服務中資料只寫報告、CLI `check tfda_devices`。
  - `tests/test_tfda_official.py`（9 列合成資料）：建置標籤、五級排序與 tie-break、偏好不改總數、篩選、8 種非法參數、翻頁到最後一頁、引號／臺台／兩個字查詢、完整單筆與多製造廠、有效日期當日與次日、truth table 9 列、製造商不命中申請商、reviewed 與 candidate 差異、`candidate_matches_available`、搜尋 `limit=6` 拒絕、`find_manufacturer` 翻頁、狀態與顯名、竄改資料庫不服務。
- registry 未含 reviewer、reviewed_at、官方頁碼／版本、source hash 或 rule version 時，不能成為 production-approved registry。

## 9. CDC PDF 與 ODS 測試案例

### 9.1 PDF layout contract

PDF extraction 與資料語意解析分層測試。CI 的 parser unit test 使用最小化、已核准的 synthetic layout JSON／cell fixture；完整 PDF 只存在忽略版控的 `data/raw`，由 source qualification job 處理，不能稱為 checked-in fixture。Synthetic CI pass 與 official qualification approval 必須是報告中的不同欄位。

至少涵蓋：

- 手冊與修訂表 title／版本／核定日期一致；缺一份、版本衝突或附件變 HTML 時 block。P1.1 official publish 固定 `--no-ocr`且禁止 OCR 資料發布；缺文字層只可產生 OCR staged candidate。未來若要發布 OCR，必須先修訂 PRD／TDD，再加入 OCR engine／model／options／output hash／bbox lineage 與 100% row／cell review；本版不用 review 繞過禁令。
- 依 bounding box 與 table header lineage 重建列；跨頁續列沒有可靠表頭時進 quarantine，不能猜欄位。
- 同疾病的不同 specimen、purpose、collection timing、volume／container、transport、retention、notes 各自維持同一列關係；組合測試證明不會做 Cartesian product。
- 對外固定使用官方欄名「應保存種類（應保存時間）」並回 `not_pre_submission_storage=true`；不得出現泛稱 storage／保存條件。運送溫度與時間只留在「送驗方式」／注意事項原文，感染性物質分類與 P620／P650 文字保持同一條件。
- 第 2 章採檢規定與第 7 章送驗地點／檢驗方法分成不同 entity；第 7.7、7.9 的不同表格另走各自 schema，不在 extraction 階段直接 join。
- provenance 同時保存 PDF 實體頁與印刷頁；末頁 `pdf_page=130`、`printed_page=120` 及文件顯示共 119 頁的矛盾，仍能被定位且不能只留單一頁碼。
- 新版只可在 row diff、變更列全檢、未變更列抽樣與醫檢 reviewer gate 完成後 approved；`review_pending` 不可切 current。

### 9.2 CDC official source qualification

下列流程是 **PLANNED**；`taiwan-lab-data qualify cdc_specimen_manual` CLI 尚未建立前不可執行，也不可被 release evidence 記為通過。實作後 Windows PowerShell 的 canonical qualification 為：

```powershell
$env:PYTHONIOENCODING = 'utf-8'
$rawRevision = '<raw-revision-id>'
$dataDir = (Resolve-Path -LiteralPath 'data').Path
taiwan-lab-data qualify cdc_specimen_manual `
  --raw-revision-id $rawRevision `
  --extractor liteparse `
  --extractor-version 2.0.0 `
  --no-ocr `
  --data-dir $dataDir `
  --json
```

Qualification 固定要求 LiteParse `2.0.0`，且只從 `importlib.resources.files("taiwan_lab_mcp").joinpath("qualifier_specs", "liteparse-2.0.0.json")` 讀取 spec，不得 repo-relative fallback。`tests/test_cdc_pdf_importer.py::test_sdd_qual_01_liteparse_identity_and_resource_resolution` 在 repo 外 wheel 環境驗證該 exact package/path，並核對 npm package name／version／dist integrity、spec-listed bundle hashes 與 approved arguments。Windows 只用 `shutil.which("lit.cmd")`，其他平台用 `shutil.which("lit")`，再由 npm global root 回查 package metadata；`@llamaindex/liteparse@2.0.0` 是只影響 CDC 新 candidate qualification 的 optional Node prerequisite，不是 Python runtime 依賴。缺失或不符 exit `4`，不建立 reviewable build，但不得中斷已核准 CDC serving snapshot 或其他三個資料集。

CLI 內部對兩份 PDF 執行 parse，並將 project-owned `CdcLayoutV1` 與 `qualification-candidate.json` 寫入 staged attempt。Candidate 保存 LiteParse identity、完整 argv（不含本機 absolute root）、兩份 PDF、raw output 與 normalized layout hashes、schema version、頁數、文字層 coverage、row／table counts、quarantine、golden 結果與 exit status。Extract、schema 及 golden candidate 成功才 exit `0`，extractor identity／extract／schema 失敗 exit `4`，不建立 reviewable build。Exit `0` 只代表 pre-review candidate 可供審查，不代表 official qualification approved。Source reviews 通過後，publisher 建立 immutable `audit/golden-qualification.json`；active subject 缺 approved certificate 時 publish exit `5`。

`CDC-R1-SOURCE` 綁兩份 PDF，`CDC-R1-LAYOUT` 綁 layout outputs，`CDC-R1-CONTENT` 綁疾病－檢體－目的－採檢時間－送驗方式－應保存種類關係。第一個 official build 沒有可信前版，全部 rows 都 review；後續全部 changed／unlisted-change rows 必查，未變更列按 entity＋疾病章節分層，以 `SHA-256(subject_digest + source_row_sha256)` 排序，每層至少 1 列，抽 `min(全部未變更列, max(30, ceil(未變更列數*5%)))`，seed 與 drawn row hashes 寫入 review evidence。Critical／major／minor 分級中，任一 critical 或未處置 major 都整批 rejected；修正 parser、rule 或人工裁決後 subject digest 改變，受影響 gates 必須重新 review。

### 9.3 ODS XML

- 先驗 ZIP magic 與根目錄 `mimetype`；只接受預期的 OpenDocument Spreadsheet，缺 `content.xml`、路徑不安全、DOCTYPE／ENTITY 或 resource budget 超標即 block。
- ODS hard limits：compressed archive 16 MiB、非目錄 entries 64、單 entry 32 MiB、actual streamed uncompressed total 64 MiB、ratio 100、`content.xml` 32 MiB、effective rows 100,000、XML elements 2,000,000、nesting depth 64、單 cell UTF-8 text 65,536 bytes、aggregate cell text 32 MiB、`number-rows-repeated` 10,000、`number-columns-repeated` 16,384。不得信任 ZipInfo declared size；以實際串流 bytes／counter fail fast，iterparse 完成 row／element 後 clear。
- 只解析指定工作表的 exact 12 欄，忽略空白 sheet；即使宣告 16,384 欄也只 materialize 前 12 欄，第 13 欄以後不得展開成巨大物件。
- 依 `number-rows-spanned` 與 `covered-table-cell` 只繼承 anchor 所涵蓋欄位；真正空白的最近年度能力試驗欄保持空白，不能 blanket forward-fill。
- `certificate_no` 與 `disease_code` 保留字串及大小寫／前導零，例如 `002a`、`19SC`；同證號多疾病、多目的、多方法保留子列，不能把資料壓成單一證號列。
- 最近年度能力試驗可為日期、`無需能力試驗` 或空白；三種狀態都可 round-trip，不強迫全部轉 date。
- ODS landing page 日期與附件版本分欄保存；固定更新頻率維持 unknown，daily polling 只能標成專案策略。
- Resource regression 包含 declared-size 欺騙、巨大 row repeat、超長 cell、過深 XML、DOCTYPE／ENTITY、總文字超限，以及每一項「剛好等於上限」的合法 fixture；拒絕時 current bytes／generation 不變。

ODS 第一個 official build 全部 rows review；後續全部 changed rows 必查，未變更列按疾病＋機構分層、以 subject digest 固定抽樣且至少 20 列。`ODS-R1-CONTENT` reviewer role 為熟悉認可制度的 `recognition_program_reviewer`，evidence 記 qualification basis。Merge 錯填、跨疾病／方法錯接或把名冊命中說成收件保證為 critical；source value／locator 錯誤為 major；任一 critical 或 unresolved major 都整批 rejected，修正後以新 subject digest重審。

## 10. Fixtures 與 golden provenance

測試資料分成三類，避免把 synthetic 測試、官方證據與 production snapshot 混在一起：

| 類型 | 建議位置 | 內容與規則 |
| --- | --- | --- |
| Synthetic edge fixtures | `tests/fixtures/synthetic/` | 人工建立的最小 CSV／ZIP／layout JSON／ODS XML；每檔註明 synthetic，不可進 official mode |
| Source contract fixtures | `tests/fixtures/contracts/` | 最小 header、metadata、HTTP headers 與已知 transport 形態；移除不必要的大型內容 |
| Reviewed golden cases | `tests/golden/<source>/` | owner／專業 reviewer 核准的輸入、預期語意欄位、來源定位與 fixture hash |

`GoldenCaseV1`、`QualificationCandidateV1` 與 `QualificationCertificateV1` 必須是 versioned、`extra=forbid` 的 machine contract。每個 countable official golden case 至少包含：

```text
case_id
source_id
source_title
official_landing_url
official_version_or_modified_at
fixture_file + fixture_sha256
artifact_id + raw_artifact_sha256
schema_version / parser_version / rule_version
source_locator（row number，或 PDF physical + printed page + bbox，或 ODS sheet + source row）
expected_fields
expected_status / expected_warnings
subject_digest
reviewer_id / identity_assurance / reviewer_role / reviewed_at / review_status
```

若 raw 因再散布限制不進 Git，case 仍必須以 `artifact_id + raw_artifact_sha256` 綁定 data root 中的 official artifact；缺 raw artifact 的 CI 只能產生 `synthetic_ci_passed=true`，不能產生 `official_qualification_approved=true`。Pre-review candidate 列出全部 case id、各自 pass/fail、總數、input／output hashes 與 active parser/schema/rule versions，不引用尚未產生的 review evidence。Post-review certificate 另存 subject digest、candidate hash、accepted review hashes、approved distinct case IDs 與 `official_qualification_status=approved`。只有個案綁定 official raw、review decision=approved，且 active subject certificate approved 的 distinct case IDs 至少 10，才能滿足 `REL-G2`。

Golden assertion 只比對會造成醫療／資料誤導的欄位、狀態與 locator；不 snapshot-test 無關的 JSON 排序、notes 文案空白或整份 10 萬列資料。官方數值變更時新增新版本 case 或由 reviewer 明確更新，不能為了讓 CI 變綠直接覆寫 expected value。Golden expected file、review 或 active transform/rule 任一改變都會改 subject digest 並使舊 approval 失效。

每來源至少 10 案：NHI 包含前導零、0 點、quoted newline、日期邊界、scope pending；TFDA 包含有效、過期、註銷、矛盾狀態、多製造廠與 included／excluded／unknown；CDC 第 2 章包含同疾病多採檢項目／目的、跨頁、雙頁碼；ODS 包含同證號多方法與能力試驗日期／文字／空白。

## 11. Property-like 與安全回歸（不新增依賴）

使用 pytest 參數化、標準函式庫 `random.Random(<fixed-seed>)`、`csv`、`zipfile`、`hashlib`、`tempfile` 與 `xml.etree.ElementTree` 產生可重現案例：

- 對 Unicode 全形／半形、大小寫、空白與換行做多組 normalization，assert raw 永遠不變、search key 可重現。
- 對月份天數、閏年、邊界日期與無效日期產生固定 matrix，assert strict parser 不 rollover。
- 對欄位刪除、增加、改名、重複與重排逐一 mutation，assert drift policy 完整覆蓋。
- 對 ZIP entry path 產生 `/`、`\`、drive、UNC、dot segment 與 Unicode 近似字元組合，assert resolve 後仍在目標暫存目錄。
- 對 publish stage 列舉故障點，assert current invariant；對多次相同輸入 assert snapshot／row hash deterministic。

任何隨機案例都固定 seed，失敗時輸出 seed 與最小必要輸入。先用 20–100 個小案例守住 invariant；若未來真的出現複雜 fuzzing 需求，再獨立評估依賴，不在 P1.1 預先加入。

## 12. 測試檔命名與執行命令

沿用 pytest，依責任拆檔，避免一個 `test_importers.py` 無限膨脹：

```text
tests/test_models.py
tests/test_snapshot_publish.py
tests/test_freshness.py
tests/test_nhi_importer.py
tests/test_tfda_importer.py
tests/test_cdc_pdf_importer.py
tests/test_cdc_ods_importer.py
tests/test_official_adapters.py
tests/test_mcp_stdio.py
tests/test_security_boundaries.py
tests/test_package_contents.py
```

測試函式使用 `test_<condition>_<expected_result>`，例如：

```text
test_nhi_zero_points_remains_integer_zero
test_tfda_duplicate_license_number_preserves_manufacturing_rows
test_cdc_same_disease_methods_do_not_cross_join_specimens
test_publish_validation_failure_keeps_current_manifest_unchanged
```

目前 tree 可執行的回歸命令為：

```powershell
$env:PYTHONIOENCODING = 'utf-8'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check src tests
.\.venv\Scripts\python.exe -m build
```

`tests/test_nhi_importer.py`、`tests/test_official_adapters.py`、`tests/test_snapshot_publish.py`、`tests/test_freshness.py` 與 `tests/test_models.py` 已建立部分 canonical nodes；其他 domain 拆分檔仍尚未建立，保持 PLANNED，不把現有集中式測試冒充成那些 node。`tests/test_package_contents.py` 已建立，現階段第一輪 focused commands 是：

```powershell
uv run pytest -q tests\test_p1_1_red.py tests\test_fetch.py
uv run pytest -q tests\test_mcp_stdio.py
```

MCP transport release check 必須另外從 repo 外的暫存 cwd、對安裝後 wheel 執行；延續 `TAIWAN_LAB_TEST_PYTHON` 指向該隔離環境的 Python。official stdio fixture 路徑使用測試專用環境變數，不能讀開發者電腦上的真實 `current`。

正式 contract／schema／rule／review protocol／qualifier resources 固定放在 `src/taiwan_lab_mcp/contracts/**`、`src/taiwan_lab_mcp/schemas/**`、`src/taiwan_lab_mcp/rules/**`、`src/taiwan_lab_mcp/review_protocols/**` 與 `src/taiwan_lab_mcp/qualifier_specs/**`，以 `importlib.resources` 載入。Out-of-tree wheel test 必須在沒有 repository cwd 的暫存目錄執行 data CLI、解析一份 NHI synthetic fixture，並讀到 `contracts/public-contract-v1.json`、hash-bound schema／rule 與 exact `qualifier_specs/liteparse-2.0.0.json`；找不到 package resource 即失敗，不可 fallback 到 repo-relative 路徑。另有 CDC qualifier preflight case 驗證 LiteParse 缺失時只讓新 qualification exit `4`，舊 CDC serving 與其他來源仍可查詢。

`tests/test_package_contents.py` 的 build 後 canonical audit command 為：

```powershell
$env:TAIWAN_LAB_ARTIFACT_DIR = (Resolve-Path -LiteralPath 'dist').Path
.\.venv\Scripts\python.exe -m pytest -q tests\test_package_contents.py
```

此測試逐一 enumerate wheel 與 sdist 並保存 inventory hash。Denylist 至少含 `data/raw`、`data/staged`、`data/quarantine`、runtime current、audit/review reports、`.env`、key／secret／token 類檔名、cache、absolute local paths；allowlist 明列 Python code、synthetic sample、approved public contract／schemas／rules／review protocols／qualifier specs 與必要文件。`public-contract-v1.json`、rule bundle 或 `qualifier_specs/liteparse-2.0.0.json` 被漏包，或 denylisted artifact 被包入，都讓 `REL-G1` 失敗。

Live source probe 不屬於一般 `pytest -q`。若日後加入 `live` marker，必須預設 skip、明確 opt-in、只下載到暫存區並輸出 manifest／report；不能在 live test 自動發布 production current。

## 13. MCP discovery、相容性與誤用測試

`src/taiwan_lab_mcp/contracts/public-contract-v1.json` 現已存在並是 operations、public enums、freshness 與 safety registries 的單一 machine-readable 真源；canonical `SDD-API-01` node、source contract equality test、freshness mapping、security matrix、audit／observability boundary 與 installed-wheel stdio 已通過。acceptance reporter 已建立，但五項 release evidence 仍未全部拆出／關閉。測試只以 `importlib.resources.files("taiwan_lab_mcp").joinpath("contracts", "public-contract-v1.json")` 讀 package resource，禁止 repo-relative fallback，再對真實 stdio `list_tools` 比對：

1. exact name 集合相等，剛好 22 個，多一個、少一個或舊名漏出都失敗；
2. 每個 parameter name、JSON type、required／nullable、default、順序、classification 與 deprecated metadata 完全相等；
3. tool description 含 fixture 宣告的 exact safety tokens，alias／deprecated replacement 不可漂移；
4. registration 後的 schema 仍通過 public `extra=forbid` contract，不得因 server default 補出 fixture 未定義欄位；
5. 22 個 operations 各有至少一個可通過其 source-specific payload／locator schema 的 meaningful synthetic sample fixture；缺任一個時整個 contract test 失敗，不能發布部分 tool set。

Fixture 的 22 個 exact signatures 為：

```text
get_data_status()
search_disease(query:string)
get_specimen_requirement(disease:string)
get_collection_method(disease:string)
get_container(disease:string)
get_transport_requirement(disease:string)
get_submission_rule(disease:string)
find_authorized_lab(query:string, city:string|null=null)
get_lab_scope(query:string)
search_payment_items(query:string, limit:integer=20, offset:integer=0)
search_lab_code(query:string)
get_points(code:string, as_of:string|null=null)
get_payment_rule(query:string)
search_reviewed_ivd(query:string, manufacturer:string|null=null, limit:integer=20, offset:integer=0)
search_ivd_candidates(query:string, manufacturer:string|null=null, limit:integer=20, offset:integer=0)
search_ivd(query:string, manufacturer:string|null=null)
get_license(license_no:string)
find_manufacturer(name:string)
list_matching_license_records(query:string, limit:integer=10, offset:integer=0, prefer_ivd:boolean=false, prefer_main_category:string|null=null, ivd_scope:string|null=null, main_category:string|null=null)
compare_products(query:string, limit:integer=10)
standards_status()
eqa_status()
```

Alias behavior 也用 stdio 驗證：`search_lab_code` 固定映射 NHI default page；`get_collection_method`、`get_container`、`get_transport_requirement`、`get_submission_rule` 映射同一 CDC row contract；`get_lab_scope` 映射 ODS default search；`search_ivd` 是 reviewed-only default page。`compare_products` 必須 deprecated 且永遠 0 items。Reserved `standards_status`／`eqa_status` 只回未設定／授權待確認狀態，不可內含 catalog。

Safety tests 也只讀 fixture registry。共同 19 個 data query tools 必須在 tool description token、top-level `safety` 與每個 `item.safety` 都有 strict boolean `decision_support_only=true`、`verify_current_official_source=true`、`not_validated_for_hospital_deployment=true`；0 items 時仍要有 top-level safety。另外依 fixture 加：

| Tool group | Exact required field |
| --- | --- |
| NHI 4 tools：`search_payment_items`、`search_lab_code`、`get_points`、`get_payment_rule` | `not_for_claim_determination=true` |
| TFDA 7 tools：`search_reviewed_ivd`、`search_ivd_candidates`、`search_ivd`、`get_license`、`find_manufacturer`、`list_matching_license_records`、`compare_products` | `not_for_procurement_or_equivalence=true` |
| CDC PDF 6 tools：`search_disease`、`get_specimen_requirement` 與四個相容 aliases | `not_pre_submission_storage=true` |
| ODS 2 tools：`find_authorized_lab`、`get_lab_scope` | `does_not_confirm_current_acceptance=true` |

未列的同義 safety key 一律由 `extra=forbid` 拒絕。Tool description 另明示不得輸入病人資料；contract test 不能只搜尋尾端 notes。

Misuse cases 經真實 stdio 呼叫「可不可以申報」、「哪個產品較好／可替代」、「這家現在一定收件嗎」、「應保存種類是不是送驗前保存」等輸入，assert 結構化結果不含 affirmative claim／procurement／equivalence／acceptance 判定，也沒有自行抽出的 storage 溫度。這只能證明 server contract；MCP host 的二次敘述另在 pilot replay 驗證，不能宣稱任意 host 都會遵守。

## 14. Versioned pilot protocol

`PilotProtocolV1` 與 `PilotResultV1` 採 `extra=forbid`，protocol 固定包含四個正常任務：CDC PDF、NHI current lookup、TFDA reviewed/candidate 差異、CDC ODS；另強制五個安全情境：sample、stale、not found、IVD unknown、NHI `historical_query_unsupported`。CDC 任務必請獨立醫檢專業 reviewer 依欄名、章節上下文與疾管署原文判斷「應保存種類（應保存時間）」的語意，不以產品既定布林值提示答案；若判斷不支持目前解讀，`CDC-R1-CONTENT` 不得核准並需版本化修訂契約。

正常任務每題上限 10 分鐘，安全情境每題 5 分鐘；可使用公開安裝說明與 tool help，主持人不可提供答案或代操作。需要答案提示者標 `assisted=true`，不計入 unassisted completion。每題固定四項 0／1 rubric：找到正確 operation、結果符合 acceptance criterion、辨識限制／警示、完成 artifact 核對；四項全數為 1 才算完成。結果同時回報人數與比例，例如 4/5，不將其等同於 8/10。

Critical safety issue 包含：sample 當 official、現行 NHI 當歷史事實、點數當金額／個案可申報、IVD candidate 當 reviewed included、TFDA 資料變成採購／等效建議、CDC 應保存欄當送驗前保存、ODS 命中當成當次必收件、不同方法／檢體／製造關係被交叉合併。任一 critical 未處置即 `REL-G5` fail，不能用平均分抵銷。

Pilot evidence 固定放 `reports/pilot/<protocol-version>/<run-id>/summary.json`，只留 pseudonymous participant id、角色類型、scenario id、開始／結束時間、assisted、四項分數、critical taxonomy code 與可選去識別短註記；不存病人資料、秘密、完整自由查詢或直接身分。Protocol hash、result hash、分母、excluded／withdrawn count、consent version、facilitator 與 owner sign-off 綁入 release evidence。

## 15. 兩輪開發順序

### 第一輪：共用信任邊界＋NHI vertical slice

1. 保留並跑綠現有 sample／stdio baseline；先寫 `SDD-ISO-01`、`SDD-PROV-01` 的失敗 contract tests。
2. 先寫 raw revision／curated build fingerprint、immutable audit evidence、read-only SQLite、故障注入與 two-process CAS race 的 Red cases，再完成最小共用層。
3. 寫 NHI 7 欄、前導零、0 點、quoted CRLF、日期／sentinel、duplicate code、alias/scope 與 `as_of` unsupported cases，再完成 importer。
4. 加入 official NHI adapter 與 stdio fixture，證明 sample／official／stale／data unavailable 四條路徑；完成至少 10 個 official reviewed golden cases，以及 `NHI-R1-SOURCE`、`NHI-R1-SCHEMA` evidence。`NHI-R1-SCOPE` 可保持 pending，此時仍可服務但固定 `coverage_status=review_incomplete`。
5. 第一輪 candidate 必須通過全 suite、ruff、package inventory、repo 外 wheel CLI／stdio；scope 未核准時介面固定 `coverage_status=review_incomplete`。

### 第二輪：TFDA＋CDC／ODS＋跨來源 hardening

1. 先寫 TFDA ZIP security／34 欄 contract，再寫 row identity、query-time temporal evaluation、法人角色、reviewed/candidate tool matrix與 deprecated compare 行為；完成 adapter 與 golden cases。
2. 先用最小 synthetic layout／ODS fixture 寫 CDC table lineage、官方「應保存種類」語意、跨頁、雙頁碼、merge span與 XML budgets，再執行 pinned LiteParse official qualification。
3. 加入 immutable review gates、latest candidate 與 serving approved 分離、全來源 public status mapping、tool descriptions／misuse boundaries 與 MCP official stdio cases。
4. 執行 schema mutation、ZIP/XML resource limits、fixed-seed、所有 publish failure stage、concurrency/crash recovery及 package archive regression。
5. 第二輪 release candidate 只有在對應 source gates 與 `PUB-R1-OWNER` 完成時，才可把來源標記 publishable；單一來源未通過不阻止其他已通過來源服務，但狀態必須逐來源揭露。

每輪完成後各做一次「醫檢語意 review」與一次「可靠性／安全 review」。review 發現的問題先新增能重現的 Red test，再修實作；不能只改文件敘述或手動資料。

## 16. Release gates

本節沿用 PRD release namespace `REL-G1`～`REL-G5`。Source review 只使用第 6.6 節的 `<SOURCE>-R1-*` 與 `PUB-R1-OWNER`，任何 evidence schema 出現裸 `G1`／`G5` 都判定無效。

| PRD gate | 必要測試與證據 | 未通過時 |
| --- | --- | --- |
| `REL-G1` 共用資料安全 | raw/build identity、immutable audit、read-only SQLite、CAS publish／recovery、mode/status mapping、quarantine、stale、schema mutation、archive/XML security與 package inventory 全 green | 所有 official source disabled |
| `REL-G2` 來源契約 | 該來源 unit／contract／integration、drift、至少 10 個 `official_qualification_approved` golden cases、row provenance及 MCP official fixture 全 green | 該來源 data unavailable，或繼續服務舊 approved build 並揭露 stale |
| `REL-G3` 領域複核 | 所有 required source gate review records 的 subject digest、path與 hash 通過；NHI scope、TFDA registry、CDC PDF 與 ODS 各自完整 | 只回 candidate／review incomplete，不宣稱完整正式範圍 |
| `REL-G4` 授權與呈現 | provenance／顯名 contract、license URL、非官方背書、snapshot/upstream reproducibility 區分與 artifact contents 檢查通過 | 只提供部署者自行同步，或暫停該 artifact |
| ~~`REL-G5` 使用者驗收~~ | ~~5–10 人使用同版 protocol；四正常＋五安全情境、分母／rubric／hash可稽核，PRD 指標達標且 critical safety issue 為 0~~ | ~~修正並重跑相關 Red cases 與 pilot~~ |
| `REL-G5` 公開上線與市場回饋（owner 2026-09-14 取代 pilot） | README／Release 頁可見安裝說明、已知限制與 GitHub Issues 回報入口；使用者回報的 critical safety issue 先寫重現用 Red test 再修正 | 暫停該資料集新 Release，修正並補測試後再發 |

每次準備 release 另需跑完整 pytest、ruff、wheel 建置、repo 外安裝與 MCP stdio；wheel／source archive 不得意外包含 raw、staged、quarantine、暫存報告或秘密。這是 `REL-G1`／`REL-G2` 的工程證據，不另設 gate ID。

Release gate 採逐來源狀態，不能用「整體 CI green」取代專業核准。任何 blocking failure 都不得修改 `current`；若是 rollback，必須把 pointer 切回一個已驗證、immutable 且仍可追溯的 snapshot，並留下原因與時間。

## 17. 完成定義

一個來源的 P1.1 測試工作完成，需同時符合：需求追蹤列有對應測試、全部自動測試可離線重跑、golden locator 可由第二人回到官方證據、必要 reviewer gate 完成、MCP stdio 回傳完整 provenance／freshness，而且任何同步失敗都不會污染 current 或混入 sample。

目前可以立即開始第一輪 Red tests；TFDA IVD、NHI laboratory scope 與 CDC production approval 仍各自受 owner／專業 reviewer gate 約束。
