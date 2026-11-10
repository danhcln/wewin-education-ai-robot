param([switch]$Plan)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$configPath=Join-Path $root '.maintenance/control-center/startup-config.json'
$config=Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$launcher=Join-Path $PSScriptRoot 'start_control_center.py'
if($Plan){ & $config.python -B $launcher --config $configPath --dry-run }
else { & $config.python -B $launcher --config $configPath }
exit $LASTEXITCODE
