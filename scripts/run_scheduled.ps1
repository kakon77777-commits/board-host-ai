# Wrapper invoked by Windows Task Scheduler so Board Host runs resident
# and independent of any interactive app being open. See
# docs/Board_Host_AI_v0.1.md §18 - local environments should use a
# scheduled single-shot run, not a permanent process.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = Join-Path $logDir "run_host.log"

# Keep the log bounded - this runs every scan_interval_minutes forever.
if (Test-Path $logFile) {
    $lines = Get-Content $logFile -Tail 5000
    Set-Content -Path $logFile -Value $lines -Encoding utf8
}

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $logFile -Value "[$timestamp] run start" -Encoding utf8

$python = Join-Path $root ".venv\Scripts\python.exe"
$script = Join-Path $root "run_host.py"
$env:PYTHONIOENCODING = "utf-8"
& $python $script 2>&1 | Out-File -FilePath $logFile -Append -Encoding utf8
$exitCode = $LASTEXITCODE

$timestamp2 = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $logFile -Value "[$timestamp2] run end, exit code $exitCode" -Encoding utf8
