# VPS preparation — chưa deploy

**2026-11-09 migration update:** current Compose/Caddy remains a simulator-only
blueprint. It is NOT the approved physical-device deployment. Keep
`WEWIN_AI_ALLOW_REAL_DEVICES=0` and `WEWIN_AI_TRUST_TLS_EDGE=0`. A separate persistent
`ai_device_issuer_key` secret mount is now required; never generate it in a
read-only `/run/secrets` directory or silently replace it during recovery.

Before physical service, deploy the device-only edge beside the loopback control
service on a WeWIN-owned host; terminate TLS/WSS with a real approved hostname and
valid ESP32-trusted certificate. Trust proxy scheme headers only from that local
terminator, overwrite client TLS-marker headers, and keep `/v1/*` private behind
VPN/ingress authorization. Disable access/error/request-body logging for bootstrap
capability URIs on EVERY proxy/monitor; application redaction cannot protect
upstream logs. Use one AI worker; connection/revocation state is process-local.
Reviewers must test forged forwarded headers, management non-exposure, timeout,
certificate chain, DNS, reconnect and revocation from the target Wi-Fi before
enabling physical flags. The existing public `/v1/*` bearer-protected blueprint
must be replaced by that private management ingress before production. No domain,
TLS certificate, VPS allocation, Docker build or production deployment was done.

Staging đang chạy trên Windows/laptop. Muốn laptop tắt mà robot vẫn hoạt động,
cần deploy và nghiệm thu Portal + AI + model provider + public knowledge trên
hạ tầng luôn bật. Không có deployment, DNS, firewall, TLS hoặc thay thiết bị
trong phiên này. Docker/daemon không có trên host, các image/Compose chưa build
hoặc chạy: **NOT TESTED ON LINUX/VPS**.

`scripts/prepare_vps_context.py` tạo thư mục context mới trong artifacts, chỉ
copy source/backend/frontend build và Connector src. Không gửi network, không
copy secret, DB, model hoặc backup firmware. Chạy build frontend trước khi tạo
context. Copy yêu cầu dependency và license notices cùng bản bàn giao.

Blueprint Compose có Portal, AI, Ollama và Caddy. AI và Portal có SQLite volume
riêng; không publish 8000/8001/8010/11434 trực tiếp, chỉ proxy 80/443. Portal gọi
AI qua origin HTTPS; không mở rộng allowlist của adapter để chấp nhận HTTP ngoài
loopback. Operator phải cung cấp hostname/DNS/TLS thật và pinned image digests;
placeholder `.invalid` cùng các trường bắt buộc ngăn deploy nhầm mặc định.

Secrets là file mount `/run/secrets`, không build arg/env plaintext frontend.
Key quản lý AI và Portal bootstrap khác nhau. Device token khác key quản lý.
Giới hạn management API bằng VPN/ingress policy trước production. Cần kiểm tra
non-root UID10001 đọc được file secrets/models và ghi được named volumes.
Không tự chmod/giảm quyền hoặc sửa firewall để làm demo chạy.

Prerequisites cần chuẩn bị và nghiệm thu riêng:

- Linux startup/dependency closure, Dockerfiles, Compose interpolation và health
  checks thực; Windows dependency lock không phải chứng nhận Linux wheel install.
- Public knowledge snapshot hợp lệ với publication policy; registry snapshot có
  đúng schema/metadata và timestamp. Không upload DB session/auth của Connector.
  Chưa export dữ liệu học sinh hoặc production DB. Read-only mount không thay
  thế bước dùng SQLite backup nhất quán thay vì copy live WAL files.
- Whisper/Supertonic model files và license; Ollama model được provision trước.
  Ollama Docker mới có volume rỗng, không mặc định có `qwen3:4b`. Không tải model
  hoặc chạy pull trong startup để giả lập readiness.
- Endpoint reachability từ Wi-Fi robot, TLS/WSS certificates, auth và physical
  enrollment review. `WEWIN_AI_ALLOW_REAL_DEVICES=0` trong blueprint, giữ nguyên.
- HA, key rotation/revocation, per-tenant quotas, encrypted backups, log rotation,
  retention/deletion cho dữ liệu học sinh và monitoring/alerts thực. Hiện một
  worker/SQLite/turn slot là staging, không hứa scale-out.
- HTTP health và provider health tách nhau: `/health` ok không chứng minh model,
  ASR/TTS, MCP hoặc robot đã hoạt động. Theo dõi stage timings, errors, connected
  simulator/physical loại riêng, queue/CPU/RAM/disk và Opus playback counters.

Resource planning: host nghiên cứu có khoảng 16 GB RAM, 8 logical threads;
qwen3:4b weights khoảng 2.50 GB và inference quan sát dùng GPU qua Ollama. Một
giả thuyết khởi điểm để benchmark là 4–8 vCPU/16 GB RAM hoặc GPU phù hợp, SSD đủ
model/DB/backup; **chưa đo CPU-only VPS hoặc capacity nhiều robot**. Độ trễ đã đo
ở laptop không chuyển thẳng thành SLA. Chi phí phụ thuộc CPU/GPU/RAM, disk,
bandwidth và số hội thoại; không có báo giá nhà cung cấp, không phát sinh mua
hoặc thanh toán hạ tầng trong phiên này.

MQTT/TLS/UDP/NAT chưa được triển khai: không mở 1883/8883 hoặc UDP range chỉ vì
repo khác hỗ trợ. Nếu factory bắt buộc transport này, cần triển khai/đánh giá
server thích hợp, thiết kế auth/key/nonce/sequence replay và NAT trước approval.

Recovery: lưu source SHA, image digests, SQLite backup và secret backup riêng;
khôi phục vào staging khác để kiểm schema/revisions trước cutover. Source
rollback không được ghi đè DB mới hoặc hồi sinh credentials revoked. Về Cloud
factory là checklist khác trong ROBOT_CONNECTION_GATE, chưa được thực hiện.
