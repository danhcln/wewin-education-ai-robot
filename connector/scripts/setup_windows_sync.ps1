<# FIX 03A: same task identity, explicit 08:00/20:00; disabled until approved. #>
[CmdletBinding(SupportsShouldProcess=$true)]
param([switch]$Enable,[switch]$Uninstall)
$ErrorActionPreference = 'Stop'
$TaskName = 'WeWIN_Website_AutoSync'
$ProjectDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$PythonPath = $null
foreach ($candidate in @((Join-Path $ProjectDir '.venv/Scripts/python.exe'),(Join-Path $ProjectDir 'venv/Scripts/python.exe'))) {
    if (Test-Path -LiteralPath $candidate) { $PythonPath = $candidate; break }
}
if (-not $PythonPath) { $PythonPath = (Get-Command python.exe -ErrorAction Stop).Source }
if ($Uninstall) {
    if ($PSCmdlet.ShouldProcess($TaskName,'Unregister scheduled task')) { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false }
    return
}
$Runner = Join-Path $ProjectDir 'run_sync.py'
$Action = New-ScheduledTaskAction -Execute $PythonPath -Argument ('-B "' + $Runner + '" --trigger task_scheduler --execute') -WorkingDirectory $ProjectDir
$Triggers = @((New-ScheduledTaskTrigger -Daily -At '08:00'),(New-ScheduledTaskTrigger -Daily -At '20:00'))
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
$Settings.WakeToRun = $false
$Settings.Enabled = [bool]$Enable
$Principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
if ($Enable) {
    Push-Location -LiteralPath $ProjectDir
    try {
        & $PythonPath -B -c "from src.config import settings; raise SystemExit(0 if settings.SYNC_SCHEDULER_OWNER == 'windows' and settings.SYNC_SCHEDULE_ARMED and not settings.AUTO_SYNC_ENABLED else 1)"
        if ($LASTEXITCODE -ne 0) { throw 'Enable requires Windows owner, explicit armed flag, and FastAPI scheduler disabled.' }
    } finally { Pop-Location }
}
if ($PSCmdlet.ShouldProcess($TaskName,'Register/update one task; no crawler launched')) {
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Triggers -Settings $Settings -Principal $Principal -Description 'WeWIN incremental sync; 08:00/20:00; explicit approval gate; no stored password or wake-up.' -Force | Out-Null
}
[pscustomobject]@{TaskName=$TaskName;Python=$PythonPath;Times=@('08:00','20:00');Enabled=[bool]$Enable;StartWhenAvailable=$true;WakeToRun=$false;PasswordStored=$false;Owner='windows'} | ConvertTo-Json
