# WeWIN Education AI Robot Platform - Environment Variables Reference

All environment variables can be set in the system environment or defined in a `.env` file at the repository root.

---

## 1. Network & General Service Variables

| Variable | Default Value | Required | Description |
| :--- | :--- | :--- | :--- |
| `WEWIN_BIND_ADDRESS` | `127.0.0.1` | No | IP address to bind FastAPI services to. Use `127.0.0.1` for local safety. |
| `WEWIN_PORTAL_PORT` | `8001` | No | Listening port for the WeWIN Education Portal. |
| `WEWIN_CENTRE_PORT` | `8000` | No | Listening port for the WeWIN Centre Connector. |
| `WEWIN_AI_PORT` | `8010` | No | Listening port for the WeWIN AI Server. |
| `WEWIN_DEVICE_EDGE_PORT` | `8013` | No | Port for local hardware test bench TLS edge. |

---

## 2. WeWIN Education Portal Variables

| Variable | Default Value | Required | Description |
| :--- | :--- | :--- | :--- |
| `WEWIN_EDUCATION_DB` | `portal/data/education.sqlite3` | No | Path to the SQLite storage file for portal users, lessons, and progress. |
| `WEWIN_TESSERACT` | `C:\Program Files\Tesseract-OCR\tesseract.exe` | No | Absolute path to Tesseract OCR executable for scanning student homework. |
| `WEWIN_OCR_LANGUAGE` | `eng+vie` | No | Language models for Tesseract OCR. |
| `WEWIN_AI_BASE_URL` | *(empty)* | No | Base URL of upstream LLM provider (OpenAI-compatible `/v1`). |
| `WEWIN_AI_MODEL` | *(empty)* | No | Model name (e.g., `gpt-4o`, `qwen2.5-7b`) for upstream LLM. |
| `WEWIN_AI_API_KEY` | *(empty)* | No | API key for upstream LLM provider. Never commit to Git. |
| `BROWSER_SESSION_STORE`| `connector/.secrets/browser-sessions.sqlite3` | No | Path to the device store. Automatically falls back to fixture if absent. |

---

## 3. WeWIN Centre Connector Variables

| Variable | Default Value | Required | Description |
| :--- | :--- | :--- | :--- |
| `DATABASE_PATH` | `connector/data/wewin_fts.db` | No | Path to the SQLite FTS5 knowledge database. |
| `KNOWLEDGE_JSON_PATH` | `connector/data/wewin_knowledge.json` | No | Path to the curated seed data for WeWIN courses and programs. |
| `ADMIN_SYNC_TOKEN` | *(empty)* | No | Secret bearer token for administrative syncing and device registration. |
| `ADMIN_SYNC_TOKEN_FILE`| `connector/.secrets/admin_sync_token` | No | Preferred alternative to `ADMIN_SYNC_TOKEN`. Reads token from file. |
| `XIAOZHI_MCP_ENDPOINT`| *(empty)* | No | WebSocket/HTTP endpoint of the XiaoZhi MCP broker. |
| `XIAOZHI_MCP_TOKEN` | *(empty)* | No | Authentication token for the XiaoZhi MCP broker. |
| `MEDIA_BACKEND_URL` | `http://127.0.0.1:8000` | No | HTTP loopback target for the media stream player. |
| `YOUTUBE_API_KEY` | *(empty)* | No | Optional YouTube Data API v3 key for educational playlist lookup. |

---

## 4. WeWIN AI Server Variables

| Variable | Default Value | Required | Description |
| :--- | :--- | :--- | :--- |
| `WEWIN_AI_PUBLIC_WS` | `ws://127.0.0.1:8010/xiaozhi/v1/` | No | Public WebSocket endpoint advertised to connected robots. |
| `WEWIN_AI_DEVICE_ORIGIN`| `http://127.0.0.1:8010` | No | Allowed HTTP origin for connected devices. |
| `WEWIN_AI_TOKENIZER` | `portal/data/ai-qwen3-tokenizer/tokenizer.json` | No | Path to local Qwen3 tokenizer JSON file. |
| `WEWIN_AI_QWEN25_TOKENIZER`| `portal/data/ai-qwen25-tokenizer/tokenizer.json`| No | Path to local Qwen2.5 tokenizer JSON file. |
| `WEWIN_AI_PROVIDER_TIMEOUT`| `90` | No | Timeout in seconds for upstream AI responses. |
| `WEWIN_AI_LLM_STREAM` | `1` | No | Enable streaming mode (`1` = true, `0` = false). |
| `WEWIN_AI_LLM_GPU_LAYERS`| `-1` | No | Number of GPU layers to offload (`-1` = all available layers). |
| `WEWIN_AI_ALLOW_REAL_DEVICES`| `0` | No | Gate for allowing physical robot connections (`0` = safe simulation only). |

---

## 5. Security Rules
- **Rule 1**: Variables ending in `_KEY`, `_TOKEN`, or `_SECRET` must NEVER be populated in sample files or checked into source control.
- **Rule 2**: Files in `.secrets/` are protected with restricted Windows file ACLs (accessible only by the running user).
