# Phase 6B.1 — nghiệm thu Linux trong môi trường lab

Ngày 26/10/2026. **Chưa thực thi các bước Linux dưới đây.** Máy hiện tại chưa có Linux phù hợp. Tài liệu này chuẩn bị lần kiểm thử tiếp theo; không phải bằng chứng triển khai VPS hoặc phê duyệt Phase 6B.2.

## 1. Chuẩn bị môi trường sau khi người dùng đồng ý

Ưu tiên một VM Ubuntu Server 24.04 LTS riêng, có systemd làm PID 1, ổ ext4 cục bộ bền vững. WSL2 có systemd cũng dùng được để kiểm tra ứng dụng, nhưng không thay thế thử reboot/uptime trên VPS. Container không chạy systemd chỉ kiểm chứng ứng dụng, không nghiệm thu service manager.

Thông số dưới đây là ước lượng cho tải nhỏ, **chưa benchmark**:

| Hạng mục | Mức tối thiểu cho lab | Khuyến nghị ban đầu |
|---|---:|---:|
| CPU | 1 vCPU | 2 vCPU |
| RAM | 1 GiB | 2–4 GiB |
| SSD | 20 GiB | 40 GiB, còn tối thiểu 2 GiB trống khi bảo trì |
| OS | Ubuntu Server 24.04 LTS, Python 3.12 | Cùng phiên bản lab đã nghiệm thu |
| Filesystem | ext4 cục bộ | ext4 cục bộ, backup ngoài máy |

Chọn Ubuntu 24.04 để thống nhất mục tiêu Python 3.12 của dependency lock. Ubuntu vẫn liệt kê 24.04 trong các bản LTS được hỗ trợ; đây không phải khẳng định lock đã được cài thành công trên Ubuntu. Nếu chọn OS/Python/kiến trúc khác, kiểm thử lại wheel và runtime.

Không tự cài WSL, bật Windows feature, sửa boot hoặc reboot Windows. Nếu người dùng chọn WSL, họ cần phê duyệt riêng việc cài distro và những thay đổi hệ điều hành cần thiết. Khi đã có distro, xác nhận:

```sh
uname -a
cat /etc/os-release
ps -p 1 -o comm=
python3 --version
systemctl --version
findmnt -T /var/lib
```

PID 1 phải là systemd để chạy phần service tests. Với WSL, việc bật `[boot] systemd=true` và shutdown/restart distro cũng chỉ thực hiện sau phê duyệt; không chạy các bước đó trên máy hiện tại.

## 2. Cô lập dữ liệu và mạng

- Dùng snapshot SQLite tự chứa đã backup qua SQLite Backup API, có đủ access metadata. Không mở trực tiếp database production từ `/mnt/e`, thư mục chia sẻ hoặc NFS.
- Giữ backend và broker thử nghiệm bind 127.0.0.1; không forward port 8000/8765 từ VM ra Internet. Không chạy server trên0.0.0.0.
- Không chuyển `.env` Windows, `.secrets` hoặc credential Cloud production vào lab. Tạo admin token thử nghiệm và file endpoint/token lab mới. Không echo secret hoặc đặt trong shell command/history.
- Mọi snapshot, export và logs nằm trong thư mục riêng 0700. Giữ các bản backup Phase6A nguyên vẹn.

## 3. Cài dependencies và bố trí thư mục — chỉ trong lab được duyệt

Tạo service account `wewin` không có shell đăng nhập. Đặt source read-only tại `/opt/wewin/current`, venv tại `/opt/wewin/venv`, bản sao SQLite tại `/var/lib/wewin/wewin_fts.db`. Dùng quyền và layout trong [runbook triển khai](E:/WEWIN_IT/Wewin_AI_Connector/deploy/linux/RUNBOOK.md).

Các lệnh cài đặt này **chưa được chạy**, chỉ dành cho lab:

```sh
sudo apt-get update
sudo apt-get install python3 python3-venv ca-certificates
sudo python3 -m venv /opt/wewin/venv
sudo /opt/wewin/venv/bin/python -m pip install -r /opt/wewin/current/deploy/linux/requirements-linux.lock
sudo /opt/wewin/venv/bin/python -m pip check
/opt/wewin/venv/bin/python -c 'import sqlite3; c=sqlite3.connect(":memory:"); c.execute("CREATE VIRTUAL TABLE t USING fts5(body)"); print(sqlite3.sqlite_version)'
```

