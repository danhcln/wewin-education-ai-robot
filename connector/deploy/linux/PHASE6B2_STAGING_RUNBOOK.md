# Phase 6B.2 — quy trình VPS staging

Ngày 26/10/2026. Người dùng xác nhận **chưa có VPS**, chỉ hoàn thiện quy trình và báo cáo. Toàn bộ lệnh Linux trong tài liệu này **chưa được thực thi**. Không dùng tài liệu như bằng chứng Linux PASS hoặc phê duyệt kết nối XiaoZhi Cloud/Phase 6B.3.

## 1. Điều kiện đầu vào

Thông tin cần cung cấp khi có máy được phép staging:

| Thông tin | Mục đích |
|---|---|
| IP/hostname, cổng SSH, username có sudo | Xác định đúng đích và quyền cài đặt |
| Đường dẫn SSH key đã có trên máy, hoặc SSH agent được chọn | Xác thực mà không gửi private key vào chat |
| Fingerprint host key từ console/bảng quản trị đáng tin | Xác minh máy chủ trước đăng nhập |
| OS/phiên bản/kiến trúc, CPU/RAM/SSD | Chọn đúng Python/wheel và ngân sách tài nguyên |
| IP/CIDR hoặc VPN quản trị, khả năng mở console cứu hộ | Giới hạn firewall, tránh mất quyền truy cập |
| Xác nhận host mới hay đã có dịch vụ/dữ liệu; cửa sổ restart/reboot | Bảo toàn cấu hình/dữ liệu có sẵn |
| Nơi backup ngoài máy, retention, người nhận cảnh báo | Phục hồi và vận hành |
| Hostname/TLS và cơ chế quản trị từ xa nếu có | Chỉ công khai sau khi được duyệt và kiểm thử |

Không gửi password, private key, JWT hoặc admin/Cloud token vào chat. Cloud token không phải điều kiện để bắt đầu staging bằng broker giả.

Đề xuất ban đầu, chưa benchmark:

- Ubuntu Server **24.04 LTS x86_64**, Python 3.12, systemd làm PID 1, filesystem ext4 cục bộ bền vững.
- Staging tải nhỏ: từ 1 vCPU/2 GiB RAM/20 GiB SSD; khuyến nghị2 vCPU/2–4 GiB/40 GiB. Chốt sau đo memory/CPU/disk và soak, không coi đây là SLA.
- Không cần GPU. Không dùng shared SQLite trên NFS hoặc nhiều VPS writer. Backup ngoài máy tách khỏi SSD chính.
- Wheelhouse hiện chuẩn bị cho CPython 3.12/x86_64/manylinux; không dùng nguyên bộ cho ARM64 hoặc Alpine/musl.

## 2. Các cổng nghiệm thu

| Cổng | Điều kiện trước khi đi tiếp |
|---|---|
| G0 — đích staging | Host và quyền thao tác được người dùng xác nhận; host key đã đối chiếu |
| G1 — môi trường | Ubuntu/arch/Python/systemd/filesystem đúng; SSH/firewall có phương án cứu hộ |
| G2 — gói/dữ liệu | SHA256 khớp; DB 257/255, public 235 / internal 7 / review 15, integrity/FTS/access metadata đúng |
| G3 — Linux ứng dụng | Cài/import dependency, health/API/MCP và22 URL hold PASS trên Linux thật |
| G4 — vòng đời service | Startup/restart/crash-recovery, quyền POSIX, WAL/flock, backup/restore và reboot PASS |
| G5 — Cloud production | Phê duyệt riêng; dừng bridge cũ, chuyển secret an toàn, chỉ một bridge production |
| G6 — lịch tự động | Chỉ đề xuất sau mọi test liên quan PASS; vẫn cần phê duyệt bật lịch riêng |

Trong lượt hiện tại G0 chưa có; G1–G5 chưa kiểm thử trên máy chủ. Không vượt cổng bằng kết quả Windows.

## 3. Bố trí gói chuyển giao

Gói được chuẩn bị trong thư mục `.maintenance` riêng, không nằm dưới static/webroot:

```
staging-package/
  source/wewin-source.zip          # source, unit, GUI build đã có; không chứa secret/DB
  private/wewin_knowledge_staging.db # snapshot đầy đủ 257 trang, dùng làm DB staging
  fixtures/wewin_before_fix02.db   # fixture 53 trang cũ chỉ cho regression, tuyệt đối không dùng làm DB ứng dụng
  wheelhouse/*.whl                 #23 wheel Linux/Python 3.12 từ lượt6B.1
  MANIFEST.json                    # phiên bản gói, từng file/hash, vai trò snapshot và expected counts
  SHA256SUMS                       # checksum để đối chiếu sau chuyển
```

