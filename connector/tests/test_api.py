import sys
import io
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient
from src.api.app import app
from src.storage.db import get_db
from src.crawler.curated_seeds import get_curated_seeds

client = TestClient(app)

def test_api_endpoints():
    # Ensure DB is seeded
    db = get_db()
    db.index_records(get_curated_seeds())

    # 1. Health
    r_health = client.get("/health")
    assert r_health.status_code == 200
    data_health = r_health.json()
    assert data_health["status"] == "healthy"
    assert data_health["database_ok"] is True
    assert data_health["total_indexed_articles"] > 0
    print("[PASS] GET /health")

    # 2. Search
    r_search = client.get("/search?q=WeWIN")
    assert r_search.status_code == 200
    data_search = r_search.json()
    assert data_search["total_results"] > 0
    print("[PASS] GET /search?q=WeWIN")

    # 3. Programs without age
    r_prog = client.get("/programs")
    assert r_prog.status_code == 200
    data_prog = r_prog.json()
    assert len(data_prog["programs"]) >= 3
    print("[PASS] GET /programs")

    # 4. Programs with age=9
    r_prog9 = client.get("/programs?age=9")
    assert r_prog9.status_code == 200
    data_prog9 = r_prog9.json()
    assert data_prog9["recommendation"] is not None
    assert "Cambridge" in data_prog9["recommendation"]["recommended_program"]
    print("[PASS] GET /programs?age=9")

    # 5. Contact
    r_contact = client.get("/contact")
    assert r_contact.status_code == 200
    data_contact = r_contact.json()
    assert "034 596 9388" in data_contact["hotline"]
    assert len(data_contact["campuses"]) == 2
    print("[PASS] GET /contact")

    # 6. XiaoZhi HTTP Tool Webhook (wewin_search)
    r_tool = client.post("/api/xiaozhi/tool", json={
        "tool": "wewin_search",
        "arguments": {"query": "IELTS"}
    })
    assert r_tool.status_code == 200
    data_tool = r_tool.json()
    assert len(data_tool["results"]) > 0
    print("[PASS] POST /api/xiaozhi/tool (wewin_search)")

    # 7. XiaoZhi HTTP Tool Webhook (wewin_get_programs for 9yo)
    r_tool_prog = client.post("/api/xiaozhi/tool", json={
        "tool": "wewin_get_programs",
        "arguments": {"age": 9}
    })
    assert r_tool_prog.status_code == 200
    assert r_tool_prog.json()["data"]["recommendation"]["age"] == 9
    print("[PASS] POST /api/xiaozhi/tool (wewin_get_programs for 9yo)")

    # 8. Sync unauthorized
    r_sync_unauth = client.post("/sync")
    assert r_sync_unauth.status_code == 401
    print("[PASS] POST /sync (Unauthorized check)")

if __name__ == "__main__":
    test_api_endpoints()
    print("ALL API ENDPOINT TESTS PASSED!")
