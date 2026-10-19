# #233: registers a Windows Scheduled Task that runs start_webapp.ps1 at
# logon. Run this once, manually, from a PowerShell window (it changes
# system state - not something to run unattended).
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path $repoRoot "scripts\start_webapp.ps1"
$taskName = "fin-ai-lab-portfolio-webapp-autostart"

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -DontStopOnIdleEnd

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Description "fin-ai-lab: portfolio_webapp (backend+frontend) przy logowaniu" -Force

Write-Host "Zarejestrowano zadanie '$taskName' - uruchomienie przy kazdym logowaniu."
Write-Host "Zeby wylaczyc: Unregister-ScheduledTask -TaskName '$taskName' -Confirm:`$false"
