# Phân tích toàn bộ ảnh GM_BOT

Ngày: 07/11/2026 (Asia/Bangkok). Đã mở trực tiếp từng file bằng công cụ xem ảnh; 11/11 mở được, không có ảnh lỗi. Nhận xét chỉ dựa trên vùng nhìn thấy, không xác nhận backend hay quyền của dịch vụ tham khảo. Chỉ kế thừa workflow và tổ chức thông tin; không sao chép thương hiệu, nhân vật hay bố cục đặc trưng.

## 1. Cấu hình GMbot AI

File: `1794045986687_198069978360956581_1780654779979847084_8cf42676ed79c7e44585dd202170c4be.jpg`

- Bố cục / menu: Sidebar trái và khối nội dung rộng; đầu trang có hướng dẫn, ba tab cấu hình / nhận dạng người nói / giao diện.
- Form / input / button: Ô tên robot, model, ngôn ngữ, giọng nói, tốc độ, cao độ và textarea vai trò/tính cách; nút tải cấu hình. Nút lưu không hiện trong vùng ảnh nên không suy luận phản hồi của nó.
- Thao tác / chức năng: Đọc cấu hình trước khi sửa; lưu cấu hình mong muốn với trạng thái và phiên bản. Không sao chép nhận định “khởi động lại là nhận cấu hình” khi chưa có Cloud API.
- Data model / API: devices, robot_config, config_history, config_sync_history; GET/PUT /robots/{id}/config, GET /history.
- Chuyển sang WeWIN: 7 tab độc lập, nhãn saved_backend_only, lời chào Win, persona riêng; wake word và Bluetooth hiển thị capability.

## 2. Dashboard học tiếng Anh

File: `1794045996367_198069978360956581_1780654779979847084_e87d305439f213e9a893b4df14bd6c58.jpg`

- Bố cục / menu: Sidebar học tập rút gọn; hero chào người dùng, bốn KPI, hai khối bài đề xuất/bài đang học và vùng ôn tập.
- Form / input / button: Device selector, nút bắt đầu bài đề xuất, tải lại, tắt bài đang học và xem báo cáo; các chỉ số trên ảnh bằng 0.
- Thao tác / chức năng: Bắt đầu bài, tiếp tục và kiểm tra báo cáo; số 0 phải xuất phát từ việc chưa có phiên học.
- Data model / API: lessons, learning_sessions, learning_progress, user_profiles; GET /learning/dashboard, POST /learning/sessions, POST /learning/sessions/{id}/complete.
- Chuyển sang WeWIN: Dashboard học riêng với dữ liệu tài khoản, chấm đáp án văn bản, lịch sử có thời gian; chưa chấm phát âm hoặc trò chuyện AI.

## 3. Chọn vai trò AI

File: `1794046009350_198069978360956581_1780654779979847084_d1145f4105c04ed45f739d6d0bd2548d.jpg`

- Bố cục / menu: Sidebar quản lý và lưới nhiều thẻ nhân vật, mỗi thẻ có ảnh, tên và mô tả dài.
- Form / input / button: Nhấp thẻ để chọn vai trò, hướng dẫn nêu bước đồng ý/để sau; cửa sổ xác nhận không nằm trong ảnh.
- Thao tác / chức năng: Xem prompt, chọn vai trò và xác nhận phạm vi áp dụng. Không tái sử dụng nhân vật hoặc minh họa GMbot.
- Data model / API: ai_roles, user_role_bindings, robot_config; GET/POST /roles, PUT /roles/{id}, POST /role-bindings.
- Chuyển sang WeWIN: 8 vai trò WeWIN có prompt riêng và avatar ký hiệu, sửa/lưu trữ có quyền; dùng cho hồ sơ hoặc gán robot trong Portal.

## 4. Bộ nhớ

File: `1794046016890_198069978360956581_1780654779979847084_09ff80e35998fe1fac78504699af45f9.jpg`

- Bố cục / menu: Một panel ngang với tiêu đề Memory, tìm kiếm, checkbox chọn tất cả và trạng thái không có dữ liệu.
- Form / input / button: Ô tìm nội dung, nút tải dữ liệu, checkbox. Ảnh không hiển thị nút sửa/xóa nên chúng là yêu cầu bổ sung của sản phẩm mới.
- Thao tác / chức năng: Tải và tìm bộ nhớ theo người dùng; thêm sửa xóa cần chính sách riêng tư rõ ràng.
- Data model / API: memories, user_id, device_id, session_id, category; GET/POST /memories, PUT/DELETE /memories/{id}.
- Chuyển sang WeWIN: Bộ nhớ chủ động, xác nhận lưu lâu dài, scope theo tài khoản; không tự thu thập cuộc trò chuyện; xác nhận trước xóa trên UI.

## 5. Tạo nhiệm vụ

File: `1794046024872_198069978360956581_1780654779979847084_7d1d21a260c68a02a79968a8f73e747a.jpg`

- Bố cục / menu: Phần bộ nhớ còn hiện phía trên; bên dưới là panel tạo nhiệm vụ, hướng dẫn và danh sách nhiệm vụ trống.
- Form / input / button: Textarea nội dung và nút Tạo; hướng dẫn kích hoạt/hoàn thành qua giọng nói trong sản phẩm tham khảo.
- Thao tác / chức năng: Tạo nhiệm vụ và xem danh sách. Không coi hướng dẫn giọng nói trên ảnh là bằng chứng robot WeWIN hỗ trợ.
- Data model / API: tasks, task_history, lesson/student/device references; GET/POST /tasks, PUT/DELETE /tasks/{id}, POST /complete.
- Chuyển sang WeWIN: Thêm tiêu đề, hạn, ưu tiên, chọn người học/robot/bài, cập nhật và hoàn thành trong web; giọng nói chưa tích hợp.

