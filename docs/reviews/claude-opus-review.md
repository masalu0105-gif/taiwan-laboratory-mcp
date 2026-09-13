# Claude Opus P1.1 規劃文件複審

審查日期：2026-09-13（Asia/Taipei）
Reviewer：Claude Opus 5（Claude Code CLI、first-party OAuth subscription）
角色：唯讀 reviewer；未修改專案、未派出 sub-agent、未使用網路
範圍：前次 Claude findings closure、PRD／SDD／TDD 一致性與新回歸

## Verdict

**NEEDS REVISION**

前次 2 個 Critical、5 個 High 大多已關閉；目前主要阻塞是修 C1 時加入的 closed response schema 漏掉其他章節要求的必要欄位，因此 contract test 無法同時滿足兩邊。

## Findings closure

| ID | 狀態 | Opus 結論 |
| --- | --- | --- |
| C1 | Partial | 已有 `QueryResultV1`、`ItemEnvelopeV1`、`ProvenanceV1`、`ReservedStatusResultV1`，但 source record／locator 仍待 machine-readable contract，且 QueryResult 漏欄位 |
| C2 | Closed | sample status 的 snapshot／build IDs 明定為 null，TDD 有對應 assertion |
| H1 | Closed | PRD 與 TDD 的 TFDA warning truth table 已一致；後續仍應由 contract resource 參數化，不再手抄 |
| H2 | Closed | 正文已統一為 `content_age_status`；建議將 legacy key 加入完整禁用清單 |
| H3 | Partial | PRD 已定 bounded-result contract；CDC、ODS、license／manufacturer 的 hard-cap cases 尚缺 TDD 明確案例 |
| H4 | Closed | NHI scope pending 可服務且固定 `coverage_status=review_incomplete`；implementation plan 尚有一句可能被讀成必須先完成 scope review |
| H5 | Closed | implementation plan 已只列 CDC 第 2 章八個官方欄位，複合欄不拆 |
| M1 | Closed | NHI 排序已統一 |
| M2 | Closed | use case 與 roadmap 舊文字已更新 |
| M3 | Closed | 已明示 53 tests 只是 v0.1.1 baseline，衝突 assertions 要 migration |
| M4 | Closed | 新 operation 上線前需有 meaningful sample fixture；措辭可再明定缺一即整個 22-tool contract 不發布 |
| M5 | Partial | TDD pilot 已要求獨立判讀，但 PRD review protocol／SDD checklist 尚未同步，部分文字仍把推論當既定事實 |
| M6 | Closed | `get_payment_rule` 的 invalid／not-found precedence 已統一；仍應補 canonical test node 與大小寫規則 |

## New High — N1：closed QueryResult 漏必要欄位

`docs/product-requirements.md` 的其他 acceptance criteria 要求下列內容，但 `QueryResultV1`／`ProvenanceV1` exact keys 尚無位置：

- serving validation/review 與 latest candidate status、stale 狀態；
- TFDA candidate coverage detail；
- TFDA `evaluated_as_of` 與 timezone；
- deprecated operation 的 replacement operation；
- sample provenance 的 nullable IDs。

Opus 建議的最小修正：加入 strict `source_status`、nullable `coverage_detail`、nullable `evaluated_as_of`／`evaluated_timezone`、nullable `replacement_operation`，並明定 sample provenance IDs 為 null；source record／locator exact schema 與 TDD 都直接引用 `public-contract-v1.json`。

## Other consistency findings

1. 建立 internal error → public `availability_reason_code` 對照，釐清 `serving_integrity_failure`、`operational_status_integrity_failure` 與 `no_serving_snapshot`。
2. CDC critical／major review rejection 條件在 PRD／TDD 與 SDD／research 間仍不一致。
3. 修正文內少數定位與語意殘留：CDC digest 章節引用、failure stage 自由文字、手冊「方法」用語、NHI 空白生效迄日、legacy architecture 標註。

## Owner gates（非文件缺陷）

- OD-01～OD-05：artifact 散布、reviewer、日期／stale policy、平台範圍。
- CDC「應保存種類（應保存時間）」的獨立專業判讀者與結論。
- 無公開 offset 的 bounded query 是否需要可翻頁介面。
- NHI 是否依目前規格在 scope review 完成前先上線。

## Reviewer boundary

這是文件審查，不是實作驗證。Repository 仍是 v0.1.1 sample baseline；`Closed` 只表示文字已對齊，不代表 P1.1 已實作或可發布。
