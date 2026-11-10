# WeWIN Phase 6A — bộ chuẩn bị Linux, chưa triển khai

Ngày 26/10/2026. Tất cả lệnh dưới đây là quy trình cho Phase 6B **sau phê duyệt**.
Không chạy lệnh cài đặt/service/timer trên máy hiện tại. Windows Task và hai cờ lịch vẫn tắt.

## Điều kiện trước chuyển đổi

- Một VPS Linux dùng systemd, Python 3.12 trở lên, ổ đĩa cục bộ bền vững, hỗ trợ SQLite FTS5. Khởi điểm đề xuất: 2 vCPU, RAM 2–4 GiB, SSD 40 GiB; đây là dự toán kỹ thuật, chưa benchmark hoặc cam kết tải.
- Chốt nhà cung cấp, vị trí, SSH key, quyền quản trị, hostname/TLS và nơi giữ backup ngoài máy. Không gửi secret trong chat hoặc commit repository.
- Linux startup, `flock`, systemd hardening, reboot/reconnect và cài wheel chưa được thực thi trên máy Windows này. Không có WSL/Docker sử dụng được. Đây là các cổng nghiệm thu bắt buộc của staging.
- Đóng P0 phân quyền: chạy kiểm thử ACL và đối chiếu kho đã phân loại. Ba Playbook cùng các trang internal/review phải không xuất hiện trong search/page/MCP/export công khai.
- Xác nhận thông tin chương trình/liên hệ hardcode với chủ nội dung; không coi dữ liệu đó là bằng chứng mới tải từ website.

## Bố trí và quyền truy cập

```
/opt/wewin/releases/<release>/     source + frontend/dist, root:root, read-only cho service
/opt/wewin/current                symlink phiên bản được duyệt
/opt/wewin/venv                   Python environment khóa phiên bản
/etc/wewin/server.env             root:wewin 0640, không chứa giá trị secret
/etc/wewin/admin_token            root:wewin 0640
/etc/wewin/xiaozhi_endpoint        root:wewin 0640 (URL có thể chứa token)
/etc/wewin/xiaozhi_token           root:wewin 0640 (có thể là file rỗng nếu token nằm trong endpoint)
/var/lib/wewin/                   wewin:wewin 0700, SQLite/WAL/SHM/guard/heartbeat/export
/var/backups/wewin/               wewin:wewin 0700, backup không phục vụ qua HTTP
```

Tạo user hệ thống `wewin` không shell đăng nhập. Không dùng NFS hoặc nhiều host ghi chung SQLite.
Không copy `.env`, `.secrets`, `.maintenance`, database, logs hoặc thư mục backup vào frontend/dist.
Không dùng JSON 4 record để khởi tạo lại kho dữ liệu. Bảo vệ cả WAL/SHM và bản backup như nội dung nội bộ.

## Dependency và kiểm thử staging

`requirements-linux.lock` khóa toàn bộ dependency runtime hiện có, đánh giá marker cho Linux/Python 3.12; **chưa xác nhận tải/cài wheel trên Linux**. Không phải lock đã kiểm chứng supply-chain bằng hashes. Lưu thêm SHA256 artifact/wheelhouse khi dựng release trên staging.

Sau phê duyệt, trong môi trường staging riêng:

```sh
python3 -m venv /opt/wewin/venv
/opt/wewin/venv/bin/python -m pip install -r deploy/linux/requirements-linux.lock
/opt/wewin/venv/bin/python -m pip check
/opt/wewin/venv/bin/python -c 'import sqlite3; c=sqlite3.connect(":memory:"); c.execute("create virtual table t using fts5(body)")'
systemd-analyze verify deploy/linux/wewin-api.service deploy/linux/wewin-bridge.service deploy/linux/wewin-sync.service deploy/linux/wewin-sync.timer
systemd-analyze calendar '*-*-* 08:00:00 Asia/Bangkok' '*-*-* 20:00:00 Asia/Bangkok'
```

