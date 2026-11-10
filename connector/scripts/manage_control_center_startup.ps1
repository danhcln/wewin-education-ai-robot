param([ValidateSet('Plan','Enable','Disable')][string]$Action='Plan')
$ErrorActionPreference='Stop'
$taskName='WeWIN_ControlCenter_AutoStart'
$description='WeWIN Control Center optional Auto Start (Phase7D.1B.2C)'
$previousDescription='WeWIN Control Center optional Auto Start (Phase7C.3)'
$root=Split-Path -Parent $PSScriptRoot
$configPath=Join-Path $root '.maintenance/control-center/startup-config.json'
$config=Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$pythonw=Join-Path (Split-Path -Parent $config.python) 'pythonw.exe'
if(-not (Test-Path -LiteralPath $pythonw -PathType Leaf)){throw 'Pinned pythonw.exe is unavailable.'}
$launcher=Join-Path $PSScriptRoot 'start_control_center.py'
$user=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$existing=Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if($existing -and $existing.Description -notin @($description,$previousDescription)){
    throw 'Existing task is not managed by this project; refusing overwrite.'
}
if($existing -and $existing.Principal.UserId -notin @($user,[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value)){
    throw 'Existing task has a different principal; refusing overwrite.'
}
if($Action -eq 'Plan'){
    [pscustomobject]@{Task=$taskName;Python=$config.python;TaskExecutable=$pythonw;Launcher=$launcher;
        Config=$configPath;Trigger='Current user logon + 15 seconds';CredentialsStored=$false;WakeComputer=$false;
        ExistingTask=[bool]$existing;EnabledNow=([bool]$existing -and $existing.Settings.Enabled);ChangesWebsiteSync=$false}
    return
}
if($Action -eq 'Disable'){
    if($existing){Disable-ScheduledTask -TaskName $taskName | Out-Null}
    Write-Output 'Control Center Auto Start disabled; running processes and website scheduler unchanged.'
    return
}
# A task must not be enabled to route around a failed/blocked manual start.
$probe=& $config.python -B $launcher --config $configPath --check
if($LASTEXITCODE -ne 0){throw 'Manual startup validation is required before registration.'}
$ready=$probe | ConvertFrom-Json
if($ready.Backend -ne 'HEALTHY' -or $ready.BridgeCount -ne 1 -or $ready.Bridge -ne 'CONNECTED' -or -not $ready.ConnectorDynamicToolLoaded){
    throw 'Manual health/singleton/new-tool validation must pass first; no task registered.'
}
$principal=New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$trigger=New-ScheduledTaskTrigger -AtLogOn -User $user
$trigger.Delay='PT15S'
$settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -DisallowHardTerminate
$taskAction=New-ScheduledTaskAction -Execute $pythonw -Argument ('-B "'+$launcher+'" --config "'+$configPath+'"') -WorkingDirectory $root
Register-ScheduledTask -TaskName $taskName -Description $description -Action $taskAction -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Write-Output 'Control Center Auto Start configured for current-user login; no password stored; website scheduler unchanged.'
