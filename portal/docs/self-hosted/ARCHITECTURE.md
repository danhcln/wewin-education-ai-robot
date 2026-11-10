# WeWIN self-hosted staging decision — 2026-11-08

Decision before implementation: option C, bounded Python Gateway using proven
FastAPI/WebSocket, libopus, faster-whisper, Ollama and Supertonic libraries.
This is an independent service/SQLite database, not a replacement Portal or an
assumption that factory TanDev firmware equals public XiaoZhi firmware.

Option A (embedding the full xinnan Python server) brings a global configuration,
ConnectionHandler and a large pinned Python 3.10 dependency graph (torch 2.2.2,
numpy 1.26.4, websockets 14.2, multiple cloud SDKs). This conflicts with the current
Portal Python 3.14 environment. Option B (separate full upstream stack) has the
best breadth, but manager-api is Java/Shiro/MySQL/Redis and manager-web is another
frontend. Keep it as the fallback if verified TanDev requires MQTT/UDP or an
unsupported protocol version. Do not start either upstream installer.

Option C is selected for a real, testable staging vertical slice with one Python
service and existing React/FastAPI/SQLite Portal. It implements the documented
WebSocket v1 path first. MQTT/UDP, public firmware activation/eFuse challenges,
device provisioning, Bluetooth control and firmware delivery remain unsupported.
No firmware/assets URL is ever offered by staging discovery.

Portal candidate + user confirmation -> authenticated management API -> validated
immutable agent revision -> runtime profile -> GET readback/hash ->
server_applied_verified. A simulator session records simulator evidence only.
device_session_verified requires physical enrollment and physical conversation
evidence; real-device enrollment remains disabled for this task.

Runtime: authenticated device -> hello -> listen/audio Opus -> ASR -> LLM with
bounded read-only MCP tools -> TTS -> paced raw Opus -> tts stop. Abort and
disconnect cancel the turn; a new turn reloads the applied revision and clears
old-role dialogue. No custom speech engine, no credentials in the frontend.

Source research, licenses and exact commits are recorded in the implementation
report. No quantitative cross-server latency/CPU claim is made without comparable
benchmarks. Separate services isolate failure; loopback staging is not a VPS
deployment or proof of robot reachability.
