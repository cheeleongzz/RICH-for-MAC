# RICH daily scheduler install. Run from elevated PowerShell:
#   powershell -ExecutionPolicy Bypass -File scripts\install_scheduler.ps1
#
# Creates two daily tasks in Windows Task Scheduler at MYT local time:
#   RICH_Daily_0800_MYT  (primary, 08:00)
#   RICH_Daily_1200_MYT  (fallback, 12:00)
#
# Tasks run only while user is logged in. Both invoke run_daily.py.

$ErrorActionPreference = "Stop"

$projectDir = "C:\Users\chaim\Desktop\RICH"
$pyExe      = "C:\Windows\py.exe"
$script     = "run_daily.py"

$action = New-ScheduledTaskAction `
    -Execute $pyExe `
    -Argument $script `
    -WorkingDirectory $projectDir

$trigger0800 = New-ScheduledTaskTrigger -Daily -At 8:00am
$trigger1200 = New-ScheduledTaskTrigger -Daily -At 12:00pm

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName "RICH_Daily_0800_MYT" `
    -Action $action -Trigger $trigger0800 -Settings $settings `
    -Description "RICH stock recommendation - primary daily run (08:00 MYT)" `
    -Force

Register-ScheduledTask `
    -TaskName "RICH_Daily_1200_MYT" `
    -Action $action -Trigger $trigger1200 -Settings $settings `
    -Description "RICH stock recommendation - fallback daily run (12:00 MYT)" `
    -Force

Write-Host ""
Write-Host "Installed:" -ForegroundColor Green
Get-ScheduledTask -TaskName "RICH_Daily_*" | Format-Table TaskName, State, @{Label='NextRun';Expression={(Get-ScheduledTaskInfo $_).NextRunTime}}
