#Requires -Version 5.1
<#
.SYNOPSIS
    一鍵安裝 Taiwan Laboratory MCP：裝查詢工具、下載官方資料包、設定 Claude 桌面版。

.DESCRIPTION
    這支腳本做的事，跟 docs/install.md 的第 1 到 5 步一模一樣，只是不用自己打指令：

      1. 裝 uv（幫忙準備 Python 的小程式），已經有就跳過。
      2. 從 GitHub 最新的 Release 裝查詢工具。
      3. 下載你要的資料包，並自動核對 SHA-256。
      4. 把資料包裝進你指定的資料夾。
      5. 把 taiwan-laboratory 加進 Claude 桌面版的設定檔（會先備份原檔）。

    重跑一次是安全的：已經裝好的資料包會回「已安裝」，不會動到任何東西。

.PARAMETER DataDir
    資料要放哪個資料夾。預設 %USERPROFILE%\taiwan-lab-data。

.PARAMETER Datasets
    要裝哪幾種資料。預設四種全裝。只想查採檢手冊和健保就寫 -Datasets nhi_fee,cdc_specimen_manual。

.PARAMETER Tag
    要裝哪一版（例如 data-20260917）。不填就用 GitHub 上最新的那一版。

.PARAMETER SkipClaudeConfig
    只裝工具和資料，不要碰 Claude 的設定檔。

.PARAMETER SkipToolInstall
    查詢工具已經是你要的版本，只想重新下載或補裝資料時用。

.PARAMETER ConfigPath
    Claude 桌面版設定檔的位置。預設 %APPDATA%\Claude\claude_desktop_config.json。

.EXAMPLE
    .\Install-TaiwanLabMcp.ps1

.EXAMPLE
    .\Install-TaiwanLabMcp.ps1 -Datasets nhi_fee,cdc_specimen_manual
