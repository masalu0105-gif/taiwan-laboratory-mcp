# Taiwan Laboratory MCP P1.1 Software Design Document

文件狀態：**Planning complete；第一輪共用信任邊界＋NHI vertical slice 已實作**；目前可執行版本仍為 `0.1.1`，worktree 已包含共用 official snapshot runtime、publisher、NHI importer 與 packaged official MCP contract 的可重跑工程切片，但正式來源 qualification、owner／scope gate、CDC／TFDA importer 與整體 release gates 尚未完成或驗證

設計日期：2026-09-13（Asia/Taipei）

適用版本：由 `0.1.1` sample-only 升級至 P1.1 official snapshot

規格階層：`docs/product-requirements.md` 是產品行為、public MCP operation／status／safety／truth table 的唯一真源；本文件只定義 internal architecture；`docs/test-driven-development.md` 定義驗證介面。`docs/research/*.md` 只提供來源觀察，`docs/implementation-plan.md` 只提供排程；兩者與 PRD/SDD 衝突的舊建議均視為 superseded。

## 1. 文件目的

本文件把已完成的來源調查轉成可實作的軟體設計。P1.1 只處理四個公開資料集：

1. NHI 醫療服務給付項目及支付標準 CSV。
2. TFDA 醫療器材許可證 CSV ZIP 與版本化 IVD 分類 registry。
3. CDC 傳染病檢體採檢手冊及修訂對照 PDF。
4. CDC 傳染病認可檢驗機構 ODS。

此版本不讀取病人資料、不串接 LIS/HIS、不提供診斷、申報、採購或產品等效建議。LOINC、FHIR、SNOMED、EQA、CAP 繼續維持未啟用介面。文件中的 `MUST` 是發布阻擋條件，`SHOULD` 是預設做法；標為 `OWNER GATE` 或 `UNVERIFIED` 的事項不可由實作者自行假設已核准。

除第 3.1 節明確列出的目前 worktree checkpoint 外，未特別標示已確認的元件、schema、路徑、CLI、測試與 gate 仍是 **PLANNED**。本文不能作為 official data 已下載、內容已複核、production-ready 或任何來源已可服務的證據。

## 2. 設計需求與可追蹤 ID

| ID | 必須維持的性質 | 驗收摘要 |
| --- | --- | --- |
| `SDD-ISO-01` | sample 與 official 資料隔離 | 一個 process 只使用一種 mode；official 不可退回 sample，也不可混查 |
| `SDD-PUB-01` | immutable snapshot 與 atomic publish | 驗證失敗或 publish 中斷時，current availability descriptor 不變 |
| `SDD-FAIL-01` | fail closed | 沒有核准 snapshot 時回 unavailable；staged、quarantine 永遠不可被 runtime 載入 |
| `SDD-PROV-01` | snapshot 與 row provenance | 每筆結果可回到原始 artifact 與列、PDF 頁或 ODS 列 |
| `SDD-FRESH-01` | freshness 與 stale 明示 | 上游檢查失敗或已知有待審新版時，回傳原因與最後成功時間 |
| `SDD-NHI-01` | NHI 語意邊界 | 7 欄 strict parse、代碼字串、點數非金額、現行資料不可冒充完整歷史 |
| `SDD-TFDA-01` | TFDA 語意邊界 | ZIP 安全、34 欄、字號非 row key、法人角色分開、IVD 逐碼核准 |
| `SDD-CDC-01` | CDC PDF 關係與審查 | 雙頁碼、跨頁表頭、同疾病多採檢項目／目的不合併，發布前人工與醫檢複核 |
| `SDD-ODS-01` | CDC ODS 合併格語意 | 只解析已知 12 欄；依 merge span 繼承，禁止 blanket forward-fill |
| `SDD-SEC-01` | 下載 trust boundary | HTTPS、host allowlist、大小限制、安全解壓、內容 magic 驗證 |
| `SDD-OBS-01` | 可觀測且不洩漏查詢 | sync 產生機器可讀報告；status 回資料狀態；預設不記錄查詢內容 |
| `SDD-AUDIT-01` | 核准證據綁定 | validation、golden 與 review records 內容定址並綁定同一 build subject digest |
| `SDD-API-01` | 單一 MCP operation contract | tool 參數、候選範圍、狀態 enum 與安全旗標只有一份 canonical matrix |
| `SDD-QUAL-01` | 官方來源 qualification 可重跑 | 完整官方 artifact 不進 Git；命令、工具版本、input/output hash 與核准報告可由第二人重跑 |

### 2.1 SDD verification interfaces

下表是14個SDD ID的一對一 primary verification interface；`SDD-ISO-01`、`SDD-PUB-01`、`SDD-FAIL-01`、`SDD-FRESH-01`、`SDD-PROV-01`、`SDD-SEC-01`、`SDD-OBS-01`、`SDD-AUDIT-01`、`SDD-NHI-01`、`SDD-API-01` 的 canonical node 已建立並可執行，其餘仍為 **PLANNED**。每個node通過後仍須由acceptance reporter寫`reports/acceptance/<release-id>/<SDD-ID>.json`，包含node ID、exit code、stdout/stderr hash、application build inventory hash與其引用的evidence hashes；不存在的node/report不得標passed。PRD acceptance nodes可補充覆蓋，但不得取代這14個架構契約的primary node。

| SDD ID | Canonical planned verification node | 必要證據／gate |
| --- | --- | --- |
| `SDD-ISO-01` | `tests/test_mcp_stdio.py::test_sdd_iso_01_official_never_falls_back_to_sample` | sample/official installed-wheel transcripts；`REL-G1` |
| `SDD-PUB-01` | `tests/test_snapshot_publish.py::test_sdd_pub_01_availability_descriptor_is_atomic_under_concurrency` | before/after descriptor hashes、barrier/crash matrix；`REL-G1` |
| `SDD-FAIL-01` | `tests/test_freshness.py::test_sdd_fail_01_operational_integrity_is_data_unavailable` | missing/corrupt/schema/hash/source/generation cases；`REL-G1` |
| `SDD-PROV-01` | `tests/test_models.py::test_sdd_prov_01_every_item_and_child_has_typed_row_evidence` | four-source locator readback；`REL-G1`、`REL-G2` |
| `SDD-FRESH-01` | `tests/test_freshness.py::test_sdd_fresh_01_internal_states_map_to_prd_freshness` | injected clock＋current/check descriptor fixture；`REL-G1` |
| `SDD-NHI-01` | `tests/test_nhi_importer.py::test_sdd_nhi_01_contract_bundle` | `NHI-G-001..010`、sentinel、as_of precedence；`REL-G2` |
| `SDD-TFDA-01` | `tests/test_tfda_importer.py::test_sdd_tfda_01_contract_bundle` | `TFDA-G-001..010`、PRD §6.3.1 truth-table fixture；`REL-G2` |
| `SDD-CDC-01` | `tests/test_cdc_pdf_importer.py::test_sdd_cdc_01_contract_bundle` | `CDC-G-001..010`、雙頁碼/lineage；`REL-G2` |
| `SDD-ODS-01` | `tests/test_cdc_ods_importer.py::test_sdd_ods_01_contract_bundle` | `ODS-G-001..010`、merge/resource-budget fixtures；`REL-G2` |
| `SDD-SEC-01` | `tests/test_security_boundaries.py::test_sdd_sec_01_trust_boundary_matrix` | host/redirect/ZIP/XML/path/SQL cases；`REL-G1` |
| `SDD-OBS-01` | `tests/test_models.py::test_sdd_obs_01_status_and_logs_exclude_query_content` | structured status/log capture；`REL-G1`、`REL-G5` |
| `SDD-AUDIT-01` | `tests/test_snapshot_publish.py::test_sdd_audit_01_subject_digest_binds_all_evidence` | tamper-each-input matrix＋review/certificate hashes；`REL-G1` |
| `SDD-API-01` | `tests/test_mcp_stdio.py::test_sdd_api_01_public_contract_resource_matches_discovery` | installed `public-contract-v1.json`與22-tool discovery equality；`REL-G1` |
| `SDD-QUAL-01` | `tests/test_cdc_pdf_importer.py::test_sdd_qual_01_liteparse_identity_and_resource_resolution` | out-of-tree wheel、missing/mismatch/success preflight；`CDC-R1-LAYOUT` |

## 3. 現況與限制

### 3.1 現有程式

以下四點是文件撰寫時的 v0.1.1 sample-only baseline，不代表目前 worktree：

- `src/taiwan_lab_mcp/server.py` 在 import 時建立 CDC、NHI、TFDA adapter，提供 18 個 MCP tools。
- `src/taiwan_lab_mcp/adapters/base.py` 只接受 `TAIWAN_LAB_DATA_MODE=sample`，由 package resources 載入四份合成 JSON。
- `src/taiwan_lab_mcp/models.py` 的 `ToolResult.data_mode` 與 `sample_only` 目前分別固定為 `sample` 與 `true`。
- `DataRecord` 已驗證 official record 必須有 retrieval、license 與非 synthetic provenance，這個安全邊界應保留。
- 現有測試已鎖定 sample warning、Unicode 查詢、角色不混淆、無結果語意、stdio transport 與禁止未實作 mode 靜默降級。

文件撰寫時唯一可驗證狀態是 sample-only baseline。現在 worktree 已包含第一輪共用 official_snapshot runtime、data CLI、manifest/current descriptor、SQLite store、package contract／rule／schema resources、NHI importer 與 official-mode stdio path；NHI 目前可由 synthetic／offline snapshot 驗證，但正式 source review、scope／owner gate、official golden、pilot 與 production qualification 仍未完成。TFDA、CDC PDF／ODS 仍維持 **PLANNED / data_unavailable**，不可把第一輪 NHI evidence 擴張成四個來源已完成。

### 3.2 已確認的上游限制

- NHI 官方宣告每日更新，但實際週末／假日 cadence 尚未有 30 天觀測；CSV 只有現行項目，沒有完整歷史，也沒有 laboratory 分類欄。
- TFDA 官方宣告每 7 日更新；CSV endpoint 實際回 ZIP。許可／登錄字號是 group key，不能當 row key；資料沒有 official `ivd=true` 欄位。
- CDC 手冊明示不定時更新；landing page 日期、附件版本和 HTTP metadata 可能不同。PDF 文字層存在，但純文字順序不足以保存表格語意。
- CDC 認可機構沒有查到官方固定更新頻率。ODS 有垂直合併格、12 個有效欄位與大量宣告但空白的重複欄。
- CDC 歷史版本完整下載來源及 bulk curated redistribution 的最終法務判斷尚未確認。

## 4. 架構決策

### 4.1 同步與查詢分成兩個程序

資料同步是具網路與寫入權限的 batch process；MCP runtime 是無網路需求、只讀 curated snapshot 的 query process。MCP tool 呼叫期間 MUST NOT 下載官方資料或寫入 snapshot。

```text
Official landing / metadata / artifact
                    |
                    v
  data CLI: discover -> fetch -> verify -> parse -> normalize
                    |                         |
                    |                         +--> quarantine + report
                    v
             staged validation -> review -> immutable curated snapshot
                                                    |
                                  atomic availability descriptor replace
                                                    |
                                                    v
                              MCP runtime -> read-only SQLite -> ToolResult
```

此切分使上游失效、PDF 審查延遲與 MCP 查詢可用性互不耦合，也讓本機 runtime 不因查詢而對外連線。這只代表適合本機離線查詢，不構成院內部署 readiness；MCP host／LLM 的傳輸、記錄、權限與 retention 不在 P1.1 已驗證範圍。

### 4.2 Curated 格式使用每來源一份 SQLite

P1.1 使用 Python standard library `sqlite3`，每個 approved snapshot 產生一份不可再修改的 SQLite 檔案：

- NHI 與 TFDA 資料量適合 indexed lookup，不應由每個 request 全量讀 JSON。
- CDC 可把不同章節與 ODS entity 分表，避免提早做有損 join。
- SQLite 支援唯讀連線、transactional build 與基本全文前綴／substring 查詢；P1.1 不加入 ORM 或搜尋服務。
- 不使用 SQLite FTS 作第一版必要條件；先用 normalized 欄位、exact index 與受限 `LIKE`。實測不足時再以 ADR 說明是否啟用內建 FTS5。

