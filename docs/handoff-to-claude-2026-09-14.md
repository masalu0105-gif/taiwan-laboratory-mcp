# Taiwan Laboratory MCP P1.1 Claude Handoff

交接日期：2026-09-14（Asia/Taipei）
交接對象：Claude Code
交接類型：第一輪共用信任邊界＋NHI vertical slice 暫停點

## Role

Claude Code 是後續 continuation implementer。請先讀本檔，再依序讀：

1. `docs/product-requirements.md`
2. `docs/software-design.md`
3. `docs/test-driven-development.md`
4. `docs/implementation-plan.md`
5. `docs/research/nhi-data-source.md`
6. `docs/reviews/claude-opus-acceptance-round2.md`
7. `AGENTS.md`（若存在）

## Repo state

- Repo：`C:\Users\User\Documents\ChatGPT\Clinical Lab Plateform`
- Remote：`https://github.com/masalu0105-gif/taiwan-laboratory-mcp.git`
- Branch：`main`
- Handoff 前 HEAD：`a144b264b71ca694bfc888ae425bc387102548d1`
- Handoff 前 `origin/main`：同上
- 本次 worktree 的 dirty changes 是 P1.1 實作範圍；請保留，不要 reset、checkout、stash、clean 或覆蓋。

## Goal and current boundary

目標是把 v0.1.1 sample-only baseline 推進到第一輪 executable vertical slice：

- packaged `public-contract-v1.json` 作為 operation、request／response schema、enum、safety、payload 與 locator 的單一 machine source of truth。
- sample／`official_snapshot` 隔離、strict status、provenance、immutable snapshot identity、唯讀 SQLite 與 fail-closed runtime。
- NHI 7 欄 CSV importer、current exact lookup、搜尋／分頁、duplicate-code block、`as_of` historical-query rejection、`coverage_status=review_incomplete`。
- NHI metadata→CSV discovery／fetch 只建立 staged candidate／validation report，不自動 publish。

目前 `NHI-R1-SCOPE`、`PUB-R1-OWNER`、正式 source qualification 與 official golden evidence 仍未完成。`build_nhi_snapshot()` 是 caller-supplied offline synthetic integration builder；它的 serving-shaped output 不等於官方資料核准，也不能用來宣稱正式 qualification。

## Implemented highlights

- `src/taiwan_lab_mcp/contracts/public-contract-v1.json` 已 packaged，MCP `list_tools`、Pydantic models 與 response schema 有 equality tests。
- `src/taiwan_lab_mcp/models.py` 已收緊 item evidence→provenance artifact binding、sample／official identity pairing、status／stale／historical 組合。
- `src/taiwan_lab_mcp/importers/nhi.py` 已支援 UTF-8/BOM、quoted CRLF、strict Gregorian `YYYYMMDD`、ASCII non-negative decimal points、`0`、`29101231` raw＋sentinel flag、duplicate normalized code block。
- `src/taiwan_lab_mcp/adapters/nhi.py` 與 `src/taiwan_lab_mcp/stores.py` 已提供 current exact lookup、全表搜尋／分頁、alias collision 全部回傳、read-only SQLite 與 official unavailable 不 fallback sample。
- `src/taiwan_lab_mcp/fetch.py`、`src/taiwan_lab_mcp/nhi_source.py`、`src/taiwan_lab_mcp/sync.py` 已提供 allowlisted HTTPS、逐跳 redirect validation、bounded streaming、metadata discovery 與 candidate report。
- 最新修正：NHI `raw_revision_id` 依 `RawRevisionFingerprintV1` 綁定 canonical discovery identity 及 primary artifact role／media type／bytes／SHA-256；fetch time、response URL、metadata body hash、redirect trace 等 volatile evidence 不參與 identity。partial discovery failure 只保留 metadata evidence，`discovery_metadata_sha256=null`。
- `src/taiwan_lab_mcp/audit.py`、`publish.py`、`acceptance.py` 已建立 immutable evidence、subject digest、CAS／lock／rollback／recovery 與 acceptance report writer；目前沒有正式 `reports/acceptance` passed evidence。

## Verification already performed

Latest local verification：

- `.venv\Scripts\python.exe -m pytest -q -ra`：`155 passed`
- `.venv\Scripts\python.exe -m ruff check src tests`：passed
- `.venv\Scripts\python.exe -m ruff format --check src tests`：passed
- `git diff --check`：passed；只見 Git LF/CRLF warning
- `uv build --wheel --sdist`：wheel／sdist passed
- archive inventory：wheel 43 files、sdist 86 files；contract present，無 raw／staged／quarantine
- repo 外 venv 強制安裝 wheel 後 MCP stdio：`6 passed`
- installed contract：101746 bytes、22 discovery tools、response schema equality passed
- repo 外 CLI smoke：`validate` passed；offline `sync` 只產生 `review_pending` candidate，沒有 current pointer，也沒有 repo-relative fallback

## Known risks and unknowns

- 沒有下載或提交官方 NHI 整批資料；upstream tests 使用 synthetic metadata／responses。
- `NHI-R1-SOURCE`、`NHI-R1-SCHEMA` 正式 evidence、10 個 `official_qualification_approved` golden cases、`NHI-R1-SCOPE`、`PUB-R1-OWNER` 尚未完成。
- NHI `29101231` 的官方 sentinel 語意、實際 daily cadence、live same-hash reproducibility 尚未確認。
- `build_nhi_snapshot()` 的 synthetic review records 與 `official_qualification_status=not_qualified` 不可升格成正式 review。
- TFDA official importer、CDC PDF／ODS importer、LiteParse qualification 仍是 planned；不可由 NHI slice 推論已完成。
- process crash／power-loss durability 仍未做超出應用層 recovery 的宣稱。
- 未知事項與本次新發現已記在 `docs/implementation-notes.md`。

## Continue order

1. 先在 Claude 端讀本檔、所有指定文件與 repo-local instructions，核對 `git status --short --branch` 及 `git log -1`。
2. 保留目前已驗證的 first-round code；若要改動，遵守 RED→GREEN，先建立 focused failing test。
3. 下一個最小切片是 NHI official qualification evidence：在 owner 明確確認 publisher OID、license／attribution、可用 artifact 範圍與 scope basis 後，才建立正式 source/schema golden cases與 review records。
4. 在 owner gate 未完成前，維持 `coverage_status=review_incomplete`、candidate-only sync 與 official unavailable／no-fallback 行為。
5. 每次 source、schema、rule 或 identity 變更後，重跑完整 pytest、Ruff、build、archive、repo 外 wheel、stdio 與 contract equality。

## Please avoid

- 不要下載、提交或發布未經範圍確認的正式 bulk data。
- 不要加入病人資料、PHI、LIS/HIS、診斷、申報決策、採購或等效建議。
- 不要把 NHI points 稱為金額、把 current snapshot 當歷史資料庫、或把 official unavailable fallback 到 sample。
- 不要一次展開 TFDA、CDC PDF 或 CDC ODS。
- 不要 `git add -A`、force push、reset、覆蓋無關 dirty work，或把 synthetic／文件通過說成 official qualification／P1.1 release complete。

## Handoff acceptance

接手後先以 `git log -1 --oneline --decorate` 取得本次 continuation commit，再以 `git status --short --branch` 確認 worktree。若需要改變 source scope、正式資料下載、owner／reviewer 身分或發布方式，先停在該 gate，記錄唯一待決事項，不自行猜測。