Chạy regression theo từng process trên DB tạm. Không chạy `unittest discover` với suite legacy chưa cô lập. Frontend dùng `npm ci` với package-lock hiện có rồi `npm run build`; không đổi thiết kế.
Bridge dùng `additional_headers`, ping/pong, giới hạn message 1 MiB, backoff 2–60 giây, tắt proxy tự nhận từ môi trường. Lock chọn websockets 16.0 đang cài trên Windows; API asyncio này được kiểm thử giả lập, kết nối XiaoZhi thật phải nghiệm thu riêng khi chuyển đổi.

## Chuyển dữ liệu và credential an toàn

1. Giữ Windows task Disabled và `AUTO_SYNC_ENABLED=false`, `SYNC_SCHEDULE_ARMED=false`. Dừng mọi writer, API và bridge cũ có kiểm soát trước chuyển active bridge; không để hai bridge cùng token kết nối đồng thời.
2. Tạo backup mới bằng SQLite Backup API; phục hồi thử và đối chiếu fingerprint, FTS, access tables. Sao chép file snapshot tự chứa qua kênh SSH bảo mật, không copy riêng database đang chạy WAL.
3. Đặt snapshot đã phân loại tại `/var/lib/wewin/wewin_fts.db`; giữ backup ngoài webroot. Không reset cursor55, history9, hoặc completed Backfill checkpoint.
4. Tạo các file secret bằng công cụ nhập kín/quản lý secret của người quản trị. Không đặt token trong command line, shell history, service unit hoặc log. Giữ nguyên XiaoZhi endpoint/token hiện tại qua file, không xoay token Cloud trong Phase 6A. Admin token riêng có thể xoay bằng cơ chế FIX01 sau khi người dùng chọn thời điểm.
5. Copy `server.env.example` thành `/etc/wewin/server.env`; điền đường dẫn, giữ lịch tắt và owner=external. Không đặt `.env` cũ trong release: `run_bridge.py` nay tôn trọng environment do service cung cấp.

## API, bridge và quản trị

API bind **127.0.0.1:8000**, một worker, không debug/reload, không access log chứa query. Bridge là service outbound riêng; không cần mở port inbound cho XiaoZhi. systemd tự restart process; heartbeat bridge chỉ chứa trạng thái/PID/thời gian, hết 45 giây coi Unknown. Robot/firmware vẫn Unknown nếu không có telemetry thiết bị.

Ban đầu dùng SSH tunnel hoặc VPN tới loopback. Không mở port8000/Control Center ra Internet.
Nếu Phase 6B phê duyệt HTTPS remote: reverse proxy TLS + VPN/IP allowlist hoặc identity gateway cho toàn bộ Control Center; `/api/auth/verify` có rate limit, body/request size limit, không log Authorization/query secrets; CORS chỉ hostname chính xác. Chặn `/ws/mcp` ở proxy; bridge outbound không cần endpoint này. Public API chỉ những route kiến thức đã duyệt, giới hạn request và pagination. Không coi bearer token đơn lẻ là đủ bảo vệ Internet admin.

Copy unit files vào `/etc/systemd/system`, daemon-reload, **chỉ start API trên staging trước**, xác minh:

```sh
/opt/wewin/venv/bin/python scripts/server_ops.py check --database /var/lib/wewin/wewin_fts.db
curl --fail http://127.0.0.1:8000/health
ss -lntp
```

Tại thời điểm chuyển bridge được duyệt mới start bridge, chạy `scripts/healthcheck.py` với environment đúng. Health script exit1 nếu bridge Unknown/disconnected, API hoặc FTS chưa đạt; không coi HTTP200 đơn lẻ là robot online.
`Restart=always` của bridge xử lý thoát bình thường; SIGINT giúp asyncio kết thúc và ghi disconnected. Hạn stop30s. API stop60s. Kiểm thử mất mạng/reboot, không để logs chứa token hoặc payload. Journald retention/rotation do người triển khai đặt hạn dung lượng và quyền đọc.

## Một scheduler owner

