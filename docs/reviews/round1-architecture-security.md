# 第一輪獨立審查：資料架構與安全

審查日期：2026-09-13（Asia/Taipei）
審查範圍：`product-requirements.md`、`software-design.md`、`test-driven-development.md`、`implementation-plan.md`、`research/*.md`、現有 `src/` 與 `tests/`
限制：本輪只做文件與現況程式的靜態審查，未修改正文、未執行正式資料同步，也未把目前 sample-only 測試視為 official mode 已驗證。

## 結論

目前設計的方向可以落地，但還不應直接開始 official publish 實作。以下有 10 項 P1：其中最危險的是 curated identity 未包含 parser／rule 版本、publish 沒有並行 compare-and-swap、review evidence 沒有不可變地綁定被核准資料，以及 quarantine 規則可能容許遺失官方列。這些問題若留到 importer 完成後再改，會同時影響四個來源。

嚴重度：`P1` = 對應來源啟用 official mode 前必修；`P2` = 公開 release／跨平台承諾前修正；`P3` = hardening。

## P1：先修共同資料與發布契約（1–5）

### 1. Curated snapshot identity 沒有綁定 transform 與 rule，原檔不變時無法套用修正

- Severity：P1（confidence 10/10）
- 檔案／行：`docs/software-design.md:155-161`、`docs/software-design.md:221-225`、`docs/test-driven-development.md:111`
- 證據：SDD 寫明「相同 primary raw SHA-256 不重建 curated snapshot，只新增 check record」，但同一 manifest 又把 `parser_version`、`schema_version`、`normalization_version`、`rule_versions` 視為 curated provenance。
- 原因：上游 bytes 不變時，parser bug fix、NHI scope／TFDA IVD rule 更新、schema 修訂或第一次建置失敗後重跑，都可能需要產生新的 curated DB。現在的去重規則會讓舊語意永久留在 serving snapshot；metadata 或授權內容改變而 payload 不變時也會被略過。
- 最小修正：拆成 `raw_revision_id` 與 `curated_build_id`。前者由 ordered artifact／discovery metadata hashes 決定；後者至少由 raw revision、application、parser、schema、normalization、rule bundle hashes 決定。只有完整 build fingerprint 相同才可跳過；同 raw＋不同 rule/parser 必須建立新 immutable curated build。TDD 增加 same-raw/different-rule、same-raw/parser-fix、failed-build-retry 三案。

### 2. `os.replace` 只有單檔原子性，沒有防止並行 publish 把新版倒退成舊版

- Severity：P1（confidence 10/10）
- 檔案／行：`docs/software-design.md:313-322`、`docs/test-driven-development.md:118-127`、`docs/test-driven-development.md:309`
- 證據：流程只規定建立 pointer temp 後 `os.replace(temp, current)`；測試只注入各階段例外，沒有兩個 publisher 同時切換的案例。
- 原因：同步排程與人工 publish 同時執行時，A、B 都可能以同一舊 pointer 通過 precondition，B 先發布新版，A 後發布較舊候選，最後 current 合法但倒退。`os.fsync()` 只作用在 temp file；未定義目錄 durability 與 crash recovery，斷電後的 pointer 保證也不明確。
- 最小修正：每來源使用 exclusive publish lock，pointer 加 `generation` 與 `parent_snapshot_id`，切換前做 compare-and-swap precondition；current 已變即拒絕。rollback 走獨立命令，必填 target、reason、actor、時間，不可偽裝成一般 publish。POSIX 明定 rename 前後 parent-directory fsync；Windows 明定實際可承諾的 replace/durability primitive與 recovery。TDD 加兩 process barrier race、舊候選晚到、publish crash/readback recovery。

### 3. Validation／review evidence 只有敘述與 hash，沒有不可變路徑，也沒綁定核准標的

- Severity：P1（confidence 10/10）
- 檔案／行：`docs/software-design.md:227-244`、`docs/software-design.md:254-259`、`docs/software-design.md:511`、`docs/software-design.md:550`
- 證據：manifest 只有 `validation.report_sha256`；`review.completed` 只有 gate、reviewer、時間。`reviews/<source>/<snapshot>/review.json` 位於 curated snapshot 外，manifest 沒有 review file path/hash，也沒有每個 completed gate 實際審查的 artifact、DB、rule bundle digest。
- 原因：publisher 無法只靠目前 schema 證明 reviewer 核准的是這一組 raw artifacts、這個 rule 版本及這個 curated DB。外部 review 檔被替換後也無法從 serving manifest 找回原核准證據。
- 最小修正：把 final validation report 與 accepted review records 複製或內容定址到 immutable audit bundle；manifest 保存相對 data-root 的 path＋SHA-256。每筆 review 明列 `subject_digest`（ordered artifacts、curated DB、transform/rule hashes）、decision、gate type、reviewer、reviewed_at。publisher 重新計算並逐 gate 比對，缺一即拒絕。另明載 reviewer identity 是本機稽核紀錄或具簽章的身分保證，不能混稱。

