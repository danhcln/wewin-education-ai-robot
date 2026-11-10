# WeWIN Education Portal

Latest device evidence and observation approval:
[Monster Desk hardware connection evidence](WEWIN_MONSTER_DESK_HARDWARE_CONNECTION_EVIDENCE.md).
This separates historical staging PASS from current host/robot readiness.

Local FastAPI + React education portal, isolated from the existing Connector demo.

Current physical connection decision: [Monster Desk GO/NO-GO report](WEWIN_MONSTER_DESK_REAL_CONNECTION_GO_NO_GO.md).
Private-CA TLS/WSS staging is available; real robot cutover remains **NO-GO**.

Independent WeWIN Agent/device registration, bootstrap and binding are now part
of the existing Portal. See [migration report](WEWIN_INDEPENDENT_ROBOT_PLATFORM_MIGRATION.md)
for tested staging behavior and the **NO-GO** gate before real Monster Desk cutover.

Open **http://127.0.0.1:8001/** after running:

```powershell
Set-Location 'E:\WeWIN_Firmware_Lab\wewin_education_portal'
.\Start-WeWIN-Education.ps1 -OpenBrowser
```

For setup use `Setup-WeWIN-Education.ps1`; stop only this runtime using `Stop-WeWIN-Education.ps1`.

First admin sign-in uses the existing Connector credential through “Đăng nhập quản trị Connector”. Create ordinary Portal accounts in Settings. No credential is hardcoded in the frontend. QA credentials in tests/qa_server.py only exist in the separate disposable QA database.

Robot saves return `saved_backend_only`. Cloud apply, wake-word deployment, Bluetooth and robot streaming remain unsupported until authorized adapters and acknowledgments are verified. No firmware changes are made.

See [implementation and acceptance report](WEWIN_EDUCATION_PORTAL_IMPLEMENTATION_REPORT.md), [API inventory](docs/API.md), [image analysis](docs/GM_BOT_REFERENCE_ANALYSIS.md), and [.env.education.example](.env.education.example).

Validation:

```powershell
python -m unittest discover -s tests -v
Set-Location frontend
npm run build
```

Robot/role workflow update: [Cloud integration acceptance report](WEWIN_ROBOT_AI_CONFIG_CLOUD_INTEGRATION_REPORT.md) and [official connection requirements](docs/ROBOT_AI_CLOUD_CONNECTION.md). Cloud read/write remains blocked until an authorized provider implementation and Agent mapping are verified.

Self-hosted staging: [implementation report](WEWIN_SELF_HOSTED_AI_ROBOT_IMPLEMENTATION_REPORT.md), [runbook](docs/self-hosted/RUNBOOK.md), and [physical connection gate](docs/self-hosted/ROBOT_CONNECTION_GATE.md). AI service runs independently at 8010; no robot endpoint or firmware change is authorized by staging tests.

Monster Desk preflight: [connection readiness and GO/NO-GO](WEWIN_REAL_ROBOT_CONNECTION_READINESS_REPORT.md).
27 AI service tests, 40 Portal tests, real-engine simulator traces and isolated
Chrome QA are complete. 8010 runs the hardened AI source with startup commit/hash
proof. Three local models were evaluated on 31 cases each; none is accepted for
unsupervised education. Physical migration remains gated on actual TanDev
identity/transport, supported provisioning/authentication and verified rollback.
