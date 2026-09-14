# 安裝說明：在自己的電腦用 Claude 查健保支付標準

這份說明帶你做完四件事：

1. 安裝查詢工具。
2. 下載已審核的健保資料。
3. 把資料裝進電腦。
4. 讓 Claude（桌面版或 Claude Code）能查。

Windows 與 macOS 各有對應指令，照你的電腦選一種做就好。全程不需要 API key，也不會把你的查詢內容傳給本專案。

> 這是個人維護的開源工具，**不是健保署官方服務**，內容以健保署公告為準。查到的點數不能直接當成金額，也不能用來判斷個案可不可以申報。

## 事前準備

- 一台可以上網的 Windows 10／11 或 macOS 電腦。
- Claude 桌面版或 Claude Code 其中一個。

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

到 [Releases 頁面](https://github.com/masalu0105-gif/taiwan-laboratory-mcp/releases) 看最上面那一版的標籤名稱（例如 `nhi-data-20260914`），把下面指令裡的 `<版本標籤>` 換成它。

Windows 與 macOS 指令相同：

```bash
uv tool install https://github.com/masalu0105-gif/taiwan-laboratory-mcp/archive/refs/tags/<版本標籤>.zip
```

成功時會看到 `Installed 2 executables: taiwan-lab-data, taiwan-lab-mcp`。

工具的位置：

- Windows：`C:\Users\<你的使用者名稱>\.local\bin\`
- macOS：`/Users/<你的使用者名稱>/.local/bin/`

## 第 3 步：下載健保資料

在同一個 Release 頁面下載兩個檔案：

- `nhi_fee-snapshot-xxxxxxxxxxxx.zip`：已審核的健保資料。
- 同名的 `.sha256` 檔：用來確認下載沒有壞掉。

打開 `.sha256` 檔，前面那一長串英數字就是這個檔案的 SHA-256。

**確認下載沒有壞掉**（算出來的值要和 `.sha256` 檔裡的一模一樣）：

- Windows：`Get-FileHash .\nhi_fee-snapshot-xxxxxxxxxxxx.zip -Algorithm SHA256`
- macOS：`shasum -a 256 nhi_fee-snapshot-xxxxxxxxxxxx.zip`

## 第 4 步：把資料裝進電腦

先決定資料要放哪個資料夾，下面用這兩個當例子：

- Windows：`C:\Users\<你的使用者名稱>\taiwan-lab-data`
- macOS：`/Users/<你的使用者名稱>/taiwan-lab-data`

**Windows**（PowerShell）：

```powershell
& "$env:USERPROFILE\.local\bin\taiwan-lab-data.exe" install-snapshot nhi_fee --bundle "$env:USERPROFILE\Downloads\nhi_fee-snapshot-xxxxxxxxxxxx.zip" --sha256 <SHA-256> --actor my-computer --data-dir "$env:USERPROFILE\taiwan-lab-data" --json
```

**macOS**（終端機）：

```bash
~/.local/bin/taiwan-lab-data install-snapshot nhi_fee --bundle ~/Downloads/nhi_fee-snapshot-xxxxxxxxxxxx.zip --sha256 <SHA-256> --actor my-computer --data-dir ~/taiwan-lab-data --json
```

- `<SHA-256>` 換成 `.sha256` 檔裡那串英數字。
- `--actor` 是記在紀錄裡的安裝者代號，隨便取一個英文代號就可以，不要用本名。

成功時最後會看到 `"result":"installed"`。如果看到 `"result":"failed"`，後面的 `error_code` 說明原因：

| error_code | 意思 | 怎麼辦 |
| --- | --- | --- |
| `BUNDLE_SHA256_MISMATCH` | 下載的檔案和發布時不一樣 | 重新下載，確認 `--sha256` 沒有貼錯 |
| `BUNDLE_MAGIC_MISMATCH` | 下載到的不是 ZIP（常見是下載到網頁） | 回 Release 頁面重新下載 |
| `BUNDLE_FILE_CONFLICT` | 資料夾裡已經有同名但內容不同的檔案 | 換一個新的空資料夾再裝 |

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

1. 「請先呼叫 get_data_status，告訴我健保資料狀態」：`nhi_fee` 應該是 `available`。
2. 「HbA1c 的健保碼是多少、支付幾點？」：應該查到 `09006C`，並附上資料來源與版本。

## 資料會過期嗎？

會。健保署宣告每天更新資料集，所以：

- 距離發布者最後一次核對健保署原始檔超過 **2 天**，查詢結果會標示「可能過期」（`upstream_check_overdue`），但仍然會回答。
- 有新版時，本專案審核通過後會發新的 Release。重做第 3、4 步就能換成新版；舊版會留在資料夾裡。

想自己確認健保署今天有沒有更新，可以執行（Windows 用 `taiwan-lab-data.exe` 完整路徑）：

```bash
taiwan-lab-data check nhi_fee --publisher-oid 2.16.886.101.20003.20065.20022 --actor my-computer --data-dir <你的資料夾> --json
```

- `"result":"unchanged"`：跟你裝的資料一樣，過期標示會消失。
- `"result":"changed"`：健保署有新版。你的查詢會繼續用已審核的舊版，並標示「有新版等待審核」。

## 已知限制

- 目前只有健保支付標準可以查正式資料。CDC 採檢手冊與 TFDA 醫材許可證還沒有正式資料，查詢會回 `data_unavailable`。
- 「哪些健保項目屬於檢驗」的範圍清單還沒審核完，結果會標 `coverage_status=review_incomplete`。
- 不支援查歷史點數；查過去日期會明確回「不支援」。
- macOS 目前由 GitHub 自動測試驗證，還沒有在實體 Mac 上完整走過這份安裝流程。

## 授權與資料來源

- 程式：MIT License。
- 健保資料：資料提供機關：衛生福利部中央健康保險署；依[政府資料開放授權條款-第1版](https://data.gov.tw/license)使用。
- 本專案與健保署無隸屬或背書關係。