#>
[CmdletBinding()]
param(
    [string]$DataDir = (Join-Path $env:USERPROFILE 'taiwan-lab-data'),

    [string[]]$Datasets = @('nhi_fee', 'tfda_devices', 'cdc_authorized_labs', 'cdc_specimen_manual'),

    [string]$Tag,

    [switch]$SkipClaudeConfig,

    [switch]$SkipToolInstall,

    [string]$ConfigPath = (Join-Path $env:APPDATA 'Claude\claude_desktop_config.json')
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Repository = 'masalu0105-gif/taiwan-laboratory-mcp'
$Actor = 'windows-installer'

# 每種資料的中文名稱，只用在畫面訊息上。
$DatasetNames = @{
    'nhi_fee'             = '健保支付標準'
    'tfda_devices'        = '食藥署醫療器材許可證'
    'cdc_authorized_labs' = '疾管署傳染病認可檢驗機構名冊'
    'cdc_specimen_manual' = '疾管署傳染病檢體採檢手冊'
}

function Write-Step { param([string]$Text) Write-Host "`n>> $Text" -ForegroundColor Cyan }
function Write-Ok { param([string]$Text) Write-Host "   OK  $Text" -ForegroundColor Green }
function Write-Info { param([string]$Text) Write-Host "       $Text" -ForegroundColor Gray }

function Stop-WithAdvice {
    param([string]$Problem, [string]$Advice)
    Write-Host "`n安裝停下來了：$Problem" -ForegroundColor Red
    if ($Advice) { Write-Host "怎麼辦：$Advice" -ForegroundColor Yellow }
    Write-Host "還是不行的話，把上面整段訊息貼到 https://github.com/$Repository/issues 回報。" -ForegroundColor Yellow
    exit 1
}

function Find-Uv {
    $command = Get-Command uv -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    # uv 裝好後這個 session 的 PATH 還沒更新，所以直接找它的預設位置。
    $fallback = Join-Path $env:USERPROFILE '.local\bin\uv.exe'
    if (Test-Path -LiteralPath $fallback) { return $fallback }
    return $null
}

function Invoke-Download {
    param([string]$Uri, [string]$OutFile)
    # Invoke-WebRequest 的進度條在大檔案上會拖慢下載，關掉再開回來。
    $previous = $ProgressPreference
    $ProgressPreference = 'SilentlyContinue'
    try {
        Invoke-WebRequest -Uri $Uri -OutFile $OutFile -UseBasicParsing
    }
    finally {
        $ProgressPreference = $previous
    }
}

function ConvertTo-Hashtable {
    param($InputObject)
    if ($null -eq $InputObject) { return $null }
    if ($InputObject -is [System.Collections.IDictionary]) {
        $copy = [ordered]@{}
        foreach ($key in $InputObject.Keys) { $copy[$key] = ConvertTo-Hashtable $InputObject[$key] }
        return $copy
    }
    if ($InputObject -is [System.Management.Automation.PSCustomObject]) {
        $copy = [ordered]@{}
        foreach ($property in $InputObject.PSObject.Properties) {
            $copy[$property.Name] = ConvertTo-Hashtable $property.Value
        }
        return $copy
    }
    if ($InputObject -is [object[]]) {
        return @($InputObject | ForEach-Object { ConvertTo-Hashtable $_ })
    }
    return $InputObject
}

Write-Host '=========================================================='
Write-Host ' Taiwan Laboratory MCP 安裝程式'
Write-Host ' 查健保支付標準、食藥署醫材許可證與疾管署檢驗資料'
Write-Host '=========================================================='
Write-Host '這不是健保署、食藥署或疾管署的官方服務，內容以三個機關的公告為準。' -ForegroundColor Yellow

# -Datasets 寫成一個逗號字串（用 powershell -File 呼叫時會這樣）也要收得下來。
$Datasets = @($Datasets | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$unknown = @($Datasets | Where-Object { -not $DatasetNames.Contains($_) })
if ($unknown.Count -gt 0) {
    Stop-WithAdvice "不認得這幾種資料：$($unknown -join '、')" "-Datasets 只能填這四個名稱：$(($DatasetNames.Keys | Sort-Object) -join '、')。"
}
if ($Datasets.Count -eq 0) { Stop-WithAdvice '沒有指定要裝哪種資料' '把 -Datasets 拿掉就會四種全裝。' }

# ---------------------------------------------------------------- 第 1 步：uv
Write-Step '第 1 步：檢查 uv（幫忙準備 Python 的小程式）'
$uv = Find-Uv
if ($uv) {
    Write-Ok "已經有 uv：$uv"
}
else {
    Write-Info '沒有找到 uv，現在自動安裝（只裝在你的使用者資料夾，不需要系統管理員權限）。'
    try {
        $installer = Invoke-RestMethod -Uri 'https://astral.sh/uv/install.ps1' -UseBasicParsing
        Invoke-Expression $installer | Out-Null
    }
    catch {
        Stop-WithAdvice "自動安裝 uv 失敗（$($_.Exception.Message)）" '手動開一個新的 PowerShell 視窗，貼上 powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"，裝完再跑一次這支腳本。'
    }
    $uv = Find-Uv
    if (-not $uv) { Stop-WithAdvice 'uv 裝完之後還是找不到' '關掉這個視窗，重新開一個 PowerShell，再跑一次這支腳本。' }
    Write-Ok "uv 裝好了：$uv"
}

# ------------------------------------------------------- 第 2 步：找出要裝的版本
Write-Step '第 2 步：查 GitHub 上的版本'
if ($Tag) {
    $releaseUri = "https://api.github.com/repos/$Repository/releases/tags/$Tag"
}
else {
    $releaseUri = "https://api.github.com/repos/$Repository/releases/latest"
}
try {
    $release = Invoke-RestMethod -Uri $releaseUri -Headers @{ 'User-Agent' = 'taiwan-lab-installer' } -UseBasicParsing
}
catch {
    Stop-WithAdvice "連不上 GitHub 或找不到版本（$($_.Exception.Message)）" "確認網路正常；有指定 -Tag 的話，到 https://github.com/$Repository/releases 確認標籤名稱拼對了。"
}
$Tag = $release.tag_name
Write-Ok "要裝的版本：$Tag"

# ---------------------------------------------------------- 第 3 步：裝查詢工具
Write-Step '第 3 步：安裝查詢工具'
if ($SkipToolInstall) {
    Write-Info '跳過（你指定了 -SkipToolInstall）。'
}
else {
    $toolZip = "https://github.com/$Repository/archive/refs/tags/$Tag.zip"
    Write-Info '第一次安裝要下載 Python，可能要等一兩分鐘。'
    & $uv tool install --force $toolZip
    if ($LASTEXITCODE -ne 0) { Stop-WithAdvice 'uv tool install 失敗（錯誤訊息在上面）' '網路不穩可以再跑一次；持續失敗就把上面的訊息回報。' }
}

# uv 通常把工具放在 %USERPROFILE%\.local\bin，但使用者可以改，所以直接問它。
$binDir = (& $uv tool dir --bin 2>$null | Select-Object -First 1)
if (-not $binDir -or -not (Test-Path -LiteralPath $binDir)) { $binDir = Join-Path $env:USERPROFILE '.local\bin' }
$mcpExe = Join-Path $binDir 'taiwan-lab-mcp.exe'
$dataExe = Join-Path $binDir 'taiwan-lab-data.exe'
if (-not (Test-Path -LiteralPath $dataExe)) { Stop-WithAdvice "裝完卻找不到 $dataExe" '重新開一個 PowerShell 視窗再跑一次這支腳本。' }
Write-Ok "查詢工具：$mcpExe"

# ------------------------------------------------------------ 第 4 步：下載資料
Write-Step "第 4 步：下載資料（$($Datasets.Count) 種）"
$downloadDir = Join-Path $env:TEMP "taiwan-lab-$Tag"
New-Item -ItemType Directory -Path $downloadDir -Force | Out-Null
Write-Info "暫存在 $downloadDir，裝完可以整個刪掉。"

$plans = @()
foreach ($dataset in $Datasets) {
    $asset = $release.assets | Where-Object { $_.name -like "$dataset-snapshot-*.zip" } | Select-Object -First 1
    $checksumAsset = $release.assets | Where-Object { $_.name -like "$dataset-snapshot-*.zip.sha256" } | Select-Object -First 1
    if (-not $asset -or -not $checksumAsset) {
        Stop-WithAdvice "版本 $Tag 裡沒有 $($DatasetNames[$dataset]) 的資料包" "到 https://github.com/$Repository/releases/tag/$Tag 看這一版有哪些檔案，用 -Datasets 只挑有的。"
    }

    $bundlePath = Join-Path $downloadDir $asset.name
    $checksumPath = Join-Path $downloadDir $checksumAsset.name
    $sizeMb = [math]::Round($asset.size / 1MB, 1)
    Write-Info "下載 $($DatasetNames[$dataset])（$sizeMb MB）…"
    try {
        Invoke-Download -Uri $asset.browser_download_url -OutFile $bundlePath
        Invoke-Download -Uri $checksumAsset.browser_download_url -OutFile $checksumPath
    }
    catch {
        Stop-WithAdvice "下載 $($asset.name) 失敗（$($_.Exception.Message)）" '網路斷了或檔案太大逾時，再跑一次這支腳本就會接著下載。'
    }

    # .sha256 檔第一個欄位就是那串雜湊值。
    $expected = ((Get-Content -LiteralPath $checksumPath -Raw).Trim() -split '\s+')[0]
    $actual = (Get-FileHash -LiteralPath $bundlePath -Algorithm SHA256).Hash
    if ($actual -ne $expected.ToUpperInvariant()) {
        Stop-WithAdvice "$($asset.name) 下載到的內容跟發布時不一樣" "刪掉 $downloadDir 整個資料夾再跑一次。持續不一樣就回報，不要繼續安裝。"
    }
    Write-Ok "$($DatasetNames[$dataset]) 下載完成，核對碼相符"
    $plans += [pscustomobject]@{ Dataset = $dataset; Bundle = $bundlePath; Sha256 = $expected }
}

# -------------------------------------------------------- 第 5 步：把資料裝進去
Write-Step "第 5 步：安裝資料到 $DataDir"
New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
$installed = @()
foreach ($plan in $plans) {
    Write-Info "安裝 $($DatasetNames[$plan.Dataset])…"
    $output = & $dataExe install-snapshot $plan.Dataset --bundle $plan.Bundle --sha256 $plan.Sha256 --actor $Actor --data-dir $DataDir --json 2>&1 | Out-String
    $result = $null
    try { $result = ($output | ConvertFrom-Json).result } catch { $result = $null }
    if ($result -eq 'installed') { Write-Ok "$($DatasetNames[$plan.Dataset]) 安裝完成" }
    elseif ($result -eq 'already_installed') { Write-Ok "$($DatasetNames[$plan.Dataset]) 本來就裝好了，沒有變動" }
    else {
        Write-Host $output
        Stop-WithAdvice "安裝 $($DatasetNames[$plan.Dataset]) 失敗" "上面那行 error_code 的意思，查 https://github.com/$Repository/blob/main/docs/install.md 的錯誤對照表。"
    }
    $installed += $plan.Dataset
}

# ------------------------------------------------------ 第 6 步：設定 Claude 桌面版
if ($SkipClaudeConfig) {
    Write-Step '第 6 步：跳過（你指定了 -SkipClaudeConfig）'
}
else {
    Write-Step '第 6 步：把工具加進 Claude 桌面版'
    $configPath = $ConfigPath
    New-Item -ItemType Directory -Path (Split-Path -Parent $configPath) -Force | Out-Null

    $config = [ordered]@{}
    if (Test-Path -LiteralPath $configPath) {
        $backupPath = "$configPath.bak-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        Copy-Item -LiteralPath $configPath -Destination $backupPath
        Write-Info "原本的設定檔已備份到 $backupPath"
        try {
            $config = ConvertTo-Hashtable (Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json)
        }
        catch {
            Stop-WithAdvice "現有的 $configPath 不是合法的 JSON，不敢動它" "先自己修好那個檔案，或把它改名備份後再跑一次；備份在 $backupPath。"
        }
        if ($null -eq $config) { $config = [ordered]@{} }
    }

    if (-not $config.Contains('mcpServers')) { $config['mcpServers'] = [ordered]@{} }
    $config['mcpServers']['taiwan-laboratory'] = [ordered]@{
        command = $mcpExe
        env     = [ordered]@{
            TAIWAN_LAB_DATA_MODE = 'official_snapshot'
            TAIWAN_LAB_DATA_DIR  = $DataDir
            PYTHONIOENCODING     = 'utf-8'
        }
    }

    $json = $config | ConvertTo-Json -Depth 20
    # Claude 讀這個檔案要 UTF-8 而且不能有 BOM。
    [IO.File]::WriteAllText($configPath, $json, (New-Object Text.UTF8Encoding($false)))
    Write-Ok "設定檔寫好了：$configPath"
}

# ---------------------------------------------------------------------- 完成
Write-Host "`n==========================================================" -ForegroundColor Green
Write-Host ' 裝好了' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
Write-Host "版本：$Tag"
Write-Host "資料夾：$DataDir"
Write-Host "已裝的資料：$(($installed | ForEach-Object { $DatasetNames[$_] }) -join '、')"
Write-Host ''
Write-Host '接下來你要做的：' -ForegroundColor Cyan
Write-Host '  1. 完全關掉 Claude 桌面版（不是關視窗，要從工作列圖示結束），再重新打開。'
Write-Host '  2. 對 Claude 說：「請呼叫 get_data_status，告訴我資料狀態」。'
Write-Host '  3. 再問一句：「登革熱要採什麼檢體、怎麼送驗？」'
Write-Host ''
Write-Host "暫存的下載檔可以刪掉：$downloadDir" -ForegroundColor Gray
