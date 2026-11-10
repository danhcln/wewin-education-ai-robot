# Factory Advanced / transport: phân tích offline bổ sung

Chỉ đọc backup, source reference và log có sẵn; không liên hệ robot/Cloud,
không mở serial, không vào AP, không gửi request cấu hình.

Factory app SHA `95f39d86990461a9b073105497cbcff0729de13c3e73f4ebf3416e7ee0e2a241`,
3,658,560 byte, version trong descriptor 2.5.3. Script xref khóa đúng hash này;
địa chỉ dưới đây không được áp dụng cho binary khác hoặc firmware hiện chạy
chưa được nhận diện. Artifact: `artifacts/staging-hardening/factory/`.

## Advanced được bật chưa?

**UNVERIFIED trên robot hiện tại.** Đã xác minh đường code compiled:

| Bằng chứng | Diễn giải có giới hạn |
| --- | --- |
| HTML offset 0x8e4a7 | Có Advanced UI và `ota_url`, phụ thuộc `show_ota_config` |
| Registration 0x4205811d–0x42058151 | `/advanced/config` trỏ tới handler 0x4205778c, `/advanced/submit` tới 0x42058a00 |
| 0x420577e2–0x420577ea | Handler đọc byte member +127 để tạo trường `show_ota_config`; không phải literal luôn true |
| 0x42058eba | Constructor AP khởi tạo member +127 bằng 0 |
| 0x42057385–0x4205738a | Manager copy flag config member +81 vào AP member +127 |
| 0x42057573–0x42057576 | Manager nhận flag từ input configuration; chưa chứng minh caller đang cấp true trên đúng device |

Source WeWIN hiện có `xiaozhi-2.5.2/main/boards/common/wifi_board.cc` đặt
`show_ota_config=true`. Component `78__esp-wifi-connect` mặc định flag false,
manager truyền flag vào AP. Đây là source đã chỉnh sửa, **không phải bằng chứng
build này đang chạy hoặc đúng source factory**. Không dùng dòng true ấy để mở gate.

## Lưu cấu hình, kiểm tra URL và reboot

Source component `wifi_configuration_ap.cc` handler `/advanced/submit`:
giới hạn body 1,024 byte, parse JSON, mở namespace `wifi` read/write,
`nvs_set_str("ota_url", ...)`, rồi `nvs_commit`. Source không probe endpoint
hoặc xác minh certificate/credential trước khi lưu; kiểm tra URL chủ yếu là kiểu
string. `Ota::CheckVersion` kiểm tra độ dài URL rồi mới gửi HTTP ở bước khác.

Binary handler 0x42058a00 có limit 0x400, parse JSON, lấy `ota_url`, kiểm tra
string/value và đường gọi setter persistent; khớp cấu trúc source reference.
Tên hàm NVS ở binary stripped được suy luận theo call sequence/source, không
tuyên bố đã chạy handler hoặc kiểm chứng persistence trên phần cứng.

Source/embedded JS chỉ hiển thị save success sau Advanced submit; source handler
không reboot ngay. Một nút `/reboot` riêng có trong trang. Thời điểm đúng firmware
factory áp dụng URL mới, có cần reconnect/reboot, và flag/quyền truy cập hiện tại
vẫn **UNVERIFIED**. Không thử các thao tác ấy.

**Advanced save là thay đổi persistent configuration, có thể ghi NVS.** Nó nằm
trong phạm vi bị cấm của phiên này dù không flash. Không cung cấp lệnh POST để
operator vô tình chạy, không gọi API dựa trên việc thấy HTML trong backup.

## HELLO và WSv1: bằng chứng cụ thể hơn string presence

`websocket-3c2767b5-52171.txt` tại function 0x42020df4 dựng hello với
`transport=websocket`, `format=opus`, `audio_params`:

- 0x42020e70: double high word 0x40cf4000, low word 0 → **16000 Hz**.
- 0x42020e83–0x42020e88: high word 0x3ff00000, low 0 → **1 channel**.
- 0x42020e93: high word 0x404e0000, low 0 → **60 ms**.
- Các key literal được đối chiếu địa chỉ DROM trong `hello-constants.json`.
- 0x4202107c–0x4202108a khởi tạo member version +172 bằng **1**;
  0x420213d1–0x420213f1 có thể ghi đè bằng version config khác 0.

Đây là bằng chứng **compiled WS path** có contract tương ứng Gateway v1;
không chứng minh path đang được chọn. Gateway vẫn chỉ hỗ trợ v1/raw Opus;
không tự nhận v2/v3 nếu runtime config override. Server downlink 24k/60ms đã
decode được bằng simulator; phần decoder/I2S/A2DP factory chưa hardware test.

## Transport/auth/rollback hiện tại

App có code/marker cả MQTT và WS. Log WeWIN v4 ghi MQTT/TLS TenClass; log live
lịch sử thiếu boot identity nên không gán nó cho TanDev Original hiện tại.
Public reference ưu tiên MQTT khi OTA có mqtt, kế tiếp WS và fallback MQTT;
không suy ra preference hiện tại của firmware factory.

Factory setup-HTTP function 0x4202ce18 có Activation-Version, Device-ID/Client-ID
và serial-related flow. Không có bằng chứng complete bootstrap có thể dùng bearer
enrollment của WeWIN; không được bỏ xác thực hoặc chỉ tin MAC. Factory activation,
eFuse challenge, Cloud rebind và provisioning credential vẫn unsupported/unverified.

USB không cần cho phân tích host. Nếu Advanced UI được TanDev hỗ trợ/bật, có thể
có đường cấu hình qua Wi-Fi không flash, nhưng chưa đủ bằng chứng để khẳng định
không cần USB trên thiết bị này. Enter AP/reboot/reset/serial cần phê duyệt riêng.

Rollback cần cơ chế được hỗ trợ để mở lại UI ngay cả khi server mới mất kết nối,
current settings/activation backup an toàn và xác nhận Cloud cũ có cấp lại cấu hình
hay còn mqtt/websocket/token đã persist. Chỉ có file backup lịch sử chưa đủ.
**Không tự sửa NVS, không đổi OTA URL, không thử khôi phục otadata/firmware.**