Toàn bộ gói phải chuyển qua SSH đã xác minh danh tính và lưu trong thư mục 0700. `private` và `fixtures` chứa cả cache nội bộ nên không chia sẻ, không đưa lên web/CDN hoặc repository công khai. SHA256 kiểm tra tính toàn vẹn; nó không thay thế xác minh SSH host key.

Source được chọn bằng danh sách cho phép, không zip nguyên repository. Không có `.env`, `.secrets`, database, WAL/SHM, cache/JSON cũ, logs, node_modules hoặc backup bên trong source archive. Không tự build lại GUI trong lượt này.

## 4. Xác minh SSH và host

1. Chỉ kết nối IP/port/user được xác nhận. Host key lấy từ console đáng tin; có thể thu candidate bằng ssh-keyscan rồi đối chiếu fingerprint trước ghi known_hosts. Không tự tin tưởng chỉ vì ssh-keyscan trả kết quả.
2. Dùng StrictHostKeyChecking=yes và known_hosts đã kiểm chứng. Không đặt password/secret vào command line.
3. Giữ console và phiên SSH hiện tại; thử phiên thứ hai bằng key trước thay SSH authentication hoặc firewall.
4. Kiểm kê dịch vụ/port/disk hiện có. Nếu gặp dữ liệu hoặc user `wewin` cũ, dừng để đối chiếu, không ghi đè.

Các lệnh đọc trên đích đã được duyệt:

```sh
cat /etc/os-release
uname -m
python3 --version
ps -p 1 -o comm=
systemctl --version
df -h
findmnt -T /var/lib
ss -lntp
getent passwd wewin
```

Ubuntu 24.04/x86_64 là target chuẩn bị; OS/arch khác cần kế hoạch tương thích mới, không tự nâng hoặc cài lại OS.

## 5. Firewall và quản trị

- Kết hợp firewall nhà cung cấp và host firewall. Allow SSH từ CIDR/VPN quản trị **trước** khi áp inbound deny; kiểm tra phiên SSH mới/console. Không bật firewall với placeholder chưa thay.
- Không allow public 8000 hoặc broker 8765. API bind 127.0.0.1; local WS/MCP không đi qua reverse proxy công khai.
- Ban đầu chỉ SSH tunnel/VPN tới loopback. Chưa public Control Center.
- Nếu sau này cần HTTPS remote: chốt hostname/TLS, gateway xác thực hoặc VPN/IP allowlist, rate limit/login, request size, CORS chính xác và log redaction; thử cả anonymous/wrong/expired credentials trước mở 443.
- HTTPS đơn lẻ không thay xác thực quản trị. Chặn database/config/backup và `/ws/mcp` ở proxy. Không mở port như tác dụng phụ cài certificate.

