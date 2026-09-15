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

### 提交、本機 MCP 設定與「有變才發」上游檢查（2026-09-14）

- owner 要求後，commit `3238d70`（feat: owner-reviewed official NHI build and local serving）已 push 到 `origin/main`；push 後 `git rev-parse HEAD` 與 `git ls-remote origin refs/heads/main` 同為 `3238d70451d1295d46d3a997cd53911823929e08`。
- 本機 MCP：以 `uv tool install` 安裝 wheel（`C:\Users\User\.local\bin\taiwan-lab-mcp.exe`、`taiwan-lab-data.exe`），並以 `claude mcp add-json taiwan-laboratory ... -s user` 加入 Claude Code 使用者設定，env 為 `TAIWAN_LAB_DATA_MODE=official_snapshot`、`TAIWAN_LAB_DATA_DIR=C:/Users/User/Documents/ChatGPT/taiwan-lab-mcp-data/data-root`、`PYTHONIOENCODING=utf-8`；`claude mcp list` 顯示 `✔ Connected`。Claude 桌面聊天 App 的設定檔未修改。
- 新增 `sync.run_nhi_upstream_check()` 與 CLI `taiwan-lab-data check nhi_fee --publisher-oid <oid> --actor <id> --data-dir <path> [--json]`：先讀 current descriptor 與 serving manifest，再跑既有 upstream sync（保留 raw revision），用 raw artifact SHA-256 與 serving build 比對，最後經既有 `publish_operational_check` 寫 immutable check record 並更新 descriptor，serving snapshot 不變。
  - 同一 SHA-256：`result=unchanged`、check success、candidate none、`stale=false`，不重建（SDD §9.2／TDD §6.4）。
  - 不同 SHA-256：`result=changed`、check success、candidate `review_pending`（id 為新 raw revision）、`stale=true` 與 `newer_candidate_pending_review`（SDD §8.3）；在該次 sync attempt 目錄寫 `diff.json`（新增／刪除代碼、逐代碼變動欄位、筆數與代碼數）與中文 `diff-summary.md`。`review_gate` 以整數運算標示筆數或代碼數變動是否超過 10%（SDD §13.2 啟動期門檻；非官方門檻）。
  - 抓取或驗證失敗：`result=failed`、check failed、`stale=true` 與 `upstream_verification_failed`；已取得不同 bytes 但驗證失敗時另標 candidate `rejected` 與 `newer_candidate_rejected`。`last_successful_check_at` 不變。
  - 尚無 serving snapshot：只留 sync report，`result=no_serving_snapshot`，不建立 descriptor。
  - CLI exit code 依 SDD §12：成功（含 changed）0、discover／fetch 失敗 3、parse／validate 失敗 4、current／check 完整性錯誤 6。
- live 實測（repo 外 uv tool 安裝版）：`taiwan-lab-data check nhi_fee --publisher-oid 2.16.886.101.20003.20065.20022 --actor claude-code-for-owner --data-dir <data-root> --json` exit 0、`result=unchanged`、check `nhi_fee-check-20260914t123202z-ae306e358a7145e5b6089d9d60c80d0d`、descriptor generation 2。MCP stdio `get_data_status` 顯示 `last_check_at=2026-09-14T12:32:02Z`、`last_successful_publish_at=2026-09-14T12:14:32Z`（未改）、`stale=false`；`get_points("09006C")` 仍回 200 點。
- ~~待 owner 決定：是否建立每日自動執行 `check` 的排程（Windows 工作排程器或 WSL cron，屬持久設定），以及有新版時要用什麼方式通知 owner；~~ 2026-09-14 owner 決定：排程用 Windows 工作排程器（選項 A），通知用 email。新版審核通過後的「發布新版」流程目前需依 `build_official_nhi_snapshot` 手動執行。
- 本 slice 另以 commit `17be1f8` push；push 後 `git rev-parse HEAD` 與 `origin/main` 同為 `17be1f85ed929055d79214dffd25a9fe0164a6cc`。

### 每日排程與 email 通知（2026-09-14）

- 排程腳本放 repo 外（本機設定，不進 git）：`C:\Users\User\Documents\ChatGPT\taiwan-lab-mcp-data\automation\`
  - `Invoke-NhiDailyCheck.ps1`：跑 uv tool 安裝版 `taiwan-lab-data.exe check nhi_fee --json`，每次寫 `logs\nhi-daily-check-<時間>.log`，並覆寫 `STATUS.txt`（第一行固定「OK：…」或「異常：…」）。`unchanged` 只更新 STATUS、不寄信；`changed` 寄信附 `diff-summary.md`；`failed`、`no_serving_snapshot`、輸出無法解析寄信並記「異常」、exit 1。
  - `Register-NhiDailyCheckTask.ps1`：建立使用者排程 `taiwan-lab-nhi-daily-check`，每天 09:30、錯過補跑、不重複執行、30 分鐘上限；動作走既有 `scheduled-task-ops\Run-HiddenTask.vbs`（wscript 隱藏執行，避免跳出主控台視窗）；已存在時拒絕覆寫，`-Check` 只讀。
- email 走 Google Workspace CLI（`gws` 0.16.0，`gmail +send`），收件人為 owner 帳號。先前記憶寫的 `gog` CLI 在本機查不到（`where gog` 無結果），實際可用的是 `gws`。
- 驗證：
  - 空 data root＋`-EmailDryRun`：runner exit 1、STATUS「異常：本機沒有正在服務的健保資料」；gws dry-run exit 0，解碼後信件收件人、中文主旨、UTF-8 多行內文正確。dry-run 不需要授權，因此只證明參數與內文組裝正確，沒有證明真的寄得出去。
  - 真實 data root（`-EmailDryRun`）：exit 0、STATUS「OK：健保支付標準表沒有變動」、check `nhi_fee-check-20260914t124544z-a039872cecd24e269d9e83ed54ce67f1`、generation 3。
  - 登記後 `-Check`：State `Ready`、Execute `wscript.exe`、NextRunTime `2026-09-15 09:30`。手動 `Start-ScheduledTask` 一次：LastTaskResult `0`、STATUS OK、check `nhi_fee-check-20260914t124610z-eff6f332d1d847d282b7b03d347bb28a`、generation 4，沒有殘留 wscript 程序。
- ~~UNVERIFIED／OWNER GATE：`gws` 目前授權失效（唯讀 `gmail users getProfile` 回 401 `invalid_grant`，2026-09-14 兩次實測），真的有新版或失敗時信件會寄不出去；STATUS 會記「email：寄送失敗」。需要 owner 本人在 PowerShell 重新登入 `gws`，之後再經 owner 同意寄一封真的測試信並到寄件備份確認。~~ 2026-09-14 owner 本人重新登入（PowerShell 停用腳本執行，`gws` 會叫到 `gws.ps1` 被擋，改用 `gws.cmd auth login`；未修改 execution policy）。唯讀 `getProfile` 成功。經 owner 同意，以排程腳本對空 data root 真實寄一封「本機沒有正在服務的健保資料」通知：STATUS「email：已寄出」，Gmail 讀回 message `1a09fff1f5bcd026` 標籤 `SENT`／`INBOX`、收件人與中文主旨正確。之後以真實 data root 重跑，STATUS 回到 OK（check `nhi_fee-check-20260914t125814z-5760272cd76b435aa4ff6d245e22270a`）。
- UNVERIFIED：`changed`、`failed` 兩條路徑的真實寄信，以及排程環境下的非 0 結束碼（`Run-HiddenTask.vbs` 程式碼以 `WScript.Quit exitCode` 回傳，未實跑）尚未實測。`gws` 登入日後若再次失效，STATUS 會記「email：寄送失敗」。

### Owner 決定：過期處理、再散布、下一步與平台（2026-09-14）

owner 在 Claude Code 對話中回覆「1A、2b 安裝說明那些都要幫我寫完、3A+B馬上做、4 同意 windows跟mac都要」：

- `D-008`（NHI 超過 7 日是否 hard-stop）：選 A，不 hard-stop。超過兩個宣告週期沒有成功 upstream check 時標 `upstream_check_overdue`，持續回答已核准舊版並顯著揭露。
- `OD-01`（curated snapshot 是否隨 GitHub Release 再散布）：選 B，NHI curated snapshot 要放上 GitHub Release，並寫完整安裝說明。`PUB-R1-OWNER` 先前核准範圍只到本機 serving；再散布的 artifact 內容、授權與 archive 檢查完成後，實際建立 Release 前仍需把具體檔案內容交 owner 確認。
- 下一步：A（NHI 收尾：overdue 標示、新版審核後發布的指令）與 B（TFDA 第一個切片）都要做。
- 規格解讀第 2–5 點（見「本切片的規格解讀」）與 `official_content_date.precision` 對外投影（非 `day|month|year` 顯示 `unknown`）：owner 同意。
- `OD-05` 平台承諾：P1.1 同時支援 Windows 與 macOS。本機只有 Windows，macOS 驗證需另找環境（CI 或 owner 的 Mac），驗證前不得宣稱 macOS 已通過。

- 2026-09-14 owner 在對話中另決定（AskUserQuestion 回覆）：
  - 公開下載包內審核紀錄的 reviewer 不寫本名，改寫「專案負責人」代號；需以新安裝版重建一次 NHI snapshot，並由 owner 再確認同樣的審核內容。
  - 下載包附上健保署原始 CSV。依據：2026-09-14 下載 `https://data.gov.tw/license`（HTTP 200、484,109 bytes），「二、授與權利」原文授權使用者不限目的、非專屬、免授權金進行重製、散布、公開傳輸等利用，並得再轉授權；條件為顯名（manifest 已帶 attribution 與 license URL）。
  - 現有本機 commit 推上 GitHub，CI 加上 macOS。
  - 下載一次 TFDA 官方 CSV ZIP 到 repo 外資料夾，只用離線驗證指令檢查，不發布、不給 MCP 查詢。

### NHI upstream check overdue（2026-09-14）

- `stores.py`：runtime 讀 descriptor 時以 injected clock（`DataContext.clock`，預設 UTC 現在時間；naive datetime 拒絕）計算 overdue：`last_successful_check_at` 為 null，或距今超過 2 個宣告週期（data.gov.tw `updateFrequency` 每 1 日 → 48 小時，剛好 48 小時不算）時，加上 `upstream_check_overdue`。與 descriptor 已存的 reason codes 合併、依 PRD registry 順序排列；status 與 provenance 用同一次計算，stored descriptor／check bytes 不改寫。`freshness_policy_version` 維持 `nhi-v1`（SDD §8.3 原本就定義兩個宣告週期）。
- `adapters/nhi.py`、`server.py` 的 `get_data_status` 都傳入 context clock。
- 測試：`tests/test_freshness.py` 新增 4 個（48 小時邊界、8 天後仍可查、與 `upstream_verification_failed` 合併順序、adapter 經 context clock 產生 warning、naive clock 拒絕）。

### 新版審核包與發布指令（2026-09-14）

- 新增 `src/taiwan_lab_mcp/nhi_review.py` 與 CLI：
  - `taiwan-lab-data prepare-review nhi_fee --data-dir <path> --output-dir <path> [--json]`：只讀 data root。descriptor 必須有 serving build 且 `latest_candidate_status=review_pending`，否則回 `NO_PENDING_CANDIDATE`（exit 5）。重新驗 serving build（`read_nhi_state`）與候選 raw revision（`_load_official_raw_revision`），把 serving build 已核准的 golden cases 重新綁到候選原始檔：raw SHA-256、evidence path、目前 transform、row locator／row hash、expected fields 改為新版實際值，reviewer 欄清空、`review_pending`。逐題比對舊值與新值，分成沒變／有變／新版找不到（找不到的題目不放進 proposed cases）。輸出三個檔：canonical 審核包 `nhi-review-<候選前 12 碼>.json`、白話審核頁 `.md`（含逐題比對、上游 `diff-summary.md`、review protocol 清單、核准步驟）、decision 範本（`decision`、`reviewer_id`、`reviewed_at` 為 null）。
  - `taiwan-lab-data publish nhi_fee --packet <json> --decision <json> --actor <id> --data-dir <path> [--json]`：decision 檔 strict 驗證（固定 10 個 key、帶時區 `reviewed_at`、三關順序、非負整數 finding counts）；`packet_sha256` 必須等於審核包實際 bytes 的 SHA-256；`decision` 必須是 `approved`；核准題號必須都在審核包；descriptor 的 serving 與候選仍須等於審核包（否則 `REVIEW_PACKET_STALE`）。通過後把核准題目與三關 review 交給既有 `build_official_nhi_snapshot`（重新檢查 raw、installed distribution、owner review 無 critical／major、至少 10 題通過），審核包與 decision 檔以 `nhi-review-packet`／`nhi-review-decision` 放進 build 的 `audit/evidence/`。
  - exit code 依 SDD §12：2 輸入／設定、5 review gate、6 integrity／publish。
- 規格解讀（SDD §12 只列 planned `review`／`publish`）：`review` 在 SDD 的語意是驗 `ReviewRecordV1`；本輪的審核包產生器不產生 review record，所以命名為 `prepare-review`，不佔用 `review`。`publish` 沿用 SDD 名稱，並透過既有 builder 重跑全部 preconditions。reviewer 身分只來自 decision 檔，不從互動文字產生。
- 未做：owner 拒絕新版（`decision=rejected`）目前只回 `REVIEW_DECISION_NOT_APPROVED`、不寫任何狀態，候選會維持 `review_pending`；把候選標成 `rejected` 的流程尚未實作。新版找不到的題目需要人工補題，工具不自動挑新題。
- 測試：`tests/test_nhi_review.py` 16 個（審核包逐題比對與只讀、找不到題目、無候選、發布後 serving 切換並查到新點數、7 種無效 decision 在任何寫入前擋下、審核包被改、審核包產生後又出現更新候選、major finding 由 builder 擋下、CLI 成功與 exit 5）。

### NHI 下載包：匯出與安裝指令（2026-09-14）

- 決策與設計見 `docs/adr/0001-nhi-snapshot-release-bundle.md`。
- 新增 `src/taiwan_lab_mcp/snapshot_bundle.py` 與 CLI：
  - `taiwan-lab-data export-snapshot nhi_fee --data-dir <path> --output-dir <path> [--json]`：serving build 必須 runtime 驗證通過且沒有 stale reason，否則 `EXPORT_SERVING_STALE`（exit 5）。輸出固定 bytes 的 ZIP 與 `.sha256`。
  - `taiwan-lab-data install-snapshot nhi_fee --bundle <zip> [--sha256 <hash>] --actor <id> --data-dir <path> [--json]`：寫入前完成全部檢查；同路徑不同內容拒絕覆寫；寫入後驗 raw revision，再經既有 publish CAS 切換。重裝同一包回 `already_installed`。exit code：2 輸入、4 下載包內容、6 衝突或 publish。