Builder 固定使用 rollback journal（`journal_mode=DELETE`），commit 後執行 `wal_checkpoint(TRUNCATE)`（若建置期間曾進 WAL）、關閉所有連線，並確認不存在 `-wal`、`-shm`、`-journal` sidecar，才計算單一 database hash。Runtime 每次 query 先讀一次 current availability descriptor，再以安全編碼的 SQLite URI `mode=ro` 開啟該 immutable database；只有完整 hash 已通過且檔案承諾永不再修改時才加 `immutable=1`。連線立即設定 `PRAGMA query_only=ON`、在支援版本設定 `PRAGMA trusted_schema=OFF`、明確停用 extension loading，所有 SQL 參數化。不共享可寫連線，也不在 runtime 自動 migrate database。

### 4.3 不建立過度通用的 importer framework

共用程式只處理下載、hash、manifest、atomic file replacement、SQLite 建置與共同文字正規化。NHI CSV、TFDA ZIP、CDC PDF、CDC ODS 的解析與領域驗證分開實作；不得為了共用而把不同來源強塞成一張通用 record table。

## 5. 元件與責任

| 元件 | 責任 | 不負責 |
| --- | --- | --- |
| `SourceDiscovery` | 從核准的官方 landing/metadata 找到當期 resource，保存實際 URL | 搜尋網路找相似資料集、臨時接受新 host |
| `Fetcher` | 限制 redirect、時間、大小；串流寫暫存檔並計算 SHA-256 | 解析領域內容、發布 current |
| source importer | 驗內容格式、解析 raw 欄位、產生 staged rows | 自動核准 schema drift 或專業語意 |
| source validator | batch/row/domain/drift 檢查，輸出 report/quarantine | 修改 raw value 來讓資料通過 |
| reviewer workflow | 記錄人工、醫檢及 owner 決議 | 以 README 文字取代可稽核 review record |
| snapshot builder | 在暫存路徑完整建立 SQLite、manifest 與 hash | 覆寫既有 snapshot |
| publisher | 驗證 approved 狀態後原子替換 current availability descriptor | 將 staged/rejected snapshot 暴露給 runtime |
| runtime store | 驗 availability descriptor、manifest、database hash並唯讀查詢 | 網路同步、規則推論、寫入資料 |
| domain adapter | 驗 query、呼叫 store、組合 ToolResult 與警示 | 隱藏 stale、混合不同 mode、做臨床推論 |

## 6. 本機資料目錄

資料根目錄由 `TAIWAN_LAB_DATA_DIR` 指定。official mode 未設定、路徑不存在或不可讀時 MUST 停止啟動。sample mode 不讀這個目錄。

```text
<data-root>/
  raw/<source-id>/<raw-revision-id>/
    artifacts/*                  # 原始 bytes，不修改
    fetch.json                   # URL、headers、大小、hash、取得時間
  staged/<source-id>/<build-attempt-id>/
    records.jsonl                # 原始欄位加 parser locator
    validation.json
    diff.json
  quarantine/<source-id>/<build-attempt-id>/
    rows.jsonl
    reasons.json
  reviews/<source-id>/<curated-build-id>/
    review.json
  curated/<source-id>/<curated-build-id>/
    data.sqlite3
    manifest.json
    audit/
      validation.json
      qualification-candidate.json
      golden-qualification.json
      reviews/<gate-id>.json
  manifests/current/
    <source-id>.json             # 單檔 availability descriptor；serving pointer + operational state
  checks/<source-id>/
    YYYY-MM-DDTHHMMSSZ.json      # 即使 hash 相同也保留 upstream check 結果
```

`source-id` 固定為 `nhi_fee`、`tfda_devices`、`cdc_specimen_manual`、`cdc_authorized_labs`。同一次 build 的暫存、raw、staged、curated MUST 在同一 filesystem 上建立，atomic rename 不跨磁碟。目錄預設不進 Git；是否經 GitHub Release 再散布 curated artifact 是 `OWNER GATE`。

版本化規則、schema、review protocol與qualifier spec必須放入Python package，讓repo外安裝的wheel仍可用`importlib.resources`解析；同步時再將實際使用的bundle hash與必要檔案複製進immutable audit bundle：

```text
src/taiwan_lab_mcp/rules/
  nhi_lab_scope/<rule-version>.jsonl
  nhi_aliases/<rule-version>.jsonl
  tfda_ivd/<rule-version>.jsonl
src/taiwan_lab_mcp/schemas/
  <source-id>/<schema-version>.json
src/taiwan_lab_mcp/review_protocols/
  <protocol-id>/<protocol-version>.json
src/taiwan_lab_mcp/qualifier_specs/
  liteparse-2.0.0.json
src/taiwan_lab_mcp/contracts/
  public-contract-v1.json
```

規則檔只有完成來源定位、reviewer 與核准日期的列才能標 `approved`。未通過法務確認前，不把整份官方附表原文複製進 Git；只保存完成決策所需的官方 locator、hash 與最小引用。Build 不接受工作目錄中的同名 top-level `rules/` 作 fallback；repo 外 wheel test 必須證明 active schema/rule 可定位且 hash 相同。

## 7. Snapshot、manifest 與 provenance

### 7.1 Raw revision、build attempt 與 curated build

三種 ID 不得混用：

- `raw_revision_id`：對下述 `RawRevisionFingerprintV1` canonical bytes 計算 SHA-256。它識別一組上游 bytes 與非揮發性 discovery identity，不是官方版本。
- `curated_build_id`：對下述 `CuratedBuildFingerprintV1` canonical bytes 計算 SHA-256，格式為 `<source-id>-build-<full sha256>`；manifest的`build_fingerprint_sha256`就是同一個full hash，禁止另算。
- `build_attempt_id`：`<UTC timestamp>-<random 128-bit hex>`，只識別一次 temp/staged 執行。失敗 attempt 可保留證據並用相同 build fingerprint 重跑，不佔用 final curated path。

只有同一 `curated_build_id` 已存在、final manifest/DB/audit 全部通過 readback 時才能 skip build。相同 raw 在 parser bug fix、schema/normalization/rule更新或 extractor output改變時 MUST 產生不同 curated build。相同 raw 的失敗 build 不得阻止重試。CDC `raw_revision_id` 必須同時包含 landing/viewer metadata、手冊 PDF 與修訂表 PDF 的 role/hash；只更新其中一份會得到新 revision。

對外 `snapshot_id` 是 `curated_build_id` 的相容欄位別名；manifest 另保留完整 `raw_revision_id`。它們皆是本地識別碼，不能顯示成官方版本。

#### Canonical JSON bytes

所有 fingerprint、subject digest 與 package resource inventory 共用同一個 project-owned `canonical_json_bytes_v1`：輸入只能含 object、array、UTF-8 string、base-10 integer、boolean 或 null，禁止 float/NaN/Infinity；object key 依 Python Unicode code point 升冪，array 維持 schema 指定順序；使用 `json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")`，不加 BOM、不加換行，也不做 Unicode normalization。日期時間在進入 canonical object 前一律為 RFC 3339 UTC、秒精度、尾碼 `Z`；無法可信轉換的官方時間只放 `*_raw`、precision 與 timezone-known 欄，不猜時區。Schema 不允許額外欄位，因此新增 fingerprint input 必須提升版本。

`RawRevisionFingerprintV1` 的 canonical object 固定為：

```json
{
  "fingerprint_schema": "raw-revision-v1",
  "source_id": "<source-id>",
  "discovery": {
    "landing_url": "<normalized exact https URL>",
    "provider_id": "<official publisher/dataset identifier or null>",
    "dataset_id": "<official dataset identifier or null>",
    "license_name": "<raw official value or null>",
    "license_url": "<normalized exact https URL or null>",
    "official_version_label_raw": "<raw value or null>",
    "official_modified_at_raw": "<raw value or null>",
    "official_modified_at_precision": "<declared precision or null>",
    "official_modified_timezone_known": false
  },
  "artifacts": [
    {"artifact_id":"<stable role-local id>","role":"<approved role>","media_type_verified":"<verified type>","bytes":123,"sha256":"<64 lowercase hex>"}
  ]
}
```

`artifacts` 依 `(role, artifact_id)` 升冪且 ID 不得重複；NHI/TFDA/ODS 的 role 固定 `primary`，CDC 依序固定 `landing_html`、`viewer_html_manual`、`manual_pdf`、`viewer_html_revision`、`revision_pdf`。參與hash的landing/license URL先以RFC 3986 parser驗證：scheme/host小寫、移除fragment、保留path/query bytes；不移除或重排query。Artifact的resolved/final/resource URL可能含短期token，完整保存於`fetch.json`與manifest，但不參與raw revision。`fetched_at`、HTTP `Date`、ETag、Last-Modified、request/run ID、重試次數、redirect trace、暫存/絕對路徑與未列 headers 全部排除；`discovery_metadata_sha256` 就是上述 `discovery` object 的 canonical bytes hash，不能另選欄位。

`CuratedBuildFingerprintV1` 固定為：

```json
{
  "fingerprint_schema":"curated-build-v1",
  "source_id":"<source-id>",
  "raw_revision_id":"<hash>",
  "application_build_sha256":"<installed distribution inventory hash>",
  "parser":{"version":"<id>","bundle_sha256":"<hash>"},
  "schema":{"version":"<id>","bundle_sha256":"<hash>"},
  "normalization":{"version":"<id>","bundle_sha256":"<hash>"},
  "rules":[{"name":"<name>","version":"<id>","bundle_sha256":"<hash>"}],
  "qualifier":{"name":"<name or null>","version":"<id or null>","spec_sha256":"<hash or null>","extractor_output_sha256":"<hash or null>"}
}
```

`rules` 依 `(name, version, bundle_sha256)` 升冪。每個 bundle hash 都是 wheel 內對應單一 package-resource bytes 的 SHA-256；多檔 bundle則對`[{"path": package-relative POSIX path, "bytes": integer, "sha256": file hash}]`依path升冪後的canonical bytes取hash。CDC的`extractor_output_sha256`是project-owned`CdcLayoutV1` canonical bytes hash，不是工具的暫存JSON hash；非CDC固定null。

`application_build_sha256` 明確選擇「已安裝distribution inventory」，不用版本字串、Git tree或不一定仍存在的wheel archive bytes。以`importlib.metadata.distribution("taiwan-laboratory-mcp")`讀取distribution files，拒絕editable/direct-directory install；從wheel `RECORD`驗每個member原始hash/size，並對所有`taiwan_lab_mcp/**`與該distribution自己的`<name-version>.dist-info/{METADATA,WHEEL,entry_points.txt}`實際bytes建立`[{"path": wheel-relative POSIX path, "bytes": integer, "sha256": file hash}]`，依path升冪後取`canonical_json_bytes_v1` SHA-256。排除`RECORD`、`direct_url.json`、`INSTALLER`、`REQUESTED`、`__pycache__`與`.pyc`等安裝器/環境衍生檔；任何RECORD mismatch或缺少預定package resource即`APPLICATION_BUILD_IDENTITY_MISSING`。Release evidence可另記原始wheel archive SHA-256，但它不參與curated identity。第二人安裝同一wheel會得到相同inventory hash；Git checkout/editable install只能產生`development` staged attempt，不得產生`state=approved`、reviewable subject或production curated path。

### 7.2 Canonical row identity

結構化來源的 `source_row_sha256` 計算方式固定為：

1. 依 approved schema 的原始欄位順序建立 JSON array，不用 object key 排序。
2. 值使用 parser 解碼後的原始 cell string；不 trim、不 NFKC、不 casefold，null 與空字串分開。
3. 以 UTF-8、`ensure_ascii=false`、無多餘空白的 JSON bytes 計算 SHA-256。

`source_row_number` 只作 snapshot 內 locator，不能作跨版 identity。各來源另有非官方的 logical key，僅供查詢或 diff：