Không chép nguyên `pip freeze` Windows vào Linux. Lock runtime hiện có 23 package; `uvicorn` dùng asyncio+h11, không yêu cầu platform extras. `pytest` không nằm trong lock runtime; các suite hiện tại dùng `unittest`. Dùng Python thực trong venv, không dùng Windows Python từ PATH của WSL.

Trong Phase6B.1 đã tải thành công đủ 23 wheel cho CPython3.12/Linux x86_64 từ PyPI, tổng khoảng4,11MiB, và ghi SHA256 từng file trong thư mục bằng chứng riêng. Chưa cài hoặc import các wheel đó trên Linux. Có thể chuyển wheelhouse đã đối chiếu checksum vào lab và cài offline bằng `pip install --no-index --find-links <wheelhouse> -r deploy/linux/requirements-linux.lock`; bước cài và `pip check` vẫn bắt buộc chạy thật trong Linux. Các wheel này không chứng nhận ARM64 hoặc Alpine/musl.

Chuẩn bị `/etc/wewin/server.env` từ template. Giữ `DEBUG=false`, `AUTO_SYNC_ENABLED=false`, `SYNC_SCHEDULE_ARMED=false`, `SYNC_SCHEDULER_OWNER=external`. File env chỉ chứa đường dẫn secret. Dùng các file secret **lab** tại `/etc/wewin`, root:wewin 0640; thư mục không cho tài khoản khác đọc. Cần tạo file endpoint/token dù tạm thời rỗng vì loader kiểm tra đường dẫn tồn tại.

Lưu ý: `sudo -u wewin` không tự đọc `EnvironmentFile` của systemd. Để chạy CLI kiểm tra, nạp file env không chứa secret bằng shell hoặc công cụ quản trị môi trường phù hợp, rồi giữ nguyên environment đó:

```sh
set -a
. /etc/wewin/server.env
set +a
cd /opt/wewin/current
```

Các lệnh CLI bên dưới giả định chạy dưới user wewin với environment lab đúng. Không nạp file env không tin cậy như mã shell. Không mở hoặc in nội dung secret-file ra terminal.

## 4. Nghiệm thu database và quyền POSIX

```sh
id
stat -c '%a %U:%G %n' /var/lib/wewin /var/lib/wewin/wewin_fts.db /etc/wewin/server.env /etc/wewin/admin_token
/opt/wewin/venv/bin/python scripts/server_ops.py check --database /var/lib/wewin/wewin_fts.db
```

Điều kiện: data dir 0700, DB 0600, secret 0640 root:wewin hoặc0600 wewin; user khác không đọc được. Kiểm tra thực bằng một user lab không thuộc group wewin; không suy POSIX từ quyền NTFS. Kết quả DB phải257 pages,255 raw FTS,235 public / 7 internal / 15 review,0 unclassified,0 duplicate, FTS consistent. Giữ nguyên2 trang rỗng, cursor 55 / history 9 và tất cả nội dung gốc.

Tạo backup với tên mới, restore-check trên bản sao. Để thử lỗi, chỉ sửa một **bản restore thử**, rồi phục hồi từ snapshot, đối chiếu fingerprints của cả pages, FTS và access tables. Không chạy restore vào database production.

```sh
/opt/wewin/venv/bin/python scripts/server_ops.py backup --database /var/lib/wewin/wewin_fts.db --snapshot /var/backups/wewin/lab-before-validation.db
```

Nghiệm thu WAL: trên DB thử kiểm tra reader/writer riêng, process crash, reopen và backup khi còn WAL. Xác minh snapshot có committed data. Không copy riêng mainDB của một writer đang chạy; không xóa `.db-wal`, `.db-shm` hoặc `.guard` thủ công.

## 5. systemd API startup/restart/failure

Xem xét unit trước khi cài vào **VM lab**. Không enable timer; trong phiên lab ban đầu cũng chỉ `start` service, chưa enable boot tự động.

```sh
systemd-analyze verify deploy/linux/wewin-api.service deploy/linux/wewin-bridge.service deploy/linux/wewin-sync.service deploy/linux/wewin-sync.timer
systemd-analyze calendar '*-*-* 08:00:00 Asia/Bangkok' '*-*-* 20:00:00 Asia/Bangkok'
```

