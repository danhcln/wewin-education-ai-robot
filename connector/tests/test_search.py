import sys
import io
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.storage.db import get_db
from src.crawler.curated_seeds import get_curated_seeds

def test_database_indexing_and_search():
    db = get_db()
    seeds = get_curated_seeds()
    db.index_records(seeds)

    # 1. Query: WeWIN Education là gì?
    res1 = db.search("WeWIN Education là gì", limit=2)
    assert len(res1) > 0
    assert any("WeWIN" in r["title"] for r in res1)
    assert any("https://wewin.edu.vn" in r["url"] for r in res1)

    # 2. Query: Chương trình tiếng Anh
    res2 = db.search("chương trình tiếng Anh", limit=2)
    assert len(res2) > 0
    assert any("Chương trình" in r["title"] for r in res2)

    # 3. Query: IELTS
    res3 = db.search("IELTS", limit=2)
    assert len(res3) > 0
    assert any("IELTS" in r["title"] or "IELTS" in r["snippet"] for r in res3)

    # 4. Query: Thông tin liên hệ
    contact = db.get_contact()
    assert "034 596 9388" in contact["hotline"]
    assert "292B Nơ Trang Long" in contact["campuses"][0]["address"]
    assert "742 Xô Viết Nghệ Tĩnh" in contact["campuses"][1]["address"]

    # 5. Query: 9 tuổi
    prog_9yo = db.get_programs(age=9)
    assert prog_9yo["recommendation"] is not None
    assert prog_9yo["recommendation"]["recommended_program"] == "Tiếng Anh Cambridge (Tiểu học)"
    assert prog_9yo["recommendation"]["age"] == 9

if __name__ == "__main__":
    test_database_indexing_and_search()
    print("ALL TESTS PASSED SUCCESSFULLY!")
