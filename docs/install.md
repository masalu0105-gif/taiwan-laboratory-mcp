# 安裝說明：在自己的電腦用 Claude 查健保支付標準與食藥署醫材許可證

這份說明帶你做完四件事：

1. 安裝查詢工具。
2. 下載健保與食藥署資料。
3. 把資料裝進電腦。
4. 讓 Claude（桌面版或 Claude Code）能查。

Windows 與 macOS 各有對應指令，照你的電腦選一種做就好。全程不需要 API key，也不會把你的查詢內容傳給本專案。

> 這是個人維護的開源工具，**不是健保署或食藥署的官方服務**，內容以兩個機關的公告為準。查到的點數不能直接當成金額，也不能用來判斷個案可不可以申報；查到的許可證不能直接當作醫療器材廣告或效能宣傳素材。

## 事前準備

- 一台可以上網的 Windows 10／11 或 macOS 電腦。
- Claude 桌面版或 Claude Code 其中一個。
- 至少 300 MB 空間（食藥署資料裝好後約 185 MB）。

## 第 1 步：安裝 uv（用來安裝工具的小程式）

uv 會幫你準備好需要的 Python，不用另外安裝 Python。已經裝過 uv 的人跳過這一步。

**Windows**：開啟「PowerShell」，貼上：

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**macOS**：開啟「終端機」，貼上：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

裝完後**關掉視窗再重新開一個**，後面的指令才找得到 uv。

## 第 2 步：安裝查詢工具

