# P1.1 實作紀錄與未決事項

核對日期：2026-09-14（Asia/Taipei）

這份紀錄只記錄目前實作能證明的範圍，以及不能由程式自行猜測的事項。它不把文件驗收或 synthetic test pass 寫成正式資料 qualification。

## 已確認

- `sample` 與 `official_snapshot` 是兩條隔離路徑；official source、manifest、raw artifact 或 SQLite 完整性失敗時不回退 sample。
- packaged `public-contract-v1.json` 現在保存每個 operation 的完整 request schema、三組 response JSON Schema、source payload 與 locator JSON Schema；MCP discovery 與 Pydantic implementation schema 都做 equality readback。
- NHI importer 只接受固定七欄、strict Gregorian `YYYYMMDD`、ASCII 非負 base-10 points；合法 `0`、原始欄位、quoted newline 與 `29101231` 都保留，duplicate logical key 以 normalized code 判斷。
- NHI importer 對 UTF-8 replacement character 與 malformed CSV quoting fail-closed；quoted CRLF 仍由 strict `csv` parser 正常保留。
- NHI points／日期的 strict numeric regex 固定使用 ASCII `0-9`；超長 decimal 轉換也會收斂成穩定 `POINTS_INVALID`，不洩漏原生整數轉換例外。
- NHI serving snapshot 目前只提供 current exact lookup、全表搜尋與分頁；合法非 null `as_of` 固定回 `historical_query_unsupported`。
- NHI scope／alias rule bundle 只有在 approved entry 具 reviewer evidence 時才影響查詢；collision 以全部 code 回傳，不任意選一個 winner。
- serving descriptor 的 operational 欄位目前與 immutable check record 綁定；check 的 hash、source、generation 或欄位不一致時回 `operational_status_integrity_failure`。
- publisher 與 runtime 都拒絕 current descriptor 的 missing／extra key 或錯誤 schema version；publisher 會在 pointer replace 前回 `CURRENT_POINTER_INTEGRITY`，不延續已損壞的 current。
- runtime 強制 serving manifest、curated DB 與 local raw artifact exact path 為各自的 `curated/<source-id>/<build-id>/` 或 `raw/<source-id>/<raw-revision-id>/` layout；即使 staged copy 具有相同 bytes/hash，也會 fail-closed，避免 staged data 被當成 serving data。
- 無 serving 的完整 descriptor 可揭露已驗證的 candidate 狀態；candidate 不會使 query 讀取 staged／quarantine 或回傳資料。
- 已提供基本 rollback／recover-current：rollback 驗證 target manifest／DB／check 並以 generation CAS 切換；recover 只接受具名成功 event，不掃描最近 build。四條 current pointer 寫入路徑都會在替換後讀回失敗時恢復 exact bytes，恢復本身失敗則回 `PUBLISH_RECOVERY_REQUIRED`。
- NHI offline builder 目前會寫 immutable `audit/validation.json`、`qualification-candidate.json`、`golden-qualification.json` 與 source/schema synthetic review records；manifest 以 data-root-relative path＋SHA-256 引用，並以 `ReviewSubjectV1` canonical digest 綁定 raw artifact、curated DB、build fingerprint、validation 與 candidate。
- publisher target validation 與 runtime 都會重新驗證 audit evidence、review gate coverage、raw/curated-only evidence path、hash readback 與 subject digest；audit tamper 不會回退 sample。
- publisher 在替換 current 前也會驗證 NHI manifest 的單一 primary artifact、canonical raw path、local availability 型別與 raw SHA-256 readback；raw path drift 會以 `ROLLBACK_TARGET_INTEGRITY` fail-closed，pointer 與 event index 保持不變。
- audit/runtime 也會比對 validation report 與 manifest 的 automated status、blocking errors 與 warnings；任一不一致都 fail-closed。
- final certificate 若宣稱 `official_qualification_status=approved`，現在還必須具備 `PUB-R1-OWNER`、至少 10 個 distinct case IDs，以及每案綁定當次 raw artifact、official-source 標記、approved review、完整 locator 與 reviewer evidence；synthetic candidate 不能被升格。
- audit/runtime 會拒絕缺少 NHI source/schema gates、非 approved human review status、validation 與 manifest row-count 不一致、quarantine 非零，或 curated SQLite 實際 row coverage 不一致的 serving build。
- builder 在任何 raw／curated 寫入前會拒絕已存在的 curated build 目錄；部分 build 不會透過重跑覆寫 manifest，必須由獨立 recovery 流程處理。
- 兩個 concurrent rollback writer（同 process 與兩 process＋barrier）的 regression 已證明每次只有一個成功、generation 單調增加，另一個收到 CAS／target-current conflict；current bytes 不被晚到 writer 覆寫。
- `taiwan-lab-data sync nhi_fee --input <caller-supplied-csv> --data-dir <path>` 已可執行 discover→fetch→parse→normalize→validate 的 offline candidate path；成功只寫 `staged/nhi_fee/<attempt>/validation.json`、標 `candidate_status=review_pending`，不自動 publish。`--fail-stage` 可注入各階段失敗，報告不含 absolute input path。
- `publish_operational_check` 已提供獨立 check writer：lock 內以 current generation CAS 更新 immutable check 與 operational descriptor，保留 serving snapshot／manifest identity，並 append `check` event；stale generation 不會留下 late check file 或改動 current。
- lock timeout regression 已用兩個 process 驗證；持鎖 writer 存在時第二個 writer 以 `PUBLISH_LOCK_TIMEOUT` fail-closed，不改動 current。
- event append failure 會以同一把 source lock 回復 current descriptor 與 event index 的原始 bytes，並移除新建但未被事件引用的 check；若回復本身失敗則回 `PUBLISH_RECOVERY_REQUIRED`。recover-current 只處理具名成功 event，會忽略殘留 atomic temp。
- 共用 fetch trust boundary 已用 stdlib 實作：只接受 allowlisted HTTPS host，逐跳重驗 redirect，限制 Content-Length 與實際串流 bytes，保存安全 headers／redirect trace／SHA-256；NHI metadata discovery 只選 exact CSV＋UTF-8 distribution 並驗 publisher、identifier、license。
- `run_nhi_upstream_sync` 與 CLI 的 explicit `--publisher-oid` path 已接上 metadata→CSV→parse→validate；成功仍只寫 `staged/.../validation.json` 並標 `review_pending`，預設 `--input` path 不會連網，也不會自動 publish。短時間重試的 sync attempt 使用 UTC timestamp＋random 128-bit hex，避免 immutable report collision。
- NHI sync 的 `raw_revision_id` 現在依 `RawRevisionFingerprintV1` 綁定 canonical discovery identity 與 primary artifact 的 role、media type、bytes、SHA-256；同步報告另保存 `discovery_metadata_sha256`。metadata fetch time、response URL、response body hash 與 redirect 等 volatile evidence 只留作 transport evidence，不改 raw identity。
- discovery 驗證失敗但 metadata 已成功取得時，report 會保留 partial metadata evidence，`discovery_metadata_sha256` 維持 `null`；malformed artifact hash 也會在 fingerprint boundary 被拒絕，不讓原生 hash／JSON 例外外洩成有效 candidate。
- upstream CSV fetch 失敗時，staged failure report 仍保留已成功讀取的 metadata/discovery identity、final URL、SHA-256 與 fetched time；不把未取得的 CSV 偽裝成 fetch evidence。
- MCP stdio 已直接覆蓋 official current lookup、`as_of` historical rejection、空 data root unavailable 與 stale serving；結果確認不會 fallback sample，stale 仍保留原 snapshot identity。
- stdio fixture 的 data-root 邊界已釐清：不存在的 `TAIWAN_LAB_DATA_DIR` 依 SDD 屬啟動設定錯誤；已存在但沒有 current snapshot 的空 root 才回 `data_unavailable`，兩者不混為同一狀態。
- `acceptance.py` 已提供 strict v1 acceptance report writer：只接受 caller 提供的 node status、exit code、輸出／build／golden／review hashes 與 data-root 內 evidence；packaged `acceptance-contract-v1.json` registry 會拒絕未登錄或仍 PLANNED 的 node，`passed` 會拒絕 missing、0 collected、skip、xfail、docs-only，report path 以 immutable canonical JSON 寫入並拒絕 hash mismatch／bytes conflict。
- acceptance validator 的 adversarial review 已補上非字串 `node_status`／`gate_disposition` 的穩定 schema error；不會把原生 `TypeError` 洩漏成 report trust-boundary 結果。這些 canonical report 目前仍只驗證 writer，尚未產生任何正式 `passed` release evidence。
- acceptance immutable-report conflict 現在只回穩定 code 與通用描述，不把 report 的絕對本機路徑放進錯誤 detail。
- audit validator 也已補上非字串 review enum／hash 與 malformed reference 的 domain-error 防禦，並在 qualification artifact lookup 前固定驗證型別；review trust-boundary 不依賴原生 `TypeError`。
- `ToolResult` 現在要求含 items 的結果必須有 provenance，且每個 item evidence 的 `artifact_id` 必須存在於該 provenance artifact registry；不合法的 row-level binding 會在 model boundary fail-closed。
- `ToolResult` 也會收緊 status／identity 組合：available 不得帶 `data_unavailable`，非 historical 結果不得帶 history capability，source status 必須和 provenance 的 review／stale reasons 相等，sample IDs 必須為 null，official available IDs 必須成對非空。
- operational check writer 對非字串 `check_result`／`latest_candidate_status` 也會先做型別驗證，回穩定 publish domain error，避免 malformed status 洩漏原生 `TypeError`。
- canonical verification node 已建立 `SDD-API-01`、`SDD-ISO-01`、`SDD-PUB-01`、`SDD-FAIL-01`、`SDD-FRESH-01`、`SDD-PROV-01`、`SDD-SEC-01`、`SDD-OBS-01`、`SDD-AUDIT-01`、`SDD-NHI-01`、`NHI-01`、`NHI-02`、`NHI-03`、`NHI-04`、`NHI-05`；其餘 SDD／來源 domain nodes 仍保持 PLANNED。

