# Kết nối quản lý Cloud cho Robot AI

Cập nhật 08/11/2026 (Asia/Bangkok). Console người dùng cung cấp: https://xiaozhi.me/console/agents.

**Người dùng đã đính chính: chưa được cấp Developer/API.** Chưa có URL contract được cấp quyền, Agent ID của Monster Desk hoặc nguồn credential quản lý trên server. Cloud Apply tiếp tục BLOCKED; không có yêu cầu quản lý nào được gửi tới Cloud trong phiên này.

## Kết quả đối chiếu

- Registry có hai robot active, chưa có `integration_id`, `external_device_id` hoặc Agent; mapping `unverified`. Không tự gọi robot có tên “WeWIN Classroom Robot 1” là Monster Desk.
- Bảng integrations của Connector và hồ sơ cloud-connection của Portal đang trống. Observation hiện có là `lan_presence`, không phải xác nhận Cloud/Agent/firmware. Không xác định owner/tenant Cloud từ quyền admin Portal.
- Host cấu hình MCP là `api.xiaozhi.me`, heartbeat `unknown`; đây là endpoint công cụ, không phải bằng chứng về API quản lý Agent hay endpoint hội thoại đang dùng trên robot.
- Mã nguồn tích hợp M5Stack cho thấy một cơ chế Developer secret/token và operations Agent. Nó không cấp quyền cho tài khoản này và không chứng minh có thể dùng API đó với Monster Desk/TanDev.

## Cách xin quyền hợp lệ

1. Tự đăng nhập Console trên bằng tài khoản thực sự sở hữu thiết bị. Chỉ xem thông tin Agent/device hiện có; không unbind, pair lại, đổi endpoint hoặc sửa cấu hình để thử tích hợp. Ghi lại Agent ID, tenant/owner reference và Device ID/MAC/serial được Console liên kết. Đối chiếu định danh phần cứng với hồ sơ Monster Desk đáng tin cậy; tên hiển thị hoặc wire ID nội bộ Portal không đủ.
2. Qua kênh hỗ trợ đang được nhà cung cấp hiển thị trong Console, hoặc đơn vị cung cấp TanDev, đề nghị cấp **Developer/management API cho bên thứ ba** trên đúng tài khoản/tenant. Tên scope và quy trình cấp quyền phải do nhà cung cấp xác nhận. Chưa xác minh có nút self-service, OAuth, service account hoặc flow đăng ký Developer công khai; không hướng dẫn bấm một mục chưa được quan sát.
3. Yêu cầu quyền đọc danh sách/chi tiết Agent, đọc liên kết device–Agent và catalog; quyền cập nhật giới hạn đúng Agent mục tiêu. Yêu cầu tài liệu base URL, phiên bản, phương thức auth, expiry/revocation, error/status codes, rate limits, timeout, update semantics, readback và concurrency. Nếu Agent dùng cho nhiều thiết bị, cần biết phạm vi tác động trước Apply.
4. Xin xác nhận riêng từng trường: assistant/agent name, prompt/persona, Greeting, language, model, voice và speech options. Không suy diễn Greeting hoặc Voice Gender có field độc lập. Yêu cầu cơ chế cấu hình có hiệu lực khi nào: hội thoại tiếp theo, reconnect hay thao tác khác. Không tự reboot/OTA hoặc flash để thử.
5. Chỉ sau khi nhận credential quản lý hợp lệ, quản trị provision vào secret store/process environment của **tiến trình Portal**. Portal hiện đọc tên biến `WEWIN_CLOUD_*` được chỉ định trong hồ sơ. File `.env` của Connector, token MCP và cookie trình duyệt không được dùng thay thế; chỉ tạo file secret bất kỳ chưa khiến Portal đọc nó. Không gửi giá trị key/token/cookie vào chat, form hoặc URL.
6. Cung cấp URL tài liệu, Agent ID và tên biến môi trường đã provision để triển khai đúng adapter. Chỉ các thông tin không bí mật này cần trao đổi. Không bật Apply chỉ vì đã lưu hồ sơ hoặc có biến môi trường.

Có thể gửi mẫu dưới đây **qua kênh hỗ trợ bạn chọn**; Portal/Codex chưa gửi mẫu này tới bên thứ ba:

