# RICH daily scheduler uninstall. Run from elevated PowerShell:
#   powershell -ExecutionPolicy Bypass -File scripts\uninstall_scheduler.ps1

$ErrorActionPreference = "Stop"

foreach ($name in @("RICH_Daily_0800_MYT", "RICH_Daily_1200_MYT")) {
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($task) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
        Write-Host "Removed: $name" -ForegroundColor Yellow
    } else {
        Write-Host "Not found: $name" -ForegroundColor Gray
    }
}