## NHI official qualification evidence 結構（2026-09-14，Claude Code 接手後第一個切片）

本節只建立「正式 golden／qualification 證據能被機器檢查」的結構。沒有下載官方資料、沒有建立任何 official golden case、reviewer 身分、review record 或 approved certificate；synthetic fixture 通過不代表 `NHI-R1-SOURCE`、`NHI-R1-SCHEMA`、`PUB-R1-OWNER` 或 P1.1 release approval。

- `models.py` 新增 `GoldenCaseV1`、`QualificationCaseResultV1`、`QualificationCandidateV1`、`QualificationCertificateV1`，全部 `extra=forbid`＋strict，並以 JSON 模式驗證。拒絕：未知欄位、`review_pending` 卻帶 reviewer 欄位、已審卻缺 reviewer／角色／assurance／帶時區的 reviewed_at、`official_source=true` 卻沒有 `raw/` 底下的 evidence path、fixture 檔名與 hash 不成對、transform 缺件；candidate 的 case_ids／case_count／逐案狀態必須一致且永遠 `not_qualified`；certificate 為 `not_qualified` 時不得列核准案例，`approved` 時至少 10 個 distinct case IDs。
- `importers/nhi.py` 新增 `active_nhi_transform()` 與 `evaluate_nhi_golden_cases(payload, cases)`：只讀呼叫端提供的 raw bytes，離線、不寫檔、不核准。逐案比對 artifact ID＋raw SHA-256、目前 parser／schema／normalization／rule／qualifier 的 version＋bundle hash、exact code 是否命中、row number＋`source_row_sha256`、指定欄位（值與 JSON 型別都要相同，避免 `True == 1`）與 result-level warnings，輸出穩定 failure codes（例如 `ARTIFACT_MISMATCH`、`TRANSFORM_MISMATCH`、`LOCATOR_MISMATCH`、`FIELD_MISMATCH:<field>`、`WARNINGS_MISMATCH`、`STATUS_MISMATCH`）。
- `build_nhi_snapshot(payload, data_root, golden_cases=...)` 會把逐案結果寫進 `audit/qualification-candidate.json`，並加上 `case_count`、input artifact hash、curated DB hash 與 active transform；任一案失敗時在任何 raw／curated／current 寫入前以 `GOLDEN_CASE_FAILED` 擋下。golden certificate 仍固定 `not_qualified`、`approved_distinct_case_ids=[]`。
- golden 比對值與 SQLite 寫入共用同一個 `_curated_row()`，比的是實際 serving 的欄位值。
- `audit.py`：runtime／publisher 讀取 candidate 與 certificate 時先過上述嚴格 schema；candidate 的 input artifact hash、curated DB hash、active transform 必須與 manifest 一致，每案 `golden_case_sha256` 必須能重算。certificate 宣稱 `approved` 時，每個核准案例另須 `evaluation_status=passed`、transform 等於目前 build fingerprint、`evidence_data_root_relative_path` 等於 manifest 的 raw artifact path；synthetic、比對失敗、transform 過期或 evidence path 不符都 fail-closed。
- 可重跑證據（synthetic）：以 data root 內保存的 raw artifact 加上 candidate 內保存的 case 定義重跑 evaluator，結果與 candidate 內容完全相同；runtime exact lookup 的 warnings 與 case 的 `expected_warnings` 一致。

