> FIX 01 (25/10/2026): Xem [FIX01_SECURITY.md](FIX01_SECURITY.md) để cấu hình token riêng và chạy security regression cô lập. Với dữ liệu hiện có, không ghi đè `.env`, không chạy crawler hoặc test suite cũ theo các bước cài mới bên dưới. Backend mặc định chỉ bind loopback.

# WeWIN AI Website Connector for XiaoZhi ESP32-S3

Hệ thống backend trung gian và MCP Tool Server cho phép trợ lý giọng nói **XiaoZhi AI** (chạy trên phần cứng **ESP32-S3 N16R8**) truy xuất thông tin, tìm kiếm và trả lời các câu hỏi về trung tâm tiếng Anh **WeWIN Education** ([https://wewin.edu.vn/](https://wewin.edu.vn/)) hoàn toàn bằng tiếng Việt với trích dẫn nguồn URL chính xác.

---

## 🌟 Điểm nổi bật của giải pháp

1. **Giữ nguyên 100% phần cứng và firmware hiện tại**:
   - Tương thích trực tiếp với ESP32-S3 N16R8, Micro INMP441, Loa MAX98357A, OLED SSD1306 và Firmware **XiaoZhi AI v2.5.2**.
   - Không cần nạp lại firmware hay can thiệp mạch điện tử.
2. **Không can thiệp website WeWIN**:
   - Không xây dựng lại website, không cần quyền quản trị WordPress (Admin Dashboard).
   - Chỉ thu thập nội dung công khai, tuân thủ `robots.txt`, có rate-limiting và cơ chế cache.
3. **Tìm kiếm siêu tốc với SQLite FTS5**:
   - Sử dụng SQLite FTS5 (Full-Text Search) tích hợp sẵn trong Python standard library.
   - Hỗ trợ tiếng Việt Unicode (`unicode61`), xếp hạng độ liên quan theo thuật toán BM25 và tạo đoạn trích dẫn (snippet) tức thì.
4. **Hỗ trợ đa giao thức MCP (Model Context Protocol)**:
   - **WebSocket MCP Bridge**: Kết nối trực tiếp tới XiaoZhi Cloud MCP Endpoint (`wss://api.xiaozhi.me/mcp/...`) theo chuẩn JSON-RPC 2.0.
   - **HTTP Tool Webhook**: Tương thích các nền tảng Function Calling (Dify, FastGPT, OpenAI tool calling) qua endpoint `/api/xiaozhi/tool`.
   - **Local WebSocket MCP Server**: Cung cấp endpoint `ws://localhost:8000/ws/mcp` cho client MCP kết nối trực tiếp.
5. **Bộ công cụ (Tools) được chuẩn hóa cho giọng nói**:
   - `wewin_search`: Tìm kiếm thông tin tổng quát, chứng chỉ Cambridge, khóa học, đội ngũ giáo viên.
   - `wewin_get_programs`: Phân loại chương trình theo độ tuổi (Mầm non 3-6t, Cambridge 6-12t, IELTS 12-18t và người lớn), tự động tư vấn chính xác khi người dùng hỏi độ tuổi (ví dụ: "con tôi 9 tuổi").
   - `wewin_get_contact`: Trả về thông tin hotline, Zalo, email, địa chỉ 2 cơ sở tại Quận Bình Thạnh và link đăng ký kiểm tra năng lực 4 kỹ năng miễn phí.
   - `wewin_get_page`: Trả về nội dung chi tiết theo URL cụ thể.
6. **Nguyên tắc "Không suy đoán" (Anti-Hallucination)**:
   - Các thông tin không niêm yết cố định trên website (như học phí cụ thể của từng cấp độ) được trả lời trung thực, hướng dẫn phụ huynh liên hệ hotline hoặc đăng ký test 4 kỹ năng miễn phí để được tư vấn chính xác.

---

## 📁 Cấu trúc thư mục dự án

```text
Wewin_AI_Connector/
│
├── .env.example              # Mẫu cấu hình môi trường (port, tokens, crawler settings)
├── .env                      # File cấu hình cục bộ (không commit)
├── .gitignore                # Danh sách file/thư mục bỏ qua khi dùng Git
├── requirements.txt          # Danh sách thư viện Python cần thiết
│
├── data/                     # Thư mục lưu trữ dữ liệu
│   ├── wewin_knowledge.json  # Dữ liệu tri thức đã chuẩn hóa (curated seeds + crawl)
│   └── wewin_fts.db          # Database SQLite FTS5 tìm kiếm toàn văn
│
├── src/                      # Mã nguồn chính của dự án
│   ├── config.py             # Quản lý cấu hình đọc từ .env
│   │
│   ├── crawler/              # PHASE 1: Thu thập và chuẩn hóa dữ liệu website
│   │   ├── curated_seeds.py  # Dữ liệu tri thức chuẩn xác được xác minh từ wein.edu.vn
│   │   ├── extractor.py      # Bóc tách HTML, loại bỏ header/footer/menu/quảng cáo
│   │   └── sitemap_crawler.py# Bộ crawler sitemap tôn trọng robots.txt, rate limit 0.8s
│   │
│   ├── storage/              # PHASE 2: Quản lý cache và FTS5
│   │   └── db.py             # SQLite FTS5 DatabaseManager (BM25 ranking, snippet)
│   │
│   ├── api/                  # PHASE 2: FastAPI Backend REST & Webhook
│   │   ├── app.py            # Khởi tạo FastAPI app, CORS, lifespan
│   │   ├── routes.py         # Endpoints: /health, /search, /programs, /contact, /page, /sync
│   │   └── schemas.py        # Pydantic schemas xác thực request & response
│   │
│   ├── mcp/                  # PHASE 3: XiaoZhi MCP Integration & Adapters
│   │   ├── tools.py          # Định nghĩa và thực thi 4 công cụ wewin_*
│   │   ├── xiaozhi_bridge.py # WebSocket Client Bridge kết nối XiaoZhi Cloud MCP
│   │   └── mcp_server.py     # Local WebSocket MCP Server endpoint (/ws/mcp)
│   │
│   └── utils/
│       └── logger.py         # Logger định dạng chuẩn UTF-8 và ghi log file
│
├── tests/                    # PHASE 4: Kiểm thử tự động
│   ├── test_crawler.py       # Kiểm thử bóc tách HTML và làm sạch boilerplate
│   ├── test_search.py        # Kiểm thử SQLite FTS5 tiếng Việt
│   ├── test_api.py           # Kiểm thử toàn diện 8 REST endpoints qua TestClient
│   └── test_xiaozhi_tools.py # Kiểm thử 5 câu hỏi chuẩn cho trợ lý XiaoZhi
│
├── run_server.py             # Chạy FastAPI Backend Server
├── run_crawler.py            # Chạy thu thập và lập chỉ mục website WeWIN
├── run_bridge.py             # Chạy WebSocket MCP Bridge kết nối XiaoZhi Cloud
│
├── README.md                 # Tài liệu tổng quan dự án
├── ARCHITECTURE.md           # Tài liệu kiến trúc hệ thống và luồng dữ liệu
├── SETUP_WINDOWS.md          # Hướng dẫn cài đặt và chạy trên Windows 10/11
├── XIAOZHI_INTEGRATION.md    # Hướng dẫn cấu hình công cụ trên XiaoZhi Console
└── TEST_REPORT.md            # Báo cáo kết quả kiểm thử thực tế 5 câu hỏi
```

---

## 🚀 Khởi động nhanh (Quick Start)

### 1. Chuẩn bị môi trường
Yêu cầu: Python 3.10 trở lên trên Windows.
```powershell
pip install -r requirements.txt
```

### 2. Tạo file cấu hình
Sao chép `.env.example` thành `.env`:
```powershell
copy .env.example .env
```

### 3. Thu thập dữ liệu và lập chỉ mục FTS5
Chạy lệnh crawler để tải nội dung từ website WeWIN và nạp vào database:
```powershell
python run_crawler.py
```

### 4. Khởi động Backend API Server
```powershell
python run_server.py
```
- API Base URL: `http://localhost:8000`
- Swagger UI Documentation: `http://localhost:8000/docs`

### 5. Chạy bộ kiểm thử (Test Suite)
```powershell
python tests/test_crawler.py
python tests/test_search.py
python tests/test_api.py
python tests/test_xiaozhi_tools.py
```

---

## 📡 Các Endpoint chính

| Method | Endpoint | Mô tả |
| :--- | :--- | :--- |
| `GET` | `/health` | Kiểm tra trạng thái hệ thống, kết nối DB và số bài viết đã lập chỉ mục |
| `GET` | `/search?q=...` | Tìm kiếm toàn văn FTS5, trả về danh sách trích đoạn và URL nguồn |
| `GET` | `/programs?age=9` | Danh sách chương trình đào tạo & gợi ý lộ trình theo độ tuổi |
| `GET` | `/contact` | Thông tin hotline, email, 2 cơ sở tại Bình Thạnh và link đăng ký test |
| `GET` | `/page?url=...` | Xem nội dung chi tiết của trang đã được cache |
| `POST` | `/sync` | Đồng bộ và thu thập lại dữ liệu website (cần `Authorization: Bearer <TOKEN>`) |
| `POST` | `/api/xiaozhi/tool` | Webhook đa năng nhận yêu cầu gọi công cụ từ XiaoZhi / Dify / OpenAI |
| `WS` | `/ws/mcp` | WebSocket MCP Server Endpoint chuẩn JSON-RPC 2.0 |

---

## 🎙️ 5 Câu hỏi chuẩn kiểm thử XiaoZhi (Phase 4)

1. **"WeWIN Education là gì?"**
   -> Trả lời: Trung tâm tiếng Anh chuyên Cambridge & IELTS tại TP.HCM, đối tác Cambridge Assessment & IDP.
2. **"WeWIN có những chương trình tiếng Anh nào?"**
   -> Trả lời: Tiếng Anh Mầm non (3-6 tuổi), Tiếng Anh Cambridge (6-12 tuổi), IELTS Explorer (12-18 tuổi và người lớn).
3. **"WeWIN có khóa IELTS không?"**
   -> Trả lời: Có lộ trình IELTS Explorer và luyện đề Cambridge IELTS; WeWIN là đối tác của IDP.
4. **"Thông tin liên hệ WeWIN là gì?"**
   -> Trả lời: Hotline 034 596 9388 / 037 866 9388, CS1: 292B Nơ Trang Long, CS2: 742 Xô Viết Nghệ Tĩnh, Bình Thạnh.
5. **"Con tôi 9 tuổi thì có chương trình nào phù hợp?"**
   -> Trả lời: Chương trình Tiếng Anh Cambridge (cấp độ Movers/Flyers tùy kết quả test 4 kỹ năng miễn phí).