| 來源 | row identity | group / logical key |
| --- | --- | --- |
| NHI | 7 個原始欄位的 canonical hash | `code_normalized`；重複 code 必須 block review |
| TFDA | 34 個原始欄位的 canonical hash | 許可／登錄字號只作 group key；製造關係不去重 |
| CDC PDF | 文件 hash + table section + PDF page + row bbox + raw cells 的 hash | 疾病、檢體、目的、時間、方法等組合只供跨版 diff，不宣稱穩定官方 ID |
| CDC ODS | 展開合法 merge span 後 12 個原始欄位的 canonical hash | 證號只作 group key；疾病／目的／方法子列保留 |

TFDA `manufacturer_site_id` 若需要 UI grouping，可由製造商、廠址、國別、製程原值的 canonical hash 產生，但 MUST 標示為本地衍生 ID。

### 7.3 Immutable manifest schema

每個 curated snapshot 的 `manifest.json` 至少包含下列欄位。實作時以 Pydantic `extra="forbid"` 驗證，schema 變更必須提升 `manifest_schema_version`。

```json
{
  "manifest_schema_version": 1,
  "snapshot_id": "nhi_fee-build-<64 lowercase hex>",
  "raw_revision_id": "<64 lowercase hex>",
  "curated_build_id": "nhi_fee-build-<64 lowercase hex>",
  "build_fingerprint_sha256": "<64 lowercase hex>",
  "discovery_metadata_sha256": "<64 lowercase hex>",
  "review_subject_digest": "<64 lowercase hex>",
  "source_id": "nhi_fee",
  "state": "approved",
  "source": {
    "provider": "衛生福利部中央健康保險署",
    "dataset_name": "醫療服務給付項目及支付標準(csv檔)",
    "dataset_id": "174450",
    "identifier": "A21030000I-D20021",
    "landing_url": "https://data.gov.tw/dataset/174450",
    "license_name": "政府資料開放授權條款－第 1 版",
    "license_url": "https://data.gov.tw/license",
    "attribution": "資料提供機關：衛生福利部中央健康保險署"
  },
  "official_version": {
    "label": null,
    "modified_at_raw": "2026-09-12 07:02:04",
    "modified_at_precision": "second",
    "timezone_known": false
  },
  "fetched_at": "2026-09-13T08:30:00+08:00",
  "discovery": {
    "data_root_relative_path": "raw/nhi_fee/<raw-revision-id>/fetch.json",
    "sha256": "<64 lowercase hex>"
  },
  "artifacts": [
    {
      "artifact_id": "nhi-primary-csv",
      "role": "primary",
      "resource_url": "https://info.nhi.gov.tw/...",
      "storage_scope": "data_root",
      "data_root_relative_path": "raw/nhi_fee/<raw-revision-id>/artifacts/source.csv",
      "local_artifact_available": true,
      "media_type_reported": "application/csv",
      "media_type_verified": "text/csv",
      "bytes": 1725985,
      "sha256": "<64 lowercase hex>"
    }
  ],
  "transform": {
    "application_version": "<package version>",
    "application_build_sha256": "<hash>",
    "parser": {"version": "nhi-csv-v1", "bundle_sha256": "<hash>"},
    "schema": {"version": "nhi-7-v1", "bundle_sha256": "<hash>"},
    "normalization": {"version": "text-v1", "bundle_sha256": "<hash>"},
    "rules": [
      {"name": "nhi_lab_scope", "version": "<version>", "bundle_sha256": "<hash>"},
      {"name": "nhi_aliases", "version": "<version>", "bundle_sha256": "<hash>"}
    ]
  },
  "counts": {
    "input_rows": 6173,
    "curated_rows": 6173,
    "quarantined_rows": 0
  },
  "validation": {
    "automated_validation_status": "passed",
    "blocking_errors": [],
    "warnings": []
  },
  "review": {
    "human_review_status": "approved",
    "required_gates": ["NHI-R1-SOURCE", "NHI-R1-SCHEMA", "PUB-R1-OWNER"],
    "completed_gates": ["NHI-R1-SOURCE", "NHI-R1-SCHEMA", "PUB-R1-OWNER"],
    "capability_reviews": [
      {"capability": "nhi_lab_scope", "gate_id": "NHI-R1-SCOPE", "status": "pending"}
    ]
  },
  "audit_evidence": {
    "validation": {"data_root_relative_path": "curated/nhi_fee/<curated-build-id>/audit/validation.json", "sha256": "<hash>"},
    "qualification_candidate": {"data_root_relative_path": "curated/nhi_fee/<curated-build-id>/audit/qualification-candidate.json", "sha256": "<hash>"},
    "golden_qualification": {"data_root_relative_path": "curated/nhi_fee/<curated-build-id>/audit/golden-qualification.json", "sha256": "<hash>"},
    "reviews": [
      {"gate_id": "NHI-R1-SOURCE", "data_root_relative_path": "curated/nhi_fee/<curated-build-id>/audit/reviews/NHI-R1-SOURCE.json", "sha256": "<hash>"},
      {"gate_id": "NHI-R1-SCHEMA", "data_root_relative_path": "curated/nhi_fee/<curated-build-id>/audit/reviews/NHI-R1-SCHEMA.json", "sha256": "<hash>"},
      {"gate_id": "PUB-R1-OWNER", "data_root_relative_path": "curated/nhi_fee/<curated-build-id>/audit/reviews/PUB-R1-OWNER.json", "sha256": "<hash>"}
    ]
  },
  "freshness": {
    "official_cadence": "P1D",
    "cadence_status": "officially_declared_not_observed_sla",
    "last_upstream_check_at": "<offset datetime>",
    "latest_official_version_seen": null,
    "serving_approved_version": null,
    "stale": false,
    "stale_reason_codes": []
  },
  "publication": {
    "curated_build_relative_path": "curated/nhi_fee/<curated-build-id>/data.sqlite3",
    "curated_sha256": "<hash>",
    "approved_at": "<offset datetime>",
    "published_at": null
  }
}
```

Manifest 不能把未知 publisher timezone 補成台北時間；保留原字串、精確度與 `timezone_known=false`。HTTP response time、portal metadata modified time、embedded data date、record max changed date與 fetched time必須是不同欄位，不得互相替代。Manifest 的 freshness 是核准當下的快照；後續 check 與 stale 變化只寫入 current availability descriptor及immutable check record，不能回頭修改 approved manifest。`published_at` 在 manifest 保持 null；唯一public/current欄名為`last_successful_publish_at`，由 descriptor與publish event記錄，`last_publish_at`是拒絕序列化的legacy key。

所有 artifact/evidence path 都是 `data_root_relative_path`，不得使用語意不明的 `relative_path`。Publisher 對每一個 path 做 data-root containment、存在性與 SHA-256 readback。若再散布的 curated bundle依法不含 raw artifact，保留 artifact URL/hash，但設 `local_artifact_available=false`；這時只能宣稱 `snapshot_traceable=true`，不能宣稱本機可開啟原檔或 `currently_reproducible_from_upstream=true`。

`review_subject_digest` 是 `canonical_json_bytes_v1` 對 `ReviewSubjectV1` object 的 SHA-256。Object 固定含 `subject_schema="review-subject-v1"`、`source_id`、`raw_revision_id`、`curated_build_id`、依 `(role, artifact_id)` 排序的 `artifacts[{artifact_id,role,sha256}]`、`curated_db_sha256`、完整 `CuratedBuildFingerprintV1`、`validation_report_sha256` 與 `qualification_candidate_sha256`；不得含 review、final certificate、published time 或 absolute path。每筆 accepted review record必須持有相同subject digest；publisher依相同 canonical bytes重新計算後逐gate比對。Final qualification certificate與manifest引用review hashes，但不加入被review record簽核的subject，避免循環依賴。

### 7.4 Review 與 qualification evidence（`SDD-AUDIT-01`）

`ReviewRecordV1` 以 Pydantic `extra="forbid"` 驗證，固定欄位為：

```text
review_schema_version=1, gate_id, decision(approved|rejected),
source_id, curated_build_id, subject_digest,
reviewer_id, reviewer_role, identity_assurance(local_asserted|cryptographically_signed),
reviewed_at(offset datetime),
protocol_id, protocol_version, protocol_sha256,
review_scope, evidence_refs[{artifact_id/path, locator, sha256}],
finding_counts{critical,major,minor}, comments, signature(nullable)
```

`local_asserted` 只表示本機稽核紀錄，不構成身分認證；只有實際驗簽通過才可寫 `cryptographically_signed`。`decision=approved` 必須 `critical=0` 且符合該 protocol 的 major/minor門檻。修正資料、parser、rule、DB、validation/golden report任一 bytes後 subject digest 都會改，全部 review records 必須重新產生，不可沿用舊簽核。

`GoldenCaseV1`固定包含`case_id`、`source_id`、input artifact/fixture hash、expected fields/warnings、完整locator、parser/schema/normalization/rule/extractor versions與hashes、reviewer role/time/decision。Pre-review `QualificationCandidateV1`保存case IDs、逐案結果、`automated_status`與`synthetic_ci_status`，其hash納入subject digest。Reviews完成後publisher才產生`QualificationCertificateV1`，保存subject digest、candidate report hash、accepted review hashes與`official_qualification_status=approved`；certificate本身不反向納入subject digest。只有綁定當次official raw artifact且certificate approved的case可計入來源至少10案；synthetic CI通過不得冒充official qualification。

Final validation、qualification candidate/certificate與各gate review record都複製進curated`audit/`後才計算manifest。`required_gates`與`completed_gates`必須集合完全相等、不得重複，而且每個completed gate恰有一份`decision=approved`、subject digest相同的review evidence；缺一即禁止發布。

`capability_reviews`不等於serving snapshot的required gates：NHI scope或TFDA IVD gate pending時，可依operation matrix服務完整source rows、明確candidate與已逐筆核准的included決議，但相應`coverage_status=review_incomplete`，不得宣稱完整範圍。Capability gate核准會改rule bundle與curated build ID，必須新build後才能變成complete。

Gate namespace固定如下；PRD release gates只使用 `REL-G1`～`REL-G5`，不得在 source review record寫裸 `G1`～`G5`：

| Source | Qualification/review gate | 對應 release gate |
| --- | --- | --- |
| NHI | `NHI-R1-SOURCE`、`NHI-R1-SCHEMA`、`NHI-R1-SCOPE` | `REL-G2`、`REL-G3` |
| TFDA | `TFDA-R1-SOURCE`、`TFDA-R1-SCHEMA`、`TFDA-R1-IVD` | `REL-G2`、`REL-G3` |
| CDC PDF | `CDC-R1-SOURCE`、`CDC-R1-LAYOUT`、`CDC-R1-CONTENT` | `REL-G2`、`REL-G3` |
| CDC ODS | `ODS-R1-SOURCE`、`ODS-R1-STRUCTURE`、`ODS-R1-CONTENT` | `REL-G2`、`REL-G3` |
| 所有來源 | `PUB-R1-OWNER` | 各來源 publish authorization；不取代 `REL-G5` pilot |

### 7.5 Availability descriptor：單一讀取協定

`manifests/current/<source-id>.json` 是 runtime 唯一讀取的可變 availability descriptor；不另設第二份 `manifests/status`。同一個 `CurrentAvailabilityV1` object 原子承載 serving pointer 與 operational status，至少包含：

```text
descriptor_schema_version, source_id, generation,
serving_snapshot_id, serving_curated_build_id, manifest_data_root_relative_path, manifest_sha256,
parent_snapshot_id, last_successful_publish_at, publisher_actor_id,
last_check_at, last_successful_check_at, latest_seen_version,
latest_seen_artifact_sha256, latest_candidate_id, latest_candidate_status,
check_result, failed_stage, error_code, stale, stale_reason_codes,
freshness_policy_version, content_age_status, content_age_evidence,
latest_check_data_root_relative_path, latest_check_sha256
```

Descriptor使用`canonical_json_bytes_v1`序列化後原子寫入；runtime拒絕duplicate JSON keys、extra fields、非canonical bytes與不合法timestamp。這個canonical form同時是CAS的before/after SHA-256輸入。