`wewin-sync.timer` là **template chưa enable/start**, không có `[Install]`. Trước Phase6B vẫn disabled và armed=false; service trigger systemd tự trả disabled trước mở DB/mạng.
Timer dự kiến 08:00/20:00 Asia/Bangkok, `Persistent=true` bắt lần bỏ lỡ, `WakeSystem=false`. Sau phê duyệt riêng việc bật lịch: thêm `[Install] WantedBy=timers.target`, giữ Windows task và FastAPI scheduler tắt, chọn owner external, đặt armed=true rồi mới enable timer. Persistent có thể chạy ngay sau bật nếu bỏ lỡ lịch; phải sẵn sàng trước thao tác này.

Một job giữ OS flock trên `sync.lock.guard`; không xóa/replace guard để unlock. Job dài không bị timeout tuổi khóa. Stop hợp tác và checkpoint mỗi URL; crash có thể lặp tối đa URL giữa commit và checkpoint, upsert không mất trang. Một service oneshot đang chạy không sinh instance song song; khóa backend vẫn chặn CLI/API.

Batch đề xuất20, delay>=2.05s và tuân thủ robots, retry hữu hạn, circuit sau3 HTTP429/5xx, bảo toàn cache khi lỗi. Cursor vòng luân phiên giữ manifest cố định. Initial Backfill đã hoàn tất là lượt nạp riêng; incremental hai lần/ngày chưa đáp ứng SLA làm mới toàn bộ436 URL mỗi ngày. Chọn SLA và budget sau đo staging; không tự tăng tần suất.

## Backup/restore và rollback

Chạy dưới user wewin với environment đúng; thư mục backup0700. Mỗi snapshot dùng tên mới. Có thể backup online bằng API SQLite; bản khôi phục thử vẫn chỉ là bản sao. Giữ7 ngày +4 tuần là gợi ý khởi đầu, chỉ xóa sau khi có bản sao off-host và restore-test đạt; chưa tạo lịch retention trong Phase6A.

```sh
/opt/wewin/venv/bin/python scripts/server_ops.py backup --database /var/lib/wewin/wewin_fts.db --snapshot /var/backups/wewin/approved-timestamp.db
```

Lệnh tự tạo `approved-timestamp.db.restore-check`, integrity/FTS và fingerprint access tables. Không tự ghi đè snapshot hoặc xóa WAL/SHM.
Rollback source: dừng timer, sync/API/bridge; backup trạng thái mới; chuyển `current` về release tương thích ACL. **Không phục hồi source trước Phase6A rồi phục vụ công khai** vì sẽ bỏ chặn Playbook.
Rollback DB chỉ khi mọi reader/writer đã dừng; khóa sync không thay việc dừng API/bridge:

```sh
/opt/wewin/venv/bin/python scripts/server_ops.py restore --database /var/lib/wewin/wewin_fts.db --snapshot /var/backups/wewin/approved-timestamp.db --safety-backup /var/backups/wewin/pre-rollback-new-timestamp.db --services-stopped
```

Helper từ chối live sync, tạo safety backup mới, dùng Backup API ghi vào SQLite, không copy đè WAL. Chỉ nhận snapshot có ACL/FTS hợp lệ. Snapshot trước Phase6A cần migrate trên bản sao trước khi phục vụ hoặc giữ backend tắt hoàn toàn.
Sau restore kiểm tra số trang/FTS/public, URL internal bị404, search tiếng Việt/Anh, MCP initialize/list/call local, secret hashes và scheduler vẫn tắt. Chỉ khởi động lại theo phê duyệt, không bật timer như tác dụng phụ của rollback.

## Tài liệu đối chiếu

- [SQLite Online Backup API](https://www.sqlite.org/backup.html): snapshot nhất quán, không dùng filecopy của DB live.
- [SQLite WAL](https://www.sqlite.org/wal.html): WAL là một phần trạng thái SQLite, cần filesystem cục bộ phù hợp.
- [systemd timer](https://www.freedesktop.org/software/systemd/man/257/systemd.timer.html): Persistent và WakeSystem độc lập.
- [websockets asyncio client](https://websockets.readthedocs.io/en/15.0.1/reference/asyncio/client.html): additional_headers, proxy và giới hạn kết nối. Kiểm tra signature thực tế cùng locked16.0 trên staging.
