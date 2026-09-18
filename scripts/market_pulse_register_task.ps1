# P3-S7: registers a daily Windows Scheduled Task that runs
# market_pulse_run_brief.ps1. Run this once, manually, from a PowerShell
# window (it changes system state - not something to run unattended).
# -StartWhenAvailable makes a missed 7:00 run (PC off) catch up on next
# boot/login, per 01-story.md's primary metric (brief ready before 8:00 on
# >=95% of business days).
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path $repoRoot "scripts\market_pulse_run_brief.ps1"
$taskName = "fin-ai-lab-market-pulse-brief"

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
$trigger = New-ScheduledTaskTrigger -Daily -At 7:00AM
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Description "fin-ai-lab: codzienny market-pulse brief (P3-S7)" -Force

Write-Host "Zarejestrowano zadanie '$taskName' - uruchomienie codziennie o 7:00."
Write-Host "Zadanie dziala w kontekscie zalogowanego uzytkownika - sprawdz w Harmonogramie zadan, ze 'uv' jest w PATH tego konta."