尚無serving build時，`serving_snapshot_id`、`serving_curated_build_id`、manifest四欄、`parent_snapshot_id`、`last_successful_publish_at`與publisher均為null，但descriptor仍可揭露candidate/check；此時依PRD truth table回data unavailable、serving statuses not applicable、`stale=false`與空reasons。只有整份descriptor尚未建立時，candidate固定回`none`，不可使用未列 enum 的 `unknown` 或掃staged猜測。

Runtime 對每次 operation 只開啟並完整讀取 descriptor 一次，驗 schema/source/generation，接著依該次讀到的同一份 bytes 驗 manifest、audit 與 DB；operation 期間不重讀 current。新連線才讀新 generation，因此一次 query 只能看到完整 A 或完整 B。Runtime 依序驗：

1. descriptor schema、source id、完整 canonical JSON與 `generation >= 1`。
2. serving欄全null或全有；全null時不開資料庫並回source unavailable。
3. 有serving時，manifest path 經 resolve 後仍位於 `<data-root>/curated/<source-id>/`，且manifest SHA-256、`state=approved`、review gates、source id與curated build id一致。
4. 有serving時，SQLite/audit path containment、SHA-256與read-only integrity。
5. 有serving時`latest_check_*`必須共同指向`<data-root>/checks/<source-id>/`的完整immutable check record且hash正確，operational status與check record一致；缺任一欄即integrity failure。只有無serving的初始descriptor可讓兩欄同為null，且其candidate/check欄亦須使用schema指定的empty狀態。

任一步失敗映射為 public `availability=data_unavailable`、`result_status=data_unavailable`。Descriptor 不存在時只讀 append-only publish-event index：沒有任何成功 publish event 表示從未建立，映射 `no_serving_snapshot` 並固定 candidate none；已有成功 event 則是遺失／損壞，internal `CURRENT_POINTER_INTEGRITY` 映射 public `serving_integrity_failure`。Descriptor 完整但沒有 serving build 也映射 `no_serving_snapshot`，並可揭露其已驗證 candidate/check；descriptor/pointer/manifest/DB/audit 其他失敗映射 `serving_integrity_failure`；check/status schema、hash、source或generation不一致的 internal `OPERATIONAL_STATUS_INTEGRITY` 映射 public `operational_status_integrity_failure`。兩種 integrity failure 固定 candidate none／ID null且不揭露候選狀態。不得降格成 stale、讀舊 generation、搜尋 staged 猜測候選或 fallback sample。

### 7.6 Operational status 更新

每次 upstream check 先寫 immutable `checks/<source-id>/<check-id>.json`，再取得與publish相同的per-source OS lock，讀取 current descriptor原始bytes/hash與generation；若檔案尚不存在則以generation 0、serving全null的in-memory baseline開始。建立`generation + 1`且「serving欄完全不變、operational欄更新」的新 descriptor；temp flush/fsync後以單一 `os.replace` 切換並readback。若鎖內 current generation/hash與check開始時的expected generation/hash不同，重讀新 descriptor並重新計算status；不得把舊snapshot identity寫回。Publish則在同一把lock中建立「新serving欄＋已知最新operational欄」的完整descriptor。`generation`因此是descriptor revision，不只是publish次數；`parent_snapshot_id`才表達serving lineage。兩條 writer path 都只做一次單檔replace，所以不存在pointer已切B而status仍指A的availability window。

Operational欄保存 `last_check_at`、`last_successful_check_at`、latest seen version/hash、candidate、check result、failed stage、internal error code與PRD允許的stale狀態。詳細證據只在 immutable check record；descriptor以path/hash引用。`last_successful_publish_at` 只在成功publish/rollback後更新，upstream check不得改寫。Operational status不能授權snapshot；publisher仍重驗manifest、audit與reviews。

### 7.7 Row-level provenance

`items` 不再是無契約的 `list[dict]`；每一筆使用 typed `ItemEnvelope`：

```text
record: source-specific typed payload
evidence: [{artifact_id, source_row_sha256, locator, raw_value_available}]
item_warnings: [stable warning code]
safety: source-specific structured safety flags
```

Snapshot 共用欄位可在 ToolResult top-level 只回一次，但每個來源 row 必須有自己的 evidence。TFDA permit group 中的每一個 manufacturing child row都要各帶 `artifact_id + source_row_sha256 + locator`；CDC 手冊列必須指向 manual PDF artifact，revision evidence另指向 revision PDF artifact，不可用一個未標 role 的 hash代表兩份 PDF。每筆 official result至少回傳：

- `snapshot_id`、`source_id`、provider、landing URL、實際 resource URL。
- official version/date 原值與精確度、`retrieved_at`。
- raw artifact SHA-256、parser/schema/rule version、license 與 attribution。
- `source_row_sha256` 及來源 locator。
- current `stale`、`stale_reason_codes`、`last_check_at`、`serving_review_status`。
- `snapshot_traceable`、`local_artifact_available`、`currently_reproducible_from_upstream` 三個獨立布林值。

Locator 依來源分別為 NHI/TFDA 的 source row number、CDC 的 `pdf_page + printed_page + table_section + row_bbox`、ODS 的 sheet name + expanded row number。頁碼或 row number 不單獨當 identity。

## 8. Pipeline 狀態機與發布

### 8.1 狀態

```text
discovered -> fetched -> raw_verified -> parsed -> validated
                                              |          |
                                              |          +-> review_pending -> approved -> published
                                              |                    |
                                              +-> quarantined       +-> rejected

任何階段 -> failed
```

- `quarantined` 保存異常 row與原因，但 P1.1 不允許以丟棄官方 source row的方式發布看似完整的 snapshot。NHI/TFDA/ODS 任一 source row若無法 round-trip，或 CDC 任一目標表列無法可靠歸欄，整批 block。
- `review_pending`、`rejected`、`failed` 不能發布。
- `published` 是 current availability descriptor/publish event 已成功切換的運維狀態；immutable manifest 本身仍保持 `state=approved`，即使尚未 serving 也不可修改。
- `stale` 是 serving snapshot 的正交狀態，不是 pipeline state。

P1.1 的 source-row disposition 固定如下，不實作 partial publish：

| Source condition | Curated disposition | Publish disposition |
| --- | --- | --- |
| NHI 任一列欄數、必要值、points或日期無法解析 | raw/staged/quarantine均保留 | 整批 block |
| TFDA 任一列欄數、必要日期或核心識別無法 round-trip | raw/staged/quarantine均保留 | 整批 block，不可只刪該列 |
| TFDA 註銷欄互相衝突、角色欄缺值 | 原列完整進 curated，加 semantic warning；query衍生狀態為 unknown | 可進 review，不得隱藏列 |
| TFDA 分類缺失、舊制或未知 | 原列完整進 curated，`ivd_scope=unknown` | 一般許可查詢可用；IVD reviewed-only不可納入 |
| CDC 目標表任一列無可靠表頭／bbox／跨頁 lineage | raw/staged/quarantine與page evidence均保留 | 整批 block |
| ODS merge span、12欄或任一資料列無法 round-trip | raw/staged/quarantine均保留 | 整批 block |
| ODS能力試驗欄為日期、文字或真空白 | 原值保留，不視為parse error | 可進 review |

因此 published snapshot 的 `counts.input_rows == counts.curated_rows`（CDC則等於 qualification確認的目標表語意列數），`quarantined_rows` 必須為 0。未來若要 partial publish，需新 PRD acceptance、owner gate、public coverage enum與每次 query警示；不得以調高 threshold 偷渡。

### 8.2 Atomic publish（`SDD-PUB-01`）

1. 在 `<data-root>` 同一 filesystem 的 unique temp directory 建立 SQLite，完成 audit bundle、sidecar absence、`PRAGMA integrity_check`、row count與 golden qualification。
2. 關閉連線，計算 DB/audit/manifest hash，將完整 build directory以不覆寫方式移入 `curated/<source>/<curated-build-id>`；同 ID 已存在但任一 hash不同即停止。
3. Publisher 對 `<data-root>/locks/<source-id>.publish.lock` 取得 OS-level exclusive lock。POSIX 用 `fcntl.flock(LOCK_EX)`；Windows 在 generated lock file固定第一 byte用 `msvcrt.locking(..., LK_NBLCK, 1)` 加 bounded retry。鎖由 OS隨 process結束釋放，不用刪 lock file判定所有權。
4. 在鎖內讀 current availability descriptor 原始 bytes/hash；尚不存在時使用generation 0、serving全null baseline。Publish request必須帶 `expected_generation` 與 `expected_parent_snapshot_id`；兩者與current不符即`PUBLISH_CAS_MISMATCH`，不得切換。第一次writer可預期generation 0；若upstream check已建立無serving descriptor，首次publish必須使用當下generation且parent仍為null。
5. 建立 generation + 1 的完整 `CurrentAvailabilityV1`：serving欄指向新build、`parent_snapshot_id`指向剛驗證的current、`last_successful_publish_at`設為這次成功切換時間，operational欄以鎖內讀到的最新check/candidate重算，不沿用候選建立時的舊值。在current同目錄寫temp，flush與`os.fsync()`後用單一`os.replace()`切換，再readback descriptor/manifest/DB/audit與generation。
6. 寫 append-only publish event，包含 before/after descriptor hashes、actor、時間與結果，最後才釋放 lock。

兩個 publisher或publish/status updater同時從 generation N出發時，只有先取得鎖且通過CAS的一方可切換；後到者必須重讀並依其operation重算，舊publish候選不得倒退current，一般 `publish` 禁止 `parent_snapshot_id`倒退。Rollback 使用獨立 `rollback` 命令，必填 target curated build、expected generation、reason、actor與時間；仍在同一鎖內CAS、generation + 1並留下 `rollback=true` event，不可偽裝成普通 publish。

POSIX 在 descriptor replace前後另對 parent directory `fsync`。Windows P1.1只承諾支援本機NTFS上 process-crash時的單檔replace atomicity，先flush file handle並readback；Python stdlib無法對目錄提供相同power-loss durability保證。啟動時若descriptor毀損，runtime保持 unavailable，不自動猜最近build；operator只能用 `recover-current --publish-event <id>` 驗證 event、manifest/DB/audit/check後重建descriptor。

### 8.3 Fail closed 與 stale（`SDD-FAIL-01`、`SDD-FRESH-01`）

- 沒有 approved official snapshot：official tool 回 `data_unavailable`。
- 新版下載或驗證失敗：繼續服務上一個 approved snapshot，並令 `stale=true`；public `stale_reason_codes` 只使用 PRD registry，具體失敗 stage 與最後成功核對時間留在 immutable check evidence／status timestamps，不塞入自由文字 reason code。
- 已發現 CDC 新版但未完成審查：服務上一個 approved snapshot，stale reason code含 `newer_candidate_pending_review`。
- NHI 預設在超過兩個宣告週期沒有成功 upstream check 時標 stale；「7 日後是否 hard-stop 查詢」仍是 `OWNER GATE`，未決定前只可持續回舊版並顯著揭露。
- TFDA `stale` 只依最後一次完整 upstream verification是否逾產品門檻，以及是否有新版待審／被拒。CSV沒有 embedded date；`portal_metadata_modified_at`、nullable `embedded_data_updated_on`、`max_record_changed_on` 分開保存為 evidence。內容日期較舊只能產生獨立 `content_age_status`，不得直接令 stale。若日後額外下載 XML取得 embedded date，XML必須成為同次 check的具名 artifact並驗跨格式一致性。
- CDC 不因文件年齡單獨判定過期；依最後成功 upstream check 及是否已知有新版判定。

`get_data_status` 必須能區分 `last_check_at`、`last_successful_check_at`、`last_successful_publish_at`、`official_content_date`、`serving_snapshot_id` 與 `latest_seen_version`。

## 9. Sample 與 official 隔離

`TAIWAN_LAB_DATA_MODE` 只接受 `sample` 或 `official_snapshot`，不接受空字串、alias 或自動模式。