Xem hướng dẫn chính thức Ubuntu về [OpenSSH](https://ubuntu.com/server/docs/how-to/security/openssh-server/) và [firewall](https://ubuntu.com/server/docs/how-to/security/firewalls/). Chưa thay SSH hoặc firewall trong lượt hiện tại.

## 6. Service user, storage và cài đặt

Những ví dụ sau chỉ dành cho **host staging mới đã được duyệt**. Nếu path/user/venv đã tồn tại, kiểm tra và dừng trước khi chạy các bước tạo/copy. Không dùng `--force`, không xóa folder để làm cho setup chạy lại.

```sh
sudo adduser --system --group --no-create-home --home /var/lib/wewin --shell /usr/sbin/nologin wewin
sudo install -d -o root -g root -m 0755 /opt/wewin /opt/wewin/releases
sudo install -d -o root -g wewin -m 0750 /etc/wewin
sudo install -d -o wewin -g wewin -m 0700 /var/lib/wewin /var/backups/wewin /var/lib/wewin-validation
sudo apt-get update
sudo apt-get install python3 python3-venv ca-certificates unzip
```

Chọn releaseID mới, không ghi đè release cũ. Chuyển gói vào thư mục riêng0700 của admin; chạy `sha256sum -c SHA256SUMS` tại root gói và so manifest với bản gốc bên Windows. Giải nén source vào `/opt/wewin/releases/<releaseID>` mới; source root:root, service chỉ đọc. Chỉ tạo `/opt/wewin/current` trỏ release khi path này chưa tồn tại; nâng phiên bản trên host cũ cần quy trình chuyển release riêng.

Tạo venv mới `/opt/wewin/venv`, cài offline từ wheelhouse đã xác minh:

```sh
sudo python3.12 -m venv /opt/wewin/venv
sudo /opt/wewin/venv/bin/python -m pip install --no-index --find-links /path/to/staging-package/wheelhouse -r /opt/wewin/current/deploy/linux/requirements-linux.lock
/opt/wewin/venv/bin/python -m pip check
```

`/path/to/...` là placeholder bắt buộc thay bằng đường dẫn gói thực. Dùng Python Linux, không Python Windows từ PATH của WSL. Các wheel đã tải được nhưng bước cài/import còn phải kiểm thử thật.

Chỉ cài `private/wewin_knowledge_staging.db` thành `/var/lib/wewin/wewin_fts.db`, owner wewin:wewin, 0600 khi **target chưa có DB/WAL/SHM và không có writer**. Nếu có, dừng và backup/đối chiếu trước, không copy đè. Fixture53 trang đặt riêng ở `/var/lib/wewin-validation/fixtures/`, chỉ regression đọc và copy nó.

## 7. Config và secret staging

- Tạo `/etc/wewin/server.env` mới từ template, root:wewin 0640. Giữ DEBUG=false, AUTO_SYNC_ENABLED=false, SYNC_SCHEDULE_ARMED=false, owner external và CORS same-origin.
- Tạo admin token staging ngẫu nhiên bằng công cụ nhập kín/secret manager hoặc Python ghi trực tiếp vào file mới bằng O_EXCL, không print; file root:wewin 0640. Không dùng token mặc định hoặc copy admin secret vào source.
- Tạo file `/etc/wewin/xiaozhi_endpoint` và `xiaozhi_token` **staging mới**, ban đầu rỗng, quyền 0640. Loader cần file tồn tại. Không copy token/endpoint Windows và chưa start bridge production.
- Khi thử bridge, chỉ điền endpoint 127.0.0.1 của broker fixture và token giả của lab vào các file lab này; không dùng credential Cloud thật.
- Trước chạy CLI, cấp environment đúng cho user wewin. `sudo -u` không tự đọc EnvironmentFile; dùng launcher quản trị environment hoặc nạp file env chỉ có cấu hình/đường dẫn, không nạp file không tin cậy như mã shell.

Thư mục dữ liệu/secrets không nằm dưới `/opt/wewin/current/frontend/dist`. Không thay config/credential đang hoạt động trên Windows.

## 8. Preflight và thử Linux

Trước khi start service, chạy `scripts/server_ops.py check` dưới user wewin với DBpath staging đúng. Điều kiện DB 257 pages / 255 raw FTS / 235 public / 7 internal / 15 review, 0 unclassified, integrity OK / FTS consistent; kiểm tra schema/fingerprints với manifest. Không cho startup tự seed một DB sai/thiếu rồi coi là migrate thành công.

Kiểm tra Linux FTS5 và POSIX permissions; user khác không đọc DB/secret. Kiểm tra WAL/flock/reader-writer/process crash trên **copy**. Không xóa WAL/SHM/guard để giải quyết lock.

Thực hiện các suite đã được đóng gói, mỗi module một process với TMPDIR riêng. Đặt WEWIN_FTS_BACKUP_FIXTURE trỏ fixture 53 trang, không trỏ DB 257 staging. Không dùng unittest discover. Không tuyên bố100 test PASS nếu có skip hoặc lỗi import.

```sh
/opt/wewin/venv/bin/python -B -m unittest tests.test_security_regression -v
/opt/wewin/venv/bin/python -B -m unittest tests.test_fts_recovery -v
/opt/wewin/venv/bin/python -B -m unittest tests.test_server_readiness -v
/opt/wewin/venv/bin/python -B -m unittest tests.test_sync_reliability -v
```

Trên restore copy, chạy `scripts/verify_phase6a.py` để kiểm REST/HTTP tool/MCP và22 URLhold. Script ASGI này không thay kiểm tra Uvicorn TCP hoặc systemd.

Nghiệm thu startup/restart, fault injection có kiểm soát, bridge độc lập/broker loopback, backup/restore và reboot theo các mục4–7 của `deploy/linux/PHASE6B1_VALIDATION_RUNBOOK.md` trong source đã cài. Không enable timer; không khởi chạy sync service.

## 9. systemd và không chạy lịch trùng

```sh
systemd-analyze verify deploy/linux/wewin-api.service deploy/linux/wewin-bridge.service deploy/linux/wewin-sync.service deploy/linux/wewin-sync.timer
systemd-analyze calendar '*-*-* 08:00:00 Asia/Bangkok' '*-*-* 20:00:00 Asia/Bangkok'
```

Chỉ copy unit sau khi parser/preflight đạt. Start API, kiểm health và listener127.0.0.1. Bridge chỉ start sau khi có broker fixture, vẫn phải hoạt động khi API dừng. Thử systemd restart/crash recovery và ghi MainPID/NRestarts, không nhầm với reconnect WebSocket.

Timer vẫn chưa cài/enable/start, owner external/armedfalse. Windows task Disabled và FastAPI scheduler false giữ nguyên. Kiểm tra OS-level lock chống chạy song song bằng test DB; không chạy crawler thật để chứng minh timer.

Reboot chỉ khi được duyệt đối với đích staging; bật boot cho API/bridge trong lab để thử, không bật sync timer. Sau reboot kiểm hash/DB/access và service tự phục hồi, rồi mới ghi PASS. Distro restart không thay bài test reboot VPS.

## 10. XiaoZhi Cloud — chuyển đổi cần phê duyệt riêng

Trong 6B.2 hiện tại không có token production trên VPS và không kết nối Cloud. Trước chuyển thật:

1. Có phê duyệt rõ mục tiêu host và thời điểm kết nối Cloud; record baseline/backup và phương án quay lui.
2. Dừng bridge Windows cũ có kiểm soát; kiểm tra mọi launcher/autorun/scheduled service liên quan, xác nhận process đã thoát. Kiểm tra Cloud dashboard nếu có nguồn trạng thái đáng tin. Không suy “không có process lúc trước” thành đảm bảo tương lai không có bridge trùng.
3. Chuyển secret qua kênh kín vào file đúng quyền; không đổi credential/firmware. Không đặt giá trị trên command line hoặc journal.
4. Start đúng một bridge Linux và kiểm handshake/tools/query public, deny 22 URLhold, redaction, reconnect có giới hạn. Backend healthy không chứng minh robot online.
5. Nếu không đạt, stop bridge Linux, xác nhận đã dừng rồi mới restart bridge Windows cũ theo phê duyệt; không để cả hai chạy trong rollback.

Giữ API/MCP nội bộ và Control Center sau SSH tunnel/VPN. Chưa có phê duyệt remote HTTPS thì không mở 443.

## 11. Monitoring, backup và rollback

Health cần xét API, SQLite/FTS và heartbeat/PID bridge; theo dõi restart count, disk free, tuổi backup và sync partial/failed. Chọn kênh cảnh báo với người dùng; chưa gửi tin hoặc tạo automation.

Backup bằng SQLite Backup API, restore-test trên copy, giữ snapshot ngoài host và thư mục 0700. Không coi JSON 4 record là backup. Retention cần người dùng chốt; không tự xóa bản sao.

Trước rollback: giữ lịch tắt; dừng mọi writer/API/bridge đúng host; backup trạng thái mới và ghi release hiện tại. Dùng release tương thích ACL, phục hồi DB bằng helper với safety backup, không copy mainDB đè WAL. Kiểm tra257/255 và phân quyền 235/7/15,22 URLhold, query tiếng Việt/Anh, logs, scheduler và chỉ một bridge sau restore. Nếu có dữ liệu mới hợp lệ sau snapshot, đối chiếu trước quay lui, không tự làm mất nó.

## 12. Cổng trước Phase 6B.3 — chỉ là kế hoạch

- [ ] G1–G4 đạt bằng chứng Linux thật, reboot/restore và giới hạn mạng đã kiểm thử.
- [ ] G5 được duyệt và Cloud bridge ổn định, chỉ một bridge production, không lộ token.
- [ ] Snapshot và baseline public/hold đã chốt; chủ nội dung biết các nguồn review chưa phát hành.
- [ ] Robot/firmware hiện có được xác minh khi người dùng duyệt test ESP32; không thay firmware hoặc credential để ép test thành công.
- [ ] Thử robot truy vấn public tiếng Việt/Anh/Oxford Phonics và deny internal theo kịch bản; so nguồn trả về, không chỉ nghe một câu trả lời “OK”.
- [ ] Tách kiểm tra runtime Linux, Cloud và ESP32; robot status vẫn Unknown khi không có telemetry.
- [ ] Scheduler còn tắt; chỉ đề xuất bật sau toàn bộ test liên quan PASS và được duyệt lịch riêng.

Chưa thực hiện các mục này, không yêu cầu cắm ESP32 trong lượt chuẩn bị 6B.2. Không làm firmware, pin hoặc YouTube.

Tài liệu OS: [Ubuntu release cycle](https://ubuntu.com/about/release-cycle). Bộ unit/lock hiện có là đầu vào cần nghiệm thu Linux, không phải chứng nhận đã triển khai.
