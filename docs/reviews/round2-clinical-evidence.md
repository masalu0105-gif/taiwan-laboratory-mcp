# 第 2 輪獨立審查：臨床證據、台灣醫檢安全與來源可追溯性

審查日期：2026-09-13（Asia/Taipei）

審查角色：clinical evidence／台灣醫檢安全／來源可追溯 reviewer

審查範圍：`docs/product-requirements.md`、`docs/software-design.md`、`docs/test-driven-development.md`、`docs/implementation-plan.md`、`docs/research/*.md` 與三份 round 1 reviews。

限制：本輪只審修訂後文件，不重新下載官方資料、不驗證程式實作，也不代表醫療、主管機關或專業團體核准。

## 結論

**CONDITIONALLY ACCEPTABLE FOR IMPLEMENTATION PLANNING。** PRD、SDD 與 TDD 已修正 round 1 的主要產品安全問題：NHI 歷史查詢、TFDA 效期與註銷分軌、reviewed／candidate IVD 查詢、CDC「應保存」語意、ODS 收件邊界、結構化警示、來源列 provenance，以及本機公開資料查詢與院內部署的界線，現在大致一致且可測。

本輪仍發現 2 項 High、2 項 Medium。它們都出現在仍被主文件列為上游依據的實作計畫或研究文件。團隊可以進行共用信任層與 NHI importer 的 implementation planning；在使用這些文件產生 TFDA／CDC 實作工作卡或啟用任何 official mode 前，應先修正 High finding，並同步處理兩項契約不一致。此結論只表示文件足以繼續工程規劃，不表示內容取得醫療核准，也不證明實作具臨床正確性。

## 仍存在的 findings

### R2-CE-01 — CDC 實作計畫仍把「應保存」寫成送驗前保存能力，且拆出來源沒有的容器／保存欄

- **Severity：High**
- **檔案／行：** `docs/implementation-plan.md:19`、`docs/implementation-plan.md:169-173`
- **對應 round 1：** PCL-04 修正不完整。
- **證據：** 計畫摘要仍承諾查詢「容器、保存、運送與送驗條件」，清理段又要求保存「採檢方法、容器、保存、運送」關係。相同文件所引用的來源研究在 `docs/research/cdc-data-source.md:61-64` 明確指出：容器與採法位於複合欄 `採檢量及規定`，溫度與包裝關係位於 `送驗方式`，`應保存種類（應保存時間）` 則是疾管署保存材料／期間。PRD `CDC-02` 與 SDD `SDD-CDC-01` 已禁止將它改稱送驗前保存條件。實作者若以計畫書的拆欄文字建 schema，仍可能抽出來源不支持的 storage instruction，直接影響採檢／送驗安全。
- **最小修正：** 將第 19 行改成官方欄位層級的描述，明列 `採檢量及規定`、`送驗方式`、`應保存種類（應保存時間）`，並就近註明最後一欄不是送驗前保存條件。將第 170 行改成「以原始表格列為最小單位，保留複合欄原文；不得自行拆出容器、採法、溫度或保存指示」，再引用 PRD `CDC-02`／SDD 第 10.3 節作唯一 schema 契約。

### R2-CE-02 — TFDA 研究文件仍允許產生 `not_cancelled_and_within_validity`，會重新導入「有效許可」推論

- **Severity：High**
- **檔案／行：** `docs/research/tfda-data-source.md:161-172`
- **對應 round 1：** PCL-01 修正不完整。
- **證據：** 研究文件第 172 行仍要求輸出 `computed_temporal_state`，並寫「只有資料一致時才可給 `not_cancelled_and_within_validity`」。但同段只證明來源有空白、已註銷、已廢止、註銷日期與有效日期等原始欄位；空白註銷狀態不是官方明文的「未註銷」。PRD `TFDA-02`（`docs/product-requirements.md:122`）與 SDD（`docs/software-design.md:499`）已改成 query-time、互不替代的 `cancellation_recorded_in_source` 與 `within_validity_period_as_of`，並禁止合成「有效許可」。研究文件仍列為 SDD 上游依據，實作者可能依舊版結論重建被禁止的狀態。
- **最小修正：** 刪除 `computed_temporal_state` 與 `not_cancelled_and_within_validity` 建議；改成保留三組原始欄位，查詢時才用明示日期／時區計算 `within_validity_period_as_of`，另以 `cancellation_recorded_in_source=true|false|unknown` 描述來源是否記錄註銷。就近補一句：兩者不可合成許可有效、上市、販售、採購或 TFDA 推薦結論。