- `sample`：只讀 package 內 `*.sample.json`；`sample_only=true`、synthetic warning 與既有測試保持不變。
- `official_snapshot`：只讀 `TAIWAN_LAB_DATA_DIR` current availability descriptors；`sample_only=false`。任何 official source unavailable 都針對該 source 回錯，不載入同領域 sample。
- process 啟動時建立單一 `DataContext(mode, data_root)` 並注入所有 adapters，禁止 adapter 自行重讀 mode 後得出不同結果。
- `ToolResult` 的 provenance 只可來自該次 query 使用的單一 snapshot。跨 source 工具日後若存在，必須讓每筆 item 分別帶 source provenance，仍不得跨 mode。
- bundled samples 不得複製到 official data root；official raw/curated 不得打包進 wheel。

## 10. Source adapter 設計

### 10.1 NHI CSV（`SDD-NHI-01`）

#### Discover/fetch

- 每次讀 data.gov.tw dataset 174450 metadata，驗 publisher OID、identifier、license、CSV format、UTF-8 與 resource URL。
- resource host 僅允許核准的 `data.gov.tw`、`info.nhi.gov.tw`/NHI 官方 host；resource id 或 host 改變時 staged 並 block review。
- CSV 以 `utf-8-sig`、`newline=""` 和 standard library `csv` 解析；不得 `splitlines()`。

#### Exact schema 與 table

固定 7 欄：`診療項目代碼`、`健保支付點數`、`生效起日`、`生效迄日`、`英文項目名稱`、`中文項目名稱`、`備註`。缺欄、重複欄、新增欄、改名、欄數錯誤、NUL、decode error 或 0 rows 都是 batch block。欄位只換序可按名稱 parse，但仍需人工核准新 schema version。

SQLite `nhi_fee` 至少保存 raw、typed/search 與 provenance 欄位：

```text
source_row_sha256 PRIMARY KEY, source_row_number,
code_raw, code_normalized,
points_raw, points,
effective_start_raw, effective_start,
effective_end_raw, effective_end, possible_open_end_sentinel,
name_zh_raw, name_zh_search, name_en_raw, name_en_search,
note_raw, note_search,
scope_status, scope_rule_version, scope_basis_locator
```

代碼永遠是字串；points只接受非負base-10 integer，0合法且單位固定為「點」，不換算金額。日期只接受有效Gregorian `YYYYMMDD`，不得猜測或轉換民國年；本次觀察的`29101231`保留為raw/ISO並可標inference，不輸出「永久有效」。

#### 查詢邊界

- `get_points(code, as_of=null)` 的precedence完全依PRD §5.3：先驗所有參數；wrong type、空字串、非strict/無效`YYYY-MM-DD`回`invalid_request`。合法non-null `as_of`在讀source availability與查code前固定回`historical_query_unsupported`、`historical_truth_supported=false`、0 items；只有null才exact lookup serving全表並回原始有效期間與`scope_status`。不得回current points、日期涵蓋布林或其他可被誤讀為as-of事實的欄位。
- `search_payment_items(query, limit=5, offset=0)` 是中性的正式全表候選搜尋，依序排序：exact code、exact official name／approved alias、prefix、substring，再以 code／`source_row_sha256` 穩定排序。每列都帶 `scope_status`、命中欄位與 truncation；每列 record 為 `NHISearchRecord`（`record_type=nhi_fee_summary`），只含 `code_raw`、`points`、起迄日、`possible_open_end_sentinel`、中英文名稱原文、`scope_status`、`note_preview`（前60字）、`note_chars`、`note_truncated`，`limit` 為1–5（owner 2026-09-15，由1–20改為1–5）；exact-code的`get_points`／`get_payment_rule`仍回完整`NHIRecord`。scope registry 未核准時仍可回候選，但 `coverage_status=review_incomplete`，不得稱完整 laboratory清單。
- 舊`search_lab_code`是`search_payment_items`的相容wrapper，回傳相同候選與scope warning；`get_payment_rule(query)` 的 wrong type／trim 後空字串回 `invalid_request`，合法非空但沒有 exact code 回 `not_found`，不套固定碼長 regex；命中時只回原始備註／定位，不作名稱搜尋或個案申報判定。
- 只有 `decision_status=approved` 的 alias參與production search。Alias registry每列保存 `alias_raw`、`code`、language、basis type/URL/locator、rule version/hash、reviewer/time/status；normalize collision時回所有命中候選，不做任意 winner。
- 空結果只表示 serving snapshot 未命中，不代表「健保不給付」。

`nhi_lab_scope` registry 欄位：`code`、`scope_status`（`in_scope|out_of_scope|review_pending`）、`basis_type`、`basis_url`、`basis_locator`、`rule_version`、`reviewer_id`、`reviewed_at`、`decision_status`。Keyword 只作 reviewer 找候選，不能改 scope status。

### 10.2 TFDA CSV ZIP（`SDD-TFDA-01`）

#### Transport 與 schema

- 直接使用官方 HTTPS CSV endpoint，按 ZIP magic 驗證，不信任 MIME 或 Content-Disposition。
- 限制 ZIP 64 MiB、唯一非目錄 entry、單檔/總解壓 256 MiB、壓縮比 30；拒絕 absolute/UNC/drive/`..` path、symlink 與副檔名不符。
- 內檔以 `utf-8-sig` CSV strict parse，完整比對研究列出的 34 欄。OAS hash 只作 drift signal，不覆蓋 payload truth。
- 所有欄位先保存 string；日期只接受 empty 或 `YYYY/MM/DD`。許可證種類 `09`、國別代碼、異動日期只以來源原值命名，不補未驗證 codebook 語意。

SQLite 保留 `tfda_source_row` 一列對一個原始 34 欄 record；另外建立只供查詢的 `tfda_permit_group` 與 `tfda_classification` view/table。不得因相同許可／登錄字號壓掉 manufacturing row。三組主/次類別轉成有 ordinal 的 array/table，raw 欄仍保留。

Immutable curated row只保存 `source_cancellation_status_raw`、`source_cancellation_date_raw/parsed`、`valid_through_raw/parsed`，不保存會隨今天失效的最終狀態。Query以injected clock或明示`evaluated_as_of`（預設Asia/Taipei當日）即時計算`cancellation_recorded_in_source`與`within_validity_period_as_of`；所有輸入組合、輸出值、inclusive date boundary與exact warning code完全引用PRD §6.3.1「TFDA cancellation × date canonical truth table」。實作不得增加、改名或合成任何public temporal state，尤其禁止`computed_temporal_state`與`not_cancelled_and_within_validity`。結果必含`evaluated_as_of`與時區，並測有效日期前一日、當日、次日及raw hash不變的跨日查詢。

Applicant 與 manufacturer 名稱、地址、統編、廠址、公司地址、國別、製程各自保存。搜尋 manufacturer 不得命中 applicant；相似品名、效能或規格不能推論臨床等效。

#### IVD registry

`tfda_ivd` 每列至少包含：

```text
classification_code, zh_name_raw, en_name_raw, risk_class_raw,
identification_text_locator, regulation_version, effective_from,
source_url, source_page, source_sha256,
ivd_scope(included|excluded|ambiguous), decision_basis,
reviewer_id, reviewed_at, rule_version, decision_status
```

Join 只使用「醫器次類別一～三」解析出的正式 code：

1. 任一 `included` 且沒有 `excluded/ambiguous` 衝突：`included`。
2. included 同時命中 excluded/ambiguous，或任一 code為ambiguous：`ambiguous`。
3. 所有 code都是reviewed excluded：`excluded`。
4. 缺次類別、舊制數字、未知code或規則版本不明：`unknown`。
5. 品名／效能／規格 keyword 只產生 review candidate，不能覆蓋逐碼決議。

Query capabilities分開：

- `search_reviewed_ivd(query, manufacturer=null, limit=5, offset=0)`只回逐碼`decision_status=approved`的`included`；nullable `manufacturer`只篩選製造商角色。`TFDA-R1-IVD`未完成時仍可回已核准列，但`coverage_status=review_incomplete`；沒有included而candidate tool有命中時回`candidate_matches_available`，不能用空結果暗示沒有IVD。Serving snapshot本身仍必須有`PUB-R1-OWNER`。
- `search_ivd_candidates(query, manufacturer=null, limit=5, offset=0)` 回 `included|ambiguous|unknown`候選；nullable `manufacturer`只篩選製造商角色；必帶 `coverage_status`、reviewed code分子/分母、舊制/缺碼/未知列數、命中依據及 truncation。Keyword只能召回候選。
- 舊 `search_ivd` 是 reviewed-only相容 alias；若沒有included命中但 candidate tool有命中，回 `result_status=candidate_matches_available`與候選tool指引，不回 `not_found`。
- `get_license` 可回全部一般許可source rows並逐列附scope。~~`list_matching_license_records`只並列原始許可欄位與來源，不比較、排序優劣或推論等效。~~
- `list_matching_license_records(query, limit=5, offset=0, prefer_ivd=false, prefer_main_category=null, ivd_scope=null, main_category=null)`（`D-015`／PRD TFDA-06）搜尋全部 `tfda_source_row`，不因註銷、缺碼或舊制排除。
  - 比對欄位：字號、中英文品名、申請商、製造商、效能、主／次類別原文。
  - 排序key：`(match_tier, preference_miss, cancellation_raw_nonempty, license_no, source_row_number)`。
    - `match_tier` 0＝normalized字號完全相同，1＝中文或英文品名完全相同，2＝品名prefix，3＝品名substring，4＝其他欄位substring。
    - `preference_miss` 為未符合 `prefer_ivd`（`ivd_scope=included`）與 `prefer_main_category` 的條件數。
  - `ivd_scope`／`main_category` 篩選先於排序套用。`main_category` 只比對三組主類別開頭的A–P字母，舊制四碼不命中任何字母。
  - 每列回 `ivd_scope`、主類別字母陣列、級數與許可證種類原文、`cancellation_recorded_in_source`、`matched_by`。
  - 不輸出分數、相似度、優劣或可替代性；只並列原始欄位與來源。
- 實作（2026-09-15）：
  - SQLite `tfda_source_row` 保存34欄原文、`source_row_sha256`、`source_row_number`，另存正規化搜尋欄（NFKC、casefold、空白壓縮，再把各種引號統一、「臺」改「台」；原文不變）、ISO日期、主類別字母、分類代碼、`ivd_scope`與rule version。`tfda_classification`每個有值的主／次類別一列；`tfda_permit_group`為view。
  - 比對用SQLite `instr()`子字串，兩個字的查詢也能命中（FTS5 trigram查不到少於3字）；排序、`total_matches`與分頁都在SQLite內完成，不把十萬列讀進記憶體。
  - `search_reviewed_ivd`／`search_ivd_candidates`的`query`比對字號、品名、效能與類別原文，製造商只由`manufacturer`參數篩選。
  - ~~四個搜尋operation每筆回`tfda_device_summary`摘要、`limit` 1–20~~ 五個搜尋operation（含`find_manufacturer(name, limit=5, offset=0)`）每筆回`tfda_device_summary`摘要、`limit` 1–5、預設5，可用`offset`翻頁（owner 2026-09-15）；`get_license`回完整`tfda_device`。
  - 附表A/B/C以外代碼、缺代碼與舊制列為`unknown`，所以正式build的`coverage_status`維持`review_incomplete`，結果附TFDA專用coverage說明。
  - 完整性檢查（descriptor、manifest、audit、資料庫與raw hash）第一次查詢時完整執行；之後在descriptor bytes與build／raw／check檔案大小、修改時間都沒變時沿用結果，stale仍每次依當下時間計算。
  - TFDA stale依官方每7日更新、兩個週期（14日）未成功檢查即`upstream_check_overdue`，沿用NHI規則，待OD-05另定。
- `compare_products` 在P1.1只回 `result_status=deprecated_unsupported`、0 items與中性tool指引；不得回可被host整理成比較表的資料。

在當期出現的399個A/B/C code未逐碼review、舊制coverage未說明或owner未核准前，`coverage_status=review_incomplete`，產品不得宣稱「完整台灣IVD清單」。`B.9225`、`B.9195`、`B.9245`必須是regression cases。

### 10.3 CDC 採檢手冊 PDF（`SDD-CDC-01`）

#### Discovery 與 artifact pairing