### 4. Serving、candidate 與 query result 共用狀態欄，會回出互相矛盾的 ToolResult

- Severity：P1（confidence 10/10）
- 檔案／行：`docs/product-requirements.md:125-136`、`docs/software-design.md:324-333`、`docs/software-design.md:470-483`
- 證據：PRD 把 `validation_status=approved` 定義為可服務；SDD ToolResult 卻定義 `validation_status=passed|review_pending`。同時，新版 review pending 時規定繼續服務上一 approved snapshot，但 `status` enum 又含 `review_pending`。
- 原因：client 無法判斷 `review_pending` 是「本次 items 不可用」或「items 是可用的舊 approved 版，但另有候選新版」。同一欄混合 validator 結果與 reviewer 決議，也會讓 release gate、status endpoint 與查詢結果各自實作不同 enum。
- 最小修正：定義唯一 state matrix，至少拆成 `result_status`、`availability`、`serving_validation_status`、`serving_review_status`、`latest_candidate_status`、`stale/stale_reason`。服務舊 approved 版時 `result_status=ok|not_found`，candidate 另標 `review_pending`；沒有 serving snapshot 才是 `data_unavailable`。PRD、SDD、TDD 共用完全相同 enum 與 allowed combinations，加入 invalid-combination contract tests。

### 5. TFDA stale 規則引用 CSV 主來源不存在的 embedded date

- Severity：P1（confidence 10/10）
- 檔案／行：`docs/software-design.md:330`、`docs/research/tfda-data-source.md:47-51`、`docs/product-requirements.md:135`、`docs/test-driven-development.md:113`
- 證據：SDD 規定依 `embedded data date` 的 10／14 日門檻，但研究明載 embedded date 只存在 XML，CSV／JSON 沒有同等欄位；P1.1 又選 CSV ZIP 為主來源。資料列最大異動日也明確不是下載或發布時間。
- 原因：CSV importer 無法照規格算此值；若錯用 max record changed date，在合法「近期無資料列異動」時仍會永久變 stale critical，與 PRD「多久未成功核對上游」的 stale 語意衝突。
- 最小修正：`stale` 只依最後一次完整成功 upstream verification 與已知新版待審判斷。`portal_metadata_modified_at`、`embedded_data_updated_on`、`max_record_changed_on` 各自保留為 nullable evidence；另設 `content_age_warning`，不可直接改寫 stale。若要額外抓 XML 只為 embedded date，須把 XML 納入同次 check 的 artifact provenance 與跨格式一致性規則。

## P1：來源資料、runtime 與 API 契約（6–10）

### 6. Row quarantine 是否容許發布未定義，可能把官方列靜默丟掉

- Severity：P1（confidence 10/10）
- 檔案／行：`docs/software-design.md:308`、`docs/software-design.md:531-536`、`docs/research/tfda-data-source.md:243-249`、`docs/product-requirements.md:133`
- 證據：SDD 只說是否可繼續由來源規則決定，卻沒列出 TFDA／ODS 的 publish disposition；TFDA 研究把空字號、日期錯誤、狀態衝突與角色缺值列為 row quarantine，其中部分列看起來可被排除後繼續。
- 原因：只要丟掉一列，後續 `not_found` 就可能只是 importer 遺失資料，不是 snapshot 未命中；同許可證多製造關係也可能被截斷。這與「原始資料完整、查無不可擴大解讀」的產品契約衝突。
- 最小修正：在 SDD 增加 per-source error disposition table。P1.1 預設任何會移除 source row 或破壞一對多關係的錯誤都 block 整批；分類 code 無法解析應保留一般許可列並令 IVD state unknown，不可 quarantine 掉原列。若日後容許 partial publish，需新的 owner gate、`coverage_status=partial`、排除列數／原因與每次 query 警示。TDD 加「單列錯誤不得產生看似完整的 published snapshot」。

### 7. Raw artifact 與每筆結果的 provenance locator 沒有可實作的共同契約

