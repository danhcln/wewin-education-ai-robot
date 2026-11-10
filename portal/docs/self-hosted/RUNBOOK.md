# WeWIN AI staging runbook

Chạy tại `E:/WeWIN_Firmware_Lab/wewin_education_portal`. Portal giữ port 8001;
AI service riêng tại 127.0.0.1:8010; QA Portal tách DB ở 8002. Không dùng port
8000 của Centre. Đây là staging loopback, không phải server robot/VPS đã nghiệm thu.

## Chạy trên máy hiện có

```powershell
.\Setup-WeWIN-AI.ps1 -DownloadMultilingualASR
.\Start-WeWIN-AI.ps1
.\Start-WeWIN-Education.ps1
```

Python 3.12 của AI tách `.venv-ai` khỏi Python 3.14 `.venv` Portal. Setup chỉ
cài requirements do WeWIN khai báo; không chạy installer upstream. TTS dùng
Supertonic 3 model đã có trong `~/.cache/supertonic3`; nếu máy khác chưa có,
cần provision đủ ONNX/config/voice styles từ nguồn model chính thức theo license,
không tự tải khi khởi động. ASR multilingual download helper pin commit
`ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66`; nếu chưa tải thì fallback cache
Whisper base.en chỉ hỗ trợ tiếng Anh. Không có fixture thay ASR/LLM/TTS.

Ollama đang chạy ở 11434 với `qwen3:4b`; chỉ đọc catalog và dùng model đã cài,
không sửa model/template/service hiện có. Structured output ràng buộc final reply;
không đọc phần suy luận thành tiếng. Chất lượng câu trả lời 4B chưa được nghiệm
thu giáo dục; đã quan sát một bản dịch nghĩa “apple” quá rộng/sai. Cần model và
bộ eval phù hợp trước dùng với học sinh. Không xem pipeline PASS là content PASS.

Windows libopus được tìm từ bản `python-client/libs/libopus/win/x64/opus.dll`
trong thư mục references đã pin; có thể đặt `WEWIN_AI_OPUS_DIR` tới bản libopus
được operator provision. Linux dùng libopus hệ thống. PyAV resample PCM,
libopus mã hóa/giải mã, faster-whisper ASR, Supertonic ONNX TTS: không viết lại
engine. Rate VAD: mono PCM16, 20 ms subframes; kết thúc sau 900 ms silence.

## Secrets và cấu hình

`Start-WeWIN-AI.ps1` tạo key ngẫu nhiên mới tại `.secrets/ai_admin_key` nếu chưa
có. Không có default key/password. Portal backend đọc cùng file; key không đi
qua frontend, query string hoặc Git. Một key này quản lý staging riêng, không
phải token MCP/XiaoZhi. Mỗi simulator/device có token riêng, server chỉ lưu hash.
File key cần operator giữ ACL/private backup phù hợp; không đưa vào source bundle.

| Biến | Mục đích |
| --- | --- |
| `WEWIN_AI_ORIGIN` | Portal backend → AI origin; default loopback HTTP 8010, VPS cần HTTPS |
| `WEWIN_AI_ADMIN_KEY_FILE` | File key backend/service, default `.secrets/ai_admin_key` |
| `WEWIN_AI_DB` | SQLite riêng AI, default `data/ai-staging.sqlite3` |
| `WEWIN_AI_ASR_MODEL` | Thư mục Whisper local hoàn chỉnh, không phải tên Cloud |
| `WEWIN_AI_TTS_MODELS` | Thư mục Supertonic ONNX/voice styles |
| `WEWIN_AI_OLLAMA` | Ollama private backend, default loopback 11434 |
| `WEWIN_AI_PUBLIC_WS` | URL discovery trả cho client, default loopback; không đặt vào robot trong task này |
| `WEWIN_AI_CONNECTOR_DB` | Public knowledge database chỉ đọc |
| `WEWIN_AI_PROVIDER_TIMEOUT` | Timeout LLM hữu hạn, default 90s |
| `WEWIN_AI_ALLOW_REAL_DEVICES` | Default tắt; KHÔNG bật trước phê duyệt kết nối thiết bị |

Staging hỗ trợ tối đa 8 connections, một speech worker/turn slot, một Uvicorn
worker. Không chạy nhiều worker/process với chung runtime cache để coi đó là
scale-out. SQLite durable revisions/operation IDs hỗ trợ restart và CAS; HA,
distributed sessions/queue, retention và production TLS còn là gate riêng.

## Dùng Portal

Admin → Robot → Cloud/MCP → WeWIN AI Server → chọn đích staging và xác nhận.
Điều này chỉ ghi liên kết Portal, chưa tạo Agent hoặc đổi thiết bị. Chọn role
hoặc cấu hình → tạo candidate → xem target Agent/revision/diff → xác nhận
“Áp dụng WeWIN AI Server”. Backend nạp runtime rồi GET readback, so sánh đúng
profile/revision/hash trước lưu `server_applied_verified`. Simulator không tạo
`device_session_verified`. XiaoZhi/TanDev Cloud ngoài vẫn khóa và hiển thị riêng.

