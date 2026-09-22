# Persona scenario report

- Matrix: `persona-scenarios-v1`
- Endpoint: `https://grok-bot-box.tail6cbb55.ts.net/mcp`
- Result: **97/100 passed**
- Median latency: 756.7 ms
- Max latency: 1507.3 ms

## Persona summary

| Persona | Passed |
|---|---:|
| 醫檢師（檢驗台） | 10/10 |
| 採檢護理師 | 9/10 |
| 外送檢驗協調員 | 9/10 |
| 公衛實驗室協調員 | 10/10 |
| 健保編碼查詢人員 | 9/10 |
| IVD 法規人員 | 10/10 |
| 採購前資料覆核人員 | 10/10 |
| 醫檢教育與工作坊講師 | 10/10 |
| MCP 安裝與整合人員 | 10/10 |
| 資料治理與安全覆核人員 | 10/10 |

## Failures

- `NURSE-10` malaria 若不在目前手冊資料中會如何回覆？ — result_status='ok', expected one of ['not_found']; returned_count=4 > 0
- `SEND-09` 手冊對檢體灑漏有什麼程序？ — result_status='not_found', expected one of ['ok']; returned_count=0 < 1
- `NHI-02` 一般人寫糖化血色素時能找到 09006C 嗎？ — result_status='not_found', expected one of ['ok']; returned_count=0 < 1; missing path 'items.0.record.code_raw'
