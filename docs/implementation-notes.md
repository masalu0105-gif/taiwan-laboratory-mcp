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

## 目前驗證證據

- `.venv\Scripts\python.exe -m pytest -q -ra`：`155 passed`。
- `.venv\Scripts\ruff.exe check src tests` 與 `ruff format --check src tests`：通過；`git diff --check`：通過（僅有 Git 的 LF/CRLF 提示）。
- `uv build --wheel --sdist`：wheel 與 sdist 均成功；`tests/test_package_contents.py` inventory 測試通過。archive inventory 為 wheel 43、sdist 86 個檔案，必要 contract/source/schema、acceptance writer 與 acceptance registry 齊全，沒有 raw／staged／quarantine／SQLite／secret artifact，兩者都沒有 `uv.lock`。
- repo 外暫存 venv 重新安裝 wheel 後，`tests/test_mcp_stdio.py`：`6 passed`（canonical API／sample `auto`／`legacy`、official current/historical、unavailable、stale）；安裝後 contract equality：22 個 discovery tools、request／response schema equality passed，packaged contract 101746 bytes。
- 同一 repo 外 wheel 在獨立暫存 cwd 完成 `data_cli validate` 與 `sync` smoke；兩者皆通過，sync 只產生 `review_pending` candidate、沒有 current pointer，也未使用 repo-relative fallback。

## 目前刻意不做

- 不在 repo 保存正式 raw／curated bulk data、病人資料、PHI、LIS／HIS、診斷、申報決策或採購建議。
- 不把 points 換算成金額，不用 current snapshot 回答歷史點數，不把 sample fixture 的官方 URL 當成 fixture 內容的來源證明。
