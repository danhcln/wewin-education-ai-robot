<#
.SYNOPSIS
    WeWIN Education AI Robot Platform - Test Suite Runner
.DESCRIPTION
    Runs all automated unit, integration, and security tests across
    Portal and Connector components.
#>

param(
    [string]$Component = "all" # "all", "portal", "connector"
)

$ErrorActionPreference = "Continue"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
Set-Location $RepoRoot

$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    $VenvPython = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $VenvPython) {
        Write-Host "[ERROR] Python not found." -ForegroundColor Red
        exit 1
    }
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  WeWIN Education AI Robot Platform - Test Suite Runner    " -ForegroundColor Cyan
Write-Host "  Target: $Component" -ForegroundColor Cyan
Write-Host "  Python: $VenvPython" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$OverallSuccess = $true

# 1. Run Portal Tests
if ($Component -in @("all", "portal")) {
    Write-Host "`n>>> Running Portal Unit Tests (portal/tests)..." -ForegroundColor Cyan
    $PortalDir = Join-Path $RepoRoot "portal"
    [System.Environment]::CurrentDirectory = $PortalDir
    Set-Location $PortalDir
    try {
        & $VenvPython -m unittest discover -s tests
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[FAIL] Portal unit tests reported failures." -ForegroundColor Red
            $OverallSuccess = $false
        } else {
            Write-Host "[PASS] Portal unit tests passed." -ForegroundColor Green
        }
    } finally {
        [System.Environment]::CurrentDirectory = $RepoRoot
        Set-Location $RepoRoot
    }
}

# 2. Run Connector Tests
if ($Component -in @("all", "connector")) {
    Write-Host "`n>>> Running Connector Security & Core Unit Tests (connector/tests)..." -ForegroundColor Cyan
    $ConnectorDir = Join-Path $RepoRoot "connector"
    [System.Environment]::CurrentDirectory = $ConnectorDir
    Set-Location $ConnectorDir
    try {
        $ConnectorSuites = @(
            "tests/test_security_regression.py",
            "tests/test_devices_auth.py",
            "tests/test_search.py tests/test_secret_redaction.py tests/test_server_readiness.py",
            "tests/test_voice_media_registry.py"
        )

        foreach ($suite in $ConnectorSuites) {
            $suiteArgs = $suite -split " "
            & $VenvPython -m unittest @suiteArgs
            if ($LASTEXITCODE -ne 0) {
                Write-Host "[FAIL] Connector suite failed: $suite" -ForegroundColor Red
                $OverallSuccess = $false
            }
        }

        Write-Host "`n>>> Running Connector API Smoke Test (test_api.py)..." -ForegroundColor Cyan
        & $VenvPython -c "import tests.test_api as t; t.test_api_endpoints()"
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[FAIL] Connector API smoke test failed." -ForegroundColor Red
            $OverallSuccess = $false
        } else {
            Write-Host "[PASS] Connector API smoke test passed." -ForegroundColor Green
        }
    } finally {
        [System.Environment]::CurrentDirectory = $RepoRoot
        Set-Location $RepoRoot
    }
}

Write-Host "`n==========================================================" -ForegroundColor Cyan
if ($OverallSuccess) {
    Write-Host "  ALL REQUESTED TEST SUITES COMPLETED SUCCESSFULLY!       " -ForegroundColor Green
} else {
    Write-Host "  SOME TESTS FAILED. Please review the output above.      " -ForegroundColor Red
}
Write-Host "==========================================================" -ForegroundColor Cyan

if (-not $OverallSuccess) {
    exit 1
}