到 [Releases 頁面](https://github.com/masalu0105-gif/taiwan-laboratory-mcp/releases) 看最上面那一版的標籤名稱（例如 `data-20260915`），把下面指令裡的 `<版本標籤>` 換成它。

Windows 與 macOS 指令相同：

```bash
uv tool install https://github.com/masalu0105-gif/taiwan-laboratory-mcp/archive/refs/tags/<版本標籤>.zip
```

成功時會看到 `Installed 2 executables: taiwan-lab-data, taiwan-lab-mcp`。

以前裝過舊版的人，把 `install` 後面加上 `--force` 再執行一次，程式才會換成新版。

工具的位置：

- Windows：`C:\Users\<你的使用者名稱>\.local\bin\`
- macOS：`/Users/<你的使用者名稱>/.local/bin/`

## 第 3 步：下載資料

在同一個 Release 頁面下載四個檔案：

| 檔案 | 內容 | 大小 |
| --- | --- | --- |
| `nhi_fee-snapshot-xxxxxxxxxxxx.zip` | 健保支付標準 | 約 2 MB |
| 同名的 `.sha256` 檔 | 用來確認上面那個檔案沒有壞掉 | 1 KB 以下 |
| `tfda_devices-snapshot-xxxxxxxxxxxx.zip` | 食藥署醫療器材許可證 | 約 65 MB |
| 同名的 `.sha256` 檔 | 用來確認上面那個檔案沒有壞掉 | 1 KB 以下 |

只想查其中一種資料，就只下載那一組。

打開 `.sha256` 檔，前面那一長串英數字就是對應檔案的 SHA-256。

**確認下載沒有壞掉**（算出來的值要和 `.sha256` 檔裡的一模一樣）：

- Windows：`Get-FileHash .\nhi_fee-snapshot-xxxxxxxxxxxx.zip -Algorithm SHA256`
- macOS：`shasum -a 256 nhi_fee-snapshot-xxxxxxxxxxxx.zip`

食藥署那個檔案用同樣方式確認。

## 第 4 步：把資料裝進電腦

先決定資料要放哪個資料夾，下面用這兩個當例子：

- Windows：`C:\Users\<你的使用者名稱>\taiwan-lab-data`
- macOS：`/Users/<你的使用者名稱>/taiwan-lab-data`

健保和食藥署裝進**同一個資料夾**，各執行一次指令。

**Windows**（PowerShell）：

```powershell
& "$env:USERPROFILE\.local\bin\taiwan-lab-data.exe" install-snapshot nhi_fee --bundle "$env:USERPROFILE\Downloads\nhi_fee-snapshot-xxxxxxxxxxxx.zip" --sha256 <健保的SHA-256> --actor my-computer --data-dir "$env:USERPROFILE\taiwan-lab-data" --json
```

```powershell
& "$env:USERPROFILE\.local\bin\taiwan-lab-data.exe" install-snapshot tfda_devices --bundle "$env:USERPROFILE\Downloads\tfda_devices-snapshot-xxxxxxxxxxxx.zip" --sha256 <食藥署的SHA-256> --actor my-computer --data-dir "$env:USERPROFILE\taiwan-lab-data" --json
```

**macOS**（終端機）：

```bash
~/.local/bin/taiwan-lab-data install-snapshot nhi_fee --bundle ~/Downloads/nhi_fee-snapshot-xxxxxxxxxxxx.zip --sha256 <健保的SHA-256> --actor my-computer --data-dir ~/taiwan-lab-data --json
```

```bash
~/.local/bin/taiwan-lab-data install-snapshot tfda_devices --bundle ~/Downloads/tfda_devices-snapshot-xxxxxxxxxxxx.zip --sha256 <食藥署的SHA-256> --actor my-computer --data-dir ~/taiwan-lab-data --json
```

- `<健保的SHA-256>`、`<食藥署的SHA-256>` 換成各自 `.sha256` 檔裡那串英數字。
- `--actor` 是記在紀錄裡的安裝者代號，隨便取一個英文代號就可以，不要用本名。
- 食藥署資料比較大，安裝時會逐一核對每個檔案，大約需要十幾秒到一分鐘。

成功時最後會看到 `"result":"installed"`。如果看到 `"result":"failed"`，後面的 `error_code` 說明原因：

| error_code | 意思 | 怎麼辦 |
| --- | --- | --- |
| `BUNDLE_SHA256_MISMATCH` | 下載的檔案和發布時不一樣 | 重新下載，確認 `--sha256` 沒有貼錯 |
| `BUNDLE_MAGIC_MISMATCH` | 下載到的不是 ZIP（常見是下載到網頁） | 回 Release 頁面重新下載 |
| `BUNDLE_SOURCE_MISMATCH` | 指令裡的 `nhi_fee`／`tfda_devices` 和檔案對不上 | 健保檔用 `nhi_fee`，食藥署檔用 `tfda_devices` |
| `BUNDLE_FILE_CONFLICT` | 資料夾裡已經有同名但內容不同的檔案 | 換一個新的空資料夾再裝 |
| `BUNDLE_PATH_TOO_LONG` | 資料夾路徑太長，超過 Windows 的 260 字元限制（還沒寫入任何檔案） | 改用短一點的資料夾，例如 `C:\Users\<你的使用者名稱>\taiwan-lab-data` |
| `BUNDLE_WRITE_FAILED` | 寫檔失敗，常見是磁碟滿了或沒有權限 | 確認磁碟空間與資料夾權限後重裝一次；已寫入的相同檔案會自動略過 |

同一份資料重裝一次會回 `"result":"already_installed"`，不會改動任何東西。

## 第 5 步：讓 Claude 能查

### Claude 桌面版

打開設定檔（沒有這個檔就新建一個）：

- Windows：`%APPDATA%\Claude\claude_desktop_config.json`
- macOS：`~/Library/Application Support/Claude/claude_desktop_config.json`

加入下面內容。已經有 `mcpServers` 的人，只要把 `taiwan-laboratory` 那一段放進去。

**Windows**（路徑裡的反斜線要寫兩個）：

```json
{
  "mcpServers": {
    "taiwan-laboratory": {
      "command": "C:\\Users\\<你的使用者名稱>\\.local\\bin\\taiwan-lab-mcp.exe",
      "env": {
        "TAIWAN_LAB_DATA_MODE": "official_snapshot",
        "TAIWAN_LAB_DATA_DIR": "C:\\Users\\<你的使用者名稱>\\taiwan-lab-data",
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

**macOS**：

```json
{
  "mcpServers": {
    "taiwan-laboratory": {
      "command": "/Users/<你的使用者名稱>/.local/bin/taiwan-lab-mcp",
      "env": {
        "TAIWAN_LAB_DATA_MODE": "official_snapshot",
        "TAIWAN_LAB_DATA_DIR": "/Users/<你的使用者名稱>/taiwan-lab-data",
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

存檔後**完全關閉 Claude 桌面版再重新打開**。

### Claude Code

在終端機執行一次（換成你自己的路徑；最後的 `--` 後面接工具位置）：

**Windows**（PowerShell）：

```powershell
claude mcp add taiwan-laboratory -s user -e TAIWAN_LAB_DATA_MODE=official_snapshot -e "TAIWAN_LAB_DATA_DIR=C:/Users/<你的使用者名稱>/taiwan-lab-data" -e PYTHONIOENCODING=utf-8 -- "C:/Users/<你的使用者名稱>/.local/bin/taiwan-lab-mcp.exe"
```

**macOS**（終端機）：

```bash
claude mcp add taiwan-laboratory -s user -e TAIWAN_LAB_DATA_MODE=official_snapshot -e TAIWAN_LAB_DATA_DIR=/Users/<你的使用者名稱>/taiwan-lab-data -e PYTHONIOENCODING=utf-8 -- /Users/<你的使用者名稱>/.local/bin/taiwan-lab-mcp
```

執行 `claude mcp list`，看到 `taiwan-laboratory` 後面是 `Connected` 就完成了。

## 第 6 步：試查一次

對 Claude 說：

1. 「請先呼叫 get_data_status，告訴我資料狀態」：`nhi_fee` 與 `tfda_device` 應該都是 `available`。
2. 「HbA1c 的健保碼是多少、支付幾點？」：應該查到 `09006C`，並附上資料來源與版本。
3. 「HbA1c 有哪些體外診斷的許可證？」：應該列出許可證摘要（一次最多 5 筆），並附上資料來源與版本。

## 資料會過期嗎？

會。查詢結果標示「可能過期」（`upstream_check_overdue`）時仍然會回答：

- 健保署宣告每天更新：距離發布者最後一次核對原始檔超過 **2 天**就會標示。
- 食藥署宣告每 7 天更新：超過 **14 天**就會標示。

官方有新版時，本專案的電腦會自動檢查。檢查通過後，會自動發布新的 Release。重做第 3、4 步就能換成新版；舊版會留在資料夾裡。

想自己確認官方今天有沒有更新，可以執行（Windows 用 `taiwan-lab-data.exe` 完整路徑）：

```bash
taiwan-lab-data check nhi_fee --publisher-oid 2.16.886.101.20003.20065.20022 --actor my-computer --data-dir <你的資料夾> --json
```

```bash
taiwan-lab-data check tfda_devices --publisher-oid 2.16.886.101.20003.20065.20065 --actor my-computer --data-dir <你的資料夾> --json
```

- `"result":"unchanged"`：跟你裝的資料一樣，過期標示會消失。
- `"result":"changed"`：官方有新版。你的查詢會繼續用已裝好的版本，並標示「有新版等待審核」；等本專案發布新的 Release 後重裝即可。

## 已知限制

- CDC 採檢手冊還沒有正式資料，查詢會回 `data_unavailable`。
- 「哪些健保項目屬於檢驗」由 AI 審核，紀錄見 [審核紀錄](reviews/nhi-lab-scope-ai-review-2026-09-14.md)。判不出來的代碼一律算檢驗；官方新版出現、還沒審過的代碼也先算檢驗，之後補審。所以「算檢驗」可能多收少數項目。
- 「哪些醫材算體外診斷」由 AI 依食藥署分類分級附表逐碼判斷，紀錄見 [審核紀錄](reviews/tfda-ivd-ai-review-2026-09-14.md)。附表 A／B／C 類判不出來、或還沒審過的代碼先算體外診斷；沒有分類代碼或只有其他類別的許可證標「不確定」（`unknown`），仍查得到。
- 食藥署許可證的比對結果不能推論產品可以互相替代。
- 最早的 `nhi-data-20260914` 資料包是審核前做的，裝好後每個項目都標 `scope_status=review_pending`。之後發布的資料包每個項目都帶判定。要看到判定，程式與資料包都要換成同一個新 Release 的版本。
- 不支援查歷史點數；查過去日期會明確回「不支援」。
- macOS 目前由 GitHub 自動測試驗證，還沒有在實體 Mac 上完整走過這份安裝流程。

## 遇到問題或有建議

歡迎直接回報，這是改進這個工具的主要方式：

- 查到的資料不對、裝不起來、結果看不懂：[回報錯誤或資料問題](https://github.com/masalu0105-gif/taiwan-laboratory-mcp/issues/new?template=bug_report.yml)
- 希望多查哪些資料、怎樣才更好用：[提出使用需求](https://github.com/masalu0105-gif/taiwan-laboratory-mcp/issues/new?template=feature_request.yml)

回報內容是公開的。請不要貼病人資料、院內資料或帳號密碼。

## 授權與資料來源

- 程式：MIT License。
- 健保資料：資料提供機關：衛生福利部中央健康保險署；依[政府資料開放授權條款-第1版](https://data.gov.tw/license)使用。
- 食藥署資料：資料提供機關：衛生福利部食品藥物管理署；依[政府資料開放授權條款-第1版](https://data.gov.tw/license)使用。
- 本專案與健保署、食藥署無隸屬或背書關係。
