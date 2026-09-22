# Security policy

## 目前支援狀態

目前為 0.1.2 個人維護的公開資料查詢工具。套件內附合成資料，經審核的正式 snapshot 另由 GitHub Releases 散布。維護者優先處理預設分支的問題；未承諾醫院正式部署、臨床適用或舊版本支援。

## 回報漏洞

先查看 [GitHub Security](https://github.com/masalu0105-gif/taiwan-laboratory-mcp/security) 是否提供 **Report a vulnerability**。若有，可在該處私下回報。

若未提供私下回報入口，請建立只包含「需要安全回報管道」的 Issue，請維護者安排聯絡方式。公開內容不要包含 exploit、機密、病人資料或未遮蔽紀錄。本專案目前不承諾固定回應時限。

回報內容請包含受影響版本、重現條件、影響範圍及使用合成資料的最小範例。發現已曝光的憑證時，憑證擁有者應撤銷或輪替該憑證；不要將其貼入 Issue。

## P1 邊界

- 僅處理公開的檢驗參考資料；不接病人資料、LIS 或院內帳號。
- 本機 stdio 不經本專案的網路服務。HTTP transport 預設限制請求頻率與大小、不快取回應、不寫 access log，並支援以 bearer-token SHA-256 啟用驗證。預設不記錄任何請求；部署者可以設 `TAIWAN_LAB_HTTP_USAGE_LOG` 主動開啟使用紀錄（見下節）。
- 來源文件中的文字視為資料，不得授權執行指令、讀取本機祕密或向第三方傳送資料。
- 正式資料只從通過來源、結構、審核與 owner gate 的 immutable snapshot 載入；匯入會驗證格式、大小及解壓縮路徑，外部連結不能任意擴大抓取範圍。
- 原始資料缺漏、過期或載入失敗時明確回報；不能用示範值或推測值代替。

MCP host 與模型提供者可能有自己的資料傳輸設定，使用者應依使用場域設定。P1 不需要在任何 host 輸入病人或院內機密資料。

## 公開 HTTP 端點

- 匿名端點只供查公開政府資料；不得傳送病人、帳號、院內或其他機密內容。
- 預設每個來源 IP 每分鐘 240 次、request body 最大 262,144 bytes；超過分別回 HTTP 429／413。
- 若部署者設定 `TAIWAN_LAB_HTTP_BEARER_TOKEN_SHA256`，所有 `/mcp` 請求必須提供對應 bearer token。設定只保存 token 的 SHA-256。
- 公開反向代理必須只連 loopback listener，並將唯一公開 hostname 列入 `TAIWAN_LAB_HTTP_ALLOWED_HOSTS`。

## 使用紀錄（本專案經營的公開端點有開）

套件預設不記錄。設了 `TAIWAN_LAB_HTTP_USAGE_LOG` 才會開，**`https://lab.masalulab.com/mcp` 這個端點有開**。

會記下來的：

- 呼叫時間、來源 IP、JSON-RPC method、工具名稱、**送進來的查詢參數原文**、HTTP 狀態碼、處理毫秒數
- 被限流或擋下來的請求，另記原因代碼

不會記下來的：

- 請求標頭。bearer token 在標頭裡，所以不會進紀錄
- 回應內容

保護措施：單筆查詢參數超過 2,000 字截斷；檔案超過 50 MB 輪替成 `.1`；寫入失敗直接放棄，不影響查詢結果。

**用這個公開端點等於同意架站的人看得到你查了什麼。** 不要在上面輸入病人資料、院內資料、帳號密碼或任何機密內容。要自己掌握紀錄就裝在自己電腦上，本機 stdio 不經任何網路服務。

部署者要關掉記錄，把 `TAIWAN_LAB_HTTP_USAGE_LOG` 拿掉即可；沒有這個環境變數就完全不寫。
