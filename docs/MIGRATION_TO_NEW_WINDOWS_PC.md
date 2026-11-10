# WeWIN Platform - Migration to a New Windows PC Runbook

This guide details how to clone, configure, and operate the **WeWIN Education AI Robot Platform** on a brand-new Windows PC.

---

## 📌 Two Distinct Scenarios

Before proceeding, determine which scenario applies:
- **Scenario A: Fresh Development / Demonstration / Partner PC (Recommended)**
  You want a clean, operational system with demo data to test, demo, or develop features without needing existing user databases or real robot hardware.
- **Scenario B: Production Database Migration**
  You are replacing the primary production host and need to migrate historical user data, real robot registrations, and student progress from an old machine.

---

## 🛠️ Step 1: Target PC Prerequisites

On the new Windows machine, ensure the following tools are installed:

1. **Operating System**: Windows 10 (Build 19041+) or Windows 11 (64-bit).
2. **Python**:
   - Version: **Python 3.10+** (64-bit) from [python.org](https://www.python.org/downloads/).
   - ⚠️ Check **"Add python.exe to PATH"** during installation.
3. **Node.js**:
   - Version: **Node.js LTS (18+ or 20+)** from [nodejs.org](https://nodejs.org/).
   - Includes `npm` package manager.
4. **Git**:
   - Download from [git-scm.com](https://git-scm.com/).
5. *(Optional for Homework OCR)* **Tesseract OCR**:
   - Install to `C:\Program Files\Tesseract-OCR\tesseract.exe` with `eng` and `vie` language packs.

---

## 📥 Step 2: Clone the Clean Repository

Open **PowerShell** (run as standard user or administrator):

```powershell
# Create your target workspace folder
New-Item -ItemType Directory -Path "C:\WeWIN_Deploy" -Force
Set-Location "C:\WeWIN_Deploy"

# Clone the private repository
git clone https://github.com/danhcln/wewin-education-ai-robot.git
Set-Location "C:\WeWIN_Deploy\wewin-education-ai-robot"
```

---

## ⚙️ Step 3: Run Automated Setup

Execute the automated Windows setup script:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1
```

**What this script performs:**
1. Verifies Python, Node.js, and npm versions.
2. Creates an isolated Python virtual environment (`.venv`).
3. Installs all required Python dependencies for Portal and Connector.
4. Installs npm packages and builds both web frontends (`portal/frontend/dist` and `connector/frontend/dist`).
5. Generates the default `.env` configuration file from `.env.example`.

---

## 🩺 Step 4: Run Health Check (Doctor)

Verify that all directories, dependencies, tokenizers, and ports are in working order:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\doctor.ps1
```

You should see:
```
[PASS] Python Executable
[PASS] Virtual Environment (.venv)
[PASS] Node.js Runtime
[PASS] Directory: portal
[PASS] Directory: connector
[PASS] Directory: scripts
[PASS] Directory: docs
[PASS] Portal Frontend Build
[PASS] Connector Frontend Build
[PASS] Tokenizer: Qwen3
[PASS] Tokenizer: Qwen2.5
[PASS] Tokenizer: Whisper
[PASS] Curated Knowledge Seeds
[PASS] Offline Demo Fixture DB
[PASS] Environment Template (.env.example)

DOCTOR RESULT: ALL CORE CHECKS PASSED
```

---

## 🧪 Step 5: Run Automated Test Suite

Verify that all unit and security regression tests pass locally:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_tests.ps1
```

All 156+ automated tests should report `[PASS]`.

---

## 🚀 Step 6: Start Platform Services

Launch the WeWIN background services:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_wewin.ps1
```

This will launch:
- **WeWIN Centre API** on `http://127.0.0.1:8000`
- **WeWIN Education Portal** on `http://127.0.0.1:8001`
- **WeWIN AI Server** on `http://127.0.0.1:8010`

Open your web browser and navigate to:
- **Education Portal**: [http://127.0.0.1:8001](http://127.0.0.1:8001)
- Default login: `local-admin` (uses token authentication or initial setup wizard).

---

## 📦 Step 7: Scenario B - Migrating Real Production Data (Optional)

If migrating production data from an old machine:

### 1. Files to Copy from Old PC:
- `portal/data/education.sqlite3` -> `portal/data/education.sqlite3`
- `connector/data/wewin_fts.db` -> `connector/data/wewin_fts.db`
- `connector/.secrets/browser-sessions.sqlite3` -> `connector/.secrets/browser-sessions.sqlite3`
- `connector/.secrets/admin_sync_token` -> `connector/.secrets/admin_sync_token`

### 2. Permissions & Verification:
- Secure the `.secrets` directory using PowerShell:
  ```powershell
  $Acl = Get-Acl "connector\.secrets"
  $Acl.SetAccessRuleProtection($true, $false)
  $Rule = New-Object System.Security.AccessControl.FileSystemAccessRule($env:USERNAME, "FullControl", "ContainerInherit,ObjectInherit", "None", "Allow")
  $Acl.AddAccessRule($Rule)
  Set-Acl "connector\.secrets" $Acl
  ```
- Re-run `.\scripts\doctor.ps1` and restart services.
