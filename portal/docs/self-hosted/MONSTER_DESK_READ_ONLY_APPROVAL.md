# Gói quan sát Monster Desk — A và USB Serial đã được phê duyệt

**Cập nhật sau cùng 09/11/2026:** đã thực hiện phiên COM6 được duyệt bằng đúng một
lần mở độc quyền, 59,968 giây, 0 byte; đã đóng, không retry. Người dùng xác nhận
không thấy reset/gián đoạn và robot bình thường. Phê duyệt một lần **đã dùng**;
không tự mở lại hoặc xóa ledger. Xem báo cáo phụ lục G. Nội dung preflight/nhãn
B/C bên dưới là lịch sử trước phiên này; không phải yêu cầu duyệt lại phạm vi cũ.

Ngày 09/11/2026, Asia/Bangkok. Người dùng đã phê duyệt A, chỉ đọc dữ liệu hiện có;
đã kiểm tra Registry và saved logs. Người dùng xác nhận chưa có dữ liệu router/
nhãn/status được lưu để cung cấp. Chưa hoàn tất identity correlation.
**Cập nhật:** người dùng đã phê duyệt USB Serial chỉ đọc, gọi là “phạm vi B” trong
yêu cầu mới. Nhãn C cho USB bên dưới là tên trong gói cũ, không phải thiếu quyền.
Preflight thấy COM6 native USB Serial/JTAG; chưa xác minh được open/close không
reset nên **chưa mở Serial**. Không cần duyệt USB lại, cần giải quyết blocker kỹ
thuật trước. Giao diện robot, capture mạng mới và mọi cutover chưa được phê duyệt.
Không gọi IP robot, bật/tắt dịch vụ để tương tác robot hoặc đổi cấu hình.

Nghiên cứu bổ sung sau commit `905026e`: parent USB serial của COM6 khớp STA MAC
trong hai log custom WeWIN lịch sử; đây chưa là chứng thực TanDev đang chạy. Không
tìm thấy USBPcap/Wireshark trong PATH/common paths/installed-program registry.
Chưa mở COM, bật ETW/capture hoặc cài driver. Native USB cũng có logic reset qua
CDC DTR/RTS; không có cấu hình phần mềm nào được chứng minh không reset trên tổ
hợp hiện tại. Xem phụ lục C của báo cáo cho các lựa chọn và giới hạn. Nếu chọn
single-open có rủi ro còn lại, trace mới hoặc cài tool/driver thì cần phê duyệt
riêng phương án cụ thể; không yêu cầu duyệt lại quyền USB read-only nói chung.

## A — định danh và thông tin mạng có sẵn, đã được duyệt

Mục đích: gắn đúng robot với DHCP/flow entry, không đoán MAC từ registry wire_id.

1. Người dùng có mặt, đối chiếu nhãn hoặc màn hình trạng thái **đang hiện sẵn** của
   Monster Desk. Không bấm BOOT/reset, đổi Wi-Fi, khởi động lại hay ra lệnh thoại.
2. Người dùng mở bảng DHCP/client list/flow history **có sẵn** trên router/AP mình
   được phép quản trị. Không yêu cầu mật khẩu, token hoặc cookie trong chat.
   AI không tự đăng nhập router hoặc truy cập địa chỉ robot theo gói A.
3. Đối chiếu identity tại chỗ; chỉ cung cấp các trường tối thiểu: alias robot,
   IP LAN, network/VLAN đã đối chiếu, thời điểm entry và host/port/protocol từ flow
   nếu router đã có sẵn. Không xuất MAC/SSID đầy đủ hoặc dữ liệu các client khác.
4. Nếu không gắn được identity chắc chắn, đánh dấu UNKNOWN rồi dừng. Espressif OUI,
   tên thân thiện hay IP của một lần cũ không đủ chứng minh đúng Monster Desk.
5. AI chỉ phân tích các trường đã được che và log cũ được cung cấp. Không ping,
   scan cổng, gửi HTTP tới robot, mở Serial hoặc bật packet capture mới.

Kết quả A: identity correlation có thời điểm; IP/subnet/VLAN; đích/cổng nếu có;
phân loại dấu hiệu với độ tin cậy. Chưa phải auth/enrollment hoặc GO cutover.
Nếu router không có flow history, không tự bật tính năng capture/mirroring.

Phiếu tối thiểu, không chứa credential:

