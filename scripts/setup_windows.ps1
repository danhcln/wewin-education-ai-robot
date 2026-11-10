<#
.SYNOPSIS
    WeWIN Education AI Robot Platform - Windows Automated Setup Script
.DESCRIPTION
    Checks prerequisites (Python, Node.js, npm, Git), sets up virtual environment,
    installs Python dependencies for Portal and Connector, builds frontend bundles,
    and initializes environment configurations.
#>

param(
    [switch]$SkipFrontendBuild = $false,
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "`n[WeWIN Setup] >>> $Message" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "[WeWIN Setup] [OK] $Message" -ForegroundColor Green
}

function Write-WarnMsg {
    param([string]$Message)
    Write-Host "[WeWIN Setup] [WARN] $Message" -ForegroundColor Yellow
}

function Write-ErrMsg {
    param([string]$Message)
    Write-Host "[WeWIN Setup] [ERROR] $Message" -ForegroundColor Red
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
Set-Location $RepoRoot

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  WeWIN Education AI Robot Platform - Windows Setup       " -ForegroundColor Cyan
Write-Host "  Repository Root: $RepoRoot" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Check Python
Write-Step "Checking Python installation..."
try {
    $PyVersion = & $PythonExe --version 2>&1
    Write-Success "Found: $PyVersion"
} catch {
    Write-ErrMsg "Python is not installed or not found on PATH. Please install Python 3.10+ from python.org."
    exit 1
}

# 2. Check Node.js and npm
Write-Step "Checking Node.js & npm..."
try {
    $NodeVersion = & node --version 2>&1
    $NpmCmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $NpmCmd) {
        $NpmCmd = "npm"
    }
    $NpmVersion = & $NpmCmd --version 2>&1
    Write-Success "Found Node $NodeVersion, npm $NpmVersion"
} catch {
    Write-ErrMsg "Node.js / npm not found on PATH. Please install Node.js 18+ from nodejs.org."
    exit 1
}

# 3. Setup Virtual Environment
Write-Step "Setting up Python virtual environment (.venv)..."
$VenvDir = Join-Path $RepoRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating virtual environment at $VenvDir..."
    & $PythonExe -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) {
        Write-ErrMsg "Failed to create virtual environment."
        exit 1
    }
    Write-Success "Created virtual environment."
} else {
    Write-Success "Existing virtual environment found."
}

# 4. Install Python Dependencies
Write-Step "Upgrading pip and installing wheel/setuptools..."
& $VenvPython -m pip install --upgrade pip wheel setuptools --quiet

Write-Step "Installing Portal dependencies (portal/requirements.txt)..."
$PortalReq = Join-Path $RepoRoot "portal\requirements.txt"
if (Test-Path $PortalReq) {
    & $VenvPython -m pip install -r $PortalReq
    Write-Success "Portal dependencies installed."
} else {
    Write-WarnMsg "portal/requirements.txt not found."
}

Write-Step "Installing Connector dependencies (connector/requirements.txt)..."
$ConnectorReq = Join-Path $RepoRoot "connector\requirements.txt"
if (Test-Path $ConnectorReq) {
    & $VenvPython -m pip install -r $ConnectorReq
    Write-Success "Connector dependencies installed."
} else {
    Write-WarnMsg "connector/requirements.txt not found."
}

# 5. Build Frontends
if (-not $SkipFrontendBuild) {
    Write-Step "Building Portal Frontend (portal/frontend)..."
    $PortalFrontend = Join-Path $RepoRoot "portal\frontend"
    if (Test-Path (Join-Path $PortalFrontend "package.json")) {
        Push-Location $PortalFrontend
        try {
            cmd.exe /c "npm install && npm run build"
            if ($LASTEXITCODE -eq 0) {
                Write-Success "Portal frontend built successfully."
            } else {
                Write-WarnMsg "Portal frontend build exited with code $LASTEXITCODE."
            }
        } finally {
            Pop-Location
        }
    }

    Write-Step "Building Connector Frontend (connector/frontend)..."
    $ConnectorFrontend = Join-Path $RepoRoot "connector\frontend"
    if (Test-Path (Join-Path $ConnectorFrontend "package.json")) {
        Push-Location $ConnectorFrontend
        try {
            cmd.exe /c "npm install && npm run build"
            if ($LASTEXITCODE -eq 0) {
                Write-Success "Connector frontend built successfully."
            } else {
                Write-WarnMsg "Connector frontend build exited with code $LASTEXITCODE."
            }
        } finally {
            Pop-Location
        }
    }
} else {
    Write-WarnMsg "Skipping frontend builds as requested (-SkipFrontendBuild)."
}

# 6. Initialize Environment Configuration
Write-Step "Configuring environment files..."
$EnvExample = Join-Path $RepoRoot ".env.example"
$EnvTarget = Join-Path $RepoRoot ".env"

if (-not (Test-Path $EnvTarget) -and (Test-Path $EnvExample)) {
    Copy-Item $EnvExample $EnvTarget
    Write-Success "Created .env from .env.example."
} elseif (Test-Path $EnvTarget) {
    Write-Success ".env already exists."
}

Write-Host "`n==========================================================" -ForegroundColor Green
Write-Host "  WeWIN Education AI Robot Platform - Setup Complete!     " -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Run diagnostics : .\scripts\doctor.ps1" -ForegroundColor White
Write-Host "  2. Run test suite  : .\scripts\run_tests.ps1" -ForegroundColor White
Write-Host "  3. Start platform  : .\scripts\start_wewin.ps1" -ForegroundColor White
Write-Host ""
