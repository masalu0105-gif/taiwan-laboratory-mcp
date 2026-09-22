---
tags:
  - 專案
  - MCP
  - IVD
  - todo
created: 2026-09-23
status: 待處理
---

# Taiwan Laboratory MCP 待辦

- GitHub：https://github.com/masalu0105-gif/taiwan-laboratory-mcp
- 首頁：https://lab.masalulab.com
- 端點：`https://lab.masalulab.com/mcp`

## 待處理

### 1. 首頁換新版（含痛點區塊）

首頁 HTML 只存在 Grok VM（`grok-bot-box`）上，筆電連不到 VM（沒 Tailscale、沒 gcloud、SSH 不通），Claude 無法代為部署。新版已推進 repo `site/index.html`。

在 **VM 的 Linux 終端機**（不是筆電 PowerShell）依序跑：

```bash
git clone --depth 1 https://github.com/masalu0105-gif/taiwan-laboratory-mcp.git /tmp/tlm
```

```bash
sudo find / -name "index.html" -path "*lab*" -not -path "/tmp/*" 2>/dev/null
```

```bash
sudo cp /tmp/tlm/site/index.html <上一步印出的路徑>
```

換完重新整理 lab.masalulab.com（Cloudflare 快取 5 分鐘）。

驗收要看到的三個改動（都在 repo `site/index.html`，最新 commit 已包含）：

| 位置 | 改前 | 改後 |
| --- | --- | --- |
| hero 示範分頁鈕 + 問句 | 「ARKRAY 許可證還有效嗎」／「ARKRAY 的 ADAMS A1c HA-8180 許可證還有效嗎？」 | 「ARKRAY HA-8180 字號與效期」／「ARKRAY HA-8180 的許可證字號是哪一個？效期到什麼時候？」 |
| hero 示範分頁鈕 + 問句 | 「PCT 幾點」／「Procalcitonin 健保給付幾點？」 | 「PCT 健保碼與點數」／「PCT 的健保代碼是哪一個？可以申報幾點？」 |
| hero 之後新區塊 | 無 | 「這些日常的痛，用問的就好」六張卡片，第一張範例句「HPV 的檢測試劑，有哪幾家有證？」 |

給另一台電腦的 Claude 的一句話指令：
> 連進 grok-bot-box VM，找到 lab.masalulab.com 首頁的 index.html 實際路徑（cloudflared 指 127.0.0.1:18083，看是哪個程序在服務 `/`），先備份原檔，再用 https://github.com/masalu0105-gif/taiwan-laboratory-mcp 最新 main 的 `site/index.html` 覆蓋，重整網站確認上表三個改動都出現。

- [ ] VM 覆蓋 index.html
- [ ] 確認線上首頁更新
- [ ] （選做）筆電裝 Tailscale 加入 tail6cbb55 tailnet，之後 Claude 可直接 scp

### 2. 發 Threads 貼文

三則定稿在下方。順序：主文 → 回覆一 → 回覆二。建議首頁換好再發，回覆二的連結點進去才看得到痛點。

- [ ] 主文
- [ ] 回覆一
- [ ] 回覆二

## 2026-09-23 已完成

- README 重排：亮點優先、九條痛點、工具清單／文件／範圍／使用建議全部精簡、限制改建議語氣
- GitHub repo 描述更新 + 8 個 topics
- 首頁新版 `site/index.html` 完成並驗過桌機／手機排版

## Threads 貼文定稿

### 主文

查食藥署許可證，一個字打錯就找不到。

不知道正式品名叫什麼，更找不到。

這不是你的問題，是那個網站的問題。

所以我做了「台灣實驗室 MCP」，一個讓 Claude 這類 AI 能直接查台灣官方資料的接口。用模糊的說法問就好：

「HPV 的檢測試劑，有哪幾家有證？」

AI 自己去比對品名跟效能，幫你鎖定最相關的幾張。

你不用先知道正確答案長什麼樣，這才是用 AI 找資料的重點。

免費、開源。覺得有用的話，到 GitHub 幫我點個 ⭐，讓更多檢驗人看到 👇

https://github.com/masalu0105-gif/taiwan-laboratory-mcp

### 回覆一

1️⃣ 業務拿來的許可證要確認？

證號查真偽、看在誰名下、有沒有註銷或快到期。
公司名下幾十張證一次列出，依效期排序，半年內要展延的直接抓出來。

2️⃣ 院內做不了的傳染病項目，要送哪一家？

疾管署認可機構名冊兩百多筆，直接問哪些能做這個項目，名單跟縣市一次列出。

3️⃣ 特殊檢體不知道怎麼送？

以前翻疾管署手冊翻半天。
現在問一句，檢體、容器、運送條件直接給你，附頁碼。

4️⃣ 申報條件搞不清楚？

這個項目多久能報一次、有什麼限制、幾點，直接問支付規範，不會把別的項目的規定混進來。

5️⃣ 查完還要整理成表、算數字？

查到的資料 AI Agent 可以接著算、接著填。
效期排序產成 Excel、許可證欄位填進採購單或評估表。
查詢只是起點，後面的整理跟運算一起交給它。

### 回覆二

三個資料集：疾管署採檢手冊與認可機構、健保檢驗支付標準、食藥署醫材許可證。

回答都附官方來源與版本，要核對隨時找得到。

不用裝，把 MCP host 指向 lab.masalulab.com/mcp 就能用。完整介紹跟接法在這：

https://lab.masalulab.com

一直想要一個真正符合台灣實驗室的 MCP，找不到，就自己跳下來做了。先做出來了，用過的人跟我說哪裡不順，有興趣一起維護也歡迎。
