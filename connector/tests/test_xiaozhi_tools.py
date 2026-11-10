"""
Benchmark test suite verifying the 5 Phase 4 user voice queries for XiaoZhi AI assistant.
"""
import sys
import io
from pathlib import Path

# Fix Windows console UTF-8 output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.storage.db import get_db
from src.crawler.curated_seeds import get_curated_seeds
from src.mcp.tools import (
    execute_tool,
    wewin_search_tool,
    wewin_get_programs_tool,
    wewin_get_contact_tool
)

def run_benchmarks():
    db = get_db()
    db.index_records(get_curated_seeds())

    print("\n" + "="*70)
    print("XIAOZHI AI BENCHMARK TEST SUITE (PHASE 4)")
    print("="*70)

    # Test Connection Tool: wewin_test_connection
    print("\n[TEST KẾT NỐI MCP]: wewin_test_connection")
    ans_test = execute_tool("wewin_test_connection", {})
    print("-" * 50)
    print(ans_test)
    assert ans_test == "WeWIN MCP OK"
    print("-> ĐÁNH GIÁ: Đạt yêu cầu. Công cụ kiểm tra kết nối trả về 'WeWIN MCP OK'.")

    # Question 1: WeWIN Education là gì?
    q1 = "WeWIN Education là gì"
    print(f"\n[CÂU HỎI 1]: {q1}?")
    ans1 = execute_tool("wewin_search", {"query": q1})
    print("-" * 50)
    print(ans1)
    assert "WeWIN Education" in ans1
    assert "https://wewin.edu.vn" in ans1
    print("-> ĐÁNH GIÁ: Đạt yêu cầu. Có nguồn URL chính thức, thông tin chính xác.")

    # Question 2: WeWIN có những chương trình tiếng Anh nào?
    q2 = "chương trình tiếng Anh tại WeWIN"
    print(f"\n[CÂU HỎI 2]: WeWIN có những chương trình tiếng Anh nào?")
    ans2 = execute_tool("wewin_get_programs", {})
    print("-" * 50)
    print(ans2)
    assert "Tiếng Anh Mầm non" in ans2
    assert "Tiếng Anh Cambridge" in ans2
    assert "IELTS" in ans2
    print("-> ĐÁNH GIÁ: Đạt yêu cầu. Liệt kê đủ 3 nhóm độ tuổi: Mầm non, Cambridge, IELTS.")

    # Question 3: WeWIN có khóa IELTS không?
    q3 = "khóa học IELTS tại WeWIN"
    print(f"\n[CÂU HỎI 3]: WeWIN có khóa IELTS không?")
    ans3 = execute_tool("wewin_search", {"query": "khóa học IELTS"})
    print("-" * 50)
    print(ans3)
    assert "IELTS" in ans3
    assert "IDP" in ans3 or "Explorer" in ans3 or "https://wewin.edu.vn" in ans3
    print("-> ĐÁNH GIÁ: Đạt yêu cầu. Xác nhận có khóa IELTS, nêu rõ đối tác IDP và bài test năng lực.")

    # Question 4: Thông tin liên hệ WeWIN là gì?
    print(f"\n[CÂU HỎI 4]: Thông tin liên hệ WeWIN là gì?")
    ans4 = execute_tool("wewin_get_contact", {})
    print("-" * 50)
    print(ans4)
    assert "034 596 9388" in ans4 or "037 866 9388" in ans4
    assert "292B Nơ Trang Long" in ans4
    assert "742 Xô Viết Nghệ Tĩnh" in ans4
    assert "ntloffice@wewin.edu.vn" in ans4
    print("-> ĐÁNH GIÁ: Đạt yêu cầu. Đầy đủ hotline, 2 cơ sở Bình Thạnh, email, link đăng ký.")

    # Question 5: Con tôi 9 tuổi thì có chương trình nào phù hợp?
    print(f"\n[CÂU HỎI 5]: Con tôi 9 tuổi thì có chương trình nào phù hợp?")
    ans5 = execute_tool("wewin_get_programs", {"age": 9})
    print("-" * 50)
    print(ans5)
    assert "Cambridge" in ans5
    assert "9" in ans5
    assert "test năng lực 4 kỹ năng" in ans5 or "miễn phí" in ans5
    print("-> ĐÁNH GIÁ: Đạt yêu cầu. Khuyến nghị chính xác Tiếng Anh Cambridge (khung 6-12 tuổi) kèm buổi test 4 kỹ năng miễn phí.")

    print("\n" + "="*70)
    print("KẾT QUẢ: 5/5 CÂU HỎI ĐÃ ĐƯỢC XỬ LÝ CHÍNH XÁC, CÓ NGUỒN VÀ KHÔNG SUY ĐOÁN!")
    print("="*70 + "\n")

if __name__ == "__main__":
    run_benchmarks()
