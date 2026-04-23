@echo off
:: ============================================================================
::  OH - Operational Hub — Installer
::  Always downloads the latest version. Send this file to clients.
:: ============================================================================
title OH - Operational Hub — Installer
echo.
echo   ============================================
echo     OH - Operational Hub — Installer
echo   ============================================
echo.

set "DEFAULT_DIR=C:\OH"
set /p "INSTALL_DIR=  Install location [%DEFAULT_DIR%]: "
if "%INSTALL_DIR%"=="" set "INSTALL_DIR=%DEFAULT_DIR%"
if "%INSTALL_DIR:~-1%"=="\" set "INSTALL_DIR=%INSTALL_DIR:~0,-1%"

echo.

:: Extract the embedded PowerShell script and run it
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$lines = Get-Content -Path '%~f0' -Raw;" ^
    "$marker = '# --- EMBEDDED PS1 START ---';" ^
    "$idx = $lines.IndexOf($marker);" ^
    "if ($idx -lt 0) { Write-Host 'ERROR: Embedded script not found.' -ForegroundColor Red; exit 1 };" ^
    "$script = $lines.Substring($idx + $marker.Length);" ^
    "$sb = [scriptblock]::Create($script);" ^
    "& $sb -InstallDir '%INSTALL_DIR%'"

if errorlevel 1 (
    echo.
    echo   Installation failed. Check errors above.
    echo.
    pause
    exit /b 1
)

echo.
set /p "LAUNCH=  Launch OH now? (y/n): "
if /i "%LAUNCH%"=="y" (
    echo.
    echo   Starting OH...
    start "" "%INSTALL_DIR%\OH.exe"
)

echo.
pause
exit /b 0

# --- EMBEDDED PS1 START ---
param(
    [string]$InstallDir = "C:\OH"
)

$ErrorActionPreference = "Stop"
$UpdateUrl = "https://raw.githubusercontent.com/onimator-rgb/oh-releases/main/update.json"