```text
WeWIN Education cần tích hợp quản lý Agent đang điều khiển Monster Desk
trên tài khoản/tenant của chúng tôi tại https://xiaozhi.me/console/agents.
Xin xác nhận dịch vụ này hỗ trợ API/SDK bên thứ ba và cấp quyền phù hợp:
- Đọc Agent, quyền sở hữu và device-to-Agent mapping;
- Đọc model/voice/language catalog;
- Cập nhật tên, system prompt/persona và Greeting nếu được hỗ trợ;
- Đọc lại cấu hình/revision, chống ghi đè và rollback có kiểm soát;
- Xác định thời điểm robot nhận cấu hình và bằng chứng acknowledgment.
Xin cung cấp tài liệu/version/base URL, phương thức auth được phép,
quy trình cấp/revoke credential và giới hạn phạm vi Agent/tenant.
Chúng tôi không dùng cookie/session browser hoặc token MCP để quản lý Agent.
```

## Điều kiện nghiệm thu sau khi được cấp quyền

Adapter cần đọc trước khi ghi, đối chiếu đúng Agent/tenant/device, giữ các trường ngoài candidate, kiểm tra catalog, timeout hữu hạn, audit không secret và không retry write mù. Candidate phải gắn với revision/mapping đã preview; Cloud đổi bên ngoài cần báo conflict. Cloud rollback là một candidate mới có xác nhận, không tự ghi lại snapshot khi request timeout hoặc readback khác.

Cloud write thật chỉ diễn ra sau khi người dùng xác nhận candidate trên Portal. Kiểm thử tự động dùng transport giả lập riêng sau khi có contract; kết quả đó không phải live Cloud PASS. Write HTTP thành công chưa đủ: cần readback đúng Agent, so sánh các trường đã yêu cầu và bằng chứng robot nhận vai trò trước khi nghiệm thu đầy đủ luồng Monster Desk. Nếu thiếu bằng chứng, không báo `applied_verified` cho luồng này.

## Phương án thay thế và phạm vi MCP

- **Console thủ công hiện tại:** có thể là đường quản trị do provider hỗ trợ, nhưng cần owner tự xác nhận device–Agent; không đáp ứng yêu cầu quản lý hoàn toàn trong Portal. Phiên này không sửa Agent qua Console.
- **Tích hợp riêng do provider cấp:** ưu tiên một API/SDK hoặc dịch vụ được TanDev/XiaoZhi xác nhận cho tenant này. Chưa có contract nên chưa triển khai transport đoán trước.
- **MCP hiện có:** có thể cung cấp dữ liệu/ngữ cảnh cho từng câu hỏi khi Cloud gọi tool được cấp quyền. Không chứng minh thay System Prompt, voice/model hoặc vai trò AI toàn cục. Không thay MCP Bridge trong phiên này.
- **Cloud/self-host khác:** cần đánh giá riêng khả năng tương thích và kế hoạch chuyển dịch được phê duyệt. Không dùng API của dịch vụ khác làm bằng chứng cho XiaoZhi hiện tại, không chuyển endpoint/firmware trong phạm vi này.

## Kiểm tra trên Portal

Admin mở Robot & AI Configuration → Cloud/MCP. Mục “Điều kiện kết nối Cloud thật” đọc metadata Registry theo robot, hiển thị từng blocker và phát hiện Agent reference xung đột. Chỉ admin có scope robot được xem; không hiển thị credential reference/value hoặc URL có query/userinfo. Dữ liệu Registry “ready/provider_verified”, secret presence và hồ sơ Portal đều không tự mở Apply.

Nguồn: [M5Stack integration source](https://github.com/m5stack/StackChan/blob/main/server/internal/xiaozhi/xiaozhi.go), [Agent schema](https://github.com/m5stack/StackChan/blob/main/server/internal/model/xiaozhi/agent.go), [XiaoZhi FAQ](https://xiaozhi.me/xz-docs/docs/help-doc/xiaozhi-ai-chatbot-q%26a/). [M5Stack documentation](https://docs.m5stack.com/en/StackChan) mô tả các hệ quản lý riêng cho sản phẩm của họ; đây là ví dụ cần phân biệt tenant/hệ thống, không phải bằng chứng Monster Desk thuộc M5Stack.