## 6. Chọn bài học

File: `1794046033393_198069978360956581_1780654779979847084_687c5b5f6167f4b2e3c533a1838d8cda.jpg`

- Bố cục / menu: Bố cục hai cột: danh sách có sẵn/của bạn bên trái và chi tiết bài bên phải.
- Form / input / button: Hai vùng danh sách có thể mở rộng; hướng dẫn đề cập Áp dụng/Hủy áp dụng, chưa có bài được chọn trong ảnh.
- Thao tác / chức năng: Tìm bài, xem nội dung, chọn bài dùng cho phiên hoặc cấu hình robot.
- Data model / API: lessons, learning_bindings, learning_sessions; GET /lessons, GET /lessons/{id}, PUT /robots/{id}/config.
- Chuyển sang WeWIN: Thư viện thẻ có tìm kiếm/trình độ/chủ đề, trang chi tiết và học trên browser; gán robot chỉ lưu quan hệ local.

## 7. Tự tạo bài học

File: `1794046041379_198069978360956581_1780654779979847084_4a53a2c7cc6deb9fc2d1b9802b6973a8.jpg`

- Bố cục / menu: Một panel tạo nội dung rộng trên nền tối, menu bên trái.
- Form / input / button: Input tên bài, textarea nội dung lớn, nút Tạo bài học.
- Thao tác / chức năng: Nhập nội dung và lưu bài mới để sử dụng.
- Data model / API: lessons: title, description, level, language, topic, content, vocabulary, exercises, status; POST/PUT /lessons.
- Chuyển sang WeWIN: Builder có nháp/xuất bản/lưu trữ, từ vựng và câu hỏi-đáp án; lưu SQLite thật và kiểm tra quyền tác giả.

## 8. Chụp ảnh tạo bài học

File: `1794046048989_198069978360956581_1780654779979847084_56c55626f8cc9c40f18e32171eb6f67d.jpg`

- Bố cục / menu: Hai cột chọn ảnh / preview; phía dưới là văn bản sau scan và bài dạy đã soạn.
- Form / input / button: Tên bài tùy chọn, tải ảnh, chụp camera, scan thành chữ, xóa ảnh; vùng nội dung đầu ra.
- Thao tác / chức năng: Chọn ảnh → preview → OCR → sửa → xác nhận → draft.
- Data model / API: OCR adapter, Lesson Draft; GET /providers, POST /ocr, POST /lessons.
- Chuyển sang WeWIN: Chấp nhận JPG/PNG/WEBP tối đa 8 MB và 20 MP, ảnh tạm không lưu; Tesseract chưa có nên báo thiếu phụ thuộc, cho nhập tay.

## 9. Chụp ảnh giải bài tập

File: `1794046057314_198069978360956581_1780654779979847084_513192ccf6e6fa6670f50499edd715e8.jpg`

- Bố cục / menu: Hai cột ảnh/preview, vùng bài sau scan và nội dung yêu cầu đang áp dụng.
- Form / input / button: Tên/ghi chú, tải/chụp/scan/xóa; hướng dẫn yêu cầu AI giải, chỉnh văn bản và kết thúc qua giọng nói.
- Thao tác / chức năng: Kiểm tra câu hỏi trước khi gửi AI; giải thích từng bước, lưu lịch sử cần đồng ý.
- Data model / API: homework_requests; POST /ocr, POST/GET /homework, GET /providers.
- Chuyển sang WeWIN: Provider OpenAI-compatible được cấu hình ở server; không có provider thì không sinh đáp án. Workflow giọng nói chưa áp dụng.

## 10. Cơ sở tri thức

File: `1794046067436_198069978360956581_1780654779979847084_8ac876bb85f1e2b2ebf10391a8730093.jpg`

- Bố cục / menu: Hai cột tải/danh sách tài liệu và chi tiết; panel hướng dẫn sử dụng tri thức.
- Form / input / button: Tiêu đề tùy chọn, chọn tài liệu, xóa file, tải lên, danh sách; ảnh ghi DOCX/TXT/MD tối đa 3 MB.
- Thao tác / chức năng: Upload, xem chi tiết và truy xuất tri thức; prompt yêu cầu tra cứu không chứng minh dịch vụ tìm kiếm thực có.
- Data model / API: knowledge_documents, knowledge_fts, knowledge_bindings; GET/POST /knowledge, POST /knowledge/upload, /reindex, /bindings; DELETE document.
- Chuyển sang WeWIN: FTS5 Portal, trích xuất DOCX/TXT/MD có giới hạn, quyền sở hữu, nguồn public_pages Connector chỉ đọc. Không sửa database demo.

## 11. Hướng dẫn sử dụng

File: `1794046091939_198069978360956581_1780654779979847084_1316b97c22073e9991b0d307c5c1a507.jpg`

- Bố cục / menu: Sidebar mục lục, hero giới thiệu, thẻ bước thao tác và các panel hướng dẫn đánh số.
- Form / input / button: Các liên kết mục lục, các bước tải/sửa/lưu cấu hình và nút về đầu trang; không có form chỉnh dữ liệu trong ảnh.
- Thao tác / chức năng: Tra cứu cách dùng và giới hạn chức năng trước thao tác.
- Data model / API: Trang tài liệu tĩnh; /help, liên kết các route và trạng thái capability.
- Chuyển sang WeWIN: Hướng dẫn WeWIN theo luồng đăng nhập, cấu hình local, học bài, bộ nhớ, provider và polling; không hướng dẫn khởi động robot để áp dụng khi chưa được hỗ trợ.
