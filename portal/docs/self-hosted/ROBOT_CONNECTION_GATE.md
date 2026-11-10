# Monster Desk: giữ nguyên thiết bị, chờ phê duyệt riêng

**Latest gate:** [real connection report](../../WEWIN_MONSTER_DESK_REAL_CONNECTION_GO_NO_GO.md).
Source82e053d adds private-CA TLS/WSS and persistent TLS pins; physical recovery,
factory transport/identity/provisioning and certificate trust remain unverified.
The snapshots and older PIDs below are historical.

**09/11/2026:** report hiện tại là
[independent migration](../../WEWIN_INDEPENDENT_ROBOT_PLATFORM_MIGRATION.md).
Owned bootstrap/Agent scope/binding/rotate/revoke và LAN device-only edge đã được
thêm, chạy trên source e2298f9 (nền tảng81a2cc0). Portal vẫn khóa physical credential/cutover; simulator
không bỏ các gate firmware/identity/TLS/provisioning/rollback vật lý dưới đây.

Ngày 08/11/2026. Đây là checklist chuẩn bị, **không phải quyền đổi endpoint,
enroll thiết bị, mở serial, ghi NVS hoặc flash**. Không có lệnh ghi phần cứng.

Preflight bổ sung: [báo cáo có bằng chứng và GO/NO-GO](../../WEWIN_REAL_ROBOT_CONNECTION_READINESS_REPORT.md).
27 service tests, 40 Portal tests, 6 Chrome checks và 11 kiểm tra live simulator
sau restart 8010 PASS; **physical vẫn NO-GO**. 8010 đã chạy source b4318f0 với
startup hash khớp. Cả ba model trong bộ 31 câu/model chưa đạt nghiệm thu giáo dục.
App factory offline có version 2.5.3, embedded image SHA hợp lệ và HTML Advanced
ở offset 0x8e4a7: `ota_url` được gửi tới `/advanced/submit`, nhưng trường này
phụ thuộc `show_ota_config`. Chưa xác minh flag/UI/handler trên robot hiện tại.
Không thử POST hoặc bật provisioning để vượt qua gate.

## Bằng chứng offline và giới hạn

Factory backup `E:/WEWIN_IT/MonsterDesk_Backup/monster_desk_original_1.bin`
chứa chuỗi `https://xiaozhi-api.tandev282.workers.dev/ota` và
`wss://api.tenclass.net/xiaozhi/v1/`. Đây là bằng chứng file lịch sử, không phải
endpoint runtime hiện tại. Log `v4_boot_captured.log` dòng 166/171–173 cho thấy
WeWIN v4 từng kết nối HTTPS và MQTT/TLS TenClass 8883; log của v4 không chứng minh
transport factory đang dùng bây giờ. Không gọi OTA factory để thử cấp config.

Public firmware SHA `a73e9a7e266e3196d1368ba46c30bee0d81f0a64` và mã WeWIN
2.5.2 có settings namespace `wifi/ota_url`, `websocket/url,token,version` và
`mqtt/*`; OTA response có thể ghi settings và activation liên quan eFuse/HMAC.
Khả năng provision OTA URL trên **factory TanDev hiện chạy vẫn UNKNOWN**, dù
compiled HTML là bằng chứng hướng cấu hình Advanced có tồn tại trong backup.
Transport preference và activation runtime UNKNOWN. Không suy diễn từ public C++.
Phân tích instructions factory đã xác minh compiled WS HELLO Opus 16k mono 60ms,
version mặc định 1 có thể config override. Advanced handler đọc flag runtime;
không phải bằng chứng WS đang được chọn hoặc Advanced đang bật. Xem
[factory analysis](FACTORY_ADVANCED_ANALYSIS_20261108.md). Advanced save có đường
ghi NVS nên vẫn nằm trong thao tác bị cấm của phiên này.
Full backup có WSS TenClass string nhưng app image riêng không có string ấy;
không coi đó là endpoint fallback hardcode hoặc current runtime.

WeWIN staging hỗ trợ WebSocket v1, raw Opus 16 kHz input/24 kHz output, mono,
60 ms; hello, listen manual/auto, WebRTC VAD, abort và reconnect. Không hỗ trợ
MQTT/UDP AES-CTR, binary v2/v3, factory activation/eFuse challenge, firmware
delivery, OTA download/upgrade hoặc thiết lập Wi-Fi của thiết bị. Nếu factory
chỉ chọn MQTT, **KHÔNG READY để kết nối**; ưu tiên mở rộng server/adapter theo
giao thức đã đối chiếu hoặc đánh giá option B trước khi cân nhắc firmware.