### 本切片的規格解讀（文件沒有寫死，先採保守做法，待文件修訂或 owner 確認）

1. TDD §10 的 golden case 欄位清單含 `subject_digest`，SDD §7.4 與 PRD §8.3 沒有。candidate hash 已是 subject digest 的輸入，case 若再含 subject digest 會形成循環；依 SDD 開頭的規格階層（SDD 管 internal architecture），`GoldenCaseV1` 先不放 `subject_digest`，案例與 subject 的綁定由 certificate 的 `subject_digest`＋`candidate_report_sha256` 承擔。需要修 TDD 或由 owner 裁示。
2. PRD §8.3 要求 case 保存「curated build／parser／schema／normalization／rule bundle versions」。curated build ID 要到 build 時才算得出來，reviewer 事前無法填寫；目前 case 綁 parser／schema／normalization／rules／qualifier 的 version＋bundle hash，curated build ID 由 candidate 綁定。
3. PRD §8.3 的「evidence path」以 `evidence_data_root_relative_path` 表示（沿用 SDD 的 `data_root_relative_path` 命名），official case 必填且必須位於 `raw/`。
4. `expected_status`／`expected_warnings` 解讀為 current exact lookup 的 result-level 值。NHI evaluator 目前只支援 `input={"code": ...}` 與 `expected_status=ok`；warnings 以 runtime 在 `NHI-R1-SCOPE` pending 時固定產生的 `coverage_review_incomplete` 為準。
5. case 的 `review_status` 使用 `review_pending|approved|rejected`；`review_pending` 時 reviewer 相關欄位必須全為 null。

