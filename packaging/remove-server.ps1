$ErrorActionPreference = "SilentlyContinue"
$taskName = "ReestrDogovorov Server"
Get-ScheduledTask -TaskName $taskName | Stop-ScheduledTask
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
Get-Process -Name "ReestrDogovorov" | Stop-Process -Force
Remove-NetFirewallRule -Name "ReestrDogovorov HTTP"
# Deliberately do not remove %ProgramData%\ReestrDogovorov:
# the shared database, configuration, logs and backups must survive updates/removal.