$StartBatB64 = "QGVjaG8gb2ZmDQpzZXRsb2NhbCBlbmFibGVkZWxheWVkZXhwYW5zaW9uDQoNCnNldCAiT0hfRElSPSV+ZHAwIg0Kc2V0ICJPSF9FWEU9JU9IX0RJUiVPSC5leGUiDQpzZXQgIlVQREFURV9VUkw9aHR0cHM6Ly9yYXcuZ2l0aHVidXNlcmNvbnRlbnQuY29tL29uaW1hdG9yLXJnYi9vaC1yZWxlYXNlcy9tYWluL3VwZGF0ZS5qc29uIg0KDQp0aXRsZSBPSCAtIE9wZXJhdGlvbmFsIEh1Yg0KZWNoby4NCmVjaG8gICBPSCAtIE9wZXJhdGlvbmFsIEh1Yg0KZWNobyAgIC0tLS0tLS0tLS0tLS0tLS0tLS0tLQ0KZWNoby4NCg0KOjog4pSA4pSAIENMRUFOVVA6IHJlbW92ZSBvYnNvbGV0ZSBmaWxlcyBmcm9tIG9sZGVyIHZlcnNpb25zIOKUgOKUgA0KZGVsICIlT0hfRElSJU9IX1VzZXJfR3VpZGUucGRmIiAyPk5VTA0KZGVsICIlT0hfRElSJU9IX1VzZXJfR3VpZGVfRU4ucGRmIiAyPk5VTA0KZGVsICIlT0hfRElSJU9IX1VzZXJfR3VpZGVfUEwucGRmIiAyPk5VTA0KZGVsICIlT0hfRElSJW9oX3VwZGF0ZXIuYmF0IiAyPk5VTA0KZGVsICIlT0hfRElSJU9IX3VwZGF0ZS5leGUiIDI+TlVMDQoNCjo6IOKUgOKUgCBVUERBVEUgQ0hFQ0sg4pSA4pSADQpwb3dlcnNoZWxsIC1Ob1Byb2ZpbGUgLUV4ZWN1dGlvblBvbGljeSBCeXBhc3MgLUNvbW1hbmQgXg0KICAiJEVycm9yQWN0aW9uUHJlZmVyZW5jZT0nU2lsZW50bHlDb250aW51ZSc7ICIgXg0KICAidHJ5IHsgIiBeDQogICIgICRqc29uID0gKEludm9rZS1XZWJSZXF1ZXN0IC1VcmkgJyVVUERBVEVfVVJMJScgLVRpbWVvdXRTZWMgMTAgLVVzZUJhc2ljUGFyc2luZykuQ29udGVudCB8IENvbnZlcnRGcm9tLUpzb247ICIgXg0KICAiICAkcmVtb3RlVmVyID0gJGpzb24udmVyc2lvbjsgIiBeDQogICIgICRkb3dubG9hZFVybCA9ICRqc29uLmRvd25sb2FkX3VybDsgIiBeDQogICIgICRleHBlY3RlZEhhc2ggPSAkanNvbi5zaGEyNTY7ICIgXg0KICAiICBpZiAoLW5vdCAkcmVtb3RlVmVyIC1vciAtbm90ICRkb3dubG9hZFVybCkgeyBleGl0IDAgfTsgIiBeDQogICIgICRjdXJyZW50VmVyID0gJzAuMC4wJzsgIiBeDQogICIgICR2ZXJGaWxlID0gSm9pbi1QYXRoICclT0hfRElSJScgJy5vaF92ZXJzaW9uJzsgIiBeDQogICIgIGlmIChUZXN0LVBhdGggJHZlckZpbGUpIHsgJGN1cnJlbnRWZXIgPSAoR2V0LUNvbnRlbnQgJHZlckZpbGUgLVJhdykuVHJpbSgpIH07ICIgXg0KICAiICAkcnYgPSAkcmVtb3RlVmVyLlNwbGl0KCcuJykgfCBGb3JFYWNoLU9iamVjdCB7IFtpbnRdJF8gfTsgIiBeDQogICIgICRjdiA9ICRjdXJyZW50VmVyLlNwbGl0KCcuJykgfCBGb3JFYWNoLU9iamVjdCB7IFtpbnRdJF8gfTsgIiBeDQogICIgICRuZWVkc1VwZGF0ZSA9ICRmYWxzZTsgIiBeDQogICIgIGZvciAoJGk9MDsgJGkgLWx0IFtNYXRoXTo6TWF4KCRydi5Db3VudCwkY3YuQ291bnQpOyAkaSsrKSB7ICIgXg0KICAiICAgICRyID0gaWYgKCRpIC1sdCAkcnYuQ291bnQpIHsgJHJ2WyRpXSB9IGVsc2UgeyAwIH07ICIgXg0KICAiICAgICRjID0gaWYgKCRpIC1sdCAkY3YuQ291bnQpIHsgJGN2WyRpXSB9IGVsc2UgeyAwIH07ICIgXg0KICAiICAgIGlmICgkciAtZ3QgJGMpIHsgJG5lZWRzVXBkYXRlID0gJHRydWU7IGJyZWFrIH07ICIgXg0KICAiICAgIGlmICgkciAtbHQgJGMpIHsgYnJlYWsgfSAiIF4NCiAgIiAgfTsgIiBeDQogICIgIGlmICgkbmVlZHNVcGRhdGUpIHsgIiBeDQogICIgICAgV3JpdGUtSG9zdCAnICBVcGRhdGU6JyAkY3VycmVudFZlciAnLT4nICRyZW1vdGVWZXI7ICIgXg0KICAiICAgIFdyaXRlLUhvc3QgJyAgRG93bmxvYWRpbmcuLi4nOyAiIF4NCiAgIiAgICAkdG1wID0gSm9pbi1QYXRoICclT0hfRElSJScgJ09IX3VwZGF0ZS5leGUnOyAiIF4NCiAgIiAgICBJbnZva2UtV2ViUmVxdWVzdCAtVXJpICRkb3dubG9hZFVybCAtT3V0RmlsZSAkdG1wIC1UaW1lb3V0U2VjIDMwMCAtVXNlQmFzaWNQYXJzaW5nOyAiIF4NCiAgIiAgICBpZiAoVGVzdC1QYXRoICR0bXApIHsgIiBeDQogICIgICAgICAkb2sgPSAkdHJ1ZTsgIiBeDQogICIgICAgICBpZiAoJGV4cGVjdGVkSGFzaCkgeyAiIF4NCiAgIiAgICAgICAgJGZpbGVIYXNoID0gKEdldC1GaWxlSGFzaCAkdG1wIC1BbGdvcml0aG0gU0hBMjU2KS5IYXNoLlRvTG93ZXIoKTsgIiBeDQogICIgICAgICAgIGlmICgkZmlsZUhhc2ggLW5lICRleHBlY3RlZEhhc2gpIHsgIiBeDQogICIgICAgICAgICAgV3JpdGUtSG9zdCAnICBIYXNoIG1pc21hdGNoIC0gdXBkYXRlIHJlamVjdGVkLic7ICIgXg0KICAiICAgICAgICAgIFJlbW92ZS1JdGVtICR0bXAgLUZvcmNlOyAiIF4NCiAgIiAgICAgICAgICAkb2sgPSAkZmFsc2U7ICIgXg0KICAiICAgICAgICB9ICIgXg0KICAiICAgICAgfTsgIiBeDQogICIgICAgICBpZiAoJG9rKSB7ICIgXg0KICAiICAgICAgICBDb3B5LUl0ZW0gJHRtcCAnJU9IX0VYRSUnIC1Gb3JjZTsgIiBeDQogICIgICAgICAgIFJlbW92ZS1JdGVtICR0bXAgLUZvcmNlOyAiIF4NCiAgIiAgICAgICAgU2V0LUNvbnRlbnQgJHZlckZpbGUgJHJlbW90ZVZlcjsgIiBeDQogICIgICAgICAgIFdyaXRlLUhvc3QgJyAgVXBkYXRlZCB0bycgJHJlbW90ZVZlcjsgIiBeDQogICIgICAgICB9ICIgXg0KICAiICAgIH0gIiBeDQogICIgIH0gZWxzZSB7ICIgXg0KICAiICAgIFdyaXRlLUhvc3QgJyAgVmVyc2lvbjonICRjdXJyZW50VmVyICcodXAgdG8gZGF0ZSknICIgXg0KICAiICB9ICIgXg0KICAifSBjYXRjaCB7ICIgXg0KICAiICBXcml0ZS1Ib3N0ICcgIE9mZmxpbmUgLSBza2lwcGluZyB1cGRhdGUgY2hlY2suJyAiIF4NCiAgIn0iIDI+TlVMDQoNCmVjaG8uDQplY2hvICAgU3RhcnRpbmcgT0guLi4NCmVjaG8uDQpzdGFydCAiIiAiJU9IX0VYRSUiDQo="