## Hai hướng

**A — giữ Cloud:** giữ các tool knowledge/media/device MCP đã được Cloud cho
phép. Không thay Agent prompt/model/voice bằng MCP. Heartbeat unknown không đủ
để kết luận hỏi đáp hiện hoạt động. Server MCP staging chỉ cung cấp ba tool
public read-only; không thay thế toàn bộ bridge/toolset hiện có.

**B — chuyển sang WeWIN sau phê duyệt:** ưu tiên cấu hình server bằng giao diện
được TanDev hỗ trợ nếu có. Cần quan sát đúng firmware/UI và tài liệu nhà cung cấp,
không thử thay `ota_url`/NVS bằng suy luận. Chưa xác định được có cần USB hoặc
flash; phát triển server không cần USB. Nếu bắt buộc firmware mới, phải là dự án
offline riêng và review/approval riêng, không thuộc quyền ghi của phiên này.

## Checklist để trình duyệt thử kết nối thật

1. Xác minh operator, đúng Monster Desk/S3 và định danh Device MAC/serial/Client ID;
   hai Registry record hiện tại chưa được coi là Monster Desk đã xác minh.
2. Sau phê duyệt cho **quan sát/đọc thiết bị**, ghi nhận firmware/slot/version,
   OTA URL, transport đang dùng, endpoint và phương thức provisioning được hỗ trợ.
   Che credentials; không gửi raw NVS/Flash hoặc token vào log/chat.
3. Đối chiếu handshake/auth/Opus/MCP với một trace được phép từ đúng firmware.
   Nếu không khớp v1/manual/auto hiện có, dừng để sửa server trước.
4. Chuẩn bị endpoint có thể truy cập từ Wi-Fi robot. `127.0.0.1:8010` hiện chỉ
   dành cho máy phát triển; không phải URL robot dùng được. LAN firewall/TLS/WSS,
   DNS/certificate và reachability chưa kiểm thử; không tự mở firewall.
5. Backup cấu hình/định danh hiện tại theo phạm vi được cấp phép và xác minh có
   đường khôi phục do operator thực hiện được. Backup lịch sử không đại diện
   NVS hiện tại. Không hứa auto rollback của bootloader.
6. Chuẩn bị device credential riêng, binding đúng Agent/owner; chỉ mở physical
   enrollment sau approval. Không dùng key quản trị hoặc token simulator cho robot.
7. Trình user chính xác thao tác thay cấu hình, phạm vi runtime/NVS có thể bị ghi,
   endpoint cũ/mới và rollback trước khi thực hiện. Không có quyền ghi ngầm định
   từ việc checklist/server test đã PASS.

## Acceptance sau approval (hiện tất cả NOT RUN)

| Test vật lý | Bằng chứng cần có |
| --- | --- |
| Kết nối WeWIN | Đúng MAC/client/Agent, session physical có xác thực |
| Hi, Lily/mic/LCD | User quan sát được wake/capture/display; không đổi model WakeNet |
| Thoại/TTS | User nghe câu hoàn chỉnh, kiểm onset/tail/reconnect, không suy từ packet count |
| Bluetooth | Pair đúng loa được chọn, A2DP phát tiếng; tên DODO chỉ là fixture lịch sử |
| WeWIN MCP | Tool thật được gọi, nguồn public đúng, user nghe câu trả lời |
| English Teacher/Consultant | UI confirmation, readback revision/hash, hội thoại dùng revision đó và user xác nhận hành vi |
| Pin | Rút USB và user quan sát vận hành bằng pin |
| Về Cloud cũ | Operator khôi phục bằng cơ chế được hỗ trợ, kiểm thoại/BT/MCP |

Định tuyến I2S/UART/BT là trách nhiệm firmware/device. Giữ GPIO15/16/17 và
WROOM nguyên trạng; không gửi `speaker.bluetooth` trong vòng staging. Không
hardcode loa. Đổi tên Win trên server không đổi “Hi, Lily”; “Hey, Win” chỉ là
định hướng nghiên cứu, không package hoặc ghi assets.

ESP-SR AFE/WakeNet/MultiNet/VAD/AEC và assets generator đã được đọc offline.
Model packaging `srmodels.bin`/font/emoji và partition size/version phải tương
thích trước một dự án khác; không có bất kỳ assets generation/deployment trong
phiên này.