### 本切片發現、尚未處理的既有風險

- `audit.py` 只檢查 review record 的 `protocol_id`／`protocol_version`／`protocol_sha256` 形狀，沒有比對 package 內已核准的 review protocol；package 目前也沒有 `review_protocols/`。因此 `build_nhi_snapshot` 產生的 synthetic review（protocol `nhi-r1-synthetic-fixture`、reviewer `offline-test-builder`）仍能讓 runtime 服務該 build。這是既有 synthetic integration builder 的設計；要收緊需要先有 owner 核准的 NHI review protocol。
- synthetic builder 的 `required_gates` 目前只有 `NHI-R1-SOURCE`、`NHI-R1-SCHEMA`，而 TDD §6.6 的 serving matrix 寫 NHI 全表 current lookup 需要 `NHI-R1-SOURCE + NHI-R1-SCHEMA + PUB-R1-OWNER`；audit 也只要求前兩者。本切片未改，避免在 owner gate 未定前改變既有 serving 行為。
- `uv build` 產生的 sdist 會包含只列在本機 `.git/info/exclude` 的 `.impeccable/hook.cache.json`（Claude Code 外掛 hook 於 2026-09-14 01:01 建立，內容為 `{"version":1,"sessions":{}}`，無機密）；`tests/test_package_contents.py` 的 denylist 沒有涵蓋這類本機工具快取。本切片未改 build 設定。
- TDD §2／§5 與實作計畫 §0 仍寫 `155 passed`；那是本切片前的數字，本切片沒有改規格文件。

### Owner 決定紀錄（2026-09-14，owner 在 Claude Code 對話中直接回覆）

這些是 owner 在對話中的決定，用來解除工程阻擋。它們本身不是 `ReviewRecordV1`，也不構成 `NHI-R1-SOURCE`／`NHI-R1-SCHEMA`／`PUB-R1-OWNER` 的 approved review record；正式 review record 仍要在 owner 實際審核後產生。

- ~~來源資訊：確認 publisher OID `A21030000I`~~（2026-09-14 更正：這是 Claude 提供給 owner 的錯誤資訊，owner 的確認因此作廢。`A21030000I` 其實是資料集 identifier `A21030000I-D20021` 的前綴。live metadata `https://data.gov.tw/api/v2/rest/dataset/174450`（HTTP 200、2588 bytes、SHA-256 `83dc8c0efb9286d811b2b0df54a9d35be4dd948487ea2a7fb4369f429bc457f3`）的 `publisherOID` 為 `2.16.886.101.20003.20065.20022`、`license` 為代碼 `"1"`、`dataProvider` 為帳號字串而非機關名稱。同一資料集網頁 `https://data.gov.tw/dataset/174450`（HTTP 200、SHA-256 `1c794289be355789020b2c3dd8c980ab32ba597518830d966795ccc13c294afa`）的「提供機關」為「衛生福利部中央健康保險署」、「授權方式」為「政府資料開放授權條款-第1版」，網頁本身沒有出現該 OID。以 `--publisher-oid A21030000I` 執行的 live sync 在 discover 階段以 `DISCOVERY_PUBLISHER_MISMATCH` 停止，沒有下載 CSV、沒有寫 raw，只留下 `staged/nhi_fee/20260914T033656Z-d878d564cc3241129bdf44de6f9675ac/validation.json`。另外 `nhi_source.py` 比對的授權字串 `政府資料開放授權條款－第 1 版` 與 API 值 `"1"` 不符，即使 OID 改正也會以 `DISCOVERY_LICENSE_MISMATCH` 停止。兩者都需 owner 重新決定。）
- 授權「政府資料開放授權條款－第 1 版」（網頁顯示寫法為「政府資料開放授權條款-第1版」）、顯名「資料提供機關：衛生福利部中央健康保險署」、只使用 CSV 不使用 TXT：仍有效。
- 2026-09-14 owner 看過上述更正證據後重新決定：live sync 的 expected publisher OID 改用 `2.16.886.101.20003.20065.20022`；授權改為核對 metadata `license` 代碼 `"1"`，並在 discovery 另記網頁顯示名稱「政府資料開放授權條款-第1版」。
- 下載：同意把官方 CSV 下載到不進 git 的本機 data root。
- Reviewer：`NHI-R1-SOURCE`／`NHI-R1-SCHEMA` 由 owner 本人審核。
- Golden cases：由 Claude 依下載的官方檔先提出候選題目與預期值，owner 之後逐題 review；review 前全部維持 `review_pending`。
- `29101231`（OD-02／D-014 的對外語意部分）：採「只顯示原值，並標示可能表示未設定結束日、未經官方確認」。這與 PRD OD-02 預設一致；目前 MCP 以 `possible_open_end_sentinel=true` 表示，沒有另加文字說明。
- 規格解讀第 1 點（`GoldenCaseV1` 不放 `subject_digest`）：owner 同意。
- `NHI-R1-SCOPE` 檢驗範圍清單：延後，之後再決定怎麼整理資料。
- OD-01 curated 再散布（NHI）：採 B，隨 MCP 發布 owner 審核過的 curated NHI 資料；更新採「上游內容有變才發新版」，由 owner 審核後發布。這需要新舊版差異偵測，屬後續切片；CDC PDF 等其他來源的再散布條件另案決定。