- 每次從官方 landing page 找手冊與修訂對照的 viewer token，再解析實際 binary URL；不得寫死 token/UUID。
- 同時保存 landing HTML hash、viewer HTML hash、兩份 PDF hash、標題、HTTP metadata、封面/頁首版本與核定日期。
- 手冊與修訂表版本不一致、非 PDF、截斷、頁面無文字層或版本資訊互相矛盾時整批 block。

#### PDF extraction gate

目前研究證明 LiteParse `--no-ocr` 可取得文字並供 screenshot 抽查，但尚未證明其 JSON 契約可穩定提供本 parser 所需的 bounding boxes、table lines與跨頁lineage。因此第一個CDC implementation slice MUST先用忽略於Git的`data/raw`現行130/29頁official artifacts做可重跑qualification，不得稱它們為checked-in fixture：

1. 確認 LiteParse JSON 是否含足夠座標與頁資訊，並記錄 LiteParse 版本及命令。
2. 用同疾病多檢體、跨頁續列與三欄修訂表重建 golden cases。
3. 若不足，再選最小必要 PDF layout dependency並新增 ADR；不得悄悄退化為純文字切割或預設 OCR。

可重跑入口固定為：

```powershell
taiwan-lab-data qualify cdc_specimen_manual `
  --raw-revision-id <id> `
  --extractor liteparse `
  --extractor-version 2.0.0 `
  --no-ocr `
  --data-dir <path> `
  --json
```

Qualifier spec 的唯一位置是 Python package resource `importlib.resources.files("taiwan_lab_mcp").joinpath("qualifier_specs", "liteparse-2.0.0.json")`；repo-relative path與`qualifiers/`別名禁止fallback。該spec以`extra=forbid` schema固定npm package `@llamaindex/liteparse`、exact version `2.0.0`、npm dist integrity、需核對的package-relative bundle files及各SHA-256、executable basename與approved argv。

LiteParse不是Python runtime dependency，而是只有 `qualify cdc_specimen_manual` 需要的optional Node prerequisite。Preflight先以`shutil.which("lit.cmd")`（Windows）或`shutil.which("lit")`（其他平台）解析唯一executable，再以`shutil.which("npm.cmd")`／`shutil.which("npm")`執行`npm root -g`與`npm prefix -g`定位global package root/bin；不得搜尋repo、PATH外猜測安裝或自動下載。Package固定解析為`<npm-root>/@llamaindex/liteparse/package.json`，executable必須位於global prefix bin且對應package.json的`bin.lit` target；版本同時以package.json及`lit(.cmd) --version`核對。Integrity固定從`<npm-root>/.package-lock.json`的`packages["node_modules/@llamaindex/liteparse"].integrity`讀取並與spec比對，再逐一hash spec列出的bundle bytes；lock entry或任何identity證據缺失回`QUALIFIER_DEPENDENCY_MISSING`，值不一致回`QUALIFIER_IDENTITY_MISMATCH`，皆exit 4且不建立reviewable build。這些錯誤只阻止CDC新candidate qualification；已核准CDC snapshot與NHI、TFDA、ODS runtime仍可各自服務。

Preflight通過後，CLI 對手冊與修訂表各執行 `lit(.cmd) parse <input> --format json --no-ocr -o <attempt-output>`，保存完整argv（不含本機絕對root）、tool/package/spec identity、raw output SHA-256與stderr hash。兩份raw extractor output必須正規化為project-owned `CdcLayoutV1`：document artifact/hash、extractor identity/options、page dimensions、physical page number、text-layer flag與逐block `bbox/text/order`；缺bbox/page或無法建立header lineage就qualification failed。Normalized layout JSON的canonical bytes、schema與hash納入curated build fingerprint。

Qualification先輸出`staged/<source>/<attempt>/qualification-candidate.json`，保存`automated_status=passed|failed`、`synthetic_ci_status=not_run|passed|failed`及逐案結果。Command在extract/schema/golden candidate成功產生時exit 0；extract/schema失敗exit 4。Source reviews核准後，publisher依第7.4節產生immutable`audit/golden-qualification.json`certificate；缺active subject的approved certificate則exit 5。CI只使用最小synthetic`CdcLayoutV1`fixture且最多令synthetic status passed，不能宣稱qualified official PDF。

P1.1 official publish禁止OCR。無可靠文字層的頁可另產candidate/staged研究輸出，但不得進approved build；若未來要發布OCR資料，必須新增PRD/TDD、綁定OCR engine/model/options/output hash並要求100% row/cell review。

#### Entity tables

不把 PDF 全部壓成一張表：

- `cdc_specimen_requirement`：第2章疾病、檢體、目的、時間、量與規定、送驗方式、官方欄名`應保存種類（應保存時間）`、注意事項。該保存欄是疾管署保存材料／期間，欄位與tool description依PRD safety registry固定標`not_pre_submission_storage=true`；真正運送溫度／時間只保留在`送驗方式`或注意事項原文，不另推導storage欄。
- `cdc_testing_location`：第 7 章疾病、採檢單位、採檢項目、檢驗方法、期限、收件單位、BSL、備註。
- `cdc_testing_period`：第 7.7 節獨立 schema。
- `cdc_receiving_unit`：第 7.9 節電話、傳真、地址獨立 schema。
- `cdc_revision_entry`：修正規定、現行規定、說明及頁面 locator，只作 diff 導航。

每列保存 `manual_version`、`approved_date_raw`、`pdf_page`、`printed_page`、`table_section`、`row_bbox`、各 cell raw text、header lineage、artifact SHA-256。`retention_raw` 不可改名成運送前保存；不同方法、檢體、目的或時間不能合併為疾病級通則。第 2 與第 7 章只在 query 層以可追溯 key 提供分開結果，不在 extraction 階段直接 join。

#### Review gates

每個新版本依序完成`CDC-R1-SOURCE`、`CDC-R1-LAYOUT`、`CDC-R1-CONTENT`、`PUB-R1-OWNER`。第一個official build沒有可信前版，所有rows視為changed並逐列核對。後續版本核對全部parser diff rows、修訂表列出的變更與未列但實際有差異的`unlisted_change`；未變更列按entity與疾病章節分層，以`SHA-256(subject_digest + source_row_sha256)`排序後，每層至少1列，總樣本為`max(30, ceil(未變更列數*5%))`或全部未變更列中的較小值，seed/drawn row hashes寫入review record。

`CDC-R1-CONTENT` reviewer role為`medical_laboratory_professional`，review record要記錄owner核對的qualification basis與scope，但不公開credential秘密。Checklist逐列確認疾病、採檢項目、目的、採檢時間、量與規定、送驗方式、`應保存種類（應保存時間）`、注意事項仍屬同一row；reviewer 必須依欄名、章節上下文與疾管署原文獨立判讀保存欄語意，不能由產品布林值提示結論。若不支持目前 `not_pre_submission_storage` 解讀，gate 不得核准並須版本化修訂 contract。跨欄／跨列污染、錯誤採檢項目／目的／送驗條件為critical；locator或原文缺失為major；只影響search normalization為minor。任何critical或unresolved major均rejected；已修正 major 產生新curated build／subject digest後重審。Reviewer有衝突時需第二位同角色review與`PUB-R1-OWNER`裁決，兩份evidence都保留。任何gate未完成都只能latest candidate pending，不能切current。

### 10.4 CDC 認可機構 ODS（`SDD-ODS-01`）

- 每次由 landing page發現附件；以 ZIP magic、根 `mimetype` 與 OpenDocument structure 驗 ODS，不信任頁面日期。
- 用 standard library `zipfile` + `xml.etree.ElementTree.iterparse` 讀取指定資料 sheet；不依賴 LibreOffice。
- 只展開已知 12 欄，限制 `number-columns-repeated`，第 13 欄以後宣告空白不建立 cell。
- 僅依 `number-rows-spanned` anchor 與 `covered-table-cell` 繼承合法垂直合併值；真正空白 cell 保留空白。
- 12 欄為證號、縣市別、機構名稱、部門別、疾病代碼、疾病名稱、檢驗目的、檢驗方法、住址、連絡電話、結束時間、最近一次年度能力試驗審查。代碼與證號皆為字串。

ODS resource budget是hard fail：archive compressed bytes `<=16 MiB`、非目錄entries `<=64`、單一entry actual streamed uncompressed `<=32 MiB`、總actual streamed uncompressed `<=64 MiB`、ratio `<=100`、`content.xml <=32 MiB`、有效rows `<=100,000`、XML elements `<=2,000,000`、nesting depth `<=64`、單cell UTF-8 text `<=65,536 bytes`、aggregate cell text `<=32 MiB`、`number-rows-repeated <=10,000`、`number-columns-repeated <=16,384`且只materialize前12欄。所有bytes/count依實際streaming值，不信ZipInfo宣告；`iterparse`處理完row/element即`clear()`。拒絕`DOCTYPE`/`ENTITY`、declared-size欺騙、過深XML與超限repeat。

SQLite 每個方法子列各存一筆。證號只作 group key，不把約 3,584 列壓成約 344 列。`latest_annual_pt_review_raw` 可為日期、`無需能力試驗` 或空白，採 tagged value，不強制全轉 date。

發布前依序需要`ODS-R1-SOURCE`、`ODS-R1-STRUCTURE`、`ODS-R1-CONTENT`與`PUB-R1-OWNER`。第一版全部rows核對；後續全部changed rows必查，未變更列依疾病與機構分層、固定subject digest seed抽樣且至少20列。Content reviewer role為`recognition_program_reviewer`，qualification basis要說明熟悉認可制度的依據。Critical包括merge錯填、跨疾病/方法錯接或把名冊命中說成收件保證；major為source value/locator錯誤。任何critical或unresolved major整批reject，修正後新subject digest必須重審。

## 11. MCP runtime contract

### 11.1 Public contract 引用與 internal mapping（`SDD-API-01`）

Public MCP contract 不在 SDD 重複定義。唯一人類可讀真源是PRD §5.3完整22-operation registry、§6.3.1 TFDA truth table、§7.1 enum、§7.2 allowed-combination/provenance、§7.3 status/freshness與§7.4 exact safety-field registry；目前唯一machine-readable真源是已建立的 package resource `src/taiwan_lab_mcp/contracts/public-contract-v1.json`。實作必須以 `importlib.resources` 讀取該resource，MCP `list_tools`與response model都由其驗證；不得由本節、adapter常數或repo-relative JSON另生第二份public contract。acceptance reporter 已建立，部分 canonical verification node 已執行，其餘 node 與正式 release evidence 仍待拆分／驗證。

Internal pipeline可使用較細狀態，但對PRD欄位的deterministic mapping固定為：

| Internal | Public mapping |
| --- | --- |
| serving不存在或sample | serving validation/review均`not_applicable` |
| serving manifest自動驗證passed且source review approved | `passed`/`approved`；其他組合不得serve |
| 無非serving candidate | `latest_candidate_status=none` |
| discovered/fetched/raw_verified/parsed/validated | `validating` |
| internal review pending | `review_pending` |
| approved但尚未切current | `publishable` + stale reason `newer_candidate_awaiting_publish` |
| validation failed、review rejected或build failed且成為latest candidate | `rejected` |
| store ready/sample | `availability=available` |
| current descriptor／operational check／manifest／DB／audit失效或無serving | `availability=data_unavailable`；query `result_status=data_unavailable` |

Internal source id也只做下列一對一投影：`nhi_fee -> nhi_fee`、`tfda_devices -> tfda_device`、`cdc_specimen_manual -> cdc_manual`、`cdc_authorized_labs -> cdc_recognized_labs`。`all_sources`與reserved status sources只存在public operation registry，不建立假的official snapshot。

任何internal state只有上述一個public mapping；未映射或一對多時拒絕序列化。其餘 enum、合法組合、operation parameter precedence、TFDA warnings與 safety flags全部由PRD/resource決定。服務舊approved snapshot時candidate只影響PRD允許的candidate/stale欄；每個result須有固定、可測note，不把traceback、本機path或staged內容回給client。

### 11.2 get_data_status