### R2-CE-03 — NHI 研究文件的歷史查詢錯誤碼仍與 public contract 不一致

- **Severity：Medium**
- **檔案／行：** `docs/research/nhi-data-source.md:141-150`、`docs/product-requirements.md:80`、`docs/software-design.md:480`、`docs/test-driven-development.md:70`
- **對應 round 1：** PCL-03／QA-03 已修主契約，但研究結論未同步。
- **證據：** NHI 研究第 150 行要求超出能力的日期查詢回 `historical_data_unavailable`；PRD、SDD 與 TDD 的 canonical public contract 則固定為 `historical_query_unsupported`、`historical_truth_supported=false`、0 items。兩者在安全意圖上相同，但錯誤碼不同會讓 importer、MCP adapter 或測試各自實作一套語意，削弱「現行 snapshot 不冒充歷史事實」的可測性。
- **最小修正：** 將研究文件的建議碼統一為 `historical_query_unsupported`，並一併寫入 `historical_truth_supported=false`、0 items、不得回 current points 或日期涵蓋布林。若希望保留 `historical_data_unavailable`，只能把它標成已廢棄的研究草案名稱，不能進 public enum。

### R2-CE-04 — CDC 研究仍使用裸 `G1`～`G5`，其專業核准證據無法直接對應修訂後 gate

- **Severity：Medium**
- **檔案／行：** `docs/research/cdc-data-source.md:110-120`、`docs/product-requirements.md:211-219`、`docs/software-design.md:579-583`、`docs/test-driven-development.md:204`
- **對應 round 1：** QA-02／PCL-10 的主文件已修，但研究文件未同步。
- **證據：** CDC 研究仍將 `G1`～`G5` 定義為來源、版面、專業內容、認可機構與發布核准；修訂後主契約明確禁止 evidence schema 使用裸 `G1`／`G5`，並把手冊與 ODS 拆成 `CDC-R1-*`、`ODS-R1-*`，共同發布另用 `PUB-R1-OWNER`。研究表也只有概括的抽樣要求，沒有帶出主文件已新增的 subject digest、固定抽樣、critical／major 判退與 re-review 規則。若實作工作卡直接引用研究 gate，owner sign-off 可能被誤當成醫檢內容 review，或留下 publisher 無法驗證的核准紀錄。
- **最小修正：** 將研究表改成現行 namespace，分開列出 CDC 手冊與 ODS gate，並在表後直接引用 PRD 8.3／SDD 10.3–10.4 的 reviewer qualification、hash-bound subject、抽樣、判退及重審規則。明示 `PUB-R1-OWNER` 只核准發布／顯名，不可替代醫檢內容或認可制度 reviewer。

## 第二輪確認已修正

- TFDA 查詢已把註銷紀錄與日期效期拆開，並禁止「有效許可」、販售、採購及官方推薦結論。
- IVD 已拆為 reviewed-only 與 candidate recall，unknown／ambiguous 不再被空結果隱藏。
- NHI 非 null `as_of` 已固定拒絕歷史斷言；支付點數不換算金額，也不判定個案可申報。
- CDC 與 ODS 已保留原始列關係、item-level provenance、收件非保證與結構化誤用警示；pilot 也不被描述為臨床成效或全面適用性的驗證。
- P1.1 已清楚限制為本機離線公開資料查詢，未宣稱院內部署 readiness、診斷權威或主管機關背書。

## 進入下一階段的判定

可開始：共用 snapshot／audit／publish 信任層與 NHI importer 的 implementation planning、Red test 規劃及 synthetic fixture 建立。

暫不應開始：依 `implementation-plan.md` 的舊 CDC 欄位描述建立 production schema；依 TFDA 研究的 `not_cancelled_and_within_validity` 建立衍生狀態；將任何來源標記為 medical-approved、officially endorsed 或 production-ready。