Copy các unit đã duyệt vào `/etc/systemd/system`, daemon-reload. Dùng bản env/data **lab**, xác nhận fingerprint trước. Sau đó:

```sh
sudo systemctl start wewin-api.service
systemctl show wewin-api.service -p ActiveState -p SubState -p MainPID -p NRestarts
curl --fail http://127.0.0.1:8000/health
ss -lntp
sudo systemctl restart wewin-api.service
curl --fail http://127.0.0.1:8000/health
```

Phải chỉ listen127.0.0.1:8000, health healthy và235 public. API service không được đổi database hoặc khởi động crawler.

Thử tự phục hồi **chỉ sau khi xác nhận đúng VM lab**: ghi MainPID và NRestarts; dùng `systemctl kill --kill-whom=main --signal=KILL wewin-api.service`; chờ ít nhất RestartSec 5s; xác minh PID đổi, NRestarts tăng và health phục hồi. Đây là fault injection có chủ đích, không chạy trên host hiện tại hoặc production. `systemctl stop` không phải bài test crash vì systemd có chủ đích giữ service dừng.

Kiểm tra nhật ký đã lọc quyền đọc, không gửi toàn bộ journal ra báo cáo. Xác minh không có credential trong log. Thử user/path quyền sai trên một override lab, phải thấy lỗi rõ ràng; rollback override và kiểm tra lại. Không nới quyền toàn filesystem để khiến test PASS.

## 6. API/MCP và bridge độc lập

Trên Linux lab, chạy các suite trong các process riêng với tempdir; không dùng unittest discover trên suite legacy. `scripts/verify_phase6a.py --database <restored-copy> --output <new-json>` kiểm tra REST/HTTP tool/MCP bằng ASGI nội bộ và DB read-only. Không coi đây là kiểm thử server TCP hoặc systemd.

Phép thử giao thức thật, token giả, hoàn toàn loopback:

```sh
/opt/wewin/venv/bin/python scripts/probe_bridge_loopback.py --snapshot /var/backups/wewin/lab-before-validation.db --directory /var/lib/wewin/probes/new-bridge-probe
```

Script tự khởi động broker 127.0.0.1 và `run_bridge.py` riêng, không chạy FastAPI, không Cloud. Kiểm tra54 RPC,22 URL hold, initialize/toolslist/toolscall/ping, JSON lỗi, ngắt 1012, reconnect, redaction và trạng thái sau process crash. Script chỉ dùng DBcopy. Kết quả phải ghi host OS Linux; một kết quả Windows không đáp ứng cổng này.

Để nghiệm thu **unit bridge** với broker giả, cần một broker lab chạy riêng trước. Có thể dùng fixture Python sau trong terminal lab; nó chủ động đóng sau initialize để quan sát backoff, không dùng credential production:

```python
import asyncio, json
from websockets.asyncio.server import serve

async def handler(ws):
    await ws.send(json.dumps({"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}))
    reply=json.loads(await asyncio.wait_for(ws.recv(),15))
    assert reply["id"]==1 and "result" in reply
    await ws.close(code=1012,reason="lab restart")

async def main():
    async with serve(handler,"127.0.0.1",8765):
        await asyncio.Future()

asyncio.run(main())
```

Đặt **file endpoint lab mới** thành `ws://127.0.0.1:8765/mcp/` và tạo token giả bằng nhập kín hoặc ghi file qua Python, không in token. Chỉ VM lab này có các file `/etc/wewin` đó. Không sửa hoặc chuyển file Cloud production của máy Windows.

Start bridge khi API đang stop trong lab, xác nhận unit không có Requires=API và vẫn kết nối broker. Kiểm tra PID, journal lỗi không chứa token, heartbeat cập nhật; chủ động tắt broker, quan sát backoff 2/4/8…60s và nối lại khi broker bật. Với unitRestartalways, thử kill mainPID của đúng bridge lab; xác minh PID mới sau RestartSec 10s. Ghi tách biệt systemd restart và WebSocket reconnect.

Để kiểm tra health ở trạng thái ổn định sau phần fault injection, thay dòng `await ws.close(...)` trong fixture lab bằng `await ws.wait_closed()`, chạy lại broker và đợi bridge connected. Fixture lúc này giữ kết nối thay vì cố tình gây lỗi liên tục.

