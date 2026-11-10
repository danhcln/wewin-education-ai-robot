# WeWIN Platform - Security Policy & Hardening Guide

## 1. Zero-Secrets Policy

The **WeWIN Education AI Robot Platform** strictly enforces a zero-secrets policy across the version-controlled repository:
- **No Private Keys, Passwords, or API Tokens in Git**: All credentials must be injected at runtime via environment variables or stored in the restricted local directory `.secrets/`.
- **Pre-Push Automated Scans**: Before code is pushed to remote repositories, regex-based entropy and keyword secret scans are executed.
- **Strict `.gitignore`**: Blocks `.env`, `*.key`, `*.pem`, `*.token`, `*.db`, `*.sqlite3`, and `.secrets/`.

---

## 2. Local File System & Directory Hardening

### The `.secrets/` Directory:
- Located at `connector/.secrets/`.
- Automatically created with restricted Windows NT ACLs (accessible only by the process owner).
- File permissions are set to `0o600` on POSIX systems.
- Production databases (`browser-sessions.sqlite3`) and rotated admin tokens (`admin_sync_token`) are strictly isolated to this folder.

### Secret Redaction in Logs:
- All loggers in `src/utils/logger.py` and `portal/backend/` pass through a redaction filter.
- Tokens, passwords, and authorization headers matching regex patterns `(token|bearer|key|secret)=([^\s&]+)` are masked with `[REDACTED]`.

---

## 3. Physical Hardware & Firmware Protection

- **Decoupled Architecture**: Software applications in this repository **cannot** flash, erase, or alter ESP32-S3 firmware, eFuses, or OTA partitions.
- **Fail-Closed Staging**: Robot connection endpoints default to simulator mode (`WEWIN_AI_ALLOW_REAL_DEVICES=0`). Real physical hardware connections require explicit, verified operator confirmation.

---

## 4. Reporting Security Vulnerabilities

If you discover a security vulnerability, please report it privately to the security team at **security@wewin.edu.vn**. Do not open public GitHub issues for sensitive security findings.
