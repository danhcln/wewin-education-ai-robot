"""
Curated, high-precision baseline knowledge directly verified from https://wewin.edu.vn/
Serves as authoritative fallback and seed records.
"""
from datetime import datetime, timezone
from typing import List, Dict, Any

def get_curated_seeds() -> List[Dict[str, Any]]:
    now_iso = datetime.now(timezone.utc).isoformat()
    records = [
        {
            "id": "seed-intro",
            "title": "Giới thiệu về WeWIN Education",
            "url": "https://wewin.edu.vn/about/",
            "category": "about",
            "content": (
                "WeWIN Education (thuộc Trung tâm Ngoại ngữ Công Thành) là hệ thống trung tâm đào tạo tiếng Anh uy tín "
                "tại TP.HCM, chuyên giảng dạy tiếng Anh trẻ em, Cambridge và luyện thi IELTS. "
                "WeWIN tự hào đạt chứng nhận từ Cambridge Assessment, là đối tác trực tiếp của IDP (đơn vị đồng sở hữu "
                "kỳ thi IELTS trên toàn thế giới) và nhận chứng nhận chất lượng từ Edu2Review. "
                "Trung tâm nổi bật với đội ngũ giáo viên bản ngữ (Anh, Mỹ, Canada) và giáo viên Việt Nam giàu kinh nghiệm, "
                "hệ sinh thái học tập hiện đại kết hợp Game, Speaking AI, cùng hệ thống Report CO báo cáo định kỳ quá trình "
                "học và hỗ trợ kèm 1:1 miễn phí bồi dưỡng ngữ pháp cho học viên."
            ),
            "retrieved_at": now_iso,
            "last_modified": now_iso,
            "source_type": "seed"
        },
        {
            "id": "seed-programs-overview",
            "title": "Chương trình đào tạo tiếng Anh tại WeWIN Education",
            "url": "https://wewin.edu.vn/#ctrinhhoc",
            "category": "programs",
            "content": (
                "Hệ sinh thái đào tạo tiếng Anh tại WeWIN Education được thiết kế bài bản theo từng độ tuổi và cấp độ:\n"
                "1. Tiếng Anh Mầm non (3 – 6 tuổi): Giúp bé làm quen tiếng Anh tự nhiên qua trò chơi, bài hát, hình thành phản xạ và sự tự tin ban đầu.\n"
                "2. Tiếng Anh Cambridge (6 – 12 tuổi, học sinh tiểu học): Phát triển toàn diện 4 kỹ năng Nghe - Nói - Đọc - Viết; lộ trình chuẩn Cambridge gồm Starters, Movers, Flyers, KET, PET.\n"
                "3. IELTS Explorer & Luyện thi IELTS (12 – 18 tuổi và trên 18 tuổi): Tiếng Anh học thuật chuyên sâu, xây dựng nền tảng từ vựng, ngữ pháp vững chắc và bứt phá band điểm IELTS phục vụ mục tiêu học tập, xét tuyển đại học hoặc du học.\n"
                "Mọi học viên mới đều được tham gia buổi Test năng lực 4 kỹ năng miễn phí để xếp lớp đúng trình độ."
            ),
            "retrieved_at": now_iso,
            "last_modified": now_iso,
            "source_type": "seed"
        },
        {
            "id": "seed-program-9yo",
            "title": "Chương trình tiếng Anh cho trẻ 9 tuổi (6-12 tuổi) tại WeWIN",
            "url": "https://wewin.edu.vn/#ctrinhhoc",
            "category": "programs",
            "content": (
                "Đối với trẻ 9 tuổi (nằm trong khung độ tuổi 6 – 12 tuổi, học sinh tiểu học), chương trình đào tạo phù hợp nhất "
                "tại WeWIN Education là 'Chương trình Tiếng Anh Cambridge'.\n"
                "Lợi ích của chương trình:\n"
                "- Rèn luyện cân bằng cả 4 kỹ năng: Nghe, Nói, Đọc, Viết.\n"
                "- Tùy vào năng lực thực tế sau buổi kiểm tra đầu vào, bé sẽ được xếp vào cấp độ tương ứng: Starters, Movers hoặc Flyers.\n"
                "- Kết hợp học trên lớp với Game tương tác, Speaking AI và tài nguyên sách online độc quyền của WeWIN.\n"
                "- Báo bài và cập nhật tiến độ học định kỳ qua Zalo cho phụ huynh; hỗ trợ kèm 1:1 ngữ pháp trước các kỳ thi tại trường phổ thông.\n"
                "Phụ huynh có thể đăng ký buổi kiểm tra đánh giá năng lực 4 kỹ năng miễn phí cho con."
            ),
            "retrieved_at": now_iso,
            "last_modified": now_iso,
            "source_type": "seed"
        },
        {
            "id": "seed-ielts",
            "title": "Khóa học luyện thi IELTS tại WeWIN Education",
            "url": "https://wewin.edu.vn/ielts-placement-test/",
            "category": "ielts",
            "content": (
                "WeWIN Education có cung cấp các khóa học luyện thi IELTS chất lượng cao cho học sinh cấp 2, cấp 3 (12 - 18 tuổi) và sinh viên/người lớn.\n"
                "Điểm nổi bật của khóa IELTS tại WeWIN:\n"
                "- WeWIN là đối tác chính thức của IDP – đơn vị đồng sở hữu kỳ thi IELTS quốc tế.\n"
                "- Lộ trình luyện thi bài bản: IELTS Explorer từ cơ bản đến chuyên sâu, ôn luyện bộ đề Cambridge IELTS mới nhất.\n"
                "- Rèn luyện 4 kỹ năng: Listening, Reading, Writing và Speaking với phản hồi chi tiết từ giáo viên chuyên môn cao.\n"
                "- Có bài thi thử (IELTS Placement Test) đánh giá trình độ đầu vào chuẩn xác để lập kế hoạch ôn thi phù hợp."
            ),
            "retrieved_at": now_iso,
            "last_modified": now_iso,
            "source_type": "seed"
        },
        {
            "id": "seed-contact",
            "title": "Thông tin liên hệ và cơ sở WeWIN Education",
            "url": "https://wewin.edu.vn/",
            "category": "contact",
            "content": (
                "Thông tin liên hệ chính thức của WeWIN Education:\n"
                "- Hotline tư vấn: 034 596 9388 hoặc 037 866 9388 (Zalo/Điện thoại: 0988 596 388)\n"
                "- Email: ntloffice@wewin.edu.vn\n"
                "- Hệ thống cơ sở tại TP.HCM:\n"
                "  + Cơ sở 1 (CS1): 292B Nơ Trang Long, Phường 12, Quận Bình Thạnh, TP.HCM (Trung tâm Ngoại ngữ Công Thành)\n"
                "  + Cơ sở 2 (CS2): 742 Xô Viết Nghệ Tĩnh, Phường 25 (Thạnh Mỹ Tây), Quận Bình Thạnh, TP.HCM\n"
                "- Fanpage Facebook: https://www.facebook.com/winwineducation\n"
                "- Đăng ký kiểm tra trình độ & tư vấn miễn phí: https://wewin.edu.vn/dang-ky-tai-khoan-sach-online-free/"
            ),
            "retrieved_at": now_iso,
            "last_modified": now_iso,
            "source_type": "seed"
        },
        {
            "id": "seed-tuition-policy",
            "title": "Chính sách học phí và lịch học tại WeWIN Education",
            "url": "https://wewin.edu.vn/",
            "category": "policy",
            "content": (
                "Về học phí và lịch học tại WeWIN Education:\n"
                "- Website WeWIN nêu rõ định hướng 'Chi phí đầu tư hợp lý' để phụ huynh có thể đồng hành lâu dài cùng con.\n"
                "- Tuy nhiên, biểu phí chi tiết và lịch học từng lớp KHÔNG niêm yết công khai cố định trên website, vì học phí "
                "và thời khóa biểu phụ thuộc vào cấp độ cụ thể (Mầm non, Cambridge Starters/Movers/Flyers hay IELTS) sau khi học viên "
                "hoàn thành bài test năng lực 4 kỹ năng.\n"
                "- Phụ huynh vui lòng liên hệ hotline 034 596 9388 / 037 866 9388 hoặc đăng ký buổi test 4 kỹ năng miễn phí "
                "để nhận thông báo học phí chính xác và lịch học phù hợp nhất."
            ),
            "retrieved_at": now_iso,
            "last_modified": now_iso,
            "source_type": "seed"
        }
    ]
    # One cache page per URL. Preserve all authored seed sections rather than
    # allowing the homepage/contact or course/age sections to overwrite each other.
    unique = {}
    for record in records:
        if record["url"] not in unique:
            unique[record["url"]] = dict(record)
        else:
            unique[record["url"]]["content"] += "\n\n" + record["title"] + "\n" + record["content"]
    return list(unique.values())
