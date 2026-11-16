# setup-v7-server.ps1
# Jianan Agent v7 - one-shot deployment on a FRESH Windows Server instance.
# Target: C:\jianan  (deploy/backup_kb.ps1 hardcodes this path)
# Prerequisites (do these BEFORE running):
#   1) Python 3.13 installed and on PATH  -> python --version
#   2) VC++ 2019 x64 runtime installed    -> onnxruntime DLL dependency
#   3) Uploaded to C:\Users\Administrator\ :
#        jianan-app-v7-20261115.tar.gz
#        env-v7.txt        (copy of local .env, contains API key)
#   4) Run as Administrator in PowerShell.
# Usage:
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File setup-v7-server.ps1
#
# ASCII-only on purpose: Windows PowerShell 5.1 reads BOM-less UTF-8 as ANSI.

param(
    [string]$UploadDir = "C:\Users\Administrator",
    [string]$PkgName   = "jianan-app-v7-20261115.tar.gz",
    [string]$EnvName   = "env-v7.txt",
    [string]$AppDir    = "C:\jianan",
    [int]$Port         = 9000
)

$ErrorActionPreference = "Stop"
function Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "  [WARN] $msg" -ForegroundColor Yellow }
function Die($msg)  { Write-Host "  [FAIL] $msg" -ForegroundColor Red; throw $msg }

$pkg = Join-Path $UploadDir $PkgName
$envfile = Join-Path $UploadDir $EnvName

Step "0. Precheck"
try { $pyver = & python --version 2>&1 } catch { Die "python not found. Install Python 3.13 first." }
Ok "python: $pyver"
if (-not (Test-Path $pkg))    { Die "Package not found: $pkg" }
if (-not (Test-Path $envfile)){ Die "Env file not found: $envfile (must be uploaded separately)" }
Ok "package and env file present"
# Port exclusion check (Windows may reserve 9000)
$excl = & netsh interface ipv4 show excludedportrange protocol=tcp 2>&1
if ($excl -match "\b$Port\b") { Warn "Port $Port may be in a system excluded range. If bind fails, use -Port 9100 and update firewall/security group." }

Step "1. Backup existing dir (if any) and create C:\jianan"
if (Test-Path $AppDir) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $bak = "C:\jianan_backup_$stamp"
    Move-Item $AppDir $bak -Force
    Warn "Existing $AppDir moved to $bak"
}
New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
Ok "created $AppDir"

Step "2. Extract package (--strip-components=1 is REQUIRED)"
& tar.exe -xzf $pkg -C $AppDir --strip-components=1
if ($LASTEXITCODE -ne 0) { Die "tar extract failed (exit $LASTEXITCODE)" }
$must = @("app\main.py","app\feedback.py","kb\kb.sqlite",
          "kb\docs_meta.json","kb\vec_index_bge-small-zh-v1.5.npz",
          "models\bge-small-zh-v1.5\model_int8.onnx","requirements.lock")
foreach ($m in $must) {
    if (-not (Test-Path (Join-Path $AppDir $m))) { Die "Missing after extract: $m" }
}
Ok "all key files present"

Step "3. Place .env (never inside the package / public repo)"
Copy-Item $envfile (Join-Path $AppDir ".env") -Force
$envtext = Get-Content (Join-Path $AppDir ".env") -Raw
if ($envtext -notmatch "LLM_API_KEY\s*=\s*\S+") { Warn "LLM_API_KEY looks empty; llmConfigured will be false" }
Ok ".env placed"

Step "4. venv + locked dependencies"
& python -m venv (Join-Path $AppDir ".venv")
if ($LASTEXITCODE -ne 0) { Die "venv creation failed" }
$py = Join-Path $AppDir ".venv\Scripts\python.exe"
& $py -m pip install --disable-pip-version-check -r (Join-Path $AppDir "requirements.lock")
if ($LASTEXITCODE -ne 0) { Die "pip install failed; check VC++ runtime and network" }
Ok "dependencies installed"

Step "5. Start script (--host 0.0.0.0 ; DO NOT use start.bat, it binds 127.0.0.1)"
$bat = Join-Path $AppDir "start-server.bat"
$lines = @(
    "@echo off",
    "cd /d $AppDir",
    "`"$py`" -m uvicorn app.main:app --host 0.0.0.0 --port $Port >> `"$AppDir\server.log`" 2>&1"
)
Set-Content -Path $bat -Value $lines -Encoding ASCII
Ok "wrote $bat"

Step "6. Firewall rule"
& netsh advfirewall firewall add rule name="jianan-app-$Port" dir=in action=allow protocol=TCP localport=$Port 2>&1 | Out-Null
Ok "firewall rule jianan-app-$Port ensured"

Step "7. Scheduled task (auto start on boot, SYSTEM)"
& schtasks /Create /TN "jianan-app" /TR "`"$bat`"" /SC ONSTART /RU SYSTEM /RL HIGHEST /F 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Warn "schtasks create failed; start manually with $bat" } else { Ok "task jianan-app registered" }

Step "8. Start service and health check"
& schtasks /Run /TN "jianan-app" 2>&1 | Out-Null
Start-Sleep -Seconds 3
$healthy = $false
$body = $null
for ($i = 0; $i -lt 30; $i++) {
    try {
        $body = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 3
        $healthy = $true
        break
    } catch { Start-Sleep -Seconds 2 }
}
if (-not $healthy) {
    Warn "health not ready. Check $AppDir\server.log ; try: $bat"
    Die "service did not become healthy within 60s"
}
Ok ("health: " + ($body | ConvertTo-Json -Compress -Depth 5))

Step "9. Optional ops tasks (backup + log rotation)"
try {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $AppDir "deploy\install_backup_task.ps1") -AlsoLogs 2>&1 | Out-Null
    Ok "ops tasks registered"
} catch { Warn "ops task registration skipped: $($_.Exception.Message)" }

Step "DONE - manual steps left"
Write-Host "  1) Alibaba Cloud ECS console: security group INBOUND allow TCP $Port (source 0.0.0.0/0)."
Write-Host "  2) Public check from your PC: http://8.137.188.115:$Port/api/health"
Write-Host "  3) Re-run 62-question eval from the DEV machine (same-day batch):"
Write-Host "     .venv\Scripts\python.exe tools\run_eval.py --base http://8.137.188.115:$Port --tag v7-online --sleep 3"
Write-Host "  4) Keep the old instance as rollback until eval passes."