Model/voice/language lấy catalog thật. Những trường voice gender/speech style,
lesson/knowledge/path/media/student binding cũ chỉ giữ metadata local; chỉ các
PROFILE_FIELDS trong adapter được gửi/so sánh trên AI server. TTS speed 0.7–2.0.
Không tuyên bố đã nạp một lesson chỉ từ ID binding.

Mỗi turn reload revision; đổi role làm sạch history cũ ở turn tiếp theo. Turn
đang nói giữ snapshot cũ. Output gửi raw Opus 24 kHz/60 ms có pacing; hiện ASR,
LLM và TTS là xử lý từng lượt đầy đủ, chưa token/sentence streaming hoặc full
duplex AEC. Abort dừng output/task; native CPU inference đã bắt đầu có thể hoàn
tất nền, speech executor một worker ngăn nhiều inference đồng thời.

## Tests có phân loại rõ

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv-ai\Scripts\python.exe -X utf8 -m unittest discover -s ai_server/tests -v
Set-Location frontend
npm run build
```

Automated service/Portal adapter tests dùng test doubles được đặt tên rõ;
không tính là live pipeline. `ai_server.simulator` là client mô phỏng, dùng
actual local speech/LLM/Opus; không tự áp dụng lên physical device. Có helper
`scripts/staging_apply_role.py` chỉ chấp nhận QA Portal 8002 và DB riêng.

## History, rollback, lỗi

History/Restore Portal luôn tạo desired version mới local. Muốn rollback AI
runtime: khôi phục desired version, tạo **candidate mới với target revision hiện
tại**, kiểm diff và xác nhận Apply riêng. Không tự ghi rollback sau timeout.
Server PUT có expected_revision và operation ID idempotent; readback mismatch,
auth/provider timeout hoặc local CAS conflict không được thành verified. Nếu
remote đã ghi mà local commit conflict, desired mới hơn giữ nguyên và job fail;
đọc lại server trước quyết định tiếp. Không retry write tự động. User reconfirm
cùng candidate dùng cùng operation ID; job applying dưới 180s chặn song song,
job quá hạn có thể reconfirm an toàn trong TTL bằng cùng idempotency key.

Tắt liên kết Portal không xóa Agent hoặc đổi robot; Cloud ngoài trở về unsupported.
Dừng AI bằng `Stop-WeWIN-AI.ps1` chỉ tác động owned process. Source rollback về
`8748d85` cần bản sao DB trước schema v6; không reset dữ liệu thật hoặc chạy mã
cũ với schema mới rồi coi là recovery PASS. Backup consistency dùng SQLite backup,
không copy live WAL DB. Không rollback lại revoked identity/credential.

## Disposable connection preflight

Xem [readiness report](../../WEWIN_REAL_ROBOT_CONNECTION_READINESS_REPORT.md) trước
khi dùng harness. Không dừng runtime 8001/8010 sẵn có. Khi 8002/8011 trống, mở hai
terminal riêng tại Portal root:

```powershell
# Terminal A
.\.venv-ai\Scripts\python.exe scripts/preflight_server.py ai
# Terminal B
.\.venv\Scripts\python.exe scripts/preflight_server.py portal
```

Harness khóa physical enrollment, dùng DB/key trong ignored
`artifacts/connection-preflight/`, không đổi môi trường của process production.
Dừng bằng Ctrl+C chỉ trong hai terminal này khi client đã xong. Không dùng QA DB,
credential hoặc endpoint loopback để provisioning robot.

`factory_connection_evidence.py` chỉ phân tích backup offline, không dùng serial.
`evaluate_staging_ai.py` chạy engine thật và lưu synthetic audio/transcript;
`check_preflight_ui.py` cần optional `playwright==1.58.0` và Chrome đã cài, dùng
context mới. Script UI có login/logout main 8001 (session/audit), mọi link/apply
chỉ 8002. Nó reset link fixture QA khi chạy lại; không chạy chồng các harness.
`capture_preflight_baseline.py` chỉ chạy trước lần kiểm tra để giữ baseline mới;
`verify_preflight_protection.py` so sánh hashes và các bảng nghiệp vụ sau đó.
Không gọi capture lần nữa để che thay đổi. Không commit artifacts/secret/model.

## Audited 8010 update and source recovery

8010 was restarted for source `b4318f0`; `/health.build` is a startup snapshot
of commit, AI source hash, PID, Python/Uvicorn and dirty state. Admin-only
`/v1/runtime` reports effective DB/provider/model directories, not secret values.
Current Agent config hash and effective prompt hash are separate; code-policy
updates can change the latter while preserving the saved config.

For another authorized staging update, create a **new** snapshot directory:

```powershell
.\.venv-ai\Scripts\python.exe scripts/snapshot_ai_staging.py --out artifacts/staging-next/restart-backup
.\Restart-WeWIN-AI-Staging.ps1 -BackupDirectory E:\WeWIN_Firmware_Lab\wewin_education_portal\artifacts\staging-next\restart-backup
```

The snapshot refuses overwrites and verifies idle/physical-disabled state,
default key, API/database Agent agreement and no main Portal staging links.
Commit and test AI source before restart. The restart command refuses stale Agent
baseline, wrong PID/start time/root, external backup path or unexpected launch
paths. Original Portal/Ollama/Centre/MCP are never restart targets.

Recovery source de081ad is extracted in the snapshot, with absolute original
DB/key/ASR/TTS/Opus/MCP paths in its launch manifest. Startup failure may restore
that code with the same database/key; it does not silently restore an old DB.
The bundle also needs the pure `knowledge_policy.py` at the old checkout's
relative sibling path; snapshot now packages it with a hash receipt. The restart
guard refuses if that copy or the active privacy policy changed since snapshot.
A separate 8012 rehearsal with old code/copied DB verified health, preserved
Agent readback and real readonly MCP; the owned process was stopped afterwards.
Use `rehearse_source_recovery.py --out artifacts/<fresh-run>` to avoid overwriting
evidence. Direct MCP stdio must use UTF-8 as the normal MCPClient does.
The automatic fallback branch was prepared and parsed, **not live fault-injected**.
Controlled config rollback has been tested only on the owned simulator Agent,
as a new revision with expected revision/readback. Physical rollback remains gated.

`staging_connection_suite.py` creates a uniquely named test Agent/device at
loopback 8010/8011, runs real speech/MCP/role/reconnect/error checks, restores its
test profile at a new revision and revokes the simulator credential. It does not
edit existing Agents. Education scripts use isolated Ollama 11435 and an ignored
E: model store; do not point them at 11434. See the current readiness report for
model scores, latency/resource caveats, tokenizer receipts and TTS limits.
For a new host, provision tokenizers explicitly with
`scripts/prepare_eval_tokenizer.py --family qwen3` (and `--family qwen2.5` if used).
Inference never downloads them. Without a supported local tokenizer, conservative
UTF-8 accounting can reject oversized required tool context instead of silently
truncating it; `/v1/runtime` reports local tokenizer availability.

## First-party WeWIN devices

Latest connection gate: WEWIN_MONSTER_DESK_REAL_CONNECTION_GO_NO_GO.md and
TLS_STAGING.md. Main device origin is now private-CA HTTPS8014; do not use the
older HTTP-origin examples as a physical or managed-TLS enrollment procedure.
After TLS pinning, source82e053d or security-compatible newer code is required for
recovery. Missing environment must fail closed; it is not permission to clear a
device's persisted TLS policy. Copy DB/issuer/TLS keypair with current revoke ledger.

See `WEWIN_INDEPENDENT_ROBOT_PLATFORM_MIGRATION.md` for the current migration gate.
Use existing Robot Management → Add Robot WeWIN → ownership attestation → Apply
Role/config (review and confirm) → Device Gateway → provision simulator. Treat
the displayed bootstrap URL as a credential. It is not retrievable after closing;
use explicit rotate if lost. Do not paste it in chat or tickets. No real Monster
Desk identifiers are prefilled or inferred from legacy wire IDs.

`Start-WeWIN-Device-Edge.ps1 -BindAddress <verified-private-IP>` starts only port8013
with a physical-disabled backend; `-BackendPort 8011` is for disposable QA.
`Stop-WeWIN-Device-Edge.ps1` checks recorded PID/start-time/command ownership.
No firewall rules are opened. Set AI `WEWIN_AI_DEVICE_ORIGIN` to the matching
reachable edge address BEFORE AI startup. Loopback legacy discovery is only for
old simulators. Real bootstrap cannot return loopback and is blocked today.

Back up SQLite with its online backup API, management key, **device issuer key**,
source fingerprint and provider configuration together into private/encrypted
storage. Do not copy live WAL files as a backup. Rehearse on separate DB/port;
verify Agent revisions/hashes, owner/tenant, binding_version, expiration and
revocation before serving requests. Restoring an old DB can revive a revoked
credential: reconcile the latest revocation ledger and rotate affected keys
before opening ingress. Never downgrade to a pre-ownership service after managed
enrollment. The legacy automatic source-recovery helper refuses snapshots with
managed devices; it is not a general enrolled-device disaster-recovery solution.

The independent QA suite only targets 8002/8011 plus host LAN8013; it creates and
revokes its own simulator. `scripts/verify_independent_protection.py` compares this
migration's fresh protected-file/business-table/Agent baseline. Physical endpoint,
NVS, OTA partitions, wake word, Bluetooth and firmware remain outside this runbook's
authorization. Keep physical issuance disabled until the separate cutover review.