輸出完全依PRD §5.3與§7.3逐一回四個source，top-level/source object只能有registry列出的keys；internal store從同一次讀取的`CurrentAvailabilityV1`與其已驗證manifest投影，不另加parser-specific status欄。唯一publish timestamp為`last_successful_publish_at`；`last_publish_at`是禁止序列化的legacy key。某一source unavailable不使其他source被報成sample或unavailable。

### 11.3 Operation／safety adapter boundary

Server只註冊PRD §5.3封閉registry中的exact operation names與signatures；compatibility alias與deprecated operation仍由同一registry建模，不由adapter自行猜參數。Domain adapter只回typed internal records；response assembler依`public-contract-v1.json`加上PRD exact safety flags。SDD不維護第二份safety key清單；key名稱、層級、適用operation、型別與必填條件只從PRD safety registry/resource載入。

Contract verifier比較resource與MCP discovery的operation集合、classification、parameter name/type/default及description safety requirements，並對PRD misuse cases執行stdio測試。任何extra/missing operation、signature drift、legacy safety alias或只在top-level note而item缺旗標都使`SDD-API-01`失敗。

## 12. CLI 設計

目前已建立 console script `taiwan-lab-data = taiwan_lab_mcp.data_cli:main`，以 standard library `argparse` 實作以下 executable slice：

```powershell
taiwan-lab-data sync nhi_fee --input <csv> --data-dir <path>
taiwan-lab-data sync nhi_fee --publisher-oid <oid> --data-dir <path>
taiwan-lab-data validate nhi_fee --input <csv> --json
taiwan-lab-data rollback <source-id> <target-curated-build-id> --expected-generation <n> --reason <text> --actor <id> --data-dir <path>
taiwan-lab-data recover-current <source-id> --publish-event <id> --actor <id> --data-dir <path>
taiwan-lab-data status --data-dir <path> --json
```

`sync`執行discover到validate；P1.1不提供隱式auto-publish。`review`驗`ReviewRecordV1`、subject/evidence hashes，不能從互動文字捏造reviewer。`publish`重跑全部preconditions、取得lock、CAS並readback；`rollback`與`recover-current`不能由一般publish參數觸發。

`qualify`、`review`、`publish` 與 TFDA／CDC／ODS subcommands 仍是 planned，尚未宣稱可執行。

Exit code：0 成功；2 使用/config；3 discovery/fetch；4 parse/validation；5 review gate；6 publish/integrity。Stdout 在 `--json` 時只輸出單一 JSON document，human log 寫 stderr，避免破壞自動化。

## 13. 驗證、錯誤與可觀測性

### 13.1 Validation report

每次 sync 的 `validation.json` 至少含：stage、開始/完成時間、source、raw revision/build attempt/curated build IDs、subject digest、artifact hashes、parser/schema/normalization/rule versions與bundle hashes、row counts、header hashes、null rates、status/code distributions、與current的drift、blocking errors、warnings、quarantine count與golden qualification reference。每個error使用穩定code，例如：

- `FETCH_HTTPS_DOWNGRADE`、`FETCH_HOST_NOT_ALLOWED`、`FETCH_SIZE_LIMIT`。
- `ARCHIVE_PATH_TRAVERSAL`、`ARCHIVE_RATIO_LIMIT`、`CONTENT_MAGIC_MISMATCH`。
- `SCHEMA_MISSING_COLUMN`、`SCHEMA_UNKNOWN_COLUMN`、`ROW_WIDTH_MISMATCH`。
- `DATE_INVALID`、`DUPLICATE_LOGICAL_KEY`、`UNKNOWN_CLASSIFICATION`。
- `REVIEW_REQUIRED`、`CURRENT_POINTER_INTEGRITY`、`OPERATIONAL_STATUS_INTEGRITY`。

錯誤訊息可含 source row number與相對 locator，不含使用者查詢、絕對 home path、環境變數或 secrets。

### 13.2 Drift gates

- Header 刪除、改名、重複、新增：block pending schema review。
- 0 rows、全面日期格式變更、decode failure：block。
- NHI 或 TFDA row/distinct key count 相對 current 超過 ±10%：啟動期 block review；30 天後依觀測基線另立 ADR 調整。
- TFDA 關鍵欄 null rate 增加超過 2 個百分點、未知 status/code 出現：block review。
- CDC table headers、頁面文字層、ODS 12 欄或 merge relation 無法重建：block。
- P1.1沒有可發布的quarantine threshold；任何source row被排除或目標CDC row無法重建都block整批。Quarantine只保存診斷證據，不能讓coverage看似complete。

### 13.3 Logging

使用 standard library `logging`，event 欄位為 timestamp、level、run_id、source_id、snapshot_id、stage、event_code、duration_ms、counts。預設不記 MCP query 或 result content；若未來加 opt-in audit log，先做 privacy review與 retention設定。

### 13.4 Release evidence

每次release保存machine-readable inventory：package version、commit、四資料集serving builds與subject digests、pytest/ruff/out-of-tree wheel結果、source qualification reports、`REL-G1`～`REL-G5`狀態、archive file inventory及pilot protocol/result hashes。Wheel與sdist逐項allowlist package code/sample/rule/schema/protocol resources，並deny `raw/`、`staged/`、`quarantine/`、local review/temp report、absolute user paths與secret-like filenames；只build成功不算archive安全證據。

`PilotResultV1`以`extra="forbid"`驗PRD固定scenario IDs、protocol hash、匿名participant ID、assisted flag、逐rubric 0/1、duration、critical issue code與consent；不保存自由文字query或病人/機密資料。Release計算人數與比例，不把4/5與8/10視為同等證據。Pilot證據只能滿足`REL-G5`，不能核准source data。

## 14. Security 與資料治理（`SDD-SEC-01`）

### 14.1 Threat model

P1.1防護範圍包括：上游/metadata回傳錯誤或惡意bytes、redirect/host漂移、archive/XML資源耗盡與路徑逃逸、意外檔案毀損、兩個合法publisher競爭、未核准candidate被serve，以及不受信任MCP query造成SQL injection或敏感log。Hash提供一致性與可追溯性，並不在pointer/manifest/DB都位於同一可寫data root時提供對惡意本機writer的authenticity。

部署SHOULD以不同OS principals執行publisher與runtime：publisher對data root可寫，runtime只有read/execute；用NTFS ACL或POSIX ownership/permissions阻止runtime與一般服務帳號寫入。若兩者共用同一使用者，本設計只防意外毀損與並行錯誤，不宣稱防該使用者竄改。能寫data root的惡意administrator、kernel compromise與供應鏈簽章驗證不在P1.1 threat model。若產品要防同機writer，下一版必須使用runtime不可取得私鑰的signed manifest/review records或受保護key store並另立ADR。

Operational status永遠不授權publish；current availability descriptor、其operational欄或引用的check record缺失、竄改、schema/hash/source不符時，該source一律`availability=data_unavailable`、`result_status=data_unavailable`，不得降格成stale。Runtime在hash驗證後只開immutable path的`mode=ro` SQLite；與publisher ACL及「final build永不修改」共同消除正常流程的check/open競爭。

### 14.2 Controls

- Downloader 只允許 HTTPS 和 per-source exact host allowlist；redirect 每一步重驗 scheme/host，拒絕 HTTPS 降級 HTTP。
- Metadata 提供的 URL仍是不受信任輸入；限制 redirect 次數、connect/read timeout、Content-Length與串流實際 bytes。
- 所有下載寫入 data root 的 generated temp name，不使用 Content-Disposition 路徑。
- ZIP entry執行path containment、symlink、entry count、單檔/總量與compression ratio檢查；大小以actual streamed bytes再次計數，不信任central directory宣告。TFDA與ODS分別使用第10.2/10.4節硬上限。
- XML使用standard library parser；解析前拒絕`DOCTYPE`/`ENTITY`，逐元素計數depth/elements/text/repeats並`clear()`，超限立即停止且current不變。
- Raw artifacts immutable；hash 不符、manifest path逃逸或 SQLite integrity失敗時 runtime停止該 source。
- 規則與 review record 綁定 artifact/rule hash；只改 reviewer文字不能核准不同資料。
- 本專案不需要 credential。若未來官方來源需 authentication，另立 threat model，不把 token放 CLI argument、manifest、log 或 Git。
- 公開query不應含PHI；runtime預設無query retention。文件與錯誤訊息提醒不要輸入病人識別資訊；本專案不能控制MCP host/LLM是否另行記錄，院內正式導入需走P2治理。
- 每筆輸出保留 attribution，並聲明 MCP不是 CDC/NHI/TFDA 官方服務或背書。

## 15. 具體模組與檔案規劃

以最小 diff 演進，不新增抽象層直到第二個來源確實重用：

| 檔案 | 變更責任 |
| --- | --- |
| `src/taiwan_lab_mcp/config.py` | 一次解析 mode、data root、source allowlist與限制 |
| `src/taiwan_lab_mcp/models.py` | Manifest、CurrentAvailability、review、ToolResult v2與 strict validators |
| `src/taiwan_lab_mcp/snapshot.py` | raw/build fingerprint、path containment、SQLite finalization/integrity |
| `src/taiwan_lab_mcp/publish.py` | per-source OS lock、generation/parent CAS、rollback/recovery與publish events |
| `src/taiwan_lab_mcp/fetch.py` | HTTPS/redirect/size受限下載與 metadata capture |
| `src/taiwan_lab_mcp/normalize.py` | 版本化 display-preserving search normalization |
| `src/taiwan_lab_mcp/stores.py` | sample store 與 official read-only SQLite store；不含領域規則 |
| `src/taiwan_lab_mcp/data_cli.py` | argparse orchestration、exit codes、JSON/human output |
| `src/taiwan_lab_mcp/importers/nhi.py` | metadata discovery、7 欄 CSV、typed fields、scope join |
| `src/taiwan_lab_mcp/importers/tfda.py` | ZIP verify、34 欄 CSV、classifications與IVD join |
| `src/taiwan_lab_mcp/importers/cdc_pdf.py` | artifact pairing、layout JSON ingestion、section entities與review diff |
| `src/taiwan_lab_mcp/importers/cdc_ods.py` | ODS ZIP/XML、merge span與12欄 schema |
| `src/taiwan_lab_mcp/qualifiers/cdc.py` | pinned LiteParse qualification、`CdcLayoutV1`與official report |
| `src/taiwan_lab_mcp/qualifier_specs/liteparse-2.0.0.json` | npm package/version/integrity、bundle hash與approved arguments |
| `src/taiwan_lab_mcp/contracts/public-contract-v1.json` | PRD §5.3、§6.3.1、§7 operation/status/truth/safety machine-readable真源 |
| `src/taiwan_lab_mcp/adapters/*.py` | 從注入 store 查詢；保留 source-specific notes/guards |
| `src/taiwan_lab_mcp/server.py` | 建立單一 DataContext、status與ToolResult contract |
| `src/taiwan_lab_mcp/{rules,schemas,review_protocols,qualifier_specs,contracts}/**` | wheel內approved rule/schema/protocol/qualifier/public-contract resources；importlib.resources載入 |
| `tests/fixtures/**` | 小型 synthetic upstream fixtures、惡意archive與layout cases；不得放官方資料冒充 fixture |
| `tests/test_models.py` | public enum/allowed-combination、manifest/review/golden strict schema |
| `tests/test_snapshot_publish.py` | atomic/CAS race、crash/recovery、rollback、tamper、SQLite read-only |
| `tests/test_freshness.py` | serving/candidate mapping、stale reason、TFDA content-age分離 |
| `tests/test_nhi_importer.py` | 7欄、quoted newline、0點、日期、candidate/alias、as_of unsupported |
| `tests/test_tfda_importer.py` | ZIP限制、34欄、multi-row permit、dynamic temporal/role、IVD registry |
| `tests/test_cdc_pdf_importer.py` |雙頁碼、跨頁、多方法、qualification/review gate |
| `tests/test_cdc_ods_importer.py` | resource budgets、merge spans、真空白、12欄、同證號多方法 |
| `tests/test_official_adapters.py` | item envelope、tool matrix與misuse boundaries |
| `tests/test_mcp_stdio.py` | sample/official installed-wheel stdio與tool discovery contract |
| `tests/test_security_boundaries.py` | host/redirect/archive/XML/SQL/path trust boundary |
| `tests/test_package_contents.py` | wheel/sdist allowlist與raw/staged/quarantine/secret denylist |