- Severity：P1（confidence 9/10）
- 檔案／行：`docs/software-design.md:113-136`、`docs/software-design.md:209-217`、`docs/software-design.md:282-292`、`src/taiwan_lab_mcp/models.py:71-78`
- 證據：manifest 範例使用 `relative_path="artifacts/source.csv"`，但 artifact 實際放在 `raw/<source>/<snapshot>/artifacts/`，沒有說相對哪個 root。ToolResult 繼續以 `items: list[dict]` 與 top-level provenance list 表示，沒有規定 grouped TFDA child row 或 CDC entity 要如何一對一連到 artifact role。
- 原因：實作者可能把 path 解成 curated 目錄、data root 或 raw snapshot，導致 readback/redistribution 行為不同。TFDA group 含多個 manufacturing rows 時，top-level provenance 也無法證明每個 child 的 row hash/locator；CDC 手冊與修訂表有兩個 PDF，更不能只回一個未標 role 的 raw SHA。
- 最小修正：artifact reference 明定 `artifact_id`、`role`、`storage_scope`、data-root-relative path、URL、hash 與 local availability；所有 path 在 publish 時做 containment/hash readback。ToolResult 定義 typed item envelope；snapshot 共用欄可 top-level 一次回傳，但每個 source row/child 必須有 `artifact_id + source_row_sha256 + locator`。Redistributed artifact 未含 raw 時明示 `local_artifact_available=false`，不能聲稱可回到本機原檔。

### 8. SQLite 的「只讀」與 immutable single-file 假設不足以直接實作

- Severity：P1（confidence 9/10）
- 檔案／行：`docs/software-design.md:82-89`、`docs/software-design.md:267-274`、`docs/software-design.md:549`
- 證據：設計只明列「建立 read-only connection，執行 `PRAGMA query_only=ON`」，沒指定 URI `mode=ro`、journal/WAL 策略、extension/trusted schema，以及 DB hash 驗證與 open 間的處理。
- 原因：一般 `sqlite3.connect(path)` 預設可寫；`query_only` 是連線後才設定。若 build 留下 WAL/SHM 或 hot journal，單獨 hash `data.sqlite3` 不代表完整內容；runtime 也可能產生 sidecar 或執行受污染 schema 中的行為。這破壞 immutable snapshot 與無寫入 runtime 的承諾。
- 最小修正：builder 固定 journal policy、commit/checkpoint/close 後確認沒有 `-wal`、`-shm`、`-journal`，再 hash。runtime 以安全建構的 SQLite URI `mode=ro` 開啟；只有在完整 hash 通過且檔案永不再修改時才用 `immutable=1`。設定 `query_only=ON`、停用 extension loading、支援時 `trusted_schema=OFF`；所有 SQL 參數化。TDD 加 write denied、sidecar absent、tampered schema/DB、開啟期間 current 切換四案。

### 9. PRD、SDD 與現有 tool signature 對 NHI／TFDA 行為不一致

- Severity：P1（confidence 10/10）
- 檔案／行：`docs/product-requirements.md:88-91`、`docs/product-requirements.md:100-101`、`docs/software-design.md:374-381`、`docs/software-design.md:418`、`docs/test-driven-development.md:63-68`、`src/taiwan_lab_mcp/server.py:70-109`
- 證據：PRD 要求 `get_points` 支援 `as_of`，SDD 卻寫「若未來加入」；現有 signature 只有 `get_points(code)`。PRD 允許名稱候選與 `scope_status`，SDD 又要求 `search_lab_code/get_payment_rule` 在 scope 未核准時直接 `scope_review_pending`。PRD 的 IVD 搜尋要呈現 ambiguous/unknown，SDD 的 `search_ivd` 只回 included。
- 原因：同一套 acceptance tests 無法同時滿足三份文件；開發者勢必自行選一種行為，造成 public MCP contract 漂移。
- 最小修正：先加一張 canonical operation matrix，逐 tool 鎖定參數、資料範圍、候選是否回傳、狀態與 backward compatibility。P1.1 若承諾 NHI-04，就現在加入 optional `as_of` 並明定 historical boundary；否則移出 PRD/TDD。候選搜尋與正式 IVD 搜尋分成不同 tool 或明確 flag，避免 `search_ivd` 名稱回傳 unknown/non-IVD 候選。

### 10. CDC/ODS review gate 編號與 PRD release gate 撞號

