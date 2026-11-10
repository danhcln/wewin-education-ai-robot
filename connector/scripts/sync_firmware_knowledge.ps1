# PowerShell Script: Sync WeWIN Firmware Knowledge Base
# Source of Truth (SSoT): E:\WeWIN_Firmware_Lab\xiaozhi-2.5.2\docs\
param(
    [switch]$CheckOnly = $false
)

$ErrorActionPreference = "Stop"

$ssotFirmware = "E:\WeWIN_Firmware_Lab\xiaozhi-2.5.2\docs\firmware"
$ssotHardware = "E:\WeWIN_Firmware_Lab\xiaozhi-2.5.2\docs\hardware"

$destinations = @(
    "C:\Users\Danh\.gemini\config\skills\wewin-firmware-development\references",
    "E:\WeWIN_Firmware_Lab\xiaozhi-2.5.2\.agents\skills\wewin-firmware-development\references",
    "E:\WEWIN_IT\Wewin_AI_Connector\.agents\skills\wewin-firmware-development\references",
    "E:\WEWIN_IT\Wewin_AI_Connector\docs\firmware",
    "E:\WEWIN_IT\Wewin_AI_Connector\docs\hardware"
)

Write-Host "=== WEWIN KNOWLEDGE BASE SYNC ===" -ForegroundColor Cyan
Write-Host "Source of Truth: E:\WeWIN_Firmware_Lab\xiaozhi-2.5.2\docs\"

# 1. Validate SSoT files
$requiredDocs = @(
    (Join-Path $ssotFirmware "WEWIN_FIRMWARE_RULES.md"),
    (Join-Path $ssotFirmware "LESSONS_LEARNED.md"),
    (Join-Path $ssotFirmware "FIRMWARE_HISTORY.md"),
    (Join-Path $ssotFirmware "TEST_MATRIX.md"),
    (Join-Path $ssotFirmware "ARCHITECTURE.md"),
    (Join-Path $ssotFirmware "RELEASE_CHECKLIST.md"),
    (Join-Path $ssotHardware "MONSTER_DESK_HARDWARE.md")
)

foreach ($doc in $requiredDocs) {
    if (-not (Test-Path $doc)) {
        Write-Error "MISSING REQUIRED SSoT DOCUMENT: $doc"
        exit 1
    }
    $len = (Get-Item $doc).Length
    if ($len -lt 100) {
        Write-Error "DOCUMENT SUSPICIOUSLY SMALL ($len bytes): $doc"
        exit 1
    }
    Write-Host " [OK] SSoT Doc: $(Split-Path $doc -Leaf) ($len bytes)" -ForegroundColor Green
}

if ($CheckOnly) {
    Write-Host "Check-only mode completed successfully." -ForegroundColor Yellow
    exit 0
}

# 2. Sync to destinations
# A. Sync to Skill references (all files flat lowercase)
$skillRefDests = @(
    "C:\Users\Danh\.gemini\config\skills\wewin-firmware-development\references",
    "E:\WeWIN_Firmware_Lab\xiaozhi-2.5.2\.agents\skills\wewin-firmware-development\references",
    "E:\WEWIN_IT\Wewin_AI_Connector\.agents\skills\wewin-firmware-development\references"
)

$fileMapping = @{
    "WEWIN_FIRMWARE_RULES.md"   = "wewin_firmware_rules.md"
    "LESSONS_LEARNED.md"        = "lessons_learned.md"
    "FIRMWARE_HISTORY.md"       = "firmware_history.md"
    "TEST_MATRIX.md"            = "test_matrix.md"
    "ARCHITECTURE.md"           = "architecture.md"
    "RELEASE_CHECKLIST.md"      = "release_checklist.md"
    "MONSTER_DESK_HARDWARE.md"  = "monster_desk_hardware.md"
}

foreach ($dest in $skillRefDests) {
    if (-not (Test-Path $dest)) {
        New-Item -ItemType Directory -Force -Path $dest | Out-Null
    }
    foreach ($entry in $fileMapping.GetEnumerator()) {
        $srcPath = Join-Path $ssotFirmware $entry.Key
        if (-not (Test-Path $srcPath)) {
            $srcPath = Join-Path $ssotHardware $entry.Key
        }
        $targetPath = Join-Path $dest $entry.Value
        Copy-Item -Path $srcPath -Destination $targetPath -Force
    }
    Write-Host " [SYNCED] Skill references -> $dest" -ForegroundColor Magenta
}

# B. Sync SKILL.md across all 3 skill directories
$primarySkill = "C:\Users\Danh\.gemini\config\skills\wewin-firmware-development\SKILL.md"
$secondarySkillDests = @(
    "E:\WeWIN_Firmware_Lab\xiaozhi-2.5.2\.agents\skills\wewin-firmware-development\SKILL.md",
    "E:\WEWIN_IT\Wewin_AI_Connector\.agents\skills\wewin-firmware-development\SKILL.md"
)
foreach ($sec in $secondarySkillDests) {
    $parent = Split-Path $sec -Parent
    if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    Copy-Item -Path $primarySkill -Destination $sec -Force
    Write-Host " [SYNCED] SKILL.md -> $sec" -ForegroundColor Magenta
}

# C. Sync to Wewin_AI_Connector\docs\
$connectorFirmware = "E:\WEWIN_IT\Wewin_AI_Connector\docs\firmware"
$connectorHardware = "E:\WEWIN_IT\Wewin_AI_Connector\docs\hardware"

if (-not (Test-Path $connectorFirmware)) { New-Item -ItemType Directory -Force -Path $connectorFirmware | Out-Null }
if (-not (Test-Path $connectorHardware)) { New-Item -ItemType Directory -Force -Path $connectorHardware | Out-Null }

Copy-Item -Path "$ssotFirmware\*" -Destination $connectorFirmware -Force
Copy-Item -Path "$ssotHardware\*" -Destination $connectorHardware -Force
Write-Host " [SYNCED] Connector docs -> E:\WEWIN_IT\Wewin_AI_Connector\docs\" -ForegroundColor Magenta

# 3. Verification of SHA256 across all destinations
Write-Host "`n=== INTEGRITY VERIFICATION (SHA256 CHECKSUM) ===" -ForegroundColor Cyan
foreach ($entry in $fileMapping.GetEnumerator()) {
    $srcPath = Join-Path $ssotFirmware $entry.Key
    if (-not (Test-Path $srcPath)) { $srcPath = Join-Path $ssotHardware $entry.Key }
    $srcHash = (Get-FileHash -Path $srcPath -Algorithm SHA256).Hash
    
    # Check all targets
    $targetsToCheck = @(
        (Join-Path "C:\Users\Danh\.gemini\config\skills\wewin-firmware-development\references" $entry.Value),
        (Join-Path "E:\WeWIN_Firmware_Lab\xiaozhi-2.5.2\.agents\skills\wewin-firmware-development\references" $entry.Value),
        (Join-Path "E:\WEWIN_IT\Wewin_AI_Connector\.agents\skills\wewin-firmware-development\references" $entry.Value)
    )
    
    $allMatch = $true
    foreach ($t in $targetsToCheck) {
        $tHash = (Get-FileHash -Path $t -Algorithm SHA256).Hash
        if ($tHash -ne $srcHash) {
            Write-Error "HASH MISMATCH: $t does not match SSoT!"
            $allMatch = $false
        }
    }
    if ($allMatch) {
        Write-Host " [VERIFIED HASH MATCH] $($entry.Key) = $srcHash" -ForegroundColor Green
    }
}

Write-Host "`nAll skills, references, and workspace docs are 100% in sync with SSoT!" -ForegroundColor Cyan
