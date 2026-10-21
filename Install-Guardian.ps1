param([switch]$Remove)
$ErrorActionPreference='Stop'
$TeamConfig = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'team.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($env:AGENT_TEAM_PROJECT) { $ProjectRoot = $env:AGENT_TEAM_PROJECT }
elseif ($TeamConfig.project) { $ProjectRoot = Join-Path $PSScriptRoot $TeamConfig.project }
else { $ProjectRoot = Split-Path -Parent $PSScriptRoot }
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$TaskName='AfterDark-Team-Guardian'
if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    return
}
$Python=(Get-Command python -CommandType Application | Select-Object -First 1).Source
$Windowless=Join-Path (Split-Path -Parent $Python) 'pythonw.exe'
if (Test-Path -LiteralPath $Windowless) { $Python=$Windowless }
$Action=New-ScheduledTaskAction -Execute $Python -Argument ('"'+(Join-Path $PSScriptRoot 'guardian.py')+'"') -WorkingDirectory $ProjectRoot
$Identity=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$Principal=New-ScheduledTaskPrincipal -UserId $Identity -LogonType Interactive -RunLevel Limited
$LogonTrigger=New-ScheduledTaskTrigger -AtLogOn -User $Identity
$RecoveryTrigger=New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) -RepetitionInterval (New-TimeSpan -Minutes 1)
$Trigger=@($LogonTrigger,$RecoveryTrigger)
$Settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName $TaskName -Action $Action -Principal $Principal -Trigger $Trigger -Settings $Settings -Description 'Owner-authorized AfterDark team supervisor. STOP always prevents work.' -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host 'Independent guardian task installed and started for the current user.'
