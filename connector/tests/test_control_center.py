import sys
from pathlib import Path

# Force UTF-8 encoding for Windows console output
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient
from src.api.app import app
from src.config import settings

client = TestClient(app)

def test_spa_serving():
    # Test root endpoint returns HTML
    res = client.get("/")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    assert "WeWIN AI Control Center" in res.text, "Index HTML missing title"
    print("[PASS] GET / -> Serves WeWIN AI Control Center SPA")

    # Test SPA client-side routes fallback to index.html
    for route in ["/assistants", "/robots", "/knowledge", "/sync", "/mcp-tools", "/logs", "/settings"]:
        res_route = client.get(route)
        assert res_route.status_code == 200, f"Route {route} returned {res_route.status_code}"
        assert "WeWIN AI Control Center" in res_route.text, f"Route {route} did not serve index.html"
    print("[PASS] SPA Route Fallback (/assistants, /robots, /knowledge, /sync, /mcp-tools, /logs, /settings)")

def test_assets_serving():
    # Verify logo and icon
    res_logo = client.get("/wewin_logo.png")
    assert res_logo.status_code == 200, f"wewin_logo.png failed: {res_logo.status_code}"
    assert len(res_logo.content) > 1000, "Logo image is empty or invalid"

    res_icon = client.get("/wewin_icon.png")
    assert res_icon.status_code == 200, f"wewin_icon.png failed: {res_icon.status_code}"
    assert len(res_icon.content) > 1000, "Icon image is empty or invalid"

    print("[PASS] Official Brand Assets (wewin_logo.png, wewin_icon.png) served correctly")

def test_auth_verify_endpoint():
    # Valid token
    admin_token = settings.ADMIN_SYNC_TOKEN
    res_valid = client.post("/api/auth/verify", json={"token": admin_token})
    assert res_valid.status_code == 200
    data = res_valid.json()
    assert data["valid"] is True
    assert data["role"] == "admin"

    # Invalid token
    res_invalid = client.post("/api/auth/verify", json={"token": "wrong_token_123"})
    assert res_invalid.status_code == 200
    data_inv = res_invalid.json()
    assert data_inv["valid"] is False

    print("[PASS] POST /api/auth/verify (Valid and Invalid tokens verified)")

def test_dashboard_stats():
    res = client.get("/api/dashboard/stats")
    assert res.status_code == 200
    data = res.json()
    assert data["service"] == "WeWIN AI Control Center"
    assert "database" in data
    assert "sync_engine" in data
    assert "mcp_bridge" in data
    assert len(data["robots"]) >= 1
    assert len(data["assistants"]) >= 1
    print(f"[PASS] GET /api/dashboard/stats -> {data['database']['total_pages']} indexed pages, {len(data['robots'])} robots")

def test_knowledge_pages():
    res = client.get("/api/knowledge/pages?page=1&limit=5")
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert data["total"] > 0
    assert len(data["items"]) <= 5
    first_item = data["items"][0]
    assert "title" in first_item
    assert "url" in first_item
    assert "content" in first_item
    print(f"[PASS] GET /api/knowledge/pages -> Total {data['total']} items, page 1 returned {len(data['items'])} items")

def test_mcp_tools():
    res = client.get("/api/mcp/tools")
    assert res.status_code == 200
    data = res.json()
    from src.mcp.tools import TOOL_DEFINITIONS
    assert data["total"] == len(TOOL_DEFINITIONS)
    tool_names = [t["name"] for t in data["tools"]]
    assert "wewin_search" in tool_names
    assert "wewin_get_programs" in tool_names
    assert "wewin_get_contact" in tool_names
    assert "wewin_get_page" in tool_names
    assert "wewin_test_connection" in tool_names
    print(f"[PASS] GET /api/mcp/tools -> Verified all 5 tools: {tool_names}")

def test_system_logs():
    res = client.get("/api/system/logs?limit=10")
    assert res.status_code == 200
    data = res.json()
    assert "logs" in data
    print(f"[PASS] GET /api/system/logs -> {len(data['logs'])} log entries returned")

def test_unlock_sync():
    admin_token = settings.ADMIN_SYNC_TOKEN
    headers = {"Authorization": f"Bearer {admin_token}"}
    res = client.post("/sync/unlock", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    print(f"[PASS] POST /sync/unlock -> {data['message']}")

if __name__ == "__main__":
    print("==================================================")
    print(" RUNNING PHASE 5 WEWIN AI CONTROL CENTER TESTS")
    print("==================================================")
    test_spa_serving()
    test_assets_serving()
    test_auth_verify_endpoint()
    test_dashboard_stats()
    test_knowledge_pages()
    test_mcp_tools()
    test_system_logs()
    test_unlock_sync()
    print("==================================================")
    print(" ALL WEWIN AI CONTROL CENTER TESTS PASSED (100%)")
    print("==================================================")
