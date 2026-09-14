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