若共用 helper 只被單一 importer使用，先留在該 importer，不為命名整齊拆檔。CDC PDF dependency選擇、curated redistribution與stale hard-stop另以 ADR記錄；其餘可逆實作細節不額外產生文件。

## 16. Migration 與 rollout

### Phase 0：保住 sample boundary

- 先擴充models/config，但`sample`仍為預設；保留既有sample provenance/mode/stdio邊界。因`compare_products`安全退場與public status enum統一，對應舊expectation要明確改成新contract test，不能同時要求舊資料回傳；其餘baseline持續通過。
- official mode沒有 data root或availability descriptor時必須明確失敗，證明無 fallback。

### Phase 1：共用 snapshot + NHI exact lookup

- 實作raw revision/curated build、audit-bound manifest、lock/CAS availability descriptor、SQLite/CLI與NHI importer。
- `get_points`提供official exact lookup；`search_payment_items`與相容wrapper提供全表候選及scope狀態，approved alias才命中。
- 模擬下載、schema、並行publish與crash/recovery，證明current不倒退且不變成半成品。

### Phase 2：TFDA

- 加安全 ZIP、34欄與multi-row permit。
- `get_license`先提供一般許可證欄位與IVD unknown；另分reviewed-only與candidate operations，legacy `compare_products`不回資料。

### Phase 3：CDC ODS，接著 PDF

- ODS先用stdlib完成merge semantics。
- PDF先完成layout spike、golden cases及ADR（若需要dependency），再進完整人工/醫檢review流程。

### Phase 4：整合驗收

- 四來源official stdio、tamper、stale、unavailable、license attribution與out-of-tree wheel測試。
- 5–10位醫檢師試用屬產品驗收，不取代資料review gates。

Migration不刪除sample fixtures，也不自動搬移使用者資料。Manifest/schema/rule不相容或transform修正時建立新curated build；runtime不就地修改舊database。

## 17. Decision log

| Decision | 狀態 | 決議與理由 |
| --- | --- | --- |
| `D-001` runtime不連網 | Accepted | 將上游不穩定與query path隔離，適合本機離線查詢；不構成院內部署readiness |
| `D-002` curated使用per-source SQLite | Accepted for P1.1 | stdlib、可索引、唯讀、無服務依賴；比每request全量JSON簡單可靠 |
| `D-003` current用per-source lock/CAS atomic availability descriptor | Accepted | serving pointer與operational狀態同檔單次replace；generation/parent阻止並行晚到舊候選倒退；rollback/recovery另有稽核命令 |
| `D-004` sample/official以process mode隔離 | Accepted | 保留示範體驗並消除混查與silent fallback |
| `D-005` source importer分開 | Accepted | 四種格式與醫療語意不同，共用領域模型會隱藏錯誤 |
| `D-006` CDC PDF layout engine | Proposed / qualification gate | LiteParse文字抽取已證明；以ignored official raw與pinned identity驗bbox/table lineage，CI fixture只驗synthetic contract |
| `D-007` curated artifact是否再散布 | Accepted for NHI（owner 2026-09-14） | NHI以GitHub Release下載包散布並附原始CSV，見`docs/adr/0001-nhi-snapshot-release-bundle.md`；TFDA／CDC仍需另案確認第三方內容、大小與更新責任 |
| `D-008` NHI stale 7日是否hard-stop | Accepted（owner 2026-09-14）：不hard-stop | 超過兩個宣告週期未成功check時runtime加`upstream_check_overdue`，持續回舊版並揭露 |
| `D-009` NHI lab scope owner/reviewer | Accepted（owner 2026-09-14）：AI reviewer | allowlist依據須為健保署支付標準官方文件原文與locator；review record必須標明AI reviewer；~~不確定者留`review_pending`~~ 不確定者一律`in_scope`並在basis寫明依owner決定（owner 2026-09-14「寧可錯殺一百，也不要放過一個」）。結果notes不另加AI審核備註（owner 2026-09-14） |
| `D-010` TFDA IVD owner/reviewer | Accepted（owner 2026-09-14）：AI reviewer | 依官方分類分級附表原文逐碼判斷；揭露同D-009；~~不確定者留`ambiguous`／`unknown`~~ 附表判不出來或查無的A/B/C代碼一律`included`並寫明依owner決定（owner 2026-09-14）；缺A–P代碼或舊制編號的許可證列仍為`unknown` |
| `D-011` CDC專業reviewer與turnaround | OWNER GATE | 每版發布需要內容複核，工程測試不能取代 |
| `D-012` 支援平台承諾 | Accepted（owner 2026-09-14）：Windows與macOS | macOS以CI macos-latest驗證；Linux仍在CI執行但不列為公開承諾平台 |
| `D-013` local integrity threat model | Accepted | hash不宣稱抵抗可寫data root的惡意writer；runtime read-only principal，若需authenticity另做signed manifest ADR |
| `D-014` NHI `29101231` sentinel對外語意 | OWNER GATE | 目前只保留raw/parsed date與`possible_open_end_sentinel=true` inference，禁止顯示「永久有效」；需由OD-02 owner核准官方語意後另建rule/build |
| `D-015` TFDA全收錄、標籤與查詢排序 | Accepted（owner 2026-09-15） | 全部104,619列可查；標籤只取官方欄位與approved registry；預設依命中程度排序、不偏類別；語意由host AI判斷後以`prefer_*`（只調順序）或篩選參數表達，不在server端猜意圖或加隱藏權重；缺分類代碼列維持`unknown`；不輸出分數、等效或採購排序 |
| `D-016` TFDA上線審核與每日檢查 | Accepted（owner 2026-09-15：「1.a 2.a 3.z你直接幫我審核」） | 三關與正式驗收題由AI代審，protocol `tfda-r1-ai-review` v1；正式build只接受protocol指定的reviewer id與role；範圍只限本機MCP服務；附表A/B/C以外代碼維持`unknown`；每日`check tfda_devices`同檔記成功檢查、新檔標`newer_candidate_pending_review`並寫差異摘要、失敗標`upstream_verification_failed`；~~新版仍需再審才發布~~（見`D-017`） |
| `D-017` TFDA每週自動更新 | Accepted（owner 2026-09-15：「A變成成自動化 我不想花太多心力維護」） | 每日`check tfda_devices --auto-publish`（`tfda_autoupdate.run_tfda_auto_update`）：同檔記成功檢查；新檔先比上線版：列數與字號數變動≤10%、主要欄位空白率上升≤2個百分點、沒有新的註銷狀態值；再以獨立解析挑≥10題驗收題；建置後、切換前以獨立解析逐列比對資料庫；全過才以protocol `tfda-r1-auto-review`發布，否則保留現行版、標`newer_candidate_pending_review`；CLI結果`published`／`blocked`（exit 5）／`auto_publish_failed`（exit 6），同一候選版`already_reported=true`時排程不重寄信；只接受正式安裝版；SDD §15「±10%啟動期block review」對TFDA改為超過才擋、未超過自動發布；有沒有新版以整個ZIP的SHA-256判斷，筆數不變的內容修改也算新版；差異報告逐字號比對兩版資料列（字號內列順序不算改動），列出`changed_permits`（改動欄位與前後值）與`validity_extended_permits`（有效日期往後延，通常是展延）；`retention-plan tfda_devices --keep 3`只列出可清的舊建置與原始檔（保留服務中與最近3個服務過的版本及其原始檔、等待中的新版原始檔；讀不到發布紀錄就不列），每日排程把清單內、路徑格式相符且不是服務中的資料夾移到資源回收筒 |
| `D-018` 健保新版自動更新 | Accepted（owner 2026-09-15：「好，那健保新版也改成自動更新」） | 每日`check nhi_fee --auto-publish`（`nhi_autoupdate.run_nhi_auto_update`）：沿用`run_nhi_upstream_check`；新檔先比上線版：列數與代碼數變動≤10%、英文名稱空白率上升≤2個百分點；以獨立解析挑≥10題驗收題（代碼、點數、起迄日、中英文名稱、備註、scope）；建置後、切換前以獨立解析逐列比對資料庫；全過才以protocol `nhi-r1-auto-review`發布；`build_official_nhi_snapshot`只在auto protocol時要求reviewer等於protocol指定身分，owner protocol流程不變；沒有核准scope規則的新代碼維持`review_pending`並列入`new_codes_without_scope`；SDD §15 ±10% block對NHI同樣改為超過才擋；GitHub Release下載包不隨本機自動更新 |

PRD owner decision 一對一追蹤如下；每個OD恰好出現一列，未列出的工程decision不得冒充owner決議：

| PRD owner decision | SDD decision | 現況與阻擋點 |
| --- | --- | --- |
| `OD-01` | `D-007` | NHI已決定以GitHub Release散布（2026-09-14）；TFDA／CDC未決 |
| `OD-02` | `D-009`、`D-014` | scope reviewer決定為AI（2026-09-14）；~~官方文件依據研究中~~ AI審核已完成為`nhi-lab-scope-v2`（2026-09-14，見`docs/reviews/nhi-lab-scope-ai-review-2026-09-14.md`），~~6,173碼中2碼仍`review_pending`~~ 依owner決定判不出來的2碼改算檢驗，已重建serving並發布`nhi-data-20260914-lab-scope`；sentinel維持原值＋可能未設定結束日推論 |
| `OD-03` | `D-010` | IVD registry reviewer決定為AI（2026-09-14）；附表逐碼AI判定已完成（2026-09-14，見`docs/reviews/tfda-ivd-ai-review-2026-09-14.md`），~~尚未接入MCP~~ 已做成`rules/tfda_ivd/v1.json`接入（2026-09-15） |
| `OD-04` | `D-011` | 待指定CDC內容與ODS認可制度reviewer及turnaround |
| `OD-05` | `D-008`、`D-012` | NHI不hard-stop、支援Windows與macOS（2026-09-14）；TFDA／CDC stale門檻仍依各來源另定 |
| `OD-06` | `D-015` | TFDA全收錄＋標籤＋host AI指定偏好／篩選（2026-09-15）；~~TFDA curated build、adapter與contract參數尚未實作~~ 已實作（2026-09-15） |
| `OD-07` | `D-016` | TFDA上線審核由AI代審、D–P代碼維持unknown、摘要不再減（2026-09-15） |
| `OD-08` | `D-017` | TFDA每週新版自動檢查、自動發布（2026-09-15） |
| `OD-09` | `D-018` | 健保新版自動檢查、自動發布（2026-09-15） |

`REL-G5` pilot 已由 owner 於 2026-09-14 取消，改為公開上線並以 GitHub Issues 收集使用者回饋（PRD §8.2、§8.4）；本文件中以 pilot 為前提的 `PilotResultV1` 等設計保留為歷史，不再是發布條件。

## 18. Definition of Done

P1.1 的任一來源只有同時符合以下條件才算 official-ready：

1. 可由CLI重跑discover至immutable raw revision與curated build；artifact/manifest/DB/audit hash可核對。
2. Source-specific schema、domain、drift、resource/security與至少10個countable official golden cases通過；所有source rows完整保留，失敗不改current。
3. 所有required source review gates以同subject digest綁定artifact/DB/transform/rule/qualification evidence，current CAS/readback成功。
4. MCP符合canonical operation/status matrix，每個row/child有typed evidence、license、freshness、coverage與結構化安全旗標。
5. sample與official的repo外installed-wheel stdio、archive inventory、tamper/CAS/crash/unavailable測試通過，證明不fallback、不混查、不倒退。

完成程式測試不代表資料或臨床內容已由主管機關核准。TFDA IVD registry、NHI laboratory scope與CDC內容仍以各自owner/reviewer gate為正式上線條件。

整體P1.1的完成單位固定為三個領域、四個資料集／查詢任務：NHI、TFDA、CDC手冊、CDC認可機構ODS。單一資料集可先獨立serve，但四者未全數通過`REL-G1`～`REL-G4`且整體未通過`REL-G5`前，不得宣稱P1.1完成。