- Severity：P1（confidence 10/10）
- 檔案／行：`docs/product-requirements.md:154-164`、`docs/software-design.md:450-462`、`docs/test-driven-development.md:295-305`
- 證據：PRD 的 `G5` 是 5–10 人使用者驗收；SDD CDC 卻把 `G5` 寫成 owner publish，ODS 又要求 `G1/G2/G4/G5`。TDD 明載沿用 PRD G1～G5、不另創 gate 編號。
- 原因：自動 publisher 若照 SDD 檢查 G5，可能誤把 owner 點擊當成 pilot gate，或錯誤要求每次 CDC 更新都重跑產品 pilot；相反地，也可能讓真正 PRD G5 被跳過。
- 最小修正：來源 review gates 改為唯一 namespace，例如 `CDC-R1 source`、`CDC-R2 layout`、`CDC-R3 clinical`、`ODS-R1 institution`、`PUB-A owner authorization`，再明確映射 PRD G2/G3。PRD G1～G5 只保留 release-level 語意，publisher 接受的是列舉出的 source review records，不接受裸 `G1` 字串。

## P2：公開 release 前 hardening（11–13）

### 11. CDC「失去文字層即 block」與「允許 OCR」互相衝突

- Severity：P2（CDC official mode 前仍須解決；confidence 10/10）
- 檔案／行：`docs/software-design.md:424-436`、`docs/test-driven-development.md:169-181`
- 證據：artifact pairing 規定任一頁無文字層就整批 block；同節後面又允許對無可靠文字層頁面 OCR，且 OCR row 提高 review 等級。TDD 仍把必要頁失去文字層列為 block。
- 原因：實作者不知道 OCR 產物可否進 staged、可否通過 review 成為 approved，或 P1.1 根本禁止 OCR；兩條都合理，但不能同時當發布規格。
- 最小修正：二選一。最小安全預設是 P1.1 允許 OCR 只產生 candidate/staged，OCR 頁所有輸出需 100% row/cell review，manifest 綁定 extractor/OCR engine、model/version、options 與 output hash；沒有可靠 bbox/lineage 一律 block publish。若暫不做這套 review，直接宣告 P1.1 OCR 不可發布。

### 12. 本機 threat model 未定義，鄰近存放的 hash 只能防意外毀損，不能防可寫入者竄改

- Severity：P2（confidence 9/10）
- 檔案／行：`docs/software-design.md:58-60`、`docs/software-design.md:267-280`、`docs/software-design.md:542-553`
- 證據：runtime 會驗 pointer、manifest、DB hash，但三者都在同一 data root；文件未說 updater、runtime、一般本機程序是否為同一 OS principal，也未定義 ACL 或簽章。
- 原因：能寫 data root 的程序可一起替換 DB、manifest 與 pointer並重算 hashes；status 也可被改成 `stale=false`。目前設計能偵測部分損壞，不構成對惡意本機 writer 的 authenticity 保證。
- 最小修正：新增 threat model。若信任 updater，明說 hash 只保證一致性／可追溯，不防 trusted-user tampering，並要求 runtime principal 對 data root 只有 read、publisher 使用獨立 write principal/ACL。若產品要防同機 writer，需用 runtime 不可取得私鑰的 signed manifest/review record或受保護 key store。status 永遠不可作 authorization，毀損或驗證失敗維持 stale。

### 13. 安全 archive/XML 測試還缺實際資源耗盡邊界

- Severity：P2（confidence 8/10）
- 檔案／行：`docs/software-design.md:544-548`、`docs/test-driven-development.md:152-154`、`docs/test-driven-development.md:183-190`、`docs/test-driven-development.md:223-233`
- 證據：ZIP 測試涵蓋 path、entry、大小與 ratio；ODS 只特別測 repeated columns 16,384，未列 repeated rows、超長 cell、XML element/depth budget、iterparse 清理或壓縮資料串流上限。
- 原因：合法 ZIP metadata 仍可包入高成本 XML；只限制前 12 欄不等於限制 rows、text、elements 或 nested markup。若 `iterparse` 不即時 `elem.clear()`，大 ODS 仍可能讓 sync process 記憶體耗盡。
- 最小修正：定義 compressed bytes、actual streamed uncompressed bytes、rows、elements、cell text length、repeat count、nesting/depth 的硬上限；解析時 incremental counting 與 clear。加 declared size 欺騙、`number-rows-repeated` 巨值、超長 cell、過深 XML、接近上限正常檔的 fixtures，並 assert current 不變。

## 建議修正順序

1. 先統一 state/gate/tool operation matrix（項目 4、9、10）。
2. 再定義 raw revision、curated build、artifact/audit binding（項目 1、3、7）。
3. 完成 publish concurrency/durability 與 SQLite runtime contract（項目 2、8、12）。
4. 把 per-source quarantine、freshness、OCR disposition 寫成決策表（項目 5、6、11）。
5. 最後補 resource-exhaustion 與 concurrency/crash tests（項目 13 及項目 2 的測試）。

Round 1 verdict：`NEEDS WORK`。上述 P1 未修前，不建議把文件標為 implementation-ready，也不應啟用任一 official current pointer。
