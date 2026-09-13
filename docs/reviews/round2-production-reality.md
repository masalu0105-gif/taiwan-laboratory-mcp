# Round 2 Production Reality Review

審查日期：2026-09-13（Asia/Taipei）

審查範圍：修訂後 PRD、SDD、TDD、implementation plan、三份 source research、Round 1 reviews、現有 `src/`、`tests/` 與 package config。

審查門檻：實際可建置、可安裝、可運作、可故障復原、可由第二人重跑驗證。只列 Round 1 修訂後仍存在的問題。

## Verdict

**NEEDS WORK，不能給 READY。** 現有 0.1.1 sample-only baseline 可測、可 lint、可 build，但完全不是 P1.1 official implementation。修訂後文件已消除 Round 1 多數契約矛盾，仍有 5 個會阻止可靠實作或 production qualification 的缺口。

### 本輪實測證據

- `\.venv\Scripts\python.exe -m pytest -q`：53 passed in 2.72s。
- `\.venv\Scripts\python.exe -m ruff check .`：passed。
- `\.venv\Scripts\python.exe -m build`：成功產生 0.1.1 sdist／wheel。
- wheel 共 23 個檔案，只含現有 Python、sample JSON 與 metadata；沒有規劃中的 schemas、rules、review protocols、qualifier spec、official importer、publisher 或 data CLI。

## Remaining findings

### R2-PR-01 — Critical — 現況仍是 sample-only，任何 official release claim 都沒有 executable evidence

- **行號：** `src/taiwan_lab_mcp/models.py:71-77`、`src/taiwan_lab_mcp/server.py:125-133`、`tests/test_boundaries.py:76-80`、`tests/test_mcp_stdio.py:41-61`、`pyproject.toml:10-27`
- **證據：** `ToolResult.data_mode` 仍是 `Literal["sample"]`、`sample_only` 仍固定 `True`；`get_data_status` 固定回 `official_data_loaded=False`；測試明確拒絕所有非 sample mode。現有 stdio 測試只驗 synthetic provenance。實測 wheel 也沒有 SDD 第 18 節規劃的 official modules/resources。
- **影響：** 文件即使自洽，也無法證明 official sync、publish、stale、review gate、repo 外 CLI 或 official stdio 任一流程可運作。
- **最小修正：** 不把目前版本稱為 P1.1 candidate。依 TDD Phase 1 先完成最小 NHI vertical slice：雙模式 model、package resources、data CLI、snapshot/publish/store、official stdio fixture與 repo 外 wheel test；通過後才讓單一 NHI source 進 qualification，其餘來源維持 `data_unavailable`。

### R2-PR-02 — High — current pointer 與 operational status 分兩次切換，發布不是 availability-atomic

- **行號：** `docs/software-design.md:138-143`、`docs/software-design.md:343-358`、`docs/software-design.md:415-426`、`docs/test-driven-development.md:222-231`
- **證據：** query 必須同時信任 current pointer 與 status，且兩者 `serving_snapshot_id` 不一致就回 `data_unavailable`。publish 流程只原子替換 current pointer，沒有把 status 初始化／切換納入同一可恢復 transaction。process 在 pointer 切到 B 後、status 仍指 A 時崩潰，會從可服務 A 瞬間變成 unavailable；這不符合 TDD 所稱 runtime 只能看到完整 A 或完整 B。
- **影響：** 正常 crash window 即可造成服務中斷；首次 publish 若 status 尚未建立也會立即 unavailable。
- **最小修正：** 選一個真源。最小方案是把 serving identity 與 publish time 只放 current pointer；status 只保存 check/candidate 狀態，runtime 可在 status 缺失或舊 generation 時仍服務 current，並以 `stale=true`＋專用 integrity reason 告警。若堅持強一致，需 journaled multi-file publish/recovery protocol及逐 crash-point測試。

### R2-PR-03 — High — build identity 的關鍵輸入沒有 canonical bytes 定義，第二人無法重算

