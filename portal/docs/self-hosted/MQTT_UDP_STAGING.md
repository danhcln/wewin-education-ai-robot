# MQTT/UDP staging — vận hành simulator

MQTT/UDP là transport opt-in của cùng AI Server. Không có server Cloud mới, không
fork Agent Runtime. WebSocket v1 mặc định giữ nguyên. Module này không cấp quyền
hoặc khả năng enrollment physical: `kind=physical, transport=mqtt_udp` bị từ chối,
kể cả khi cờ physical của WS được bật.

## Cấu hình

| Biến | Mặc định / ý nghĩa |
|---|---|
| WEWIN_AI_MQTT_ENABLED | `0`; chỉ `1` mới mở listener khi AI app startup |
| WEWIN_AI_MQTT_BIND | `127.0.0.1`; numeric private/loopback IPv4 cụ thể, không wildcard/public |
| WEWIN_AI_MQTT_PORT | `18883`; MQTT 3.1.1 simulator loopback |
| WEWIN_AI_MQTT_PUBLIC_HOST | `127.0.0.1`; host quảng bá trong bootstrap và UDP hello |
| WEWIN_AI_UDP_BIND | `127.0.0.1` |
| WEWIN_AI_UDP_PORT | `18884` |
| WEWIN_AI_MQTT_TLS_CERT | PEM certificate/chain của staging; bỏ trống ở simulator TCP loopback |
| WEWIN_AI_MQTT_TLS_KEY | Private-key **path**, không đưa giá trị vào chat/Git |

LAN bind đòi certificate/key và MQTT port **8883**. Source Wi-Fi wrapper tham khảo
chọn TLS khi port bằng 8883; dùng port TLS tùy ý không chứng minh firmware sẽ dùng
TLS. Không mở firewall, Internet/NAT forwarding hoặc thay Windows trust store từ
runbook này. Public host phải thuộc quyền quản lý WeWIN; bootstrap HTTPS edge
chỉ trả password MQTT khi hostname khớp origin và endpoint dùng 8883.
Non-loopback config cũng yêu cầu HTTPS device origin cùng hostname broker trước
khi listener được mở; không cấp credentials qua HTTP bootstrap LAN.

Đối với TLS fixture trên port ephemeral, simulator truyền SSLContext rõ ràng;
đây không phải cấu hình có thể đưa nguyên xi vào stock firmware.

## Chạy kiểm thử cô lập

Không cần chạy Portal/AI production hoặc cấp credential thiết bị thật:

```powershell
.\.venv-ai\Scripts\python.exe -X utf8 -m unittest ai_server.tests.test_mqtt_udp -v
```

Tests tạo temporary DB, khóa quản trị/issuer mới, ephemeral loopback TCP/UDP ports,
synthetic audio và AI doubles; tự đóng listener, sessions và child MCP process.
Simulator library nằm ở `ai_server/mqtt_simulator.py`, chỉ chấp nhận IP loopback.
Không dùng simulator này với IP robot hoặc router.

Trên máy có `SSLKEYLOGFILE` trong environment, chạy test bằng process con đã loại
biến đó để tránh ghi TLS session secrets. Không thay environment toàn máy. Phiên
bàn giao đã làm như vậy. Avast trên máy này thay certificate TLS loopback; socket
TLS test đánh dấu SKIP/BLOCKED với issuer evidence, không disable validation hoặc
tự thêm Avast CA. MemoryBIO test riêng vẫn xác minh TLS chain/hostname thật bằng
OpenSSL, không phải network/firmware trust test.

## Provisioning simulator bằng management API

Một instance thử riêng có thể dùng cấu hình sau (chỉ hướng dẫn, không tự chạy trên
máy đang vận hành). Chuẩn bị admin key mới trong file đầu tiên, không đưa giá trị
vào terminal/chat. Issuer key được tạo riêng khi provision lần đầu:

```powershell
$env:WEWIN_AI_DB='E:\WeWIN_Firmware_Lab\wewin_education_portal\data\ai-mqtt-simulator.sqlite3'
$env:WEWIN_AI_ADMIN_KEY_FILE='E:\WeWIN_Firmware_Lab\wewin_education_portal\.secrets\mqtt-simulator\admin.key'
$env:WEWIN_AI_DEVICE_ISSUER_KEY_FILE='E:\WeWIN_Firmware_Lab\wewin_education_portal\.secrets\mqtt-simulator\issuer.key'
$env:WEWIN_AI_DEVICE_ORIGIN='http://127.0.0.1:18010'
$env:WEWIN_AI_PUBLIC_WS='ws://127.0.0.1:18010/xiaozhi/v1/'
$env:WEWIN_AI_ALLOW_REAL_DEVICES='0'
$env:WEWIN_AI_MQTT_ENABLED='1'
$env:WEWIN_AI_MQTT_BIND='127.0.0.1'
$env:WEWIN_AI_MQTT_PUBLIC_HOST='127.0.0.1'
$env:WEWIN_AI_MQTT_PORT='18883'
$env:WEWIN_AI_UDP_BIND='127.0.0.1'
$env:WEWIN_AI_UDP_PORT='18884'
.\.venv-ai\Scripts\python.exe -m uvicorn ai_server.app:app --host 127.0.0.1 --port 18010 --workers 1
```