### 同步保留原始檔、授權代碼核對與官方 CSV 下載（2026-09-14）

- `sync.py`：只有從上游抓到的 bytes 會在 fetch 階段寫入 `raw/nhi_fee/<raw-revision-id>/artifacts/source.csv` 與 `fetch.json`；之後 parse／validate 失敗也保留原始檔（SDD 失敗矩陣要求 raw 保留）。同一 raw revision 再抓時不覆寫第一份 `fetch.json`；既有 raw bytes 不同時回 `IMMUTABLE_RAW_CONFLICT` 且不覆寫；`--input` 離線檔沒有上游來源證明，不建立 raw。報告的 artifact 加上 `data_root_relative_path`，存到本機時 `local_artifact_available=true`，另加 `raw_fetch_record_data_root_relative_path`。
- `nhi_source.py`：授權改為核對 metadata 代碼 `"1"`；discovery 另存 `license_code`、網頁顯示名稱「政府資料開放授權條款-第1版」與 `https://data.gov.tw/license`。`tests/test_fetch.py` 的 synthetic metadata 改成 live 觀察到的形狀（publisher OID `2.16.886.101.20003.20065.20022`、license `"1"`）。
- 未改：`build_nhi_snapshot` 的 synthetic discovery identity 與 `tests/test_snapshot_publish.py` 仍使用舊字串 `A21030000I`／「政府資料開放授權條款－第 1 版」。它們只影響 synthetic build 的 hash，不是官方 discovery；待 synthetic builder 下一次調整時一併更新。
- live 下載（owner 已授權）：`taiwan-lab-data sync nhi_fee --publisher-oid 2.16.886.101.20003.20065.20022 --data-dir C:\Users\User\Documents\ChatGPT\taiwan-lab-mcp-data\data-root --json` exit 0、`status=passed`、`candidate_status=review_pending`、6,173 rows、1,725,985 bytes、SHA-256 `624e8d0ace8f7e0d5c3ed3102069df94ee25f05e2b39a0d60822e7f1a51ca271`、raw revision `75b33643398099badae9a59ba4067f3aa70b0cd8f551ea18f8dee6696eaa62ab`、官方 `modifiedDate` `2026-09-14 07:05:47`（時區未標）。hash 與研究文件 2026-09-13 的下載相同：官方更新時間變了、檔案內容沒變。沒有建立 curated build 或 current pointer；data root 位於 repo 外，不進 git。

### Owner gate：尚待決定的事項

- `NHI-R1-SOURCE`／`NHI-R1-SCHEMA` 的 reviewer_id 寫法、review protocol 內容（checklist、major／minor 門檻）與存放位置；Claude 需先交一頁白話版審核清單給 owner。
- 至少 10 個 official golden cases 的預期值核定（等官方檔下載並產生候選後由 owner review）。
- `PUB-R1-OWNER` 發布授權。
- `NHI-R1-SCOPE` reviewer 與 allowlist 依據（owner 已決定延後）。
- 規格解讀第 2–5 點是否採用（本輪尚未逐點詢問）。

## UNVERIFIED／OWNER GATE

- 本輪沒有下載或提交 NHI 正式整批資料。`build_nhi_snapshot` 接受呼叫端已取得的 bytes，屬 offline integration builder，不等於完成 `NHI-R1-SOURCE`、`PUB-R1-OWNER` 或正式發布授權。
- upstream fetch 的測試只使用 synthetic metadata／response；正式 live invocation 尚未執行，CLI 要求 caller 明確提供 expected publisher OID。當前測試字串不構成官方 OID、來源或授權核准證據。
- `NHI-R1-SCOPE` 尚未完成，因此目前 rule bundle 為空，服務結果固定揭露 `coverage_status=review_incomplete`；沒有可自行推導的 laboratory allowlist。
- NHI `生效迄日=29101231` 的官方語意仍未確認；程式只保存 raw date、parsed date 與 sentinel flag，不解釋為永久有效。
- 官方來源 cadence、live upstream same-hash reproducibility、正式 source review evidence、第二人重算與 official qualification certificate 尚未驗證；目前 golden certificate 明確為 `not_qualified`，candidate 的 `synthetic_ci_status=passed` 不代表正式 qualification。
- process crash／power-loss 與檔案系統／OS 的斷電 durability 尚未驗證；目前只驗證 event append failure 的應用層回復、lock timeout、兩 process＋barrier CAS，以及 recover-current 忽略殘留 temp。
- `SDD-SEC-01` 本輪 canonical test 已覆蓋 HTTPS／redirect／bounded stream、evidence path containment 與 SQLite read-only；ZIP/XML archive boundary 仍隨 TFDA／CDC 來源切片保留為未完成範圍。`SDD-AUDIT-01` 目前驗證 audit reference/hash readback 與 validation tamper，完整 tamper-each-input matrix 與正式 review/certificate evidence 仍未完成。
- `sync` 的 live upstream invocation、上游版本欄位與完整 HTTP failure taxonomy 尚未驗證；目前測試只使用 synthetic metadata／response，正式 CLI 仍要求 caller 明確提供 expected publisher OID，不把 candidate report 說成已完成官方同步。
- canonical domain test 檔名／node 尚未全部拆分；acceptance reporter 已建立，但目前尚未以它產生任何「passed」canonical release evidence，也沒有把集中式測試冒充成完整 canonical release evidence。
- CDC PDF／ODS、TFDA official importer／IVD review、hospital deployment readiness 尚未實作。

