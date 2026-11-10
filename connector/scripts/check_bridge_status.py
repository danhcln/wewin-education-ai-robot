import sys
from pathlib import Path
import urllib.request
import json

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import settings

token = settings.ADMIN_SYNC_TOKEN
req = urllib.request.Request("http://127.0.0.1:8000/api/dashboard/stats")
req.add_header("X-Admin-Token", token)
try:
    with urllib.request.urlopen(req, timeout=3) as r:
        d = json.loads(r.read().decode())
        m = d.get("mcp_bridge", {})
        print(f"{m.get('connection_status', 'unknown')},{m.get('tools_registered', 0)}")
except Exception:
    print("unknown,0")

