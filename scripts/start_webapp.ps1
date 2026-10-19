# #233: starts portfolio_webapp (backend + frontend) in the background --
# meant to run unattended via the Task Scheduler entry from
# register_webapp_autostart_task.ps1, but safe to run manually too. For
# interactive foreground use with visible output, run
# `uv run fin-ai-lab web` / `npm run dev --prefix frontend` directly instead.
#
# Each service runs inside its own powershell.exe child process (same
# pattern as market_pulse_run_brief.ps1's `*>` redirect) rather than via
# Start-Process's own -RedirectStandardOutput -- that parameter forces
# UseShellExecute=$false, which skips the PATHEXT resolution `npm`/`uv`
# need to find their .cmd/.exe on PATH.
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $repoRoot "data\private\webapp-logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$backendLog = Join-Path $logDir "backend.log"
$frontendLog = Join-Path $logDir "frontend.log"

Start-Process -FilePath "powershell.exe" -WindowStyle Minimized -ArgumentList @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
    "Set-Location '$repoRoot'; uv run fin-ai-lab web *> '$backendLog'"
)

Start-Process -FilePath "powershell.exe" -WindowStyle Minimized -ArgumentList @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
    "Set-Location '$repoRoot'; npm run dev --prefix frontend *> '$frontendLog'"
)

Write-Host "portfolio_webapp: backend i frontend odpalone w tle. Logi w $logDir"

# `uv run fin-ai-lab web` (Python import + uvicorn bind) can take longer
# than a fixed guess, especially on this machine -- poll the real health
# endpoint instead of sleeping blind, so the browser tab that opens next
# actually has a backend to talk to.
$healthUrl = "http://127.0.0.1:8010/health"
$deadline = (Get-Date).AddSeconds(30)
$backendReady = $false
while ((Get-Date) -lt $deadline) {
    try {
        Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 2 | Out-Null
        $backendReady = $true
        break
    } catch {
        Start-Sleep -Milliseconds 500
    }
}
if (-not $backendReady) {
    Write-Host "Backend nie odpowiedzial w 30 s - sprawdz $backendLog"
}

Start-Process "http://localhost:5173"
