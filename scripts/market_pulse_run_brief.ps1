# P3-S7: run by the Windows Scheduled Task registered via
# market_pulse_register_task.ps1. Not meant to be run manually except to
# test the wiring - use `uv run fin-ai-lab market-pulse brief` directly for
# everyday interactive use.
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$today = Get-Date -Format "yyyy-MM-dd"
$outputDir = Join-Path $repoRoot "data\briefs"
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
$outputPath = Join-Path $outputDir "$today.md"
$logPath = Join-Path $outputDir "$today.log"

try {
    & uv run fin-ai-lab market-pulse brief --output $outputPath *> $logPath
} catch {
    Add-Content -Path $logPath -Value "FAILED: $_"
    exit 1
}
