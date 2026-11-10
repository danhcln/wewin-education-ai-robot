# WeWIN Education AI Robot Platform

> **Clean, Portable, Self-Contained Education AI & Device Management Monorepo**  
> Designed for reproducible deployment on any Windows PC without requiring physical robot hardware.

---

## 🌟 Overview

The **WeWIN Education AI Robot Platform** is an enterprise-grade education and robotics integration suite. It provides:
1. **WeWIN Education Portal** (`portal/`): Full-stack learning management, curriculum authoring, student homework OCR, RBAC authentication, and educational AI role configuration.
2. **WeWIN Centre API & MCP Bridge** (`connector/`): Verified WeWIN knowledge base, FTS5 full-text search, media catalogs, device enrollment, and Model Context Protocol (MCP) tool integration.
3. **WeWIN AI Server** (`portal/ai_server/`): Local edge AI streaming runtime supporting WebSocket protocol, tokenizers (Qwen3, Qwen2.5, Whisper), and device state coordination.
4. **Offline Demo Fixtures**: Built-in mock robot devices and knowledge seeds allowing full demonstration, evaluation, and development on fresh installations without a physical robot.

---

## 🏗 System Architecture & Service Ports

| Service | Directory | Default Port | Description |
| :--- | :--- | :--- | :--- |
| **WeWIN Centre API / UI** | `connector/` | `8000` | Knowledge FTS5 search, media streaming, device auth & MCP tools |
| **WeWIN Education Portal** | `portal/` | `8001` | React + TypeScript web portal, FastAPI educational backend |
| **WeWIN AI Server** | `portal/ai_server/` | `8010` | Real-time AI WebSocket streaming gateway & tokenizers |
| **Device Edge TLS** | `portal/scripts/` | `8013` | Optional local edge TLS termination for physical hardware testing |

---

## 🚀 Quick Start on Windows

### Prerequisites
- **Windows 10/11 (64-bit)**
- **Python 3.10+** (tested up to Python 3.14)
- **Node.js 18+** & npm (for building web frontends)
- **Git**

### 1. Clone Repository
```powershell
git clone https://github.com/danhcln/wewin-education-ai-robot.git
cd wewin-education-ai-robot
```

### 2. Automated Setup
Run the automated Windows setup script to configure Python virtual environment, install dependencies, and build frontend assets:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1
```

### 3. Run Environment Diagnostics
Verify all directories, build artifacts, tokenizers, and ports:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\doctor.ps1
```

### 4. Run Test Suite
Execute the 156+ automated unit and security tests:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_tests.ps1
```

### 5. Start Platform Services
Launch all WeWIN background services and automatically open the Education Portal in your default browser:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_wewin.ps1
```

Access the user interfaces:
- **Education Portal**: [http://127.0.0.1:8001](http://127.0.0.1:8001)
- **WeWIN Centre**: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- **AI Server Status**: [http://127.0.0.1:8010/health](http://127.0.0.1:8010/health)

### 6. Stop Services
Cleanly stop all background services:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop_wewin.ps1
```

---

## 📁 Repository Structure

```
wewin-education-ai-robot/
├── .env.example                     # Unified environment template
├── .gitignore                       # Production-grade secret & build filter
├── README.md                        # Platform overview & quick start
├── docs/                            # Comprehensive engineering guides
│   ├── ARCHITECTURE.md              # Monorepo architecture & service interactions
│   ├── MIGRATION_TO_NEW_WINDOWS_PC.md # Step-by-step migration & deployment runbook
│   ├── ENVIRONMENT_VARIABLES.md     # Full environment variable catalog
│   ├── API.md                       # Complete REST & WebSocket API specification
│   ├── TROUBLESHOOTING.md           # Diagnostics, common issues & resolutions
│   └── SECURITY.md                  # Security boundary, token isolation & audits
├── scripts/                         # Windows automation scripts
│   ├── setup_windows.ps1            # Automated dependency & build installer
│   ├── start_wewin.ps1              # Service launcher with PID tracking
│   ├── stop_wewin.ps1               # Safe graceful shutdown script
│   ├── doctor.ps1                   # Pre-flight environment diagnostics
│   └── run_tests.ps1                # Automated test runner across components
├── portal/                          # WeWIN Education Portal
│   ├── backend/                     # FastAPI educational backend
│   ├── ai_server/                   # WebSocket AI server & MCP stdio bridge
│   ├── frontend/                    # React 18 + Vite + Tailwind CSS web application
│   ├── data/                        # Bundled tokenizer assets (Qwen3, Qwen2.5, Whisper)
│   ├── tests/                       # 102 isolated unit tests & demo fixtures
│   └── requirements.txt             # Portal Python dependencies
└── connector/                       # WeWIN Centre & Knowledge Base
    ├── src/                         # Core API, crawler, media registry & device store
    ├── frontend/                    # WeWIN Centre management web interface
    ├── data/                        # wewin_knowledge.json seeds
    ├── deploy/                      # Linux service templates & startup specs
    ├── scripts/                     # Token rotation & maintenance utilities
    ├── tests/                       # Unit tests & security regression suite
    └── requirements.txt             # Connector Python dependencies
```

---

## 🔒 Security & Privacy Notice

- **No Secrets in Version Control**: `.env`, tokens, private keys, certificates, and production SQLite stores are strictly excluded by `.gitignore`.
- **Offline Self-Containment**: The codebase operates safely without network dependencies or external proprietary cloud models for core educational workflows.
- **Role-Based Access Control**: Strict segregation between Admin, Teacher, Student, and Guardian roles.
- **Fail-Closed Gateways**: Physical robot firmware flashing and hardware modifications are completely decoupled from this software platform.

---

## 📄 License & Attribution

Developed for **WeWIN Education Platform**. All rights reserved.
For internal deployment and authorized partner evaluations only.