- 規格解讀：規格沒寫使用者端的取得與啟用方式（見 ADR 背景）。安裝時 check record 沿用發布者最後一次成功檢查時間，使用者端 48 小時後會看到 `upstream_check_overdue`。
- 測試：`tests/test_snapshot_bundle.py` 14 個（匯出內容只含 raw＋curated、清單 hash、stale 時拒絕匯出、空 data root 安裝後可查、重裝不變、較新包切換並保留 parent、5 種竄改在寫入前擋下、非 ZIP 與整包 SHA-256 不符、既有檔案衝突不覆寫、CLI）。
- ~~尚未做：以「專案負責人」代號重建本機 NHI snapshot（需 owner 再確認）、實際匯出正式下載包、建立 GitHub Release（需 owner 確認實際檔案）。~~ 前兩項已完成（見下方「公開版重建與下載包」）；建立 GitHub Release 仍待 owner 確認實際檔案。

### 公開版重建與下載包（2026-09-14）

- owner 在對話中看過 `owner-review\nhi-public-rebuild-confirmation-2026-09-14.md`（改前／改後原文）後回覆「核准重建」，時間記為 `2026-09-14T21:56:03+08:00`。
- 以修復後的 uv tool 安裝版（`distribution` identity、review protocol 第 2 版）重建：
  - raw revision 不變 `75b33643…`。
  - 10 個 golden cases 取自原 build，只改 reviewer 為「專案負責人」、reviewed_at 為確認時間。
  - 三關 finding counts 不變；SOURCE／SCHEMA 說明不變；PUB 說明改為確認頁上的新文字。
  - evidence 放三個檔：本名改代號的公開版 approved golden 檔 `nhi-golden-approved-2026-09-14-public.json`、原網站核對報告、確認頁。
- 結果：build `nhi_fee-build-76a1402a4dab09361252852e6a8ae0fbd9fa85c0d1ea0feb00a70d8e4b6b55ad`、6,173 rows、DB SHA-256 `659d0c03…`（與原 build bytes 相同）、manifest SHA-256 `fec96b40…`、generation 8、publish event `publish-1993a745…`。新 build 目錄所有檔案逐一搜尋本名：0 筆。舊 build `nhi_fee-build-17880b71…` 保留在 data root，可 rollback。
- 以新的 MCP stdio 行程查詢：`get_points("09006C")` ok、200 點、snapshot 結尾 `0d8e4b6b55ad`、stale false；`get_data_status` nhi_fee available。
- 匯出下載包：`C:\Users\User\Documents\ChatGPT\taiwan-lab-mcp-data\release\nhi_fee-snapshot-76a1402a4dab.zip`，1,630,389 bytes，SHA-256 `aa29a34f1c8399f2aa5938bf057b2568ed02fd0d9fd1397291ebe600bd6a0ec6`，manifest＋13 個檔案；ZIP 內每個檔案搜尋本名：0 筆。
- 試裝：
  - 第一次試裝到 session scratchpad 深層資料夾時，`install-snapshot` 以未處理的 `FileNotFoundError` 當掉。原因是 `audit\evidence\` 暫存檔完整路徑超過 Windows 260 字元上限，已寫入部分檔案，沒有切換 current。
  - 改試裝到 `C:\Users\User\Documents\ChatGPT\taiwan-lab-mcp-data\trial-install`：`installed`、generation 1、寫入 13 檔；再裝一次 `already_installed`、寫入 0 檔；查 `09006C` 200 點、stale false、`local_artifact_available=true`。
- 長路徑修正：
  - `install_nhi_snapshot_bundle` 新增 `max_path_length`（Windows 預設 259，其他平台不限）。寫入任何檔案前，先計算每個目標連同暫存檔名的絕對路徑長度，超過回 `BUNDLE_PATH_TOO_LONG`（exit 2）。
  - 寫檔的 `OSError` 改回 `BUNDLE_WRITE_FAILED`（exit 6），不再丟出 traceback。
  - `docs/install.md` 錯誤表補上這兩個碼。
  - 新增 3 個測試。
  - 深層試裝資料夾留在 scratchpad，未刪除（本機擋刪除指令）。

### Owner 決定：AI 審核、取消 pilot、清理舊資料（2026-09-14）

owner 在 Claude Code 對話中回覆「1A 2A但是給AI審 3A 4B甚至我想取消5-10人串接MCP的測試 直接上線,並且直接由市場來給我回饋 健保表裡面哪些項目算檢驗的範圍清單？這個就是給 AI 幫我去做審理就好了。再來，舊資料就清掉吧。」：

- 1A：TFDA 官方來源身分由 Claude 查證並整理成確認頁，owner 確認後才啟用自動下載。
- 2A（AI 審）：`TFDA-R1-IVD` 醫材分類由 AI 審核。
- 3A：PRD／SDD／TDD 同步 owner 決定。已修改 PRD §8.2 `REL-G5` 列、§8.4 註記、§9 新增「Owner 已決定」表、§11；SDD §17 `D-007`～`D-010`、`D-012` 與 OD 對照表；TDD §16 `REL-G5` 列。原文以刪除線或「保留作歷史」標示，沒有直接刪除。
- 4B＋取消 pilot：不找 5–10 位受測者，改為公開上線並以 GitHub Issues 收集回饋。PRD §8.1 量化 UX 指標因此沒有受測資料，不得宣稱達標。
- `NHI-R1-SCOPE` 檢驗範圍清單由 AI 審核。
- 清掉舊資料。
- 落地要求（寫入 PRD §9）：
  - AI 審核的 review record 必須標明 reviewer 是 AI。
  - 每筆正式結果的 notes 揭露「由 AI 審核，未經人工複核」。
  - 不確定的項目維持 `review_pending`／`ambiguous`／`unknown`。
- NHI scope 分類依據調查：
  - 健保署查詢服務每筆只回 `treaT_CHAP_CODE`。實測 09006C 醣化血紅素、13007C 細菌培養、18001C 心電圖、19001C 腹部超音波同為「第二部第二章第一節」，00101B 門診診察費為「第二部第一章第一節」。
  - 只靠節分不出檢驗與非檢驗，正在另查支付標準官方文件的項目標題與代碼範圍。
- TFDA 官方身分查證（2026-09-14）：
  - 機器讀取資料 `https://data.gov.tw/api/v2/rest/dataset/9576`：HTTP 200、13,375 bytes、SHA-256 `cd96d639…`。
    - `publisherOID=2.16.886.101.20003.20065.20065`、`identifier=A21020000I-000053`、`license="1"`
    - `updateFrequency` 每 7 日、`modifiedDate=2026-09-11 15:57:04`
    - distribution 三筆（CSV／JSON／XML）皆在 `data.fda.gov.tw`。
  - 資料集網頁 `https://data.gov.tw/dataset/9576`：HTTP 200、540,536 bytes、SHA-256 `56ce0132…`。
    - 提供機關「衛生福利部食品藥物管理署」、授權方式「政府資料開放授權條款-第1版」、更新頻率「每7日」、計費「免費」
    - 網頁上沒有 publisherOID。
  - 確認頁：`taiwan-lab-mcp-data\owner-review\tfda-source-identity-confirmation-2026-09-14.md`，待 owner 確認。
- 清理舊資料的模擬：
  - 第一次把 data root 複製到 session scratchpad 後移除舊 build，結果 `data_unavailable`。
  - 推測原因是副本路徑太長（scratchpad 本身約 95 字元），與移除舊 build 無關。
  - 在短路徑重做對照：`%TEMP%\tlsim-a`（完整副本）與 `%TEMP%\tlsim-b`（移除舊 build `17880b71…`）都是 `available`，`09006C` 都是 200 點。從 tlsim-b 重新匯出的下載包 SHA-256 與已發布的 `aa29a34f…` 完全相同。
  - 結論：新 build 不依賴舊 build，可以清掉。
  - 另記風險：data root 放在很深的資料夾時，Windows 260 字元路徑上限會讓 runtime 讀不到 audit evidence，回 `serving_integrity_failure`。安裝時已有路徑長度檢查；自行搬移資料夾的使用者仍可能碰到，安裝說明建議短路徑。
- 清理方式：本機擋刪除指令，因此寫成 owner 雙擊執行的腳本。
  - 腳本：`taiwan-lab-mcp-data\automation\Clear-OldTaiwanLabData.ps1`，桌面啟動檔 `C:\Users\User\Desktop\clear-taiwan-lab-old-data.cmd`。
  - 執行流程：先列清單、要求輸入 Y；舊 build 若仍是 serving 就停止；全部移到資源回收筒（可還原，非永久刪除）；最後以 `taiwan-lab-data status` 確認 nhi_fee 仍 available。
  - 清單：舊 build `17880b71…`、`trial-install`、`trial-install-2`、`release-download-check`、`%TEMP%\tlsim-a`、`tlsim-b`、`tlsim-b-moved`、`tlsim-b-export`。
  - 刻意保留：serving build、raw、checks／publish events、`owner-review` 原始審核紀錄（其中兩個檔含本名，屬 owner 審核原始紀錄，不視為舊版資料）、`release` 正式下載包、`tfda-validation`。

### TFDA 自動下載（2026-09-14）

- owner 看過 `owner-review\tfda-source-identity-confirmation-2026-09-14.md` 後回覆「正確，開始做自動下載」。
- 新增 `src/taiwan_lab_mcp/tfda_source.py`：
  - `discover_tfda_resource`：比對 metadata 的 `publisherOID`（呼叫端明確傳入，owner 確認值 `2.16.886.101.20003.20065.20065`）、`identifier=A21020000I-000053`、`license="1"`；只接受唯一一筆 UTF-8 CSV distribution，下載網址必須是 HTTPS 且 host 為 `data.fda.gov.tw`。
  - `run_tfda_upstream_sync`：metadata 只從 `data.gov.tw` 讀；ZIP 下載上限 64 MiB、content type 限 `application/zip`／`application/octet-stream`。
    - 下載成功即保存 `raw/tfda_devices/<raw revision>/artifacts/source.zip` 與 `fetch.json`。同 bytes 重抓沿用同一 raw revision，不改寫第一份 fetch 紀錄；既有 raw bytes 不同回 `IMMUTABLE_RAW_CONFLICT`。
    - 接著跑既有 ZIP 與 34 欄檢查，只寫 `staged/tfda_devices/<attempt>/validation.json`。discover／fetch 失敗不留 raw；ZIP 或欄位失敗保留 raw。
    - 不建立 candidate、curated、current descriptor，MCP 查不到 TFDA 正式資料。
  - raw revision ID 依 `RawRevisionFingerprintV1`：非揮發 discovery 身分＋ZIP 大小與 SHA-256。
- CLI：`taiwan-lab-data sync tfda_devices --publisher-oid <oid> --data-dir <path> --json`（exit 0 通過、3 discover／fetch 失敗、4 ZIP／欄位失敗）；與 `--input` 互斥。
- 測試：`tests/test_tfda_source.py` 13 個（身分正確、5 種身分漂移、成功保存 raw 與報告、同 bytes 沿用 raw revision、非 ZIP 保留 raw 但失敗、discover／fetch 失敗不留 raw、CLI）。原本 `sync tfda_devices --publisher-oid` 一律拒絕的測試改為「與 `--input` 同時給才拒絕」。
- 儲存量提醒：每份官方 ZIP 約 16 MB，官方每 7 日更新；內容有變才會多存一份 raw。
- 第一次真實下載（2026-09-14 22:4x，uv tool 安裝版）當掉：
  - 解壓時 `MemoryError: Unable to allocate output buffer`，CLI 直接丟 traceback，沒有寫 staged 報告。ZIP 已先保存為 raw revision `aa38597717b13ee18b02e5e203b94b0a7f69e49dba6fb75d3fdd81bdc90a9f8c`（16,265,433 bytes）。
  - 原因是整台電腦可承諾記憶體（commit）幾乎用完：`FreeVirtualMemory` 約 714–790 MB／上限 81,640 MB，實體記憶體仍有 13 GB 空閒。主要占用者：
    - 5 個 `mempalace.mcp_server`（各 3–7 GB private，約 25 GB）
    - WSL `vmmemWSL` 13.8 GB
    - 3 個 `mempalace-mcp --read-only`（各 703 MB）
    - Rojak `vibe_mcp_safe_start.py` 1.4 GB
  - 以上都不是這個專案的行程，沒有結束任何行程。
  - 同一份 ZIP 稍後以離線 `validate` 重跑通過。
  - 量測：解壓峰值約 141 MB；`parse_tfda_csv` 會把 104,619 列、每列 34 欄全部留在記憶體，量測行程在這一步再次 `MemoryError`。
- 修正（commit `2e60fa5`）：
  - `importers/tfda.py` 把逐列檢查抽成串流產生器 `_iter_tfda_records`。`parse_tfda_csv` 仍建立完整列（留給之後建資料庫用）。
  - 新增 `summarize_tfda_csv`，只計數、不保留每列資料；結果與原本「完整解析＋摘要」完全相同，錯誤碼也相同，有測試比對。
  - 離線驗證、上游下載、`validate` CLI 都改用串流摘要；`MemoryError` 回 `RESOURCE_EXHAUSTED`，照常寫失敗報告（CLI 回 JSON、exit 4），不再丟 traceback。
  - 新增 8 個測試（摘要一致、4 種失敗碼一致、上游解壓／摘要兩處記憶體不足、CLI 記憶體不足）。
  - 驗證：repo 內 298 passed（另 2 個為 repo 內舊 `dist/` 已知失敗）；repo 外 wheel 全部測試 298 passed、2 skipped；本機工具以 `uv pip install --python` 就地更新。
- 修正後真實下載重跑（2026-09-14 22:57，本機工具）：
  - exit 0、`passed`；metadata 與 CSV 皆 HTTP 200，ZIP 16,265,433 bytes、SHA-256 `de880620…`。
  - 沿用第一次當掉時已保存的 raw revision `aa385977…`。
  - 104,619 列、93,219 個許可證字號；註銷狀態空白 49,659／已註銷 53,731／已廢止 1,229。
  - 報告：`staged/tfda_devices/20260914T145722Z-d87ce1fa4c074eb69f41cd71b4f7cd97/validation.json`。
