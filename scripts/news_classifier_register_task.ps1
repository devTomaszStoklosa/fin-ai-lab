# P4-S2: registers a daily Windows Scheduled Task that runs
# news_classifier_run_labeling.ps1. Run this once, manually, from a
# PowerShell window (it changes system state - not something to run
# unattended). 6:30, half an hour before market-pulse's 7:00 brief
# (scripts/market_pulse_register_task.ps1) - no dependency between the two,
# just spread out so they don't contend for the same machine at once.
# -StartWhenAvailable makes a missed run (PC off) catch up on next
# boot/login.
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path $repoRoot "scripts\news_classifier_run_labeling.ps1"
$taskName = "fin-ai-lab-news-classifier-label"

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
$trigger = New-ScheduledTaskTrigger -Daily -At 6:30AM
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Description "fin-ai-lab: codzienne etykietowanie teachera P4 (Groq)" -Force

Write-Host "Zarejestrowano zadanie '$taskName' - uruchomienie codziennie o 6:30."
Write-Host "Zadanie dziala w kontekscie zalogowanego uzytkownika - sprawdz w Harmonogramie zadan, ze 'uv' jest w PATH tego konta."
