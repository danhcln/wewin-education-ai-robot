<#
.SYNOPSIS
    WeWIN Education AI Robot Platform - Windows Services Startup Script
.DESCRIPTION
    Launches WeWIN Centre (port 8000), WeWIN Education Portal (port 8001),
    and WeWIN AI Server (port 8010) as background services, with port check,
    PID tracking, and graceful logging.
#>

param(
    [string]$BindAddress = "127.0.0.1",
    [int]$PortCentre = 8000,
    [int]$PortPortal = 8001,
    [int]$PortAi = 8010,
    [switch]$NoBrowser = $false
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
Set-Location $RepoRoot

$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    $VenvPython = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $VenvPython) {
        Write-Host "[ERROR] Python executable not found. Run .\scripts\setup_windows.ps1 first." -ForegroundColor Red
        exit 1
    }
}

function Test-PortOccupied {
    param([int]$Port)
    $conn = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
    return [bool]$conn
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  Starting WeWIN Education AI Robot Platform               " -ForegroundColor Cyan
Write-Host "  Bind Address: $BindAddress" -ForegroundColor Cyan
Write-Host "  Centre: $PortCentre | Portal: $PortPortal | AI Server: $PortAi" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# Check for port collisions
$Occupied = @()
foreach ($p in @($PortCentre, $PortPortal, $PortAi)) {
    if (Test-PortOccupied -Port $p) {
        $Occupied += $p
    }
}

if ($Occupied.Count -gt 0) {
    Write-Host "[WARN] The following port(s) are already occupied: $($Occupied -join ', ')" -ForegroundColor Yellow
    Write-Host "Please stop running services using .\scripts\stop_wewin.ps1 or specify different ports." -ForegroundColor Yellow
    exit 1
}

$LogDir = Join-Path $RepoRoot "logs"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

$Pids = @{}

# 1. Start WeWIN Centre (Connector) on Port 8000
Write-Host "[1/3] Starting WeWIN Centre on http://${BindAddress}:${PortCentre}..." -ForegroundColor Cyan
$ConnectorDir = Join-Path $RepoRoot "connector"
$p1 = Start-Process -FilePath $VenvPython `
    -ArgumentList "-m", "uvicorn", "src.api.app:app", "--host", $BindAddress, "--port", "$PortCentre" `
    -WorkingDirectory $ConnectorDir `
    -RedirectStandardOutput (Join-Path $LogDir "connector.log") `
    -RedirectStandardError (Join-Path $LogDir "connector_err.log") `
    -PassThru -WindowStyle Hidden

$Pids["connector"] = $p1.Id
Write-Host "      Centre running with PID: $($p1.Id)" -ForegroundColor Green

# 2. Start WeWIN Education Portal on Port 8001
Write-Host "[2/3] Starting WeWIN Education Portal on http://${BindAddress}:${PortPortal}..." -ForegroundColor Cyan
$PortalDir = Join-Path $RepoRoot "portal"
$p2 = Start-Process -FilePath $VenvPython `
    -ArgumentList "-m", "uvicorn", "backend.app:app", "--host", $BindAddress, "--port", "$PortPortal" `
    -WorkingDirectory $PortalDir `
    -RedirectStandardOutput (Join-Path $LogDir "portal.log") `
    -RedirectStandardError (Join-Path $LogDir "portal_err.log") `
    -PassThru -WindowStyle Hidden

$Pids["portal"] = $p2.Id
Write-Host "      Portal running with PID: $($p2.Id)" -ForegroundColor Green

# 3. Start WeWIN AI Server on Port 8010
Write-Host "[3/3] Starting WeWIN AI Server on http://${BindAddress}:${PortAi}..." -ForegroundColor Cyan
$p3 = Start-Process -FilePath $VenvPython `
    -ArgumentList "-m", "uvicorn", "ai_server.app:app", "--host", $BindAddress, "--port", "$PortAi" `
    -WorkingDirectory $PortalDir `
    -RedirectStandardOutput (Join-Path $LogDir "ai_server.log") `
    -RedirectStandardError (Join-Path $LogDir "ai_server_err.log") `
    -PassThru -WindowStyle Hidden

$Pids["ai_server"] = $p3.Id
Write-Host "      AI Server running with PID: $($p3.Id)" -ForegroundColor Green

# Save PID file
$PidFile = Join-Path $RepoRoot ".wewin_pids.json"
$Pids | ConvertTo-Json | Set-Content $PidFile -Encoding UTF8

Start-Sleep -Seconds 2

Write-Host "`n==========================================================" -ForegroundColor Green
Write-Host "  WeWIN Education AI Robot Platform is Running!           " -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "Access URLs:" -ForegroundColor Cyan
Write-Host "  - Education Portal UI : http://${BindAddress}:${PortPortal}" -ForegroundColor White
Write-Host "  - WeWIN Centre API/UI : http://${BindAddress}:${PortCentre}" -ForegroundColor White
Write-Host "  - AI Server Endpoint  : http://${BindAddress}:${PortAi}" -ForegroundColor White
Write-Host "Logs are stored in: $LogDir" -ForegroundColor Gray
Write-Host "To stop all services: .\scripts\stop_wewin.ps1" -ForegroundColor Yellow

if (-not $NoBrowser) {
    Start-Process "http://${BindAddress}:${PortPortal}"
}