## 官方 golden 候選與審核清單草案（2026-09-14，待 owner review）

- 位置（repo 外，不進 git）：`C:\Users\User\Documents\ChatGPT\taiwan-lab-mcp-data\owner-review\`
  - `nhi-golden-candidates-2026-09-14.json`：10 個 `GoldenCaseV1`（`NHI-G-001`～`NHI-G-010`），全部 `official_source=true`、`review_status=review_pending`、reviewer 欄位為 null，綁定 raw artifact SHA-256 `624e8d0ace8f7e0d5c3ed3102069df94ee25f05e2b39a0d60822e7f1a51ca271` 與 evidence path `raw/nhi_fee/75b33643398099badae9a59ba4067f3aa70b0cd8f551ea18f8dee6696eaa62ab/artifacts/source.csv`；檔案 25,357 bytes、SHA-256 `a5c98d9012af0bf7df9f2fb21f5ec797efb465ea80114a51b8474e93df47b763`。
  - `nhi-golden-candidates-2026-09-14.md`：同 10 題的人工核對表（由程式從原始檔取值產生）。
  - `nhi-review-checklist-draft.md`：`NHI-R1-SOURCE`／`NHI-R1-SCHEMA` 白話審核清單草案；嚴重程度沿用 PRD §8.3 定義；「輕微問題可否通過」與「審核人名稱寫法」待 owner 決定。
- 選案涵蓋 TDD §10 要求：前導零（`06008C`）、0 點（`3F`）、名稱內換行（`F28`）、日期邊界（最早 `19950301`、最晚 `20260901`）、scope pending（全部 `review_pending`）；另含英文名空白（`09139C`）、7 碼代碼（`03003BA`）、最高點數（`36027B`）、sentinel（`12001C`）、全形字（`12003C`）與 `09006C`。整張表沒有 2 月 29 日生效日，也沒有「前導零且 0 點」的列，因此分開選。
- `evaluate_nhi_golden_cases(原始檔, 10 題)` 全部 `passed`、failure codes 為空。這只證明候選值與原始檔一致；owner 尚未對照健保署網站核對，不是 `official_qualification_approved`。

### 10 題候選的網站核對（2026-09-14，Claude 代為核對，不是 owner review）

- owner 要求 Claude 以瀏覽器模擬人工核對。Claude 在內建瀏覽器打開 `https://info.nhi.gov.tw/INAE5000/INAE5001S0`，以網站 UI 查 `09006C`（含詳細頁）與 `06008C`，並擷取網頁實際送出的查詢：`POST /api/inae5000/inae5001s01/SQL0001`，body 為 `{"KEYWORD":"","CNAME":"","ENAME":"","CODE":"<code>","MEMO":"","TREAT_CHAP_CODE":"","PAY_S_DATE":"","RDO_TYPE":"2","showPage":1,"showCounts":10}`（`RDO_TYPE=2` 為「目前給付中的項目」）。其餘題目在同一頁面以同一查詢服務比對；之後用程式重查 10 題並逐欄比對，寫入 `owner-review\nhi-golden-browser-check-2026-09-14.json`（16,709 bytes、SHA-256 `663db32b7ce9e178a3e9d6d47acab82acf12d92877b03c2160b0b97ca6f694a3`）與人讀報告 `nhi-golden-browser-check-2026-09-14.md`。
- 結果：8 題中文名、英文名、點數、起訖日、備註完全一致（含 `F28` 名稱內換行、`P1016C` 945 字備註、`12003C` 全形字）。`3F` 與 `36027B` 的備註文字一字不差，但查詢網站各多 7 個 `\r\n` 換行（CSV 384／316 字，網站 398／330 字）；官方 CSV 全表備註沒有換行。這是兩個官方出口的呈現差異，候選值對 raw CSV 仍正確。
- 其他觀察：網站顯示迄日為民國 `999.12.31`（= CSV `29101231`）；網站有 CSV 沒有的「所屬章節」（`treaT_CHAP_CODE`，例如 `09006C` 為「第二部第二章第一節」，`3F`、`P1016C` 為 null），可作後續 `NHI-R1-SCOPE` 的候選依據，但本輪未使用。
- ~~待 owner 決定：換行差異是否依 PRD「minor」視為一致；10 題 review 要以 owner 名義（附 Claude 核對報告為 evidence）或照實記為 Claude 自動核對。~~ 2026-09-14 owner 決定：換行差異依 PRD「minor」視為一致；10 題以 owner 本人名義核准，Claude 核對報告作為 evidence。
- 已產生 `owner-review\nhi-golden-approved-2026-09-14.json`（26,456 bytes、SHA-256 `4e1662bc3f6ea683315d83df71b11d5d5d39fc4cc087a7b70f08b4b25c14d506`）：10 個 `GoldenCaseV1` 皆 `review_status=approved`、`reviewer_role=project_owner`、`identity_assurance=local_asserted`、`reviewed_at=2026-09-14T18:09:42+08:00`，並引用 candidates 檔與網站核對證據檔的 SHA-256。10 案重新通過 `GoldenCaseV1` 驗證與 `evaluate_nhi_golden_cases`（10/10 passed）。reviewer 姓名只寫在 repo 外檔案：GitHub repo `masalu0105-gif/taiwan-laboratory-mcp` 為 PUBLIC（`gh repo view` 實測），repo 內文件不寫 owner 姓名。
- 2026-09-14 owner 另以本人名義核准審核清單 A 段（`NHI-R1-SOURCE`）與 B 段（`NHI-R1-SCHEMA`），證據為清單中列出的 live metadata、資料集網頁、raw artifact 與程式統計；姓名只記在 repo 外審核檔。此為 owner 在對話中的決定，對應的 `ReviewRecordV1` 尚待依正式 build 的 subject digest 產生。
- 2026-09-14 Claude 更正先前說法：先前告訴 owner「發布授權可等資料庫建好、owner 實際查過再問」與規格衝突。PRD `REL-G4`、SDD §7.3 manifest 範例與 TDD §6.6 serving matrix 都要求 NHI 全表 current lookup 具備 `NHI-R1-SOURCE + NHI-R1-SCHEMA + PUB-R1-OWNER`；目前 `audit.py` 只要求前兩者，屬既有缺口。另查 `src/**/*.py` 與 `public-contract-v1.json`，沒有 PRD `REL-G4` 要求的「非官方服務聲明」。
- 2026-09-14 owner 決定：以本人名義核准 `PUB-R1-OWNER`，範圍限「本機 MCP 可查詢正式 NHI snapshot」；GitHub Release／curated artifact 再散布仍需另行核准。非官方服務聲明採簡短版「非健保署官方服務，內容以健保署公告為準。」，加在每筆正式 NHI 結果的 notes。
- ~~核准範圍只到 10 個 golden cases。`NHI-R1-SOURCE`、`NHI-R1-SCHEMA` 審核清單 A／B 段與 `PUB-R1-OWNER` 尚未核准；~~ 三個 serving gates 已由 owner 在對話中核准，但尚未產生對應的 review record；尚未產生 `ReviewRecordV1`、`QualificationCertificateV1` 或 official curated build。approved golden 檔尚未放入 `tests/golden/nhi_fee/`（公開 repo，需另決定是否納入）。