function Get-ReadmeContent($ver) {
    return @"
OH - Operational Hub v$ver
===========================

Operations dashboard for managing your Onimator bot campaigns.


GETTING STARTED
---------------
1. Double-click START.bat to launch OH
2. Set your Onimator bot folder path (top bar) and click Save
3. Click "Scan & Sync" to discover all devices and accounts
4. Click "Cockpit" for your daily operations overview

OH will guide you through setup on first launch.


UPDATES
-------
OH updates automatically every time you run START.bat.
You can also click "Check for Updates" inside the app.


DATA & PRIVACY
--------------
All data is stored locally on your machine:
- Database: %APPDATA%\OH\oh.db
- Logs: %APPDATA%\OH\logs\oh.log

No account data is sent to external servers.


SYSTEM REQUIREMENTS
-------------------
- Windows 10 or 11 (64-bit)
- No additional software needed


SUPPORT
-------
Contact your service provider for assistance.
"@
}

# ===================================================================
Write-Host "  [1/5] Checking latest version..." -ForegroundColor Cyan

try {
    $json = (Invoke-WebRequest -Uri $UpdateUrl -TimeoutSec 15 -UseBasicParsing).Content | ConvertFrom-Json
    $version     = $json.version
    $downloadUrl = $json.download_url
    $expectedHash = $json.sha256
    $changelog   = $json.changelog

    if (-not $version -or -not $downloadUrl) {
        Write-Host "  ERROR: Invalid update data from server." -ForegroundColor Red
        exit 1
    }
    Write-Host "         Latest version: v$version" -ForegroundColor Green
} catch {
    Write-Host "  ERROR: Cannot reach update server." -ForegroundColor Red
    Write-Host "  Check your internet connection and try again." -ForegroundColor Red
    exit 1
}

# ===================================================================
Write-Host "  [2/5] Creating folder..." -ForegroundColor Cyan

try {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    Write-Host "         $InstallDir" -ForegroundColor Green
} catch {
    Write-Host "  ERROR: Cannot create folder: $InstallDir" -ForegroundColor Red
    Write-Host "  Try running as Administrator or choose a different location." -ForegroundColor Red
    exit 1
}

# ===================================================================
Write-Host "  [3/5] Downloading OH.exe (~75 MB)..." -ForegroundColor Cyan