- 每日排程加入 TFDA（repo 外 `taiwan-lab-mcp-data\automation\Invoke-NhiDailyCheck.ps1`，同一個 09:30 排程）：
  - 流程：NHI check 之後執行 `taiwan-lab-data sync tfda_devices --publisher-oid <owner 確認值>`。
  - 成功：STATUS 多一行「食藥署醫材資料：下載並檢查通過（N 筆）」。
  - 失敗：寄 TFDA 專用通知信（說明 TFDA 還沒給 MCP 查詢、健保不受影響），STATUS 第一行改為「異常：食藥署醫材資料下載或檢查失敗；…」，原本 NHI 正常時的 exit 0 改為 exit 1。
  - 第一次試跑發現：Windows PowerShell 5.1 的 `ConvertFrom-Json` 不接受空字串 key（TFDA 摘要的 `cancellation_status_counts` 以 `""` 計空白註銷狀態），TFDA 明明通過卻被判失敗。改為依 exit code 判斷成敗，只用文字比對取 `rows`、`stage`、`error_code`。
  - 試跑紀錄（email 皆為 dry-run，沒有真的寄出）：
    - 正常：exit 0、STATUS「OK：健保支付標準表沒有變動」＋「食藥署醫材資料：下載並檢查通過（104,619 筆）」。
    - 故意傳錯 TFDA 發布機關代號：exit 1、STATUS「異常：食藥署醫材資料下載或檢查失敗；健保支付標準表沒有變動」＋「（discover／DISCOVERY_PUBLISHER_MISMATCH／exit=3）；email：試跑成功（沒有真的寄出）」。
    - 之後再跑一次正常流程，STATUS 恢復 OK。

### GitHub Release `nhi-data-20260914`（2026-09-14）

- owner 看過 release notes 草稿（`taiwan-lab-mcp-data\release\release-notes-nhi-data-20260914.md`）與檔名、大小、SHA-256 後回覆「建立 Release」，條件是 CI 全部通過。
- 目標 commit `402246a` 的 CI run `34852852048`：windows-latest、ubuntu-latest（3.10、3.13）、macos-latest 全部 success 後才建立。
- `gh release create nhi-data-20260914 --target 402246ab29caf040e331ee90098848b3e55dd0b3`：https://github.com/masalu0105-gif/taiwan-laboratory-mcp/releases/tag/nhi-data-20260914 ，非 draft、非 prerelease；遠端 tag `refs/tags/nhi-data-20260914` 指向 `402246a`。附件 `nhi_fee-snapshot-76a1402a4dab.zip`（1,630,389 bytes）與 `.sha256`（100 bytes）。
- 從 Release 重新下載到 `taiwan-lab-mcp-data\release-download-check`：`sha256sum -c` OK；安裝到全新資料夾 `taiwan-lab-mcp-data\trial-install-2`：`installed`、generation 1、寫入 13 檔；查 `09006C` 200 點、stale false、snapshot 結尾 `0d8e4b6b55ad`。
- 這是 NHI curated snapshot 的第一次公開散布，不代表 `REL-G5` 使用者試用、`NHI-R1-SCOPE` 或 P1.1 release approval 完成。
- review protocol 第 2 版：新增 package resource `src/taiwan_lab_mcp/review_protocols/nhi-r1-owner-review/2.json`，builder 常數 `OWNER_REVIEW_PROTOCOL_VERSION` 改為 `"2"`。與第 1 版的差異只有：`PUB-R1-OWNER` 範圍改為 `local_mcp_serving_and_github_release_bundle`（依 owner 2026-09-14 選 OD-01 B）、移除「再散布需另行核准」、checklist 加入下載包內容限制（ADR 0001）、公開審核紀錄使用「專案負責人」代號、每次建立 Release 前 owner 確認檔名／大小／SHA-256；另加 `supersedes_version` 與 `reviewer_alias`。來源、格式、golden case 與嚴重度規則和第 1 版完全相同（有測試比對）。第 1 版保留在 package，因為現有 build 的審核紀錄引用它。

### 本機工具重裝失敗與修復（2026-09-14）

- 21:52 以 `uv tool install --force <protocol v2 wheel>` 更新本機工具時失敗：`failed to remove directory ...\uv\tools\taiwan-laboratory-mcp\Scripts: 存取被拒 (os error 5)`。uv 已刪掉整個 `Lib`，但 `Scripts\python.exe` 被兩個執行中的 MCP server 行程占用（`taiwan-lab-mcp.exe` PID 17196、47944，21:32、21:33 由 Claude Code 啟動），刪不掉，環境變成半毀：`taiwan-lab-data.exe --help` 回 `No module named taiwan_lab_mcp`。若未修復，隔天 09:30 排程檢查會失敗。
- 修復方式：不結束任何行程，改用 `uv pip install --python <tool env>\Scripts\python.exe <wheel>` 把套件與相依套件重新裝回同一個環境。
- 之後更新本機工具的做法：MCP server 可能正在執行時，一律用上述 `uv pip install --python ...` 就地重裝，不用 `uv tool install --force`（它會先刪除整個環境）。

### GitHub CI 失敗的更正（2026-09-14）

- 2026-09-14 21:35 查 `gh run list`：從 commit `3238d70` 起，`3238d70`、`17be1f8`、`4353943`、`be5401c` 四次 CI 都是 failure。先前回報「push 成功、local == remote」只驗證了 commit 有推上去，沒有檢查 GitHub CI 結果；本機驗證只在 repo 外跑了 `tests/test_mcp_stdio.py`，沒有照 CI 在 repo 外跑全部測試。
- 失敗點（run `34846439844`，windows-latest，步驟「Verify installed wheel outside repository」）：`tests/test_nhi_importer.py::test_official_build_refuses_development_install_identity` 預期「開發安裝」會被拒絕，但 CI 這一步是用安裝好的 wheel 跑，程式判定為正式安裝，所以沒有拒絕（`DID NOT RAISE`）。本機照 CI 方式在 repo 外跑全部測試可重現：1 failed、258 passed、2 skipped。
- 修正：測試改用 monkeypatch 固定回傳 `development` identity，不再依賴目前的安裝方式。之後每次驗證改為照 CI 在 repo 外跑全部測試，並在 push 後查 CI 結果。修正 commit `1c1d9d6` 的 CI windows-latest job 已 success。
- 同一批 CI 另一個問題：ubuntu／macOS job 在「Test source and MCP stdio」步驟卡住，直到 job 15 分鐘上限被取消（例：run `34846439844` 的 ubuntu job 結尾為 `Terminate orphan process ... (python)`）。原因：`publish._source_lock` 在非 Windows 分支用阻塞式 `fcntl.flock(LOCK_EX)`，沒有 timeout；`tests/test_p1_1_red.py` 的 lock timeout 測試讓子行程持鎖、主行程以 `timeout_seconds=0.0` 取鎖，在 POSIX 會永遠等待。Windows 分支原本就有 bounded retry，所以只有 Windows job 會跑完。SDD §8.2 只寫 POSIX 用 `fcntl.flock(LOCK_EX)`，TDD 要求測 lock timeout；修正為 `LOCK_EX | LOCK_NB` 加上與 Windows 相同的 deadline 重試，逾時回 `PUBLISH_LOCK_TIMEOUT`。POSIX 本機重現（WSL Ubuntu 24.04、系統 Python 3.12.3、lock 檔在 WSL `/tmp`）：以同一情境的探測腳本（子行程持鎖、主行程 `timeout_seconds=0.0`）跑修正前 `git archive HEAD src` 的程式，20 秒後被 `timeout` 終止（exit 124）；跑修正後程式立即回 `PUBLISH_LOCK_TIMEOUT`（0.00 秒），子行程 exit 0。macOS 仍以 CI macos-latest job 驗證。修正 commit `380cec2` 的 CI run `34851536352`：windows-latest（3.13）、ubuntu-latest（3.10、3.13）、macos-latest（3.13）四個 job 全部 success，是 `a144b26` 之後第一次全綠，也是 macOS 第一次在 CI 跑完全部測試與 repo 外 wheel 驗證。

### TFDA 第一個切片：離線 ZIP 驗證（2026-09-14）

依 owner「3B 馬上做」開始 TFDA。範圍依 SDD §10.2、TDD §8.1 與研究文件切片 1，只做不需要 owner 決定的部分；沒有下載官方 TFDA 檔。

- 新增 `src/taiwan_lab_mcp/importers/tfda.py`（internal source id `tfda_devices`，依 SDD §6 與 §11.1 投影表）：
  - `extract_tfda_csv`：先檢查大小（ZIP 64 MiB）與 ZIP magic bytes（HTML 錯誤頁、純 CSV 回 `CONTENT_MAGIC_MISMATCH`），壞檔回 `ARCHIVE_CORRUPT`；恰好一個 entry（`ARCHIVE_ENTRY_COUNT`）；路徑正規化（反斜線視為 `/`）後拒絕 `..`、絕對路徑、UNC、drive path（`ARCHIVE_PATH_TRAVERSAL`）；拒絕目錄、symlink、加密 entry、非 `.csv`（`ARCHIVE_ENTRY_TYPE`）。解壓時以實際讀出的 bytes 計數，超過 256 MiB 回 `ARCHIVE_SIZE_LIMIT`、超過壓縮比 30 回 `ARCHIVE_RATIO_LIMIT`；宣告大小被竄改時由 CRC／大小比對回 `ARCHIVE_CORRUPT`。只在記憶體處理，不把 server 檔名寫到磁碟。
  - `parse_tfda_csv`：`utf-8-sig`、strict CSV、header 必須完全等於研究文件第 5 節的 34 欄（測試直接比對研究文件 header 原文）；錯誤碼沿用 NHI parser 命名（`SCHEMA_HEADER_MISMATCH`、`SCHEMA_DUPLICATE_COLUMN`、`ROW_WIDTH_MISMATCH`、`ZERO_ROWS` 等）。所有欄位保留原字串（統編前導零、級數、許可證種類 `09` 不轉數字、規格內換行保留）。`source_row_sha256` 依 SDD §7.2 以 34 欄原值 JSON array 計算；同許可證字號多列全部保留。
  - `tfda_validation_summary`：列數、不同許可證字號數、多列字號數、單一字號最多列數、註銷狀態原值分布、各欄空值數、header hash、ZIP／entry 大小與 SHA-256。
  - `run_tfda_offline_validation`：只寫 `staged/tfda_devices/<attempt>/validation.json`；離線輸入沒有上游來源證明，不建立 raw、candidate、curated 或 current descriptor（與 NHI `--input` 相同規則）。
- CLI：`taiwan-lab-data validate tfda_devices --input <zip> --json`（exit 0／4）與 `taiwan-lab-data sync tfda_devices --input <zip> --data-dir <path> --json`；TFDA 帶 `--publisher-oid`、`--metadata-url` 或 `--fail-stage` 時直接拒絕。
- 規格解讀（保守做法，待文件修訂或 owner 確認）：
  1. 日期欄（註銷日期、有效日期、發證日期、異動日期）只接受空字串或 strict `YYYY/MM/DD`，前後空白也算無效，整批 block（SDD §10.2「日期只接受 empty 或 YYYY/MM/DD」）；有效日期空白整批 block（PRD §6.3.1）。研究文件「發證日期晚於有效日期進 quarantine」SDD／TDD 沒有，本輪不實作。
  2. 許可證字號空白整批 block（研究文件 §7 列為 quarantine；目前 publish 規則 quarantine 必須為 0，等同 block）。
  3. 「恰好一個非目錄 entry」解讀為 archive 只能有一個 entry，連目錄 entry 也不允許。壓縮比剛好 30 通過、超過才拒絕；比例以 entry 解壓 bytes ÷ entry 壓縮 bytes 計算。
  4. entry 名稱只要求 `.csv` 副檔名，不要求一定是 `68_2.csv`。
- 未做（依規格需要 owner 決定或屬後續切片）：TFDA live 下載（publisher OID、metadata API、license 代碼、host allowlist 文件都沒寫）、raw 保存、註銷／效期 truth table、三組分類 code 解析、IVD registry（`TFDA-R1-IVD` reviewer 未指定，OD-03）、curated SQLite、public contract 補欄位（TFDARecord 缺 PRD 要求欄位、warning registry 缺 TFDA codes）、official adapter、golden cases。這一片不代表 `REL-G2` 或任何 TFDA gate 完成。
- 測試：`tests/test_tfda_importer.py` 42 個（研究 header 比對、字串與 row hash、多列字號、摘要數字、magic bytes、截斷 ZIP、10 種 entry 規則、反斜線路徑、解壓上限剛好等於與超過、壓縮檔上限、壓縮比、宣告大小竄改、16 種 CSV／日期／必填失敗、無 BOM 警告、staged 報告只寫 staged、失敗報告、CLI）。
- 官方檔一次性驗證（owner 同意）：2026-09-14 21:32 以 curl 下載 `https://data.fda.gov.tw/data/opendata/export/68/csv`（HTTP 200、`application/zip`、無 redirect），存於 repo 外 `C:\Users\User\Documents\ChatGPT\taiwan-lab-mcp-data\tfda-validation\tfda-68-csv-20260914.zip`（16,265,433 bytes、SHA-256 `de880620c56177e492806618f103fc7ac55b4f7302e7870c9992facba7f08292`，與研究文件 2026-09-13 的 ZIP hash 相同）。以 uv tool 安裝版 `taiwan-lab-data validate tfda_devices --input ... --json` 檢查：exit 0、`passed`；entry `68_2.csv` 70,554,601 bytes、SHA-256 `bce64d9276d1072ce9b52c098bbd943184a357d1dcff2cab722e75ddb5d5c370`；104,619 列、93,219 個許可證字號、11,229 個字號有多列、單一字號最多 4 列；註銷狀態空白 49,659／已註銷 53,731／已廢止 1,229；空值數 註銷日期 49,543、註銷理由 53,879、舊證字號 103,615、醫療器材級數 11,439、劑型 104,619、包裝 104,432、申請商名稱 1、申請商統一編號 794、製造廠國別 25，均與研究文件 §5／§6 實測值一致；四個日期欄沒有格式錯誤、有效日期沒有空白。輸出存於同資料夾 `validate-20260914.json`。這只是離線檢查，沒有建立 raw revision、candidate 或任何 MCP 可查的資料。

### 健保「哪些項目算檢驗」AI 審核（2026-09-14）

- owner 決定：
  - `NHI-R1-SCOPE` 由 AI 審核（見上方「Owner 決定：AI 審核、取消 pilot、清理舊資料」）。
  - owner 另說「哪些項目算檢驗，你不需要幫我加上備註」，所以結果 notes 不加 AI 審核備註（PRD OD-02 已以刪除線標示）。
