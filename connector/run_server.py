"""
Server Launcher for WeWIN AI Website Connector.
Runs FastAPI server via Uvicorn.
Usage:
    python run_server.py
"""
import sys
import io
from pathlib import Path
import uvicorn

# Fix Windows console UTF-8 output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import settings

def main():
    print("=" * 60)
    print("  WeWIN AI Website Connector for XiaoZhi ESP32-S3")
    print(f"  Listening on: http://{settings.SERVER_HOST}:{settings.SERVER_PORT}")
    print(f"  Documentation: http://localhost:{settings.SERVER_PORT}/docs")
    print("=" * 60)

    uvicorn.run(
        "src.api.app:app",
        host=settings.SERVER_HOST,
        port=settings.SERVER_PORT,
        reload=settings.DEBUG,
        log_level="info"
    )

if __name__ == "__main__":
    main()