### 正式 NHI build 與本機 serving（2026-09-14）

- 非官方服務聲明：`adapters/base.py` 對 `source_id=nhi_fee` 且有 snapshot 的正式結果加上 notes「非健保署官方服務，內容以健保署公告為準。」（owner 核准的簡短版）。sample 結果不加。
- `audit.py` 改為 NHI serving 必須包含 `NHI-R1-SOURCE`、`NHI-R1-SCHEMA`、`PUB-R1-OWNER` 三個 gate（對齊 TDD §6.6 serving matrix）；synthetic builder 同步補上 synthetic `PUB-R1-OWNER` review。
- 新增 package resource `src/taiwan_lab_mcp/review_protocols/nhi-r1-owner-review/1.json`：owner 核准的 A／B 清單、`PUB-R1-OWNER` 範圍（只限本機 MCP serving）、golden case 覆蓋要求與嚴重度政策（critical／major 拒絕、minor 記錄後接受）。檔案不含 owner 姓名。
- `importers/nhi.py`：`_application_build_identity()` 回傳 `distribution` 或 `development`；抽出 `_write_curated_db()` 讓 synthetic 與正式 build 共用同一份 SQLite schema；新增 `build_official_nhi_snapshot()`。它在任何 curated 寫入前依序確認：raw bytes 與 `fetch.json` 及 raw revision ID 一致、application identity 為 installed distribution（editable／development 回 `APPLICATION_BUILD_IDENTITY_MISSING`）、三個 owner review 齊全且無 critical／major、至少 10 個 approved official golden cases 全部通過。之後寫 DB、validation、candidate、三份 `ReviewRecordV1`（`identity_assurance=local_asserted`）、approved `QualificationCertificateV1`、manifest、check record，最後經 `publish_current_descriptor` CAS 發布。
- 規格解讀（待文件確認）：SDD §7.3 manifest 範例的 `modified_at_precision` 為 `second`，但 PRD public `OfficialContentDate.precision` 只允許 `day|month|year|unknown`。manifest 保留 raw precision，`stores.py` 對外投影時非 `day|month|year` 一律顯示 `unknown`，避免宣稱超出契約的精確度。
- 正式 build（repo 外 installed wheel、application identity `distribution` `c63972f5e092cf8831d6e907f4d9ae5ee0717c878cd978928b69513b2e593397`、review protocol SHA-256 `02e54bec67bb4aad9d5907fd68e3cd74f2395a193c184639a66f1a5d2042a01a`）：data root `C:\Users\User\Documents\ChatGPT\taiwan-lab-mcp-data\data-root`，snapshot `nhi_fee-build-17880b71d636e6a7fade0aa6671570e650cc2efa7b387fefe2cb861c2c9f012c`，6,173 rows，DB SHA-256 `659d0c034da1e677543f89c6839f3bd9b4429e29edd6a32b51c3f8e8efcc26c7`，manifest SHA-256 `fb6fa688ef2ec3250d7463dfae93f0b55856fa3c004694c11a2e959c3f36654c`，generation 1，publish event `publish-58fe6593f71497a8b04505d26a3342f7ca8e9169c0d8382695cc5ed3fe5caefe`。三份 review 的 reviewer 為 owner（姓名只在 repo 外 data root），`NHI-R1-SCHEMA` 記 2 個 minor（兩題備註只差換行）；publisher actor 記為 `claude-code-for-owner`。證據檔（approved golden bundle、網站核對報告）已複製進該 build 的 `audit/evidence/`。
- 同一 installed wheel 以 official mode 查詢：`get_points("09006C")` 為 `ok`、200 點、`effective_end_raw=29101231`、attribution 與授權正確、notes 含非官方聲明；`as_of="2026-09-13"` 回 `historical_query_unsupported`、0 items；`ZZZ999` 回 `not_found`；`search_payment_items("醣化")` 共 13 筆；status 為 `available`、`serving_review_status=approved`、`coverage_status=review_incomplete`。
- repo 內 `dist/`（2026-09-14 00:40 建立、git ignored）是舊 archive，不含新增的 review protocol；未覆寫。在未設定 `TAIWAN_LAB_ARTIFACT_DIR` 時，`tests/test_package_contents.py` 會讀到這份舊 archive 而失敗；本輪 archive 驗證改用 session scratchpad 內重建的 wheel／sdist。
- 仍未做：curated artifact 再散布（GitHub Release）核准、`NHI-R1-SCOPE`、新舊版差異偵測（「有變才發」）、`review`／`publish` CLI、audit 對 review protocol 是否為 package 內核准版本的比對。

