<#
.SYNOPSIS
    WeWIN Education AI Robot Platform - Windows Services Shutdown Script
.DESCRIPTION
    Safely stops all WeWIN background services (ports 8000, 8001, 8010)
    using saved PIDs and network listener detection.
#>

param(
    [switch]$Force = $false
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
Set-Location $RepoRoot

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  Stopping WeWIN Education AI Robot Platform Services     " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$PidFile = Join-Path $RepoRoot ".wewin_pids.json"
$StoppedPids = @()

# 1. Stop from PID file
if (Test-Path $PidFile) {
    try {
        $Pids = Get-Content $PidFile -Raw | ConvertFrom-Json
        foreach ($prop in $Pids.PSObject.Properties) {
            $service = $prop.Name
            $pidVal = $prop.Value
            if ($pidVal) {
                $proc = Get-Process -Id $pidVal -ErrorAction SilentlyContinue
                if ($proc) {
                    Write-Host "Stopping $service (PID: $pidVal)..." -ForegroundColor Yellow
                    Stop-Process -Id $pidVal -Force
                    $StoppedPids += $pidVal
                }
            }
        }
    } catch {
        Write-Host "[WARN] Could not parse PID file: $_" -ForegroundColor Yellow
    }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

# 2. Check ports 8000, 8001, 8010 for any remaining listeners
$Ports = @(8000, 8001, 8010)
foreach ($port in $Ports) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($conn in $conns) {
        $owningPid = $conn.OwningProcess
        if ($owningPid -and ($StoppedPids -notcontains $owningPid)) {
            $proc = Get-Process -Id $owningPid -ErrorAction SilentlyContinue
            if ($proc -and ($proc.ProcessName -match "python|node")) {
                Write-Host "Stopping listener on port $port (PID: $owningPid, Name: $($proc.ProcessName))..." -ForegroundColor Yellow
                Stop-Process -Id $owningPid -Force
                $StoppedPids += $owningPid
            }
        }
    }
}

if ($StoppedPids.Count -gt 0) {
    Write-Host "`n[OK] Successfully stopped $($StoppedPids.Count) WeWIN process(es)." -ForegroundColor Green
} else {
    Write-Host "`n[INFO] No active WeWIN processes found running." -ForegroundColor Cyan
}
