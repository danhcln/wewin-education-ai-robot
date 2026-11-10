# WeWIN Platform - Troubleshooting & FAQ Guide

## 1. PowerShell Execution Policy Restrictions

### Symptom:
```
File C:\...\scripts\setup_windows.ps1 cannot be loaded because running scripts is disabled on this system.
```

### Resolution:
Launch PowerShell scripts by explicitly passing `-ExecutionPolicy Bypass`:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1
```
Or set execution policy for the current user process:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

---

## 2. Port Collisions (Ports 8000, 8001, 8010)

### Symptom:
```
[WARN] The following port(s) are already occupied: 8000, 8001
```

### Resolution:
1. Run the safe shutdown script:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\stop_wewin.ps1
   ```
2. If another application (e.g., IIS, Docker, or another dev server) is using the port, inspect the owner:
   ```powershell
   Get-NetTCPConnection -LocalPort 8000 -State Listen | Select-Object OwningProcess
   ```
3. Or specify custom ports when starting:
   ```powershell
   .\scripts\start_wewin.ps1 -PortCentre 8800 -PortPortal 8801 -PortAi 8810
   ```

---

## 3. Node.js / npm Command Recognition

### Symptom:
```
'tsc' is not recognized as an internal or external command
```

### Resolution:
In standard Windows PowerShell, invoke npm commands using `npm.cmd` or run via `cmd.exe`:
```powershell
cmd.exe /c "cd /d portal\frontend && npm install && npm run build"
```
Ensure Node.js is installed from [nodejs.org](https://nodejs.org) and present in your system `PATH`.

---

## 4. SQLite File Locking on Windows (`WinError 32`)

### Symptom:
```
PermissionError: [WinError 32] The process cannot access the file because it is being used by another process: '...education.sqlite3'
```

### Resolution:
Windows maintains exclusive file locks on open SQLite handles.
1. Ensure running server processes are stopped before deleting or replacing `.sqlite3` files.
2. In unit test suites, avoid deleting directories containing open SQLite connections until the test runner process has exited.
3. The platform uses SQLite URI mode with `?mode=ro` (read-only) for concurrent reporting processes to prevent locking write transactions.

---

## 5. Tokenizer & Model Weights

### Symptom:
```
FileNotFoundError: ai-qwen3-tokenizer/tokenizer.json
```

### Resolution:
1. Run `.\scripts\doctor.ps1` to verify tokenizer file paths.
2. Bundled tokenizers are located at:
   - `portal/data/ai-qwen3-tokenizer/tokenizer.json`
   - `portal/data/ai-qwen25-tokenizer/tokenizer.json`
   - `portal/data/ai-whisper-base/tokenizer.json`
3. If running local GGUF models via llama.cpp or Ollama, configure `WEWIN_AI_BASE_URL` in `.env` to point to your local model endpoint (e.g., `http://127.0.0.1:11434/v1`).
