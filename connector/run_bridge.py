"""
Launcher for XiaoZhi Cloud MCP WebSocket Bridge.
Connects to XiaoZhi Cloud MCP Endpoint and bridges tool calls to WeWIN backend.
Usage:
    python run_bridge.py
"""
import sys
import io
import asyncio
import os
from urllib.parse import urlsplit
from pathlib import Path
from dotenv import load_dotenv

# Fix Windows console UTF-8 output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# Project root path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Guarantee .env is loaded from project root with override=False before loading config
load_dotenv(PROJECT_ROOT / ".env", override=False)

from src.mcp.xiaozhi_bridge import XiaoZhiMcpBridge

def main():
    print("=" * 65)
    print("  XiaoZhi Cloud MCP WebSocket Bridge for WeWIN Education")
    print("=" * 65)

    bridge = XiaoZhiMcpBridge()
    full_url = bridge.get_full_url()

    if not full_url:
        print("[WARNING] XIAOZHI_MCP_ENDPOINT is not configured in .env!")
        print("Please check your .env file in the project root directory:")
        print(f"Path: {PROJECT_ROOT / '.env'}")
        return

    print(f"  Target Endpoint (Masked): {XiaoZhiMcpBridge.mask_url(full_url)}")
    print("  Starting bridge loop... (Press Ctrl+C to stop)")
    print("=" * 65)

    guard=None
    # Simulated loopback brokers are isolated tests; every real Cloud bridge
    # for this checkout shares one OS lock, independent of JWT or retry age.
    if urlsplit(full_url).hostname not in ('127.0.0.1','localhost','::1'):
        from src.sync.locking import SyncLock,SyncAlreadyRunningError
        guard=SyncLock(os.getenv('BRIDGE_SINGLETON_PATH') or PROJECT_ROOT/'.maintenance/production-bridge.lock')
        try:guard.acquire('mcp_bridge')
        except SyncAlreadyRunningError:
            print('A production MCP Bridge is already running; no second connection was started.')
            return
    try:
        asyncio.run(bridge.run())
    except KeyboardInterrupt:
        print("\n[INFO] XiaoZhi Bridge stopped by user.")
    finally:
        if guard:guard.release()

if __name__ == "__main__":
    main()
