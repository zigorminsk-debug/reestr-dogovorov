param(
    [Parameter(Mandatory = $true)][string]$InstallDir,
    [int]$Port = 8080,
    [string]$BootstrapFile = ""
)

$ErrorActionPreference = "Stop"
$taskName = "ReestrDogovorov Server"
$firewallName = "ReestrDogovorov HTTP"
$dataDir = Join-Path $env:ProgramData "ReestrDogovorov"
$configPath = Join-Path $dataDir "server.json"
$authPath = Join-Path $dataDir "auth.json"
if (-not $BootstrapFile) { $BootstrapFile = Join-Path $dataDir "bootstrap-admin.json" }
$executable = Join-Path $InstallDir "ReestrDogovorov.exe"

if (-not (Test-Path $executable)) { throw "Application executable not found: $executable" }
foreach ($directory in @("data", "backups", "exports", "logs")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $dataDir $directory) | Out-Null
}

if (Test-Path $authPath) {
    # Remove an obsolete bootstrap secret without replacing the existing administrator.
    Remove-Item $BootstrapFile -Force -ErrorAction SilentlyContinue
} else {
    if (-not (Test-Path $BootstrapFile)) { throw "Administrator credentials were not supplied by the installer." }
    $arguments = @("--init-admin", "--credentials-file", "`"$BootstrapFile`"")
    $initialization = Start-Process -FilePath $executable -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
    if ($initialization.ExitCode -ne 0 -or -not (Test-Path $authPath)) {
        throw "Administrator initialization failed. The server will not be started."
    }
}
if (Test-Path $BootstrapFile) { Remove-Item $BootstrapFile -Force }
& icacls.exe $authPath /inheritance:r /grant:r "*S-1-5-18:F" "*S-1-5-32-544:F" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not protect auth.json with a SYSTEM/Administrators-only ACL." }

if (Test-Path $configPath) {
    try {
        $saved = Get-Content $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($saved.port) { $Port = [int]$saved.port }
    } catch {
        Write-Warning "Server config could not be read; port $Port will be used."
    }
} else {
    $config = @{ host = "0.0.0.0"; port = $Port } | ConvertTo-Json
    [System.IO.File]::WriteAllText($configPath, $config, [System.Text.UTF8Encoding]::new($false))
}

Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue | Stop-ScheduledTask -ErrorAction SilentlyContinue
Get-Process -Name "ReestrDogovorov" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction -Execute $executable -Argument "--serve" -WorkingDirectory $InstallDir
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "Shared contract registry HTTP server" -Force | Out-Null

if (-not (Get-NetFirewallRule -Name $firewallName -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -Name $firewallName -DisplayName "Reestr Dogovorov HTTP $Port" -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -Profile Domain,Private | Out-Null
} else {
    Set-NetFirewallRule -Name $firewallName -DisplayName "Reestr Dogovorov HTTP $Port" -Direction Inbound -Action Allow -Profile Domain,Private
    Get-NetFirewallRule -Name $firewallName | Get-NetFirewallPortFilter | Set-NetFirewallPortFilter -Protocol TCP -LocalPort $Port
}

$shortcut = Join-Path $InstallDir "Клиентский ярлык.url"
$url = "http://$($env:COMPUTERNAME):$Port/"
[System.IO.File]::WriteAllText($shortcut, "[InternetShortcut]`r`nURL=$url`r`n", [System.Text.Encoding]::ASCII)
Start-ScheduledTask -TaskName $taskName
Write-Output "Reestr Dogovorov is configured at $url. Data: $dataDir"
