<#
.SYNOPSIS
    WeWIN Education AI Robot Platform - Environment Diagnostic Script
.DESCRIPTION
    Verifies that all prerequisites, environment configs, directory structures,
    build artifacts, tokenizers, and ports are correctly configured for running
    WeWIN Education AI Robot Platform on Windows.
#>

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
Set-Location $RepoRoot

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  WeWIN Education AI Robot Platform - Doctor Diagnostics   " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$GlobalStatus = $true
$Checks = @()

function Record-Check {
    param([string]$Name, [bool]$Passed, [string]$Details = "")
    $script:Checks += [PSCustomObject]@{
        Name    = $Name
        Passed  = $Passed
        Details = $Details
    }
    if ($Passed) {
        Write-Host "  [PASS] $Name" -ForegroundColor Green
        if ($Details) { Write-Host "         $Details" -ForegroundColor Gray }
    } else {
        $script:GlobalStatus = $false
        Write-Host "  [FAIL] $Name" -ForegroundColor Red
        if ($Details) { Write-Host "         $Details" -ForegroundColor Yellow }
    }
}

# 1. Python Check
$PyExe = (Get-Command python -ErrorAction SilentlyContinue).Source
if ($PyExe) {
    $PyVer = & python --version 2>&1
    Record-Check "Python Executable" $true "$PyVer at $PyExe"
} else {
    Record-Check "Python Executable" $false "python not found on PATH"
}

# 2. Virtualenv Check
$VenvPy = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (Test-Path $VenvPy) {
    Record-Check "Virtual Environment (.venv)" $true "Found at $VenvPy"
} else {
    Record-Check "Virtual Environment (.venv)" $true "Optional (using system Python). Run .\scripts\setup_windows.ps1 to create isolated .venv"
}

# 3. Node.js & npm Check
$NodeCmd = (Get-Command node -ErrorAction SilentlyContinue).Source
if ($NodeCmd) {
    $NodeVer = & node --version 2>&1
    Record-Check "Node.js Runtime" $true "$NodeVer at $NodeCmd"
} else {
    Record-Check "Node.js Runtime" $false "node not found on PATH"
}

# 4. Project Folders Check
$RequiredDirs = @("portal", "connector", "scripts", "docs")
foreach ($d in $RequiredDirs) {
    $dp = Join-Path $RepoRoot $d
    Record-Check "Directory: $d" (Test-Path $dp) "Expected at $dp"
}

# 5. Frontend Dist Check
$PortalDist = Join-Path $RepoRoot "portal\frontend\dist\index.html"
Record-Check "Portal Frontend Build" (Test-Path $PortalDist) "portal/frontend/dist/index.html"

$ConnectorDist = Join-Path $RepoRoot "connector\frontend\dist\index.html"
Record-Check "Connector Frontend Build" (Test-Path $ConnectorDist) "connector/frontend/dist/index.html"

# 6. Data & Tokenizers Check
$TokenizerQwen3 = Join-Path $RepoRoot "portal\data\ai-qwen3-tokenizer\tokenizer.json"
Record-Check "Tokenizer: Qwen3" (Test-Path $TokenizerQwen3) "ai-qwen3-tokenizer/tokenizer.json"

$TokenizerQwen25 = Join-Path $RepoRoot "portal\data\ai-qwen25-tokenizer\tokenizer.json"
Record-Check "Tokenizer: Qwen2.5" (Test-Path $TokenizerQwen25) "ai-qwen25-tokenizer/tokenizer.json"

$TokenizerWhisper = Join-Path $RepoRoot "portal\data\ai-whisper-base\tokenizer.json"
Record-Check "Tokenizer: Whisper" (Test-Path $TokenizerWhisper) "ai-whisper-base/tokenizer.json"

$KnowledgeSeeds = Join-Path $RepoRoot "connector\data\wewin_knowledge.json"
Record-Check "Curated Knowledge Seeds" (Test-Path $KnowledgeSeeds) "connector/data/wewin_knowledge.json"

$FixtureDb = Join-Path $RepoRoot "portal\tests\fixtures\fixture_browser_sessions.sqlite3"
Record-Check "Offline Demo Fixture DB" (Test-Path $FixtureDb) "portal/tests/fixtures/fixture_browser_sessions.sqlite3"

# 7. Environment Template Check
$EnvExample = Join-Path $RepoRoot ".env.example"
Record-Check "Environment Template (.env.example)" (Test-Path $EnvExample) ".env.example present at root"

# 8. Port Status Check
Write-Host "`nPort Status Overview:" -ForegroundColor Cyan
$Ports = @(
    @{ Name = "WeWIN Centre API"; Port = 8000 },
    @{ Name = "WeWIN Education Portal"; Port = 8001 },
    @{ Name = "WeWIN AI Server"; Port = 8010 }
)

foreach ($item in $Ports) {
    $p = $item.Port
    $conn = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
    if ($conn) {
        Write-Host "  - Port $p ($($item.Name)): ACTIVE (PID: $($conn.OwningProcess))" -ForegroundColor Green
    } else {
        Write-Host "  - Port $p ($($item.Name)): AVAILABLE" -ForegroundColor Gray
    }
}

Write-Host "`n==========================================================" -ForegroundColor Cyan
if ($GlobalStatus) {
    Write-Host "  DOCTOR RESULT: ALL CORE CHECKS PASSED                   " -ForegroundColor Green
    Write-Host "  The environment is ready to start. Run .\scripts\start_wewin.ps1" -ForegroundColor Green
} else {
    Write-Host "  DOCTOR RESULT: SOME CHECKS FAILED                       " -ForegroundColor Red
    Write-Host "  Please resolve failed items or run .\scripts\setup_windows.ps1" -ForegroundColor Yellow
}
Write-Host "==========================================================" -ForegroundColor Cyan