| Trường | Người dùng xác nhận / điền trong phiên riêng |
|---|---|
| Robot alias | Monster Desk được đối chiếu tại chỗ |
| Identity khớp DHCP entry | Có / không / chưa rõ; không công bố raw MAC |
| IP robot, prefix/VLAN | Giá trị hiện tại đã xác minh; không dùng IP laptop |
| IP laptop | Quan sát gần nhất192.168.2.82/23; cần đọc lại khi bắt đầu |
| Thời điểm / timezone | Asia/Bangkok, kèm timestamp của router |
| Flow metadata đã có | Destination hostname hoặc IP/port được che phù hợp, TCP/UDP |
| Firmware/build đang hiện sẵn | Chỉ nếu có màn hình/status không cần thao tác mới |

## Gói B cũ — giao diện hỗ trợ / quan sát mạng mới, chưa được duyệt

Quyền USB Serial “B” mới không cấp quyền cho các thao tác mạng trong mục này.

Trước B phải biết đúng IP robot và phương thức được TanDev hỗ trợ. Trình danh sách
URL/động tác cụ thể để người dùng duyệt; không đoán hoặc gọi API chỉ vì thấy route
trong backup. Không thu raw /get_config hoặc /advanced/config nếu response có thể
lộ Wi-Fi password/token/secret OTA URL. Chỉ đọc trang trạng thái được che phù hợp;
không Save/Submit/Reboot/reset/activate hoặc đưa robot vào provisioning.

Nếu cần lưu lượng mới: phải có quyền router/AP và scope chỉ đúng thiết bị, thời
lượng ngắn, metadata-only. Capture NIC laptop thông thường không nhìn thấy unicast
robot↔Cloud qua Wi-Fi/router. Không dùng ARP spoofing, MITM, đổi gateway/proxy, cài
CA, TLS decryption hay bắt lưu lượng của cả lớp học. Không bật mirror/monitor mode
hoặc thay router config nếu chưa được duyệt riêng.

Chỉ TCP443 không phân biệt HTTPS OTA với WSS. TCP8883 gợi ý MQTT/TLS nhưng chưa đủ
kết luận; UDP có thể là DNS/NTP hoặc giao thức khác. Đối chiếu SNI/flow/app log
đúng build khi có bằng chứng hợp lệ; không cần đọc payload/credentials để phân loại.

## USB Serial chỉ đọc — đã duyệt dưới tên B mới (C trong gói cũ)

COM6 đã được liệt kê lại từ Windows; 115200 vẫn là baud lịch sử. Chưa mở cổng do
chưa xác minh tránh reset. Có quyền đọc không đồng nghĩa có quyền reset để lấy log.

1. Xác minh cổng console được nhà sản xuất hỗ trợ và driver/control-line behavior.
   Không đoán UART từ chân Bluetooth GPIO1/2, không gắn USB-TTL chưa rõ điện áp/pin.
2. Người dùng duyệt tác động cấp nguồn: cắm USB có thể đổi nguồn hoặc reset; mở
   COM có thể pulse DTR/RTS ngay lúc mở. Chỉ đọc log không bảo đảm không reset.
3. Không chạy logger/IDF monitor/esptool sẵn có mà chưa review hành vi reset/open.
   Không gửi ký tự/command, không chọn download/BOOT mode, không reset để lấy boot log.
4. Chỉ quan sát hoạt động tự nhiên đã được duyệt; không lưu raw log. Trích whitelist:
   build/version/slot có nguồn, transport event, protocol/audio parameters và public
   host/port. Bỏ password/bearer/activation code/serial secret/session key/nonce/SSID.
5. Nếu không bảo đảm tránh reset, dừng và xin phương thức quan sát khác. Không dùng
   read_flash hoặc dump NVS để lấy credential chỉ nhằm biết endpoint.

## Không có trong A/B/C

Đổi OTA URL, ghi NVS/assets/partitions/otadata, flash/erase, đổi Bluetooth/wake word,
Cloud rebind, cấp credential thật, cài CA, bỏ TLS validation, làm hỏng config để thử
recovery. Mọi cutover/write cần review và phê duyệt khác; lỗi không cấp thêm quyền.

Điểm dừng: nếu chưa xác minh phương thức không reset thì dừng trước open. Không
tự chuyển từ quan sát được duyệt sang thao tác mạng/cấu hình hoặc thử kết nối WeWIN.
Báo cáo kỹ thuật:
[WEWIN_MONSTER_DESK_HARDWARE_CONNECTION_EVIDENCE.md](../../WEWIN_MONSTER_DESK_HARDWARE_CONNECTION_EVIDENCE.md).
