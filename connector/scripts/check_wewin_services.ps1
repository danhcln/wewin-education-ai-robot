$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$configPath=Join-Path $root '.maintenance/control-center/startup-config.json'
$config=Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
& $config.python -B (Join-Path $PSScriptRoot 'start_control_center.py') --config $configPath --check
exit $LASTEXITCODE