Khởi động lại API lab và chạy `scripts/healthcheck.py` trong environment lab. Exit 0 chỉ khi API/FTS/bridge đều đạt; missing/stale heartbeat hoặc bridge dừng phải exit 1. Không suy ra ESP32 online từ kết quả này.

## 7. Reboot và persistent storage

Chỉ sau phê duyệt reboot **VM lab**, enable đúng 2 service API/bridge trong lab để thử boot; timer tiếp tục disabled và armed false. Reboot VM, kiểm tra activePID, bindloopback, fingerprints, backuprestore, heartbeat và tất cả22 URLhold. Sau thử dừng/disable các service lab khi không dùng.

Với WSL, ghi riêng distro restart và Windows reboot; không gọi distro restart là bài test boot VPS. Không sửa cấu hình boot Windows để hoàn thành phép đo.

## 8. Checklist VPS sau khi nghiệm thu lab và được duyệt riêng

- [ ] Chốt OS/CPU/RAM/SSD dựa trên lab và đo tải; không coi cấu hình gợi ý là SLA.
- [ ] SSH key, xác minh host key qua console đáng tin; tạo admin sudo riêng. Thử phiên SSH thứ hai và giữ console trước khi thay chính sách đăng nhập.
- [ ] Firewall inbound deny mặc định; allow SSH từ IP/VPNquản trị trước; không allow 8000/8765. HTTPS 443 chỉ mở nếu được duyệt; bridge chỉ cần kết nối outbound.
- [ ] API loopback, debug false, CORS same-origin hoặc danh sách chính xác; không wildcard credentials.
- [ ] Quản trị qua SSH tunnel/VPN; nếu cóHTTPS remote cần TLS, identity/VPN/IP allowlist, rate limit/login, không log Authorization hoặc secret query.
- [ ] Chặn WS/MCP nội bộ và database/config/backup ở reverse proxy; không công khai Control Center như tác dụng phụ cài TLS.
- [ ] Backup WAL-aware mới ngay trước chuyển; restore-test và so sánh toàn bộ fingerprints/access metadata.
- [ ] Chuyển snapshot tự chứa bằng SSH, không thay SQLite bằng JSON 4 record; giữ bản gốc Windows và backup off-host.
- [ ] Service user wewin, source/read-only, data dir 0700/DB 0600, secret files riêng, không dùng root chạy ứng dụng.
- [ ] Chỉ chuyển Cloud bridge trong cửa sổ được duyệt; giữ token kín, tránh 2 bridge active cùng credential. Giai đoạn6B.1 này chưa cho phép kết nối Cloud thật.
- [ ] Một scheduler owner duy nhất; Windows task Disabled, FastAPI scheduler false và armed false vẫn giữ cho tới phê duyệt lịch riêng.
- [ ] Monitoring: health gồmAPI/SQLite/bridge, kiểm tra sync partial/failed, restart count, dung lượng đĩa, tuổi backup; kênh cảnh báo phải được người dùng chọn, không tự gửi tin.
- [ ] Thử restore off-host, mất mạng, process crash/reboot và soak 24–48h; telemetry robot vẫn Unknown khi không có nguồn thật.
- [ ] Rollback được duyệt: dừng timer/writers, backup mới, đổi source về release có ACL, restore qua Backup API với safety backup, kiểm tra lại22 URLhold. Không bật lại lịch hoặc dùng source cũ bỏ ACL.

## 9. Cách ghi kết quả

Mỗi bước lưu OS/Python/package versions, command, exitstatus, timestamp, fingerprint trước/sau và logs đã lọc secret. Chỉ PASS thực tế khi đã chạy trong đúng môi trường. Fault injection/broker giả ghi rõ điều kiện mô phỏng. Không có Linux thì ghi CHƯA KIỂM THỬ cho startup, POSIX permissions,flock,systemd,reboot và persistent storage Linux; không chuyển PASS Windows thành PASS Linux.

## Tài liệu chính thức

- [Ubuntu release cycle](https://ubuntu.com/about/release-cycle).
- [Microsoft: systemd trên WSL](https://learn.microsoft.com/en-us/windows/wsl/systemd).
- [systemd execution environment](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html).
- [Uvicorn settings](https://uvicorn.dev/settings/).