- **行號：** `docs/software-design.md:171-175`、`docs/software-design.md:208-210`、`docs/software-design.md:248-257`、`docs/software-design.md:309`、`docs/test-driven-development.md:146-148`
- **證據：** `raw_revision_id` 納入 `discovery_metadata_sha256`，`curated_build_id` 納入 `application_build_sha256` 與多個 bundle hash，但文件沒有定義 discovery metadata 哪些欄位參與 canonical JSON，也沒有定義 application build 是 wheel bytes、Git tree、installed package inventory或版本字串。若把取得時間／volatile HTTP headers 納入 discovery metadata，同一 artifact 每次 check 都會變 raw revision；若不同環境各自 build wheel，application hash也可能漂移。
- **影響：** immutable ID、review subject digest、skip-build與 second-person reproduction 都可能對同一內容算出不同結果。
- **最小修正：** 新增一張 fingerprint input schema：逐欄列 canonicalization、排序、null處理與排除的 volatile fields。`application_build_sha256` 最小可定義為 release wheel 的 SHA-256，sync 必須保存 wheel hash；開發模式則明確不可產生 production-approved build。

### R2-PR-04 — High — CDC qualifier 的 package path 與安裝依賴契約仍矛盾

- **行號：** `docs/software-design.md:148-160`、`docs/software-design.md:549-563`、`docs/software-design.md:750-760`、`docs/test-driven-development.md:295-310`、`docs/test-driven-development.md:419-430`、`pyproject.toml:10-13`
- **證據：** SDD 先指定 `src/taiwan_lab_mcp/qualifier_specs/liteparse-2.0.0.json`，但 qualification 段落又寫從 package resource `qualifiers/liteparse-2.0.0.json` 載入；兩者不是同一路徑。Python package dependencies沒有 LiteParse，文件也未定義 npm prerequisite 如何安裝、版本缺失時哪三個 source仍可正常服務。現有 wheel實測不含任一路徑。
- **影響：** repo 外安裝的 canonical CDC command 會因資源路徑或外部 executable 缺失而失敗，且失敗範圍可能被錯誤擴大到整個 MCP。
- **最小修正：** 統一為 `qualifier_specs/`，加入 package-content test；在安裝文件與 CLI preflight 明定 `@llamaindex/liteparse@2.0.0` 是 CDC-sync optional prerequisite、核對方式與錯誤碼。缺 LiteParse 時只讓 CDC candidate qualification unavailable，不影響已核准 snapshot與其他三來源。

### R2-PR-05 — Medium — 時程沒有涵蓋文件自己新增的 production qualification 成本

- **行號：** `docs/implementation-plan.md:226-230`、`docs/product-requirements.md:201-221`、`docs/product-requirements.md:225-247`、`docs/software-design.md:818-824`、`docs/test-driven-development.md:457-484`
- **證據：** implementation plan 仍估 24–39 個工程工作日加受測排程，但修訂後 gate 已包含：跨平台 lock/CAS/crash recovery、四來源各至少 10 個 official reviewed golden cases、CDC 首版全列 review、399 個 TFDA A/B/C codes 的逐碼處理、owner/專業 reviewer、archive/out-of-tree qualification，以及 5–10 人九情境 pilot。同時 stale hard-stop、支援平台、CDC reviewer turnaround與 artifact redistribution仍是 OWNER GATE。
- **影響：** 這個估算可作純開發粗估，不能用作 P1.1 release commitment；專業複核與未決策等待時間很可能超過工程實作本身。
- **最小修正：** 拆成「engineering effort」與「calendar lead time」，並為每個 owner/reviewer gate標 owner、最晚決策日及不通過時的縮限版本。首個可交付 milestone限定 NHI-only official beta；四來源全數 qualified 與 pilot另估，不沿用 24–39 日總承諾。

## Production gate conclusion

- **可確認：** sample-only 0.1.1 baseline 可測、可 lint、可打包。
- **未確認：** official importer、snapshot durability、publisher recovery、package resource resolution、CDC qualification、專業 review與 pilot。
- **Production readiness：FAILED / NEEDS WORK。** 至少先關閉 R2-PR-02～04，並以實作後的 NHI repo-outside wheel E2E 證據證明共同層，再評估是否進 TFDA／CDC。