## 目前驗證證據

以下為 2026-09-14 同步保留原始檔與授權代碼核對修改後、基於 commit `a14b1da` 加上未提交 worktree 變更的重跑結果（前兩版記錄為 `155 passed`、`177 passed`）：

- `.venv\Scripts\python.exe -m pytest -q`：`184 passed`（155＋qualification evidence 切片 22＋raw 保留 5＋授權代碼 2）。
- `.venv\Scripts\ruff.exe check src tests` 與 `ruff format --check src tests`：通過；`git diff --check`：通過（僅有 Git 的 LF/CRLF 提示）。
- `uv build --wheel --sdist --out-dir <session scratchpad>`（未覆寫 repo 內 `dist/`）：wheel 與 sdist 均成功；以 `TAIWAN_LAB_ARTIFACT_DIR` 指向該輸出跑 `tests/test_package_contents.py`：`2 passed`。archive inventory 為 wheel 43、sdist 88 個檔案；sdist 為 git 追蹤的 86 檔＋`PKG-INFO`＋本機快取 `.impeccable/hook.cache.json`（見上方風險）。沒有 raw／staged／quarantine／SQLite／`uv.lock`。
- repo 外暫存 venv（`uv venv`＋`--force-reinstall` wheel）在 repo 外 cwd 執行 `tests/test_mcp_stdio.py`：`6 passed`；import 路徑來自該 venv 的 site-packages。安裝後 contract：101746 bytes、22 個 discovery tools，operation 名稱集合、request properties 與 response schema equality 均為 true；安裝後 `NHI_LICENSE_CODE="1"`。
- 同一 repo 外 wheel 在獨立暫存 cwd：`taiwan-lab-data validate nhi_fee --json` exit 0、`validation_status=passed`；`sync nhi_fee --input --json` exit 0、`status=passed`，沒有建立 `raw/` 與 `manifests/current`，stdout 不含暫存目錄絕對路徑。
- live 官方下載結果見上方「同步保留原始檔、授權代碼核對與官方 CSV 下載」。
- 以上測試通過與候選比對通過只證明工程結構可用，不是 official qualification、`REL-G2` 或 P1.1 release approval。

## 目前刻意不做

- 不在 repo 保存正式 raw／curated bulk data、病人資料、PHI、LIS／HIS、診斷、申報決策或採購建議。
- 不把 points 換算成金額，不用 current snapshot 回答歷史點數，不把 sample fixture 的官方 URL 當成 fixture 內容的來源證明。