- 審核紀錄（依據文件、判定標準、逐項與逐碼結果、與衛福部值集差異）：`docs/reviews/nhi-lab-scope-ai-review-2026-09-14.md`。
- 規格解讀：
  - 規則版本改為 `nhi-lab-scope-v2`，保留 v1 空規則檔作歷史，理由是規則檔內容與 hash 綁在 build fingerprint。
  - `coverage_status=complete` 的條件是 build 內每一列都有核准規則；manifest `capability_reviews` 的 `NHI-R1-SCOPE` 依此寫 `approved` 或 `pending`，runtime 讀 manifest 並再確認沒有 `review_pending` 列。
  - SDD 沒寫這個判斷方式，這是依 SDD「Capability gate核准會改rule bundle與curated build ID，必須新build後才能變成complete」的實作解讀。
- 判定標準由 AI reviewer 自訂，寫在規則檔 `note`：取自病人的檢體在實驗室進行的檢查算檢驗；在病人身上進行的檢查、採檢處置、計畫管理費與治療不算；官方文字沒說明檢查對象與方法的留 `review_pending`。
- 依據與對照資料（repo 外 `taiwan-lab-mcp-data\nhi-scope-research\`）：
  - 支付標準 ZIP：`dl-99892-…-1.zip`，9,243,815 bytes，SHA-256 `09f3dcf8…`。
  - 第二部第二章第一節 doc：SHA-256 `410d4159…`。
  - 衛福部 TW Core「檢驗值集」2022-07-01：`twcore-ValueSet-laboratory-category-tw-2022-07-01.json`，41,674 bytes，SHA-256 `cf01d953af43bb58cd9b49412e88de4043a207b798eb224c1c659c60d8049dfa`，只作對照。
  - 產生規則檔的腳本：`build_scope_bundle.py`，SHA-256 `be4e7c29…`。
- 結果：6,173 碼中算檢驗 959、不算 5,212、無法判定 2。無法判定的是 30011B 黴菌平板試驗、30505B 電氣解析術，支付標準與 CSV 都沒有說明，網路搜尋也沒找到。
  - 因為這 2 碼，正式資料重建後 `coverage_status` 仍是 `review_incomplete`。
- 產出：
  - `src/taiwan_lab_mcp/rules/nhi_lab_scope/v2.json`：3,592,558 bytes，SHA-256 `37d52b6e…`。
  - owner 可讀清單 `taiwan-lab-mcp-data\owner-review\nhi-lab-scope-list-2026-09-14.csv`：UTF-8 BOM，1,963,434 bytes，SHA-256 `dbffcb1f…`。
- 程式改動：
  - `rules/nhi.py` 接受 v1／v2，並要求每筆規則版本等於規則檔版本。
  - importer 的 transform、curated row、manifest capability status 與 golden case 預期 warnings 改為依規則與列涵蓋度計算。
  - `stores.py` 的 `rule_bundle_version` 與 `coverage_status` 改讀 manifest，不再寫死。
  - 審核包重綁 golden cases 時同步更新 `expected_warnings`，有變化時列在逐題比對。
- 測試：
  - 新增 `tests/test_nhi_scope.py` 5 個：規則檔版本與 AI reviewer、版本不一致拒絕、全列有規則時 `complete`、缺規則時 `review_incomplete`、golden warnings 跟著涵蓋度。
  - 新增 `tests/test_nhi_review.py` 1 個：審核包重綁 warnings。
  - 依新行為更新 3 個既有測試：stdio 單列 09006C 變 `complete`、alias 搜尋兩列 scope、package 必含 v1／v2 規則檔。
- 驗證：
  - in-repo `pytest` 306 passed（`TAIWAN_LAB_ARTIFACT_DIR` 指向新 build）。
  - `ruff check`／`ruff format --check src tests` 通過；`git diff --check` 通過。
  - `uv build` wheel 241,407 bytes（50 檔，SHA-256 `7f781b54…`）、sdist 462,393 bytes（102 檔）。
  - repo 外 venv 安裝 wheel，在 repo 外 cwd 以 `--import-mode=importlib` 跑全部測試：306 passed，import 路徑為該 venv site-packages。
  - 安裝後 contract 101,746 bytes 與 repo 相同；stdio discovery 22 個工具，名稱與 contract operations 相同。
- 尚未做：
  - 本機 serving build 與已發布的 `nhi-data-20260914` 仍是 v1 規則，全部 `review_pending`。
  - 用 v2 重建 serving、發新 Release，都需要 owner 確認。
  - 30011B、30505B 待有官方說明或 owner 知道內容後再判。
- CI：commit `7a298a1` 的 GitHub Actions run `34863292781` 四個 job（ubuntu 3.10／3.13、windows 3.13、macos 3.13）皆 success。

### Owner 決定：判不出來的一律納入，並核准重建（2026-09-14）

- owner 在 Claude Code 對話中回覆（2026-09-14T23:43:38+08:00，transcript timestamp `2026-09-14T15:43:38.595Z`）：
  - 原話：「核准重建 我覺得說不定喔，那個你找不出來的，或者是你不知道要判到底是不是的，你就給他放進去。我們寧可錯殺一百，也不要放過一個。」
- 落地：
  - PRD OD-02／OD-03 與 SDD D-009／D-010 以刪除線保留舊規則，改為「判不出來的一律納入，依據寫明依 owner 決定」。
  - 規格解讀：這個決定只套用在本次逐碼審核判不出來的代碼（NHI 30011B、30505B；TFDA 附表判不出來 17 碼與附表查無 3 碼）。沒有 A–P 分類代碼或舊制編號的 TFDA 許可證列涵蓋各類醫材，未套用，仍為 `unknown`，待 owner 決定。
- NHI 規則檔改判：
  - `nhi-lab-scope-v2` 改為 961 in／5,212 out／0 pending，`status=complete`。
  - commit `33a7bdb`：`v2.json` 3,592,715 bytes，SHA-256 `6b4ec1b1a241aa5419368c17e8de544c8173bf7849cbea97a3751d95e6f52a5c`。
  - v2 第一版（`7a298a1`）沒有被任何 build 或 Release 使用，所以沿用版本名，沒有另開 v3。
  - owner 清單重產：1,963,542 bytes，SHA-256 `122b2cfb…`。
- TFDA 決議檔改判：
  - 附表 548 項中 538 算 IVD、13 不算；附表查無的 3 碼也算 IVD。
  - 決議檔 461,561 bytes，SHA-256 `ab83604b…`。
  - owner 清單 265,331 bytes，SHA-256 `7797cfae…`。
  - 產生腳本 SHA-256 `7e7cb91e…`。
- 重建：
  - 新 wheel（`uv build`，SHA-256 `de908043…`）以 `uv pip install --python <uv tool python> --reinstall-package` 裝進 uv tool 環境；identity 為 `distribution`，規則檔 `complete`、6,173 筆。
  - 重建腳本 `taiwan-lab-mcp-data\automation\rebuild_nhi_scope_v2.py`（SHA-256 `94c0c439…`），先 dry run 印出 10 題改前→改後，再 `--apply`。
  - golden cases：沿用原 build 的 10 題，只改 `transform`、`expected_fields.scope_status`、`expected_warnings`（`["coverage_review_incomplete"]`→`[]`）與 `reviewed_at`（owner 回覆時間）。reviewer 仍為「專案負責人」。
  - 三關 review：SOURCE 不變；SCHEMA、PUB 原文加一句以 v2 重建，`reviewed_at` 改為 owner 回覆時間；finding counts 不變。
  - evidence：
    - `nhi-golden-approved-2026-09-14-scope-v2.json`（SHA-256 `91d912e4…`）
    - 原網站核對報告
    - 重建紀錄 `owner-review\nhi-scope-v2-rebuild-confirmation-2026-09-14.md`（SHA-256 `88ccfbdc…`）
  - 結果：
    - build `nhi_fee-build-4ecd71e74f3bc4444a18eabba990fec318915f9bf8a4423769e457bdfe9ebe98`，6,173 rows。
    - DB SHA-256 `f315aae1…`，manifest SHA-256 `07964d45…`。
    - generation 13，publish event `publish-4fd9673c…`。
    - 舊 build `76a1402a…` 保留可 rollback。
  - 已知不一致：review protocol 第 2 版要求 golden cases 涵蓋「scope pending」情境；依 owner 決定已沒有 pending 代碼，無法涵蓋。protocol 未修改，已寫進重建紀錄。
- 重建後以 uv tool 的 MCP stdio 行程查詢：
  - 09006C：200 點、`in_scope`、`nhi-lab-scope-v2`、`coverage_status=complete`、warnings 空、stale false。
  - 18001C：`out_of_scope`。
  - 30011B：`in_scope`，locator 寫明依 owner 決定。
  - 64：`in_scope`。
  - `get_data_status` 的 nhi_fee 為 available、complete。
- 新下載包：
  - `export-snapshot` 輸出 `taiwan-lab-mcp-data\release\nhi_fee-snapshot-4ecd71e74f3b.zip`：1,718,253 bytes，SHA-256 `9642f2ca0eb0b9a29d392072d8325cee00fd0c9e18457eb613341c8f9bd3e6d6`，manifest＋13 檔。
  - ZIP 內每個檔案搜尋 owner 本名：0 筆。
  - 試裝到 `%TEMP%\tlv2`（帶 `--sha256`）：`installed`、generation 1、寫入 13 檔；查 09006C 為 200 點、`in_scope`、`complete`、warnings 空。試裝資料夾未刪除（本機擋刪除指令）。
- 相容性：
  - 舊 Release `nhi-data-20260914` 的 tag 指向 `402246a`。那版程式把 `rule_bundle_version` 寫死為 v1、`coverage_status` 寫死為 `review_incomplete`。
  - 新下載包要搭配含 v2 程式的新 tag，安裝說明因此改寫為「程式與資料包都換成同一個新 Release」。
- ~~尚未做：建立新的 GitHub Release，需 owner 確認 tag 名稱、檔名、大小、SHA-256。~~ 已完成，見下節。

### GitHub Release `nhi-data-20260914-lab-scope`（2026-09-14）

- owner 看過 tag 名稱、對應 commit、檔名、大小、SHA-256 與說明草稿後，在對話中回覆「建立 Release」。
- 發布內容：
  - `gh release create nhi-data-20260914-lab-scope --target 0fbb58d…`，title「健保支付標準審核版資料：加上算不算檢驗判定（2026-09-14）」。
  - 說明文字取自 `taiwan-lab-mcp-data\release\release-notes-nhi-data-20260914-lab-scope.md`。
  - 附件：`nhi_fee-snapshot-4ecd71e74f3b.zip`（1,718,253 bytes）與 `.sha256`（100 bytes）。
- 驗證：
  - `gh release view`：非 draft，tag 指向 `0fbb58da7be0651022cbfe5eba9ab7e1d07ce845`（`git rev-parse` 相同）。`gh release list` 顯示此版為 Latest，舊版 `nhi-data-20260914` 保留。
  - 重新下載到 session scratchpad：ZIP SHA-256 `9642f2ca0eb0b9a29d392072d8325cee00fd0c9e18457eb613341c8f9bd3e6d6`，與本機檔及 `.sha256` 內容一致。
- 第一次執行時，同一串指令前段的 `gh release view --json isLatest` 欄位不存在而中止，Release 沒有建立。改用 `gh release list` 後重跑才建立，只建了一次。

### 食藥署沒有分類代碼的許可證列：數量評估（2026-09-14）

- owner 決定：舊制那些「維持現狀」，並要求先評估數量、是否影響搜尋。本節只統計，沒有改任何判定。
- 統計對象：官方 ZIP `tfda-68-csv-20260914.zip` 共 104,619 列，其中 17,606 列三個「醫器次類別」都沒有 A–P 代碼。
  - 17,605 列次類別空白。
  - 1 列是小寫 `d.5630 噴霧器`。
- 依「醫器主類別」分組：

| 組別 | 列數 | 許可證字號數 | 仍有效（註銷狀態空白） | 品名像 IVD（關鍵字，僅供估計） | 其中仍有效 |
|---|---:|---:|---:|---:|---:|
| 主類別是 A／B／C | 2,211 | 1,951 | 641 | 1,783 | 525 |
| 主類別是 D–P 其他大類 | 5,668 | 5,150 | 1,630 | 50 | 8 |
| 舊制四位數字主類別 | 9,337 | 9,233 | 253 | 119 | 0 |
| 主類別也沒有（或只有 `E000` 這類無名稱代碼） | 389 | 360 | 52 | 11 | 0 |

- 例子：
  - 主類別 A／B／C 的有效列：「“百得” 胃蛋白酶原Ⅰ酵素免疫檢測試劑」「亞培設計師總甲狀腺素檢驗試劑組」。
  - D–P 的有效列：「“星歐”拋棄式軟性隱形眼鏡」「“先健科技公司”赫特爾心房間隔缺損封堵器」。
  - 舊制的有效列：「牙科用注射針」「"柯惠" ＧＩＡ自動手術縫合器」。
- 品名關鍵字只用來估計比例，不是判定依據。

### Owner 決定：TFDA 全收錄、標籤與查詢方式（2026-09-15，OD-06／D-015）

- 過程：
  - owner 先說：「全部都要收…那 10 萬多筆全部都要收，全部都要找得到。只是你要再去稍微打標籤，然後再讓它去依照標籤去分它的權重吧」，並提到非 IVD 產業（例如競品比較）也要能用這個資料庫。
  - Claude 提出 A／B 兩案：
    - A：預設依命中程度、不偏類別，由 host AI 依使用者問法指定偏好或篩選。
    - B：server 固定依標籤加權，IVD 永遠在前。
  - owner 回覆「A 這樣才有做 data 清理的意義在啊，對吧？」。
- 已同步：
  - PRD：§5 工具表 `list_matching_license_records` 列、新增 TFDA-06、Owner 決定表新增 OD-06。
  - SDD：§10.2 查詢規則、`D-015`、OD 對照表 `OD-06`；並修正 `OD-02` 列已過期的「2碼仍review_pending」。
  - TDD：§8 分頁與排序測試、stdio 工具簽名。
  - 舊文字以刪除線保留。
- 規格解讀（owner 未逐項指定，依 A 案內容落地）：
  - 「權重」實作為排序 key 中的 `preference_miss`，只在同一命中程度內調整順序，不改變 `total_matches`。
  - server 不從 query 文字猜意圖。
  - 缺分類代碼的 17,606 列依 owner 2026-09-14「舊制那些維持現狀」維持 `unknown`，與 TDD「主類別 A／B／C 本身不得讓資料變成 IVD」一致。
  - 「官方註銷欄空白者在前」只是排序，不得稱為有效許可（PRD TFDA-02）。
  - 可並排原始欄位供使用者自行比較；`compare_products` 維持 deprecated，不輸出優劣、等效或可替代，這是原始 goal 的限制。
- 尚未實作：TFDA curated build、IVD registry 入 repo、adapter、contract 新參數、TFDA 三關審核與下載包（下載包上限 64 MiB 需調整）。

### 資料庫型 MCP 踩坑調查與 owner 決定 A（2026-09-15）

- owner 要求上網找「建置這樣子 database 的 MCP」別人踩過的坑。
- 調查方式：派三個 sonnet subagent，分三個方向：MCP 限制、中文搜尋與更新、安全與法規。
- 主 session 自行重新核對的部分：
  - Claude Code 文件「warning when MCP tool output exceeds 10,000 tokens and limits output to 25,000 tokens by default」。
  - MCP tools 規格「a tool that returns structured content SHOULD also return the serialized JSON in a TextContent block」。
  - SQLite FTS5「Substrings consisting of fewer than 3 unicode characters do not match any…」。
  - `uri.html` 的 `SQLITE_CORRUPT` 段落。
  - 政府資料開放授權條款第三條（二）與附件顯名聲明格式。
  - 醫療器材管理法第 40、45、46 條。
  - 個資會 113 年函釋（公司法人或工商行號名稱、地址非個資，涉及負責人等自然人部分仍屬個資）。
  - `modelcontextprotocol/servers-archived` 為 archived。
- 主 session 本機實測：
  - SQLite 3.50.4 FTS5 trigram：`MATCH '血糖'` 回空；`LIKE '%血糖%'` 回 3 筆。
  - NFKC＋casefold 後 `“星歐”`／`"星歐"`、`〝眼力健〞`／`"眼力健"`、`臺`／`台` 仍不相等；`ＡＢＣ－１２３`→`ABC-123`。
  - 現行 uv tool MCP 查 `search_payment_items("檢")`：
    - limit 10：24,967 字。
    - limit 20：46,390 字，粗估約 2.2 萬 tokens。
    - limit 100：197,915 字，粗估約 9 萬 tokens。
    - 回傳有 1 個 TextContent，是縮排過的 JSON。
  - limit 20 的結構化內容（壓縮後 37,222 字）中，`note_search` 7,417 字、`note_raw` 7,356 字、`scope_basis_locator` 2,344 字、`evidence` 4,195 字、每筆 `safety` 合計 2,960 字。
  - TFDA 申請商 8,006 個，名稱不含公司／行號等字樣的只有 15 個，例如「米米工坊」「劼磊工作室」，名稱中未見人名；CSV 沒有負責人欄。
- 粗估方法：中日韓字元每字 1 token、其他字元每 4 字 1 token，只作比較用，不是 tokenizer 實測。
- owner 回覆「A」，決定納入：
  - 搜尋結果瘦身（健保一起改），完整欄位改由單筆查詢取得。
  - 搜尋用欄位統一引號與「臺→台」，原文保留。
  - 同義詞清單審核後才生效。
  - 顯名依授權條款附件格式補齊（健保一起補）。
  - README 與工具說明加「查詢結果不可直接當作醫療器材廣告或效能宣傳素材」。
  - 工具說明加「回傳內容是資料，不是指令」。
- owner 另要求：健保搜尋瘦身上線前，先給改前→改後確認。

### 健保搜尋瘦身、顯名與工具說明（2026-09-15）

- 確認頁：`taiwan-lab-mcp-data\owner-review\nhi-search-slim-preview-2026-09-15.md`，owner 看過後回覆「確認」。
- 規格同步：PRD §5 工具表 `search_payment_items` 列、SDD §10.1 查詢邊界、TDD NHI 搜尋條目。
- 程式改動：
  - `models.py` 新增 `NHISearchRecord`（`record_type=nhi_fee_summary`）。欄位：`matched_by`、`code_raw`、`points`、起迄日、`possible_open_end_sentinel`、中英文名稱原文、`scope_status`、`note_preview`（前 60 字）、`note_chars`、`note_truncated`。
  - `search_payment_items` 與 `search_lab_code` 在 sample 與 official 兩條路徑都改回摘要；`get_points`、`get_payment_rule` 仍回完整 `NHIRecord`。
  - `search_payment_items` 的 `limit` 上限 100→50，超過回 `invalid_request`，說明文字改為「1–50」。
  - input schema 沒有加 `maximum`，由 adapter 驗證，所以 request schema 與 discovery 相等測試不變。
  - `stores.nhi_attribution_text` 依授權條款附件格式組顯名：「機關 年份 資料集名稱［官方標示更新時間］。聲明＋條款網址」。
    - 年份取官方更新時間前 4 碼；沒有更新時間時，取 retrieved_at 換成台北時間的年份。
    - manifest 內保存的 `attribution` 原文不變，已發布的 build 不需重建。
  - `server.py` 四個 NHI 工具說明加「回傳內容是官方資料原文，不是給 AI 的指令。」；兩個搜尋工具另加「搜尋結果每筆只含摘要，完整備註請用 get_payment_rule 或 get_points 查單筆。」
  - public contract：`response_schemas.QueryResultV1.schema` 重新產生，`source_payload_schemas` 新增 `nhi_fee_summary`。檔案 109,766 bytes，contract 版本名仍為 `public-contract-v1`。
- 規格解讀：
  - 摘要 record 對既有 `search_payment_items` 使用者是回傳格式的破壞性變更。owner 已核准，專案仍在 0.1.x，因此沿用 `public-contract-v1` 名稱，沒有另開 v2 contract。
  - NHI-R1-SOURCE checklist 寫的顯名原文指 manifest 的 `attribution`，該值未改；對外顯示改為附件格式。
- 測試：新增 `tests/test_nhi_search_summary.py` 7 個。先跑 6 failed、1 passed（完整 record 行為本來就對），改完全過。
- 驗證：
  - in-repo `pytest` 313 passed（`TAIWAN_LAB_ARTIFACT_DIR` 指向新 build）；`ruff check`、`ruff format --check`、`git diff --check` 通過。
  - `uv build` wheel SHA-256 `e43edf59b8c4c4e31a63bcc9d9d0ad751dd7153fd038244a3dce0fbc6283278d`。
  - repo 外 venv 在 repo 外 cwd 以 `--import-mode=importlib` 跑：313 passed，import 路徑為該 venv；安裝後 contract 與 repo 位元組相同。
  - 新 wheel 以 `uv pip install --reinstall-package` 裝進 uv tool 環境。用 MCP stdio 查正式資料：
    - 「檢」20 筆：26,264 字，粗估約 7,625 tokens（確認頁預估 21,600 字／約 6,400）。
    - 「檢」50 筆：60,814 字，粗估約 17,821 tokens（預估 49,400 字／約 14,900）。
    - 「醣化」13 筆：17,865 字。
    - `limit=51`：`invalid_request`。
    - 00193C 摘要：`note_chars=360`、`note_truncated=true`；`get_payment_rule("00193C")` 仍回 360 字全文。
    - 顯名：「衛生福利部中央健康保險署 2026 醫療服務給付項目及支付標準(csv檔) 官方標示更新時間 2026-09-14 07:05:47。此開放資料依政府資料開放授權條款…」。
  - 實測比預估多約 20%：確認頁模擬時把每筆出處簡化成列號＋雜湊，實作沿用原本完整出處格式（artifact id、locator、`raw_value_available`），另外顯名文字變長。50 筆仍低於 Claude Code 25,000 tokens 截斷上限。
- 尚未做：
  - GitHub Release 下載包說明與 README 顯名文字，下次發 Release 時一起更新。
  - 食藥署查詢照同樣原則實作。

### 搜尋一次最多 20 筆（2026-09-15）

- owner 看完瘦身結果後回覆「我覺得給20筆就很夠了」。
- 規格解讀：套用在健保 `search_payment_items`（`search_lab_code` 本來固定 20 筆），以及尚未實作的 TFDA `list_matching_license_records`（PRD TFDA-06、TDD 分頁條目）。其他 TFDA 搜尋工具目前仍是 sample 骨架，這次沒動。
- 改動：
  - `adapters/nhi.py` 的 `SEARCH_PAGE_MAX` 50→20，說明文字改為「limit 為 1–20 的整數」。
  - PRD §5 工具表與 TFDA-06、SDD §10.1、TDD 兩處、README 同步。
  - 前一節「上限 100→50」保留作歷史。
- 測試：`test_nhi_search_summary.py` 改為測 `limit=20` 可用、`limit=21` 回 `invalid_request`。先跑 1 failed、6 passed，改完全過。
- 驗證：
  - in-repo `pytest` 313 passed，`TAIWAN_LAB_ARTIFACT_DIR` 指向新 build；`ruff check`、`ruff format --check`、`git diff --check` 通過。
  - wheel SHA-256 `2801c40908ec99c7a1b89ed581de78ca94e13417456e88e2cce39c68741cbd14`。
  - repo 外 venv、repo 外 cwd 以 `--import-mode=importlib` 跑：313 passed。
  - 新 wheel 以 `uv pip install --reinstall-package` 裝進 uv tool 環境，MCP stdio 查正式資料：
    - 「檢」`limit=20`：回 20 筆，總共 1,270 筆，`truncated=true`，26,264 字（粗估約 7,625 tokens）。
    - 「檢」`limit=20, offset=1260`：回最後 10 筆，`truncated=false`。
    - `limit=21`：`invalid_request`。

### 食藥署許可證查詢：資料庫建置與摘要搜尋（2026-09-15）

- owner 要求：「開始做食藥署許可證查詢。10 萬多筆全收錄並加上標籤；搜尋每筆只回摘要，一次最多 20 筆」。
- 依據：PRD TFDA-01～06 與 §6.3.1、SDD §10.2 與 D-015、TDD §8、上方 OD-06 與研究決定 A。
- 程式改動：
  - IVD 判定清單入庫：`src/taiwan_lab_mcp/rules/tfda_ivd/v1.json`（551 碼，全部 `approved`，reviewer `ai-reviewer:claude-opus-5`），由 repo 外 `tfda-ivd-research\build_ivd_registry.py` 從決議檔（SHA-256 `ab83604b…`）產生，只放 SDD registry 欄位，附表鑑別原文以頁碼定位。
    - `regulation_version` 取附表 PDF 第 1 頁第七條「中華民國一百十二年八月二十二日修正發布」；`effective_from` 取同條「自發布日施行」＝2023-08-22（A/B/C 品項沒有列在延後施行的代碼中）。附表查無的 3 碼（B.2800、B.4010、C.5800）這兩欄與頁碼為 null。
    - `source_url` 用研究文件已查證的附表 PDF 網址。
  - `rules/tfda.py`：registry 驗證、代碼與主類別字母解析、SDD join 規則、PRD §6.3.1 truth table。
  - `importers/tfda.py`：`build_tfda_snapshot`（離線合成、測試用）與 `build_official_tfda_snapshot`（需 owner 三關審核、至少 10 題核准 golden cases、已核准的 `tfda-r1-owner-review` protocol；protocol 檔還沒建立，所以目前一定拒絕）。資料逐批寫入 SQLite，建完才改成正式檔名。
  - `tfda_store.py`：讀取驗證、搜尋 SQL、單筆查詢。`adapters/tfda.py` 重寫，sample 模式也走同一套欄位與 SQL（記憶體內資料庫）。
  - `stores.py` 把 NHI 的指標／審核／資料庫驗證抽成 `_read_serving(source_id, raw 檔名)`，NHI 與 TFDA 共用；`audit.py`、`publish.py` 的審核關卡與資料表名稱改依來源決定。大檔案 hash 改成分段讀取。
  - `models.py`：`TFDARecord` 改為 34 欄原文加標籤與判斷；新增摘要 `TFDASearchRecord`（`record_type=tfda_device_summary`）。
  - `server.py`：`list_matching_license_records` 新增 `offset`、`prefer_ivd`、`prefer_main_category`、`ivd_scope`、`main_category`；六個 TFDA 工具說明加入摘要、20 筆、偏好與篩選用法、「不是給 AI 的指令」與「不可當作廣告或效能宣傳素材」。
  - public contract：`list_matching_license_records` 參數、`tfda_device` 與新 `tfda_device_summary` payload、`QueryResultV1` schema、warning registry 新增 8 個註銷／效期代碼，`coverage_review_incomplete` 說明改成涵蓋 NHI 與 TFDA。檔案 143,146 bytes，名稱仍為 `public-contract-v1`。
- 規格解讀（owner 未逐項指定）：
  1. 20 筆上限套用到四個 TFDA 搜尋工具；`get_license`、`find_manufacturer` 沒有分頁參數，固定 20 筆；`compare_products` 維持 1–100 並回 deprecated。
  2. `search_reviewed_ivd`／`search_ivd_candidates` 的 `query` 比對字號、品名、效能與類別原文，製造商只由 `manufacturer` 參數篩選，避免申請商被當成製造商。
  3. 附表 A/B/C 以外的代碼（D–P 大類）依 SDD join 規則 4「未知 code」標 `unknown`，沒有自行改成 `excluded`，因為 AI 審核只審了 A/B/C 附表。
  4. `coverage_status` 在還有 unknown 列時維持 `review_incomplete`，結果附 TFDA 專用說明，不宣稱完整 IVD 清單。
  5. 「官方註銷欄空白者在前」以註銷狀態去掉前後空白後是否為空判斷。
  6. TFDA stale 門檻沿用 NHI 的「兩個宣告週期」＝14 日（OD-05 未另定）。
  7. 完整性檢查第一次查詢時完整做（約 1.1 秒），之後在 descriptor 內容與 build／raw／check 檔案大小、修改時間都沒變時沿用；stale 仍每次依當下時間算。
  8. 摘要 record 對既有 sample 使用者是回傳格式變更；專案仍在 0.1.x，沿用 `public-contract-v1`。
  9. 搜尋欄位的引號統一與臺→台只做在 TFDA；健保已發布的資料庫沒有重建，這次不動。
  10. 同義詞清單：目前沒有經審核的同義詞，所以沒有做同義詞比對。
- 測試：新增 `tests/test_tfda_ivd_registry.py` 15 個（先 1 error 後 green）、`tests/test_tfda_official.py` 33 個（先 1 error 後 green）；`test_package_contents.py` 必要檔加入 `rules/tfda_ivd/v1.json`。
- 驗證：
  - in-repo `pytest` 361 passed（`TAIWAN_LAB_ARTIFACT_DIR` 指向新 build）；`ruff check`、`ruff format --check`、`git diff --check` 通過。
  - `uv build`：wheel 295,610 bytes、53 檔，SHA-256 `e8f9d872b07209c275416aa539738fcca7bbb0142786303436413cc2e51c564c`；sdist 543,642 bytes、110 檔；兩者都沒有 SQLite、ZIP、raw 或 `uv.lock`。
  - repo 外 venv、repo 外 cwd 以 `--import-mode=importlib` 跑：359 passed、2 skipped（package 檢查沒有指定 build 資料夾），import 路徑為該 venv；安裝後 contract 與 repo 位元組相同（143,146 bytes）。
  - 真實資料試建（不是正式發布）：用 2026-09-14 官方 ZIP（SHA-256 `de880620…`）以 `build_tfda_snapshot` 建到 `%TEMP%\tfdarc`，審核紀錄是測試用 `offline-test-builder`，不在正式 data root、不給本機工具使用。
    - 104,619 列，建置 10.8 秒，資料庫 166,920,192 bytes。
    - 標籤：`included` 17,081（官方註銷欄空白 9,455）、`excluded` 495、`unknown` 87,043；其中舊制 9,337、缺代碼 8,269、D–P 等未審核代碼 69,428（與 2026-09-14 無代碼列評估 17,606 = 9,337 + 8,269 一致）。附表 A/B/C 代碼 399 個全部已審核。
    - 以新 wheel 的 MCP stdio 查詢：`get_data_status` 的 tfda_device 為 available、`review_incomplete`（第一次 1,162 ms）；「糖化」20 筆：共 81 筆，221 ms，文字 34,859 字（粗估 9,893 tokens）；「隱形眼鏡」`prefer_ivd=true` 20 筆：共 3,674 筆，33,403 字；`limit=21` 回 `invalid_request`；`get_license` 單筆 5,531 字；`search_reviewed_ivd("隱形眼鏡")` 回 `candidate_matches_available`；`search_ivd_candidates("HbA1c")` 20 筆 35,291 字。
    - 同一段程式在 adapter 內直接查：一般查詢 98–155 ms；只打一個字「醫」命中全部 104,619 列，763 ms。
  - 用新 wheel 讀正式 data root（唯讀）：nhi_fee 仍為 available、complete、build `4ecd71e7…`；09006C 200 點、`in_scope`；「檢」20 筆共 1,270 筆；TFDA 回 `no_serving_snapshot`。
- 風險與待決：
  - 一頁 20 筆 TFDA 摘要約 3.5 萬字、粗估約 1 萬 tokens，接近 Claude Code 的 10,000 tokens 警告線，低於 25,000 tokens 截斷線（粗估，不是 tokenizer 實測）。
  - D–P 大類 69,428 列標 `unknown`，要不要改判需 owner 決定。
  - 正式上線還缺：TFDA owner review protocol、10 題以上正式 golden cases、三關審核（`TFDA-R1-SOURCE`、`TFDA-R1-SCHEMA`、`PUB-R1-OWNER`）；下載包：資料庫 167 MB，現行下載包上限 64 MiB 壓縮／256 MiB 解壓，需要另外量測與調整。
  - 每日排程的 TFDA 檢查還只下載與驗證，沒有寫入 serving 的檢查紀錄；上線後 14 日內要補，否則會標 stale。
  - `%TEMP%\tfdarc` 試建資料約 190 MB 留在電腦上（本機擋刪除指令）。

### Owner 決定與食藥署許可證本機上線（2026-09-15，OD-07／D-016）

- owner 在 Claude Code 對話中回覆（transcript timestamp `2026-09-15T03:14:27.986Z`，uuid `5359b56e-ccc1-4432-aa96-24795930b109`）：「1.a 2.a 3.z你直接幫我審核」。
  - 1.a：附表 A/B/C 以外大類（D–P）的代碼維持 `unknown`。
  - 2.a：一頁 20 筆的摘要內容先不減。
  - 3：上線審核不由 owner 本人看，直接由 AI 代審。「3.z」解讀為選項 3 加上「你直接幫我審核」。
- 規格同步：PRD §9 新增 OD-07；SDD 新增 `D-016`、OD 對照表 `OD-07`，並更新 `OD-03`、`OD-06` 已過期的「尚未接入／尚未實作」（刪除線保留）；TDD 加 `tests/test_tfda_publish.py`。
- 程式（commit `6c77671`，CI run `34925101870` 四個 job 皆 success）：
  - 審核規則檔 `src/taiwan_lab_mcp/review_protocols/tfda-r1-ai-review/1.json`：`status=owner_delegated`，記錄 owner 原話與時間；reviewer 為 `ai-reviewer:claude-opus-5`、role `ai_reviewer_delegated_by_owner`；`PUB-R1-OWNER` 範圍只限本機 MCP 服務，不含 GitHub Release 下載包。
  - `build_official_tfda_snapshot` 只接受規則檔指定的 reviewer id 與 role（三關審核與驗收題都檢查），不符回 `OWNER_REVIEW_REVIEWER_MISMATCH`／`GOLDEN_CASE_NOT_APPROVED`，且在寫任何 curated 檔之前拒絕。
  - `tfda_source.run_tfda_upstream_check` 與 `taiwan-lab-data check tfda_devices`：同一份 ZIP 記成功檢查；新 ZIP 繼續服務舊版、標 `newer_candidate_pending_review`，寫 `diff.json` 與中文 `diff-summary.md`（資料列數、字號數、新增／消失字號、內容不同的列數）；下載或檢查失敗標 `upstream_verification_failed`。
  - 測試 `tests/test_tfda_publish.py` 9 個。**這批測試與程式同時寫成，沒有先跑出失敗再修**（前一批 `test_tfda_official.py`、`test_tfda_ivd_registry.py` 有先 red）。
- 規格解讀：
  1. 規則檔名與 status 不沿用 `nhi-r1-owner-review`／`owner_approved`，因為這次不是 owner 本人審核；閘門名稱 `PUB-R1-OWNER` 維持不變，審核紀錄寫明是 AI 代審。
  2. 正式結果 notes 沒有加「由 AI 審核，未經人工複核」：PRD §9 OD-02 在 2026-09-14 已由 owner 取消這段備註；AI 身分寫在審核紀錄、規則檔與驗收題。
  3. 官方每週更新後的新版，每日檢查只標示「有新版等待審核」並寄信，不會自動換版；換版要再審一次（本次授權只涵蓋這一版）。
- AI 審核做了什麼（repo 外 `C:\Users\User\Documents\ChatGPT\taiwan-lab-mcp-data\tfda-review\`）：
  - 來源（`TFDA-R1-SOURCE`）：raw revision `aa385977…` 的 `fetch.json` 為 canonical，ZIP 16,265,433 bytes、SHA-256 `de880620…` 相符；metadata 發布機關代號、識別碼、授權代碼 1 與 2026-09-14 owner 確認頁一致；今天 09:30 排程重新下載的檔案 hash 相同。官方許可證查詢網站 `info.fda.gov.tw` 在這台電腦 DNS 解析失敗（`curl: (6) Could not resolve host`），沒有做網站逐筆比對，記為 minor 1。
  - 欄位（`TFDA-R1-SCHEMA`）：`verify_curated_roundtrip.py`（SHA-256 `7c8bed5d…`）自己解壓、解析 CSV、解析分類代碼與判定標籤，與資料庫逐列比對 104,619 列：列號、row hash、34 欄原文、分類代碼、主類別字母、IVD 標籤 0 筆不符；報告 `tfda-curated-roundtrip-2026-09-15.json`（SHA-256 `e363fd57…`）。比對的資料庫 SHA-256 `6d5d204b…` 與後來正式建置的資料庫相同。
  - 驗收題：`select_golden_cases.py`（SHA-256 `62771d09…`）以獨立解析從原始檔挑 14 題，每題寫出 34 欄原文與標籤預期值，涵蓋有效、已註銷、已廢止、註銷狀態空白但有日期、有狀態沒日期、過期未註銷、同字號兩家製造廠（2 列）、`excluded`（B.9245）、舊制、缺代碼、D–P 代碼、統編前導零與級數空白、英文品名尾端換行；程式內建比對全部通過。清單 `tfda-golden-ai-review-2026-09-15.md`（SHA-256 `97227287…`），預期值 `tfda-golden-ai-approved-2026-09-15.json`（SHA-256 `99052e91…`）。
  - 發布（`PUB-R1-OWNER`）：顯名、授權網址、「非食藥署官方服務」說明、工具說明提示、20 筆摘要與 coverage 說明已在前一節測試與 stdio 實測確認；minor 1：D–P 大類維持 unknown（1.a）、一頁約 3.5 萬字接近 Claude Code 警告線（2.a）。
  - 四份佐證檔在附加前搜尋 owner 本名與帳號：0 筆。
- 上線（repo 外 `automation\publish_tfda_official.py`，SHA-256 `1fec35ca…`；先 dry run 確認條件再 `--apply`，用 uv tool 環境的正式安裝版 wheel SHA-256 `e8363ef8…`）：
  - build `tfda_devices-build-cb94a6ca1ae38a2e68c9bd25d287192ad3b7836b3ddc5ef4c52ebbb040c11b53`，104,619 列，建置 13 秒，資料庫約 160 MB。
  - manifest SHA-256 `43036477…`；generation 1；publish event `publish-baef6a69…`。
  - IVD 涵蓋：399 個 A/B/C 代碼全部已審核；舊制 9,337、缺代碼 8,269、未審核代碼 69,428 列，`coverage_status=review_incomplete`。
- 上線後驗證：
  - 本機工具 `taiwan-lab-mcp.exe` 以 MCP stdio 讀正式 data root：22 個工具；`tfda_device` available、`review_incomplete`、不 stale；nhi_fee 仍 available、complete，09006C 200 點。
  - 「糖化血色素」20 筆：共 31 筆，227 ms，34,953 字（粗估 9,853 tokens）；「隱形眼鏡」篩 `unknown`：3,674 筆；`get_license("衛部醫器陸輸字第000546號")` 回 2 列、兩家製造廠分開，顯名含「官方標示更新時間 2026-09-11 15:57:04」；`search_reviewed_ivd("HbA1c")` 73 筆；`find_manufacturer("Roche")` 1,799 筆。
  - 每日排程腳本 `Invoke-NhiDailyCheck.ps1`（改為 `check tfda_devices`，SHA-256 `b08c0b7c…`）以 `-EmailDryRun` 試跑：exit 0，STATUS「OK：健保支付標準表沒有變動」＋「食藥署醫材許可證：沒有變動（104,619 筆）」；TFDA descriptor generation 2、`last_successful_check_at=2026-09-15T03:32:39Z`。
- 風險與後續：
  - 官方每 7 日更新；下一版出現後查詢會標「有新版等待審核」，要再審一次才換版。
  - 還沒有 TFDA 下載包（資料庫約 160 MB，現行下載包上限 64 MiB 壓縮）。
  - 觀察：「糖化血色素」第一筆是已註銷的「糖化血色素檢測試劑組」，因為排序先看命中程度（品名開頭相同）才看註銷欄，這是 TFDA-06 規定的順序。

### 搜尋一次最多 5 筆（2026-09-15）

- owner 看完上線回報後回覆「20筆好像還是有點太多，還是給5筆 有需要的話可以再進一步找」。
- 規格解讀：
  - 套用到所有搜尋工具：健保 `search_payment_items`（相容名稱 `search_lab_code` 固定前 5 筆），食藥署 `search_reviewed_ivd`、`search_ivd_candidates`、`list_matching_license_records`、`find_manufacturer`（相容名稱 `search_ivd` 固定前 5 筆）。上限 5、預設 5；「進一步找」用 `offset` 翻頁或換更精確的關鍵字。
  - `find_manufacturer` 原本沒有分頁參數、固定前 20 筆；改成 5 筆後沒有分頁就看不到第 6 筆以後，所以新增 `limit`（預設 5）與 `offset`（預設 0）。
  - 單筆查詢不算搜尋，不改：`get_license` 同一字號全部列（最多 20 列；現有資料單一字號最多 4 列）、`get_points`、`get_payment_rule`；CDC 工具仍是合成示範資料，也不改。`compare_products` 維持 1–100 並回 deprecated。
  - 前兩節「上限 100→50」「最多 20 筆」保留作歷史；OD-07 的「一頁 20 筆暫不再減」以括號註明同日改為 5 筆。
- 改動：`adapters/nhi.py`、`adapters/tfda.py` 的 `SEARCH_PAGE_MAX` 20→5、預設值與說明文字「1–5」；`server.py` 工具簽名、預設值與說明（告訴 host AI 用 offset 翻頁）；public contract 五個 operation 的 `limit` 預設改 5、`find_manufacturer` 新增兩個參數（143,636 bytes）；PRD §5.3、TFDA-06、OD-07 註記，SDD §10.1／§10.2，TDD，README。
- 測試：先改 `test_nhi_search_summary.py`（`limit=5` 可用、預設 5、`limit=6` 拒絕）與 `test_tfda_official.py`（預設 5 筆與第二頁、偏好與候選分兩頁、`limit=6` 拒絕、新增 `find_manufacturer` 翻頁測試），跑出 6 failed、35 passed，改程式後全過。
- 驗證：
  - in-repo `pytest` 371 passed（`TAIWAN_LAB_ARTIFACT_DIR` 指向新 build）；`ruff check`、`ruff format --check`、`git diff --check` 通過。
  - wheel 301,116 bytes，SHA-256 `2d552c7635e60179193a7de46fed8792ff68dd2af183fdedf9fb34a74fb550ff`；sdist 554,646 bytes。
  - repo 外 venv、repo 外 cwd 以 `--import-mode=importlib` 跑：369 passed、2 skipped；安裝後 contract 與 repo 位元組相同。
  - 新 wheel 裝進 uv tool 環境，本機工具以 MCP stdio 查正式資料（食藥署與健保都是已上線的資料，不需要重建）：
    - `list_matching_license_records("糖化血色素")`：共 31 筆，回 5 筆、`truncated=true`，11,128 字（粗估 3,192 tokens；原本 20 筆 34,953 字）；`offset=5` 第二頁 5 筆；`limit=6` 回 `invalid_request`「limit 為 1–5 的整數」。
    - `search_reviewed_ivd("HbA1c")`：共 73 筆，回 5 筆，10,984 字。
    - `find_manufacturer("Roche")`：共 1,799 筆，回 5 筆，11,074 字；`offset=5` 第二頁 5 筆。
    - `search_payment_items("檢")`：共 1,270 筆，回 5 筆，8,790 字（粗估 2,544 tokens；原本 20 筆 26,264 字）；`offset=1265` 回最後 5 筆、`truncated=false`；`search_lab_code("檢")` 同樣 5 筆。
  - 第一次查詢 1,407 ms（含完整性檢查），之後 110–193 ms。

### 食藥署每週新版自動更新（2026-09-15，OD-08／D-017）

- owner 在 Claude Code 對話中回覆（transcript timestamp `2026-09-15T06:06:13.559Z`，uuid `297f1356-831a-4d5d-90dd-769c6747955e`）：「A變成成自動化 我不想花太多心力維護」。A 是上一則回報的選項「每次新版比對完直接換上，事後寄信」。
- 規格同步：PRD §9 新增 OD-08、OD-07「官方新版仍需再審」加刪除線；SDD 新增 `D-017`、`D-016` 對應句加刪除線、OD 對照表 `OD-08`；TDD 加 `tests/test_tfda_autoupdate.py`；README。
- 程式：
  - 審核規則檔 `src/taiwan_lab_mcp/review_protocols/tfda-r1-auto-review/1.json`：`status=owner_delegated`，記錄 owner 原話與時間；reviewer `automated-check:tfda-auto-update`、role `automated_checker_delegated_by_owner`，寫明沒有人或 AI 逐版審。
  - `build_official_tfda_snapshot` 新增 `review_protocol`（只接受 `tfda-r1-ai-review/1` 與 `tfda-r1-auto-review/1`）與 `pre_publish_check`：資料庫建好後、寫任何審核紀錄與切換版本前執行，回傳的報告成為審核證據。
  - 新模組 `src/taiwan_lab_mcp/tfda_autoupdate.py`，`run_tfda_auto_update` 流程：
    1. 跑原本的每日檢查；沒有新版就結束。
    2. 新版和上線版比，下列任一項成立就擋下（`blocked`），不建置：資料列數或許可證字號數變動超過 10%；中文品名、英文品名、申請商、製造商、主類別一、次類別一、級數、製造國別的空白比例上升超過 2 個百分點；出現上線版沒有、也不是空白／已註銷／已廢止的註銷狀態。
    3. 用自己的 ZIP／CSV 解析（不經過 importer）挑驗收題：先挑固定涵蓋清單的列，再補平均分布的列到至少 10 題，逐欄寫預期值。
    4. 建置；切換前以獨立解析逐列比對資料庫（列號、row hash、34 欄原文、分類代碼、主類別字母、IVD 標籤），不符就不切換（`auto_publish_failed`）。
    5. 全部通過才發布（`published`），審核證據含 `tfda-auto-roundtrip.json`。
  - 同一個被擋下或失敗的新版每天都會再被發現，`already_reported=true` 時排程不重寄信。
  - CLI：`taiwan-lab-data check tfda_devices --auto-publish`，只限 `tfda_devices`；`blocked` exit 5、`auto_publish_failed` exit 6。
  - 每日排程 `Invoke-NhiDailyCheck.ps1`（SHA-256 `f78d148f…`）改帶 `--auto-publish`：`published` 寄「已自動更新」信（附差異摘要，附表 A/B/C 出現未審核代碼時列出）；`blocked`、`auto_publish_failed` 寄信並把 STATUS 第一行改成「異常」，已通知過的只寫 STATUS 不寄信。
- 規格解讀：
  1. SDD §15 寫「NHI 或 TFDA row／distinct key count 相對 current 超過 ±10%：啟動期 block review」「TFDA 關鍵欄 null rate 增加超過 2 個百分點、未知 status／code 出現：block review」。依 owner 決定，TFDA 改成「超過才擋、沒超過自動發布」；關鍵欄清單由我訂（見上）。
  2. 「未知 code 出現」沒有列入擋下條件：附表 A/B/C 出現未審核代碼時，這些列本來就標 `unknown`，不會被說成體外診斷；改在通知信列出代碼。依 owner 2026-09-14「寧可錯殺一百」原則，之後可請 AI 補判。
  3. ~~健保新版不在這次決定範圍，仍照原流程等 owner 審核。~~（同日 OD-09 改為自動更新，見下方「健保新版自動更新」）
- 測試：先寫 `tests/test_tfda_autoupdate.py` 8 個，跑出 8 failed，實作後全過。
- 驗證：
  - in-repo `pytest` 379 passed（`TAIWAN_LAB_ARTIFACT_DIR` 指向新 build）；`ruff check`、`ruff format --check` 通過。
  - wheel 310,294 bytes，SHA-256 `64e48801d54dd11323ef4af3a8f5424a38298d67cbcd02300e431943eba1d9e9`；sdist 565,629 bytes；wheel 含 `tfda_autoupdate.py` 與新規則檔。
  - repo 外 venv、repo 外 cwd 以 `--import-mode=importlib` 跑：377 passed、2 skipped；安裝後 contract 與 repo 位元組相同。
  - 真實資料演練（唯讀，不換版）：對目前上線的資料庫跑獨立逐列比對：104,619 列 0 不符，2.5 秒；從原始檔挑出 14 題驗收題，1.5 秒，程式比對全部通過；附表 A/B/C 未審核代碼 0 個；上線版和自己比的擋下條件為空。
  - 新 wheel 裝進 uv tool 環境，每日排程以 `-EmailDryRun` 試跑：exit 0，STATUS「OK：健保支付標準表沒有變動」＋「食藥署醫材許可證：沒有變動（104,619 筆）」，TFDA 回 `unchanged`、`already_reported=false`。
  - 真的有新版時會走「擋下」或「發布」哪條路，要等官方下一次更新才看得到；兩條路都只有合成資料測試。
- 風險：
  - 硬碟：每換一版多一份約 160 MB 資料庫和 16 MB 原始檔，舊版不會自動刪（留著可以退回）；一年約 9 GB。C 槽目前剩 68 GB（已用 93%）。
  - 自動發布只擋「變動量」與「解析正確」，擋不住官方內容本身寫錯。

### 展延偵測與只留最近 3 版（2026-09-15）

- owner 回覆「A 再來我怕有一些他是做展延，就可能是用同一筆去做修改。這樣子總筆數沒有異動的話，系統也偵測得到嗎？」。
  - A 是上一則的選項「只留最近 3 版，更舊的自動丟到資源回收筒」。
- 回答（改動前的程式就成立）：判斷有沒有新版是比對整個 ZIP 的 SHA-256，任何一筆內容改動都算新版，跟總筆數無關；自動更新會整份重建，展延後的新有效日期查得到。
- 原本不足的地方：差異報告只列新增、消失的許可證字號，同字號改內容只算進「內容不同 N 列」，看不出是哪一張、改了什麼。
- 程式：
  - `tfda_source._tfda_upstream_diff` 逐字號比對兩版資料列（同一字號內的列順序不算改動），`diff.json` 新增：
    - `changed_permits`：字號、改動欄位、前後值；多列字號另標第幾列，列數不同記「資料列數」。
    - `validity_extended_permits`：有效日期最大值往後延的字號。
  - `diff-summary.md`（也就是通知信內容）新增「內容有改的字號 N 個」「有效日期往後延（通常是展延）：N 個」與逐字號清單，例如「字號：有效日期 舊值 → 新值」。
  - 標題改成「上游有新版」，拿掉「等待審核」的固定句，因為自動更新成功時也會用同一份摘要。
  - `tfda_autoupdate.plan_tfda_retention` 與 `taiwan-lab-data retention-plan tfda_devices --keep 3`，只列清單、不刪檔：
    - 保留：服務中版本與最近 3 個服務過的版本（依發布／回退紀錄）及其原始檔，加上等待中的新版原始檔。
    - 列出：其他 TFDA 建置資料夾（含失敗殘留）與原始檔。
    - 讀不到發布紀錄或保留版本的 manifest 時，什麼都不列。
  - 每日排程 `Invoke-NhiDailyCheck.ps1`（SHA-256 `50298263…`）在食藥署檢查後跑清單，只處理路徑格式符合、不是服務中版本的資料夾，用 VisualBasic `DeleteDirectory(..., SendToRecycleBin)` 移到資源回收筒（與 2026-09-14 清理腳本同一種作法），STATUS 加「舊版 N 個資料夾已移到資源回收筒」。
- 規格解讀：
  1. 「最近 3 版」含服務中那一版。
  2. 回收筒用的是 Windows 回收筒自己的容量上限；超過時 Windows 會永久清掉回收筒裡最舊的東西。
  3. 健保資料量小（每版約 6 MB），不在這次清理範圍。
- 測試：先加 5 個測試，跑出 5 failed、17 passed：
  - `test_tfda_publish.py` 1 個：筆數不變時列出展延與改名。
  - `test_tfda_autoupdate.py` 4 個：只有展延也自動發布、清理清單留 3 版與等待中新版、3 版以內不列、CLI。
  - 實作後全過。
  - 「只有展延也自動發布」其實在改前就能發布，失敗點是新的 `validity_extended_permits` 欄位還不存在。
- 驗證：
  - in-repo `pytest` 384 passed；`ruff check`、`ruff format --check`、`git diff --check` 通過。
  - wheel 312,175 bytes，SHA-256 `0caae6b83b75c6c08f5354e83bd5fe659e1fb5522e5273f19e58bda1f2150477`。
  - repo 外 venv 382 passed、2 skipped；安裝後 contract 與 repo 位元組相同。
  - 真實資料模擬（記憶體內改一份副本，不寫檔、不發布）：把 `衛部醫器陸輸字第000801號`「“河南駝人”多功能氣管插管」有效日期 2026/12/06 改成 2031/12/06。
    - 總筆數兩版都是 104,619。
    - `changed_permits` 只有這一筆，`validity_extended_permits` 為這個字號。
    - 摘要出現「衛部醫器陸輸字第000801號：有效日期 2026/12/06 → 2031/12/06」。
    - 比對兩份 7 千萬字元的 CSV 共 6.7 秒。
  - 新 wheel 裝進 uv tool 環境：
    - `retention-plan` 對正式 data root 回保留 1 版、`remove_paths` 空。
    - 每日排程 `-EmailDryRun` 試跑 exit 0，STATUS「食藥署醫材許可證：沒有變動（104,619 筆）」，清理步驟有執行、沒有移動任何檔案。
- 尚未實際發生過：真的把舊版移到回收筒（至少要第 4 版上線後才會發生），以及真實官方展延出現在通知信；兩者目前只有合成資料測試與上面的模擬。

### 健保新版自動更新（2026-09-15，OD-09／D-018）

- owner 在 Claude Code 對話中回覆（transcript timestamp `2026-09-15T10:22:05.922Z`，uuid `c55a6288-783b-4762-8d54-e3f12321e9f0`）：「好，那健保新版也改成自動更新」。
- 規格同步：
  - PRD §9 新增 OD-09，OD-08「健保新版仍需 owner 審核」加刪除線；SDD 新增 `D-018` 與 OD 對照表 `OD-09`；TDD 加 `tests/test_nhi_autoupdate.py`；README。
  - 上方食藥署一節「健保新版不在這次決定範圍」加刪除線。
- 程式：
  - 審核規則檔 `src/taiwan_lab_mcp/review_protocols/nhi-r1-auto-review/1.json`：`status=owner_delegated`，記錄 owner 原話與時間；reviewer `automated-check:nhi-auto-update`、role `automated_checker_delegated_by_owner`；gate `NHI-R1-SOURCE`、`NHI-R1-SCHEMA`、`PUB-R1-OWNER`（範圍 `local_mcp_serving`）。
  - `build_official_nhi_snapshot` 新增 `review_protocol` 與 `pre_publish_check`：
    - 預設仍是 owner 審核規則，手動審核流程不變。
    - 自動規則要求每份審核紀錄與驗收題的 reviewer 都是 `automated-check:nhi-auto-update`；其他規則回 `REVIEW_PROTOCOL_INVALID`。
    - `pre_publish_check` 在資料庫建好、算完 hash 之後、切換版本之前執行，回傳的報告成為審核證據。
  - 新模組 `src/taiwan_lab_mcp/nhi_autoupdate.py`，`run_nhi_auto_update` 流程：
    1. 跑原本的每日檢查；沒有新版就結束。
    2. 新版和上線版比，下列任一項成立就擋下（`blocked`），不建置：資料列數或代碼數變動超過 10%；英文名稱空白比例上升超過 2 個百分點。
    3. 用自己的 CSV 解析（不經過 importer）挑至少 10 題驗收題，逐題寫代碼、點數、起訖日與檢驗範圍判定。
    4. 建置；切換前以獨立解析逐列比對資料庫（列號、row hash、代碼、點數原文與數值、起訖日原文、中英文名稱、備註、檢驗範圍判定），不符就不切換（`auto_publish_failed`）。
    5. 全部通過才發布（`published`），審核證據含 `nhi-auto-roundtrip`。
  - 新版出現檢驗範圍清單還沒判定的代碼時照樣發布，這些代碼標「未判定」，並列在 `new_codes_without_scope`。
  - 開發環境安裝（沒有 build identity）一律不自動發布，回 `APPLICATION_BUILD_IDENTITY_MISSING`。
  - CLI：`taiwan-lab-data check nhi_fee --auto-publish` 開放給健保；`blocked` exit 5、`auto_publish_failed` exit 6，與食藥署相同。
  - 差異摘要標題改成「健保支付標準表：上游有新版」，拿掉「新版審核通過並發布之前…」一句，因為自動發布成功時也用同一份摘要。
  - 每日排程 `Invoke-NhiDailyCheck.ps1`（SHA-256 `541029c1…`）健保檢查改帶 `--auto-publish`：
    - `published`：寄「健保支付標準已自動更新」信，列出未判定的新代碼；STATUS「OK：健保支付標準表已自動更新到新版」。
    - `blocked`、`auto_publish_failed`：寄信（已通知過的不重寄），STATUS 第一行「異常」，exit 1。
- 規格解讀：
  1. SDD §15 的 ±10% 與 null rate 門檻套用到健保；關鍵欄只選英文名稱，因為中文名稱、點數、起訖日空白時官方檔會被 schema 驗證直接拒收。
  2. 未判定的新代碼不擋發布：檢驗範圍工具本來就對未判定代碼回 `review_incomplete`，不會被說成檢驗項目；改在通知信列出。
  3. 舊版不自動清理：每版約 8 MB。
- 測試：先寫 `tests/test_nhi_autoupdate.py`，跑出 8 failed；實作後 9 個全過。`tests/test_tfda_autoupdate.py` 原本斷言「CLI 對 nhi_fee 帶 `--auto-publish` 會拒絕」，改名為 `test_cli_auto_publish_routes_tfda` 並拿掉這條斷言。
- 驗證：
  - in-repo `pytest` 393 passed（`TAIWAN_LAB_ARTIFACT_DIR` 指向新 build）；`ruff check`、`ruff format --check`、`git diff --check` 通過。
  - wheel 319,962 bytes，SHA-256 `7b92b01cacb1775d4ce50467e0a61f771f09132f0d8def69bd9d57ce4783abc3`；sdist 582,411 bytes；wheel 58 個檔案，含 `nhi_autoupdate.py` 與新規則檔。
  - repo 外 venv、repo 外 cwd 以 `--import-mode=importlib` 跑：391 passed、2 skipped；import 路徑來自該 venv；安裝後 contract 與 repo 位元組相同。
  - 真實資料演練（唯讀，不換版）：對上線版 `57bdfe9ebe98…` 跑獨立逐列比對 6,173 列通過，0.09 秒；挑出 10 題驗收題，程式比對 0 不符；上線版和自己比的擋下條件為空。
  - 新 wheel 裝進 uv tool 環境，每日排程 `-EmailDryRun` 試跑：exit 0，STATUS「OK：健保支付標準表沒有變動」＋「食藥署醫材許可證：沒有變動（104,619 筆）」；健保回 `unchanged`、`already_reported=false`、`new_codes_without_scope=[]`。
- 尚未實際發生過：官方健保新版上線後走「發布」或「擋下」；兩條路目前只有合成資料測試。
- 限制：GitHub Release 下載包不會跟著本機自動更新換版；其他安裝者仍拿到 owner 審核過的舊包。

### Owner 決定：下載包加入食藥署、自動發布、未審核代碼先算、疾管署由 AI 審（2026-09-15，OD-04／OD-10～12）

- owner 在 Claude Code 對話中說「好，那下載包也發一版新的 目前有什麼還需要我做裁決的嗎？」（transcript timestamp `2026-09-15T10:49:59.327Z`，uuid `f3015e4d-1abd-441d-bad0-ea202bffdf4e`）。
- 先查證：GitHub 最新 Release `nhi-data-20260914-lab-scope` 的健保 build 結尾 `57bdfe9ebe98`，與本機服務中的健保 build 相同；只重發健保，資料不會變。
- 以選項題問四件事，owner 回答（`2026-09-15T10:54:18.876Z`，uuid `a7cbc03c-07e5-4f0f-83f6-4cdcfc13fcad`）：
  1. 新的下載包要放哪些資料：「健保＋食藥署 (Recommended)」→ OD-10。
  2. 本機自動換版後 GitHub 下載包要不要自動發：「自動發 (Recommended)」→ OD-11。
  3. 官方新版多出還沒審過的代碼怎麼標：「先當成「算」 (Recommended)」→ OD-12。
  4. 疾管署採檢手冊與認可檢驗機構名單誰審：owner 自填「Ai全程代審 不用特別備注未經人工審核」→ OD-04。新版處理時間沒有問到，仍未決定。
- 規格同步：PRD §9 填入 OD-04、新增 OD-10～12，OD-01／07／08／09 相關句加刪除線；SDD 新增 `D-019`～`D-021`，`D-007`／`D-011`／`D-016`／`D-018` 加註，OD 對照表；新增 `docs/adr/0002-tfda-bundle-and-automatic-release.md`，ADR 0001 §6 標出被取代部分；TDD。
- 審核規則第 2 版（第 1 版保留，現有 build 仍引用）：
  - `nhi-r1-auto-review/2.json`、`tfda-r1-auto-review/2.json`、`tfda-r1-ai-review/2.json`：`PUB-R1-OWNER` 範圍改為 `local_mcp_serving_and_github_release_bundle`，`amendments` 記錄 owner 原話與時間。
  - `tfda-r1-ai-review/2` 另把「搜尋摘要最多 20 筆」改為 5 筆（owner 同日決定；那則原話沒有逐字查 transcript 時間，未填 timestamp）。
  - importer 常數 `TFDA_REVIEW_PROTOCOL_VERSION`、`TFDA_AUTO_REVIEW_PROTOCOL_VERSION`、NHI `AUTO_REVIEW_PROTOCOL_VERSION` 改為 `"2"`。
- 未審核代碼先算（OD-12／D-021）：
  - 健保：`_curated_row`、驗收題比對、寫資料庫與 `NHI-R1-SCOPE` capability 狀態加上 `unreviewed_in_scope`，只有 `build_official_nhi_snapshot` 與 `prepare-review` 傳 `True`。
    - 改前（正式建置）：沒有核准規則的代碼 `scope_status=review_pending`，整份查詢 `coverage_status=review_incomplete`、警告 `coverage_review_incomplete`。
    - 改後（正式建置）：`scope_status=in_scope`、`scope_basis_locator`「尚未審核的代碼：依專案負責人 2026-09-15 決定先算檢驗，之後補審」，查詢 `coverage_status=complete`。
    - 離線合成建置不變，仍是 `review_pending`。
  - 健保自動更新的獨立逐列比對與挑題改用同一個預設，拿掉「未判定」挑題條件與 `coverage_review_incomplete` 預期警告；`new_codes_without_scope` 照常列出。
  - 食藥署：`derive_ivd_scope` 對附表 A/B/C 類、registry 沒有決定的代碼回 `included`（`UNREVIEWED_ANNEX_CODE_SCOPE`），所有建置都適用；獨立比對 `_scope` 同規則；`IvdCoverage.unknown_code_rows` 不再計入這些列。D–P 類與沒有分類代碼的列仍為 `unknown`。
    - 上線資料用到的 A/B/C 代碼在 2026-09-15 已全部審過（見「食藥署每週新版自動更新」一節：未審核代碼 0 個），所以現有標籤不會因這次修改而變。
  - 每日排程通知信（repo 外 `Invoke-NhiDailyCheck.ps1`）的「暫時標未判定」改為「依你 2026-09-15 的決定先算檢驗／先算體外診斷，之後補審」。
- 測試：
  - 先改 5 個測試檔（新增 2 個測試、2 組判定參數、3 處 protocol 版本、package 清單），跑出 7 failed、42 passed。
  - 實作後，原本以「未審代碼 → `coverage_review_incomplete`」為前提的正式建置測試資料跟著改：`test_snapshot_bundle.py`、`test_nhi_review.py`、`test_nhi_importer.py` 的預期警告改為空；`test_nhi_review.py` 一題的前後差異改為沒有差異；`test_nhi_autoupdate.py` 的逐列比對改用自動發布出來的正式建置。
- 驗證：
  - in-repo `pytest` 396 passed（`TAIWAN_LAB_ARTIFACT_DIR` 指向新 build）；`ruff check`、`ruff format --check`、`git diff --check` 通過。
  - wheel 328,282 bytes，SHA-256 `c853391b5b776141b91aaf6350f8d08ab9552689f8e2e53efd760bb2c86f6482`，61 個檔案，含 8 份審核規則；sdist 589,297 bytes。
  - repo 外 venv、repo 外 cwd 以 `--import-mode=importlib` 跑：394 passed、2 skipped；import 路徑來自該 venv；安裝後 contract 與 repo 位元組相同。
- 這一段尚未做：食藥署下載包的匯出與安裝、本機食藥署以第 2 版規則重建、自動發布腳本與新的 GitHub Release、疾管署資料本身。

### 食藥署下載包：匯出與安裝（2026-09-15，OD-10／D-019）

- 程式：
  - `snapshot_bundle.py` 改成健保、食藥署共用：`export_snapshot_bundle(data_root, source_id, output_dir=…)`、`install_snapshot_bundle(data_root, source_id=…, bundle_path=…, actor=…)`。健保原本的 `export_nhi_snapshot_bundle`、`install_nhi_snapshot_bundle` 保留，改呼叫共用版。
  - 兩個來源的差異集中在一張表：原始檔名（`source.csv`／`source.zip`）、非官方聲明、freshness 規則版本（`nhi-v1`／`tfda-v1`）、讀取服務狀態與驗原始檔的函式。
  - 讀寫改成每次 1 MiB 串流：
    - 匯出：先逐檔算大小與 SHA-256，再邊讀邊寫進暫存 ZIP，寫完才換成正式檔名。
    - 安裝：先逐項解壓、只驗大小與 SHA-256、不寫檔；全部通過、衝突與路徑長度也檢查過，才逐項解壓寫入。
  - 上限：壓縮後 64 MiB → 128 MiB，解壓後 256 MiB → 512 MiB。
  - 安裝指令的來源和下載包不同，回 `BUNDLE_SOURCE_MISMATCH`（exit 4），不寫任何檔案。
  - CLI `export-snapshot`、`install-snapshot` 開放 `tfda_devices`。
  - `docs/install.md` 改寫：兩組下載檔、兩個安裝指令、食藥署 14 天標過期、官方有新版後自動發布、錯誤碼表加 `BUNDLE_SOURCE_MISMATCH`，已知限制與顯名加入食藥署。
- 測試：
  - 先寫 `tests/test_tfda_bundle.py` 5 個，跑出 5 failed（找不到新函式）；實作後全過。
  - 其中一題原本讀 `result.stale`，查詢結果沒有這個欄位（在 `provenance` 底下），改成 `result.provenance.stale`；這是測試寫錯。
  - 健保 `tests/test_snapshot_bundle.py` 16 個沒有改，全過，代表串流改寫沒有改變健保下載包的行為。
- 真實資料試跑（本機食藥署服務版，build 結尾 `bbb040c11b53`；輸出在 session scratchpad，沒有公開）：
  - 匯出兩次：都是 64,830,989 bytes、SHA-256 `a6d2e5c4cb800608d0b656a67990f6c379fce40b6b9611125bceeee72a056b0f`，14 個檔案，5.0 秒；行程記憶體高峰（working set）約 41 MB。
  - 裝進 `%TEMP%\tlb-tfda`：`installed`、generation 1、寫入 14 個檔案，3.3 秒，記憶體高峰約 49 MB。
  - 裝好後 `read_tfda_state` 為 available、沒有過期；涵蓋統計與本機服務版相同：已審代碼 399／399、舊制 9,337 列、缺代碼 8,269 列、只有其他類別 69,428 列。
  - 這次試跑的服務版是用第 1 版審核規則建置，只用來驗程式；公開前會先以第 2 版規則重建。
  - 試裝資料夾約 185 MB 留在 `%TEMP%\tlb-tfda`，沒有刪（本機擋刪除指令）。
- 驗證：
  - in-repo `pytest` 401 passed（`TAIWAN_LAB_ARTIFACT_DIR` 指向新 build）；`ruff check`、`ruff format --check`、`git diff --check` 通過。
  - wheel 329,255 bytes，SHA-256 `eeeaddfeb9d44066ae49969630746853bf6b4f52eb6d25090929bec975b95445`；sdist 593,797 bytes。
  - repo 外 venv、repo 外 cwd 以 `--import-mode=importlib` 跑：399 passed、2 skipped；安裝後 contract 與 repo 位元組相同。
- GitHub CI（commit `178df9a`，run `34963723643`）失敗：
  - 只有 Windows job 失敗，2 failed、397 passed：`test_install_tfda_bundle_serves_the_same_permits`、`test_cli_export_and_install_tfda_snapshot`。
  - 原因：CI 的 pytest 暫存資料夾路徑較長，食藥署 build 審核證據檔的完整路徑 267 字元，被安裝前的 Windows 路徑長度檢查擋下（`BUNDLE_PATH_TOO_LONG`，上限 259）。檢查照設計運作；本機暫存路徑較短，所以本機沒有重現。
  - 修正：這兩個測試關掉路徑長度檢查（直接呼叫的測試傳 `max_path_length=None`，CLI 測試暫時改掉函式預設值）。路徑長度檢查本身由 `tests/test_snapshot_bundle.py::test_install_refuses_paths_over_the_limit_before_writing` 測。
  - 一般使用者：以重建後的食藥署 build 計算，最長檔案是 `curated/tfda_devices/<build>/audit/evidence/tfda-source-identity-confirmation-2026-09-14.md`（相對路徑 167 字元）；裝在安裝說明建議的 `C:\Users\User\taiwan-lab-data` 時，連同暫存檔名共 207 字元；使用者名稱 20 個字元時 223 字元，都在上限內。
  - 這段期間發布腳本回 `waiting_for_ci`，沒有發布任何 Release。

### 食藥署「哪些醫材算體外診斷」AI 審核（2026-09-14）

- owner 要求：「食藥署哪些醫療器材算體外診斷試劑，你幫我摘下來，然後幫我做一個判別」；`TFDA-R1-IVD` reviewer 為 AI（上方 Owner 決定 2A）。
- 摘錄：
  - 背景 agent 從附表 PDF 依表格框線抽出 A 237、B 105、C 206，共 548 項。
  - 輸出 `taiwan-lab-mcp-data\tfda-ivd-research\annex-abc-items.json`，763,551 bytes，SHA-256 `d0c6db82…`，主 session 重算 hash 相同。
  - 主類別標題附表沒有，留空不補字。
  - 抽查 B.9225、B.9195、B.9245、A.1020、C.3400 的內容與 agent 回報一致；A.1020 名稱與許可證資料相同。
- 規格解讀：
  - 醫療器材管理法第 3 條只定義「醫療器材」，查過的條文中沒有「體外診斷醫療器材」定義。
  - 所以判定依 SDD D-010「依官方分類分級附表原文逐碼判斷」，只看附表鑑別文字。
- 審核紀錄：`docs/reviews/tfda-ivd-ai-review-2026-09-14.md`，含判定標準與不算／無法判定／查無清單。
- 結果：
  - 附表 548 項中，算 IVD 518、不算 13、無法判定 17。
  - 許可證資料用到的 399 碼中，算 372、不算 12、無法判定 12、附表查無 3。
- 產出（repo 外）：
  - 決議檔 `tfda-ivd-research\tfda-ivd-decisions-2026-09-14.json`：460,315 bytes，SHA-256 `ffe88867…`，含 SDD registry 欄位中目前拿得到的部分。
  - owner 清單 `owner-review\tfda-ivd-list-2026-09-14.csv`：UTF-8 BOM，264,089 bytes，SHA-256 `9253c2bc…`，551 列。
  - 產生腳本 `tfda-ivd-research\build_ivd_decisions.py`：SHA-256 `68a8f664…`。
- 尚未做：
  - 決議檔還沒轉成 repo 內版本化 registry，也沒接進 MCP；TFDA curated build 與 adapter 尚未實作。
  - `regulation_version`、`effective_from` 欄位沒有官方來源值，接入時需再確認。

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
