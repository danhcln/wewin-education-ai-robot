import sys
import io
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.crawler.extractor import PageExtractor

def test_extractor():
    sample_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Chương trình Cambridge - WeWIN Education</title>
        <meta name="description" content="Chương trình tiếng Anh Cambridge chuẩn quốc tế cho trẻ từ 6 đến 12 tuổi">
    </head>
    <body>
        <header>
            <nav class="nav-menu">
                <a href="/">Trang chủ</a>
                <a href="/about">Giới thiệu</a>
            </nav>
        </header>
        <div class="sidebar">
            <p>Banner quảng cáo</p>
        </div>
        <main>
            <div class="entry-content">
                <h1>Khóa học tiếng Anh Cambridge cho trẻ</h1>
                <p>WeWIN Education tự hào là đối tác đào tạo chương trình Cambridge hàng đầu tại TP.HCM.</p>
                <p>Khóa học gồm các cấp độ Starters, Movers, Flyers, KET, PET rèn luyện 4 kỹ năng.</p>
            </div>
        </main>
        <footer>
            <div class="footer-wrapper">
                <p>Hotline: 034 596 9388</p>
            </div>
        </footer>
    </body>
    </html>
    """
    res = PageExtractor.clean_html(sample_html, "https://wewin.edu.vn/cambridge/")
    assert res is not None
    assert "Chương trình Cambridge" in res["title"]
    assert "WeWIN" not in res["title"]  # Cleaned suffix
    assert res["category"] == "cambridge"
    assert "Starters, Movers, Flyers" in res["content"]
    assert "Banner quảng cáo" not in res["content"]
    assert "Trang chủ" not in res["content"]
    print("[PASS] test_extractor passed successfully!")

if __name__ == "__main__":
    test_extractor()