$exePath = Join-Path $InstallDir "OH.exe"
$tmpPath = Join-Path $InstallDir "OH_download.exe"

try {
    $wc = New-Object System.Net.WebClient
    $wc.DownloadFile($downloadUrl, $tmpPath)
    $wc.Dispose()
} catch {
    Write-Host "  ERROR: Download failed - $($_.Exception.Message)" -ForegroundColor Red
    Remove-Item $tmpPath -Force -ErrorAction SilentlyContinue
    exit 1
}

if ($expectedHash) {
    Write-Host "         Verifying integrity..." -ForegroundColor DarkGray
    $fileHash = (Get-FileHash $tmpPath -Algorithm SHA256).Hash.ToLower()
    if ($fileHash -ne $expectedHash) {
        Write-Host "  ERROR: File integrity check failed!" -ForegroundColor Red
        Remove-Item $tmpPath -Force -ErrorAction SilentlyContinue
        exit 1
    }
    Write-Host "         Integrity verified (SHA256)" -ForegroundColor Green
}

Copy-Item $tmpPath $exePath -Force
Remove-Item $tmpPath -Force -ErrorAction SilentlyContinue

$sizeMB = [math]::Round((Get-Item $exePath).Length / 1MB, 1)
Write-Host "         Downloaded: $sizeMB MB" -ForegroundColor Green

# ===================================================================
Write-Host "  [4/5] Creating launcher and config..." -ForegroundColor Cyan

Set-Content -Path (Join-Path $InstallDir ".oh_version") -Value $version -NoNewline

$startBatBytes = [System.Convert]::FromBase64String($StartBatB64)
$startPath = Join-Path $InstallDir "START.bat"
[System.IO.File]::WriteAllBytes($startPath, $startBatBytes)

$readmeContent = Get-ReadmeContent $version
[System.IO.File]::WriteAllText((Join-Path $InstallDir "README.txt"), $readmeContent, [System.Text.Encoding]::UTF8)

if ($changelog) {
    $clContent = "OH - Operational Hub`r`n===================================`r`n`r`nv$version ($(Get-Date -Format 'yyyy-MM-dd'))`r`n--------------------`r`n$($changelog -replace '\\n', "`r`n")`r`n"
    [System.IO.File]::WriteAllText((Join-Path $InstallDir "CHANGELOG.txt"), $clContent, [System.Text.Encoding]::UTF8)
}

Write-Host "         START.bat, README.txt created" -ForegroundColor Green

# ===================================================================
Write-Host "  [5/5] Creating shortcuts..." -ForegroundColor Cyan

try {
    $WshShell = New-Object -ComObject WScript.Shell

    $desktopPath = [System.Environment]::GetFolderPath("Desktop")
    $lnk = $WshShell.CreateShortcut((Join-Path $desktopPath "OH - Operational Hub.lnk"))
    $lnk.TargetPath = $exePath
    $lnk.WorkingDirectory = $InstallDir
    $lnk.IconLocation = "$exePath,0"
    $lnk.Description = "OH - Operational Hub"
    $lnk.Save()
    Write-Host "         Desktop shortcut created" -ForegroundColor Green

    $startMenuDir = Join-Path ([System.Environment]::GetFolderPath("Programs")) "OH"
    New-Item -ItemType Directory -Path $startMenuDir -Force | Out-Null
    $lnk2 = $WshShell.CreateShortcut((Join-Path $startMenuDir "OH - Operational Hub.lnk"))
    $lnk2.TargetPath = $startPath
    $lnk2.WorkingDirectory = $InstallDir
    $lnk2.IconLocation = "$exePath,0"
    $lnk2.Description = "OH - Operational Hub"
    $lnk2.Save()
    Write-Host "         Start Menu shortcut created" -ForegroundColor Green

    [System.Runtime.Interopservices.Marshal]::ReleaseComObject($WshShell) | Out-Null
} catch {
    Write-Host "         Shortcuts failed (non-critical)" -ForegroundColor Yellow
}

# ===================================================================
Write-Host ""
Write-Host "  ============================================" -ForegroundColor Green
Write-Host "    Installation complete!" -ForegroundColor Green
Write-Host "  ============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Version:  v$version"
Write-Host "  Location: $InstallDir"
Write-Host ""
Write-Host "  Use the desktop shortcut or OH.exe to launch."
Write-Host "  OH will auto-update on every launch."
Write-Host ""

exit 0
