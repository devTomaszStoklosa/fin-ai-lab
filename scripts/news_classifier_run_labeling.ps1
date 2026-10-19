# P4-S2: run by the Windows Scheduled Task registered via
# news_classifier_register_task.ps1. Not meant to be run manually except to
# test the wiring - use `uv run fin-ai-lab news-classifier label` directly
# for everyday interactive use.
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$today = Get-Date -Format "yyyy-MM-dd"
$outputDir = Join-Path $repoRoot "data\news_classifier_runs"
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
$logPath = Join-Path $outputDir "$today.log"

try {
    & uv run fin-ai-lab news-classifier label --max-calls 300 *> $logPath
} catch {
    Add-Content -Path $logPath -Value "FAILED: $_"
    exit 1
}
