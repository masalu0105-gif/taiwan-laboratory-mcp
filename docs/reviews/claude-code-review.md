# Claude Code 獨立規格 Review

審查日期：2026-09-13（Asia/Taipei）
Reviewer：Claude Code（OAuth-authenticated CLI；read-only review）
範圍：PRD、SDD、TDD、implementation plan、research、prior reviews、現有 `src/` 與 `tests/`
結論：**NEEDS REVISION**

限制：本次是文件與與現況程式審查，不是醫療核准，也不是 official-mode 實作驗證。現有 `0.1.1` 維持 sample-only 是已知的 implementation gap，不單獨視為文件缺陷。

## Critical

### C1 — Public schema 要求 `extra=forbid`，但沒有完整封閉欄位表

- 位置：`docs/product-requirements.md:219`、`docs/software-design.md:463-470`、`docs/test-driven-development.md:165`
- 問題：文件要求 public model 不得多欄或少欄，但 PRD／SDD 仍使用「至少包含」，未列完整型別與 required/nullability。`historical_truth_supported`、traceability、分頁欄位等散落於其他段落；`standards_status` 與 `eqa_status` 也沒有完整 response schema。
- 最小修正：PRD 建立每種 public response 的完整封閉欄位 registry，含型別、required、nullable 與適用 operations；machine-readable contract 由此產生。

### C2 — Sample mode 的 `get_data_status` 無法同時符合 availability 與 snapshot required 規則

- 位置：`docs/product-requirements.md:212`、`:237-238`、`docs/test-driven-development.md:167`
- 問題：sample mode 被定義為 `availability=available`，但 available 又要求 snapshot／curated build identifiers；sample fixtures 沒有 official snapshot/build。
- 最小修正：明定 sample mode 的 snapshot/build 欄位為 `null`，仍可 `availability=available`，且必須保留 sample 警示，禁止製造假的 official identifiers。

## High

### H1 — TFDA unknown cancellation × unknown validity warning 不一致

- 位置：`docs/product-requirements.md:159-160`、`docs/test-driven-development.md:316-317`
- 問題：同一 truth-table case 的 warning set 不同。
- 最小修正：TDD fixture 與 PRD truth table 使用同一 machine-readable case source，不再手抄第二份。

### H2 — `content_age_warning` 與 canonical `content_age_status` 漂移

- 位置：`docs/software-design.md:526`、`docs/test-driven-development.md:208`、`docs/product-requirements.md:206,251,253`
- 最小修正：SDD／TDD 全部改為 `content_age_status`，contract test 拒絕 legacy key。

### H3 — 多個查詢 operation 沒有明確上限與 truncation contract

- 位置：`docs/product-requirements.md:78-85,93-94`、`docs/test-driven-development.md:506,523`
- 問題：CDC、ODS、license/manufacturer 等查詢缺 limit/default；`get_lab_scope` 引用未定義的 default page。大資料可能產生無界回傳或靜默截斷。
- 最小修正：定義所有 list operations 的 bounded result contract；未帶分頁參數者也必須有固定 hard cap，回 `total_matches`、`returned_count`、`truncated`。

### H4 — NHI 第一個 vertical slice 的 gate 定義互相衝突

- 位置：`docs/test-driven-development.md:243,555`、`docs/software-design.md:345-349`、`docs/product-requirements.md:340`
- 問題：一處要求 `NHI-R1-SCOPE` 完成才算第一切片，其他地方允許 `coverage_status=review_incomplete` 先服務。
- 最小修正：明確選擇第一切片允許 scope review pending；`search_payment_items` 可先服務，但不可宣稱完整 laboratory coverage。

### H5 — Implementation plan 的 CDC 欄位仍可能誘導拆出來源沒有的獨立欄

- 位置：`docs/implementation-plan.md:19`、`docs/research/cdc-data-source.md:57-66`
- 問題：implementation plan 列出的「檢體種類／採檢方法／感染性生物材料分類」並非研究確認的獨立官方表頭，可能讓實作者拆解複合原文並重組成官方未提供的指示。
- 最小修正：只列研究確認的 8 個官方欄位，複合欄保留原文，不另拆成 public clinical instruction。

## Medium

1. NHI 搜尋排序在 PRD／SDD／TDD 不完全一致；分頁前必須採單一排序規則。
2. `docs/use-cases.md` 與 `ROADMAP.md` 仍有已被新規格取代的 CDC 容器／保存及 NHI 同碼歷史版本文字。
3. TDD 說保留全部 53 個舊測試，但其中部分 sample-only assertions 需要 migration，不能原封不動視為新契約測試。
4. PRD 要求 sample mode 支援 4 個新增 operations，但 synthetic fixtures 可能沒有足夠欄位形成有意義的示範結果。
5. CDC「應保存種類（應保存時間）」不是送驗前保存條件的解讀仍需獨立醫檢專業判斷，review protocol 不應預設結論。
6. `get_payment_rule` 的 query 不是 exact code format 時，`invalid_request` 與 `not_found` precedence 未定義。

## Owner decisions（不是文件錯誤）

- Curated official snapshots 是否隨 GitHub Release 再散布。
- NHI laboratory scope reviewer 與依據；是否首版固定標示 review incomplete。
- TFDA IVD registry reviewer。
- CDC 內容 reviewer 與「應保存」語意的獨立判讀。
- 各來源 stale 門檻與首版平台承諾。
- 是否接受 NHI 單一來源先獨立上線，不等四個資料集全部完成。

## 預期 implementation gaps

- Official mode importer、snapshot、publisher、store 尚未實作。
- Planned contracts/rules/schemas/resources 尚未建立。
- TDD planned test nodes 尚未實作。
- Official golden qualification、review records 與 5–10 人 pilot 尚未執行。

## Claude 建議的最小修正順序

1. 補完整封閉 public schema。
2. 定義 sample `get_data_status` 的 nullable snapshot/build 行為。
3. 讓 TFDA warning fixture、`content_age_status` 與 PRD 完全一致。
4. 統一所有查詢的 bounded result、NHI 第一切片 gate 與 CDC 官方欄位。