Đây là optional manual staging run. Test suite bàn giao dùng temporary DB và fake
providers, không chạy câu lệnh server này hoặc gọi model production. Để đánh giá
ASR/LLM/TTS thật còn cần cấu hình model/provider như runbook hiện có.

Ở một AI staging instance riêng, dùng DB/admin/issuer riêng và bật transport như
bảng cấu hình. Không reuse DB/credential production chỉ để thử. API hiện có:

1. Admin tạo/apply owned Agent qua `PUT /v1/agents/{agent_id}` với owner/tenant.
2. `POST /v1/device-provisions` với credential quản trị và owner/tenant; body thêm
   `transport: "mqtt_udp"`, `kind: "simulator"`, cùng ownership attestation và
   confirmation như trước. Không có row cũ nào tự chuyển transport.
3. Simulator POST bootstrap URL được cấp với đúng Device-Id/Client-Id. URL là
   scoped capability secret, chỉ chuyển out-of-band; không copy vào log/report.
4. Response chứa `mqtt.endpoint/client_id/username/password/publish_topic/keepalive`,
   `server_time`, metadata WeWIN; không có WS object, firmware URL hoặc activation.
   Password là credential WeWIN riêng, gắn binding/rotation/expiry, không phải
   credential TanDev. Default WS provisioning vẫn nhận WS-only response.
5. Dùng `Simulator(config)` để CONNECT, HELLO, gửi một frame uplink hợp lệ thiết lập
   UDP tuple trước khi yêu cầu TTS, rồi gửi listen/abort/MCP/goodbye theo session.

API diagnostics hiện có ghi online chỉ sau HELLO verified; chưa chứng minh thiết
bị thật. Rebind/rotate/revoke giữ owner/tenant/version guards. Client phải lấy
bootstrap mới sau rebind/rotate. Endpoint hỏng trả lỗi; không fallback credential
sang Cloud cũ hoặc tự sửa cấu hình đã lưu trên robot.

## Contract và giới hạn

- Specialized broker MQTT 3.1.1, Clean Session, username/password, QoS0; không Will,
  QoS1/2, retained/DUP control, shared/wildcard subscription, persistent broker
  state hoặc broker bridge. Các packet ngoài tập hỗ trợ bị đóng cổng.
- Uplink ACL `wewin/devices/{device_id}/up`; downlink riêng
  `wewin/devices/{device_id}/down`. Firmware tham khảo không tự subscribe trong
  protocol nên có implicit private delivery sau CONNECT. Explicit SUBSCRIBE QoS0
  chỉ được dùng với topic riêng. Đây không phải broker MQTT đa dụng.
- HELLO JSON **v3**, transport `udp`; không nhầm với MQTT wire version 3.1.1.
  Opus 16k mono/60ms uplink, 24k mono/60ms downlink. Header 16 byte big-endian:
  type/flags/length/SSRC/timestamp/sequence; header là CTR IV.
- Key 128-bit ngẫu nhiên mới mỗi audio session, random SSRC, sequence tăng; replay,
  wrong tuple/IP, stale session, malformed bounds và overlapping CTR ranges bị bỏ.
  Gói UDP không biết session không nhận phản hồi. Không đoán NAT destination.
- Downlink flags=1 để tách IV domain khỏi uplink flags=0; source tham khảo bỏ qua
  flags khi nhận. TanDev Original runtime chấp nhận cách này còn UNVERIFIED.
- AES-CTR legacy **không có integrity/authentication**. Seq tăng từng 1 với timestamp
  cố định và payload dài hơn block có thể overlap CTR counter range. Receiver guard
  drop trường hợp đó, không sửa được ciphertext mà firmware đã phát. Simulator
  dùng clock tăng; không tuyên bố chống được attacker on-path hoặc bảo mật stock
  firmware trong production. Đây là lý do physical path vẫn đóng.
- UDP tuple đầu tiên phải được quan sát từ uplink trước TTS. Wake/greeting chưa có
  uplink, NAT rebind và AEC/timestamp thực trên robot còn cần xác minh; không tự
  gửi probe, mở port tùy ý hoặc trả audio tới endpoint suy đoán.
- Tối đa 8 broker peers, 8 audio sessions chung với WS, CONNECT deadline 5s,
  keepalive 5–240s/timeout 1.5x, 16KiB MQTT packet, 1275-byte Opus frame,
  128 queued messages, 1500 control packets/phút/peer; lease audio tối đa 600s.
  Shared pipeline còn áp dụng hello/audio/turn limits như WS.
- Goodbye dọn audio và keys nhưng giữ TCP để HELLO lại; TCP reconnect có session/key
  mới. Abort hủy turn/MCP child đang chạy; shutdown/startup bind failure dọn sockets.

## Điều kiện robot thật

Chưa đủ: exact original MQTT wire/client/TLS wrapper, runtime bootstrap/activation,
timestamp và flags behavior, public/owned TLS chain, supported provisioning và
recovery khi endpoint mới không hoạt động. Không dùng cert/pin 192.168.2.10 để
chứng minh trust cho 192.168.2.82/23. Không thử recovery bằng cách làm hỏng thiết bị.
Mọi tương tác Monster Desk tiếp theo cần phạm vi phê duyệt mới; COM6 không mở lại.
