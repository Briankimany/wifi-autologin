#Requires -Version 5.1
<#
.SYNOPSIS
    Install the captive-portal watchdog on Windows.

.DESCRIPTION
    Creates a .venv, installs Playwright (+ Chromium or uses an installed
    browser channel), creates the config templates, runs a smoke test, and
    optionally registers a Scheduled Task that runs the watchdog every few
    minutes.

.PARAMETER Channel
    Use an installed browser instead of downloading Chromium.
    Values: "chrome", "msedge". The choice is saved as WIFI_CHANNEL.

.PARAMETER RegisterTask
    Register a Scheduled Task that runs the watchdog every few minutes.

.PARAMETER IntervalMinutes
    How often the Scheduled Task runs (default 3).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install_windows.ps1 -Channel chrome

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install_windows.ps1 -Channel chrome -RegisterTask
#>
param(
    [string]$Channel = "",
    [switch]$RegisterTask,
    [int]$IntervalMinutes = 3,
    [string]$TaskName = "WifiWatchdog"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "[1/5] Locating Python..."
$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) {
    $pyExe = "py"; $pyArgs = @("-3")
} else {
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) { throw "Python 3 not found. Install it from https://www.python.org/downloads/" }
    $pyExe = "python"; $pyArgs = @()
}

Write-Host "[2/5] Creating virtual environment (.venv)..."
if (-not (Test-Path "$Root\.venv\Scripts\python.exe")) {
    & $pyExe @pyArgs -m venv "$Root\.venv"
}
$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { throw "venv was not created" }

Write-Host "[3/5] Installing dependencies..."
& $venvPy -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
& $venvPy -m pip install -r "$Root\requirements.txt"
if ($LASTEXITCODE -ne 0) { throw "dependency install failed" }

if ($Channel) {
    Write-Host "[4/5] Using installed browser channel: $Channel (no download)"
    $env:WIFI_CHANNEL = $Channel
    [Environment]::SetEnvironmentVariable("WIFI_CHANNEL", $Channel, "User")
} else {
    Write-Host "[4/5] Downloading Chromium..."
    $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $Root "ms-playwright"
    & $venvPy -m playwright install chromium
    if ($LASTEXITCODE -ne 0) {
        throw "Chromium download failed (network/CDN). Re-run this script, or use -Channel chrome to use an already-installed Google Chrome, or -Channel msedge for Edge."
    }
}

Write-Host "[5/5] Creating config files and running smoke test..."
if (-not (Test-Path "$Root\watchdog\code.txt")) {
    Copy-Item "$Root\watchdog\code.txt.example" "$Root\watchdog\code.txt"
    Write-Host "      created watchdog\code.txt - put your voucher code in it"
}
if (-not (Test-Path "$Root\watchdog\telegram.conf")) {
    Copy-Item "$Root\watchdog\telegram.conf.example" "$Root\watchdog\telegram.conf"
    Write-Host "      created watchdog\telegram.conf - optional Telegram alerts"
}
& $venvPy "$Root\smoke_test.py"
if ($LASTEXITCODE -ne 0) { throw "Smoke test failed. See the error above." }

if ($RegisterTask) {
    Write-Host "Registering Scheduled Task '$TaskName' (every $IntervalMinutes min)..."
    $taskPy = $venvPy
    $pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"
    if (Test-Path $pythonw) { $taskPy = $pythonw }

    $action = New-ScheduledTaskAction -Execute $taskPy `
        -Argument "`"$Root\watchdog\watchdog.py`" --run" `
        -WorkingDirectory $Root
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
        -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
        -RepetitionDuration (New-TimeSpan -Days 3650)
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
        -MultipleInstances IgnoreNew -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
        -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal -Force | Out-Null
    Write-Host "Registered. Check it with: Get-ScheduledTask -TaskName '$TaskName'"
    Write-Host "Remove it with:        Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
}

Write-Host ""
Write-Host "INSTALL_OK"
Write-Host "Manual login:  .\.venv\Scripts\python.exe wifi_login.py --code YOUR_CODE"
Write-Host "Watchdog once: .\.venv\Scripts\python.exe watchdog\watchdog.py --run"
