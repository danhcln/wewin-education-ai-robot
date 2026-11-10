import asyncio
import os
import tempfile
import time
import unittest
from pathlib import Path
import websockets
from src.mcp.xiaozhi_bridge import XiaoZhiMcpBridge
from src.mcp import bridge_status

class TestBridgeReconnect(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.status_file = Path(self.tmpdir.name) / "bridge-status.json"
        os.environ["BRIDGE_STATUS_PATH"] = str(self.status_file)
        self.port = 18765
        self.connection_count = 0
        self.server_ready = asyncio.Event()

    async def asyncTearDown(self):
        os.environ.pop("BRIDGE_STATUS_PATH", None)
        self.tmpdir.cleanup()

    async def test_bridge_auto_reconnect_and_backoff(self):
        # Create a mock WebSocket server that drops the first connection and accepts the second
        async def mock_handler(websocket):
            self.connection_count += 1
            if self.connection_count == 1:
                # First attempt: drop immediately to trigger backoff & reconnect
                await websocket.close(code=1001, reason="Simulated network failure")
            else:
                # Second attempt: keep alive and handle ping/heartbeat
                try:
                    async for msg in websocket:
                        pass
                except websockets.exceptions.ConnectionClosed:
                    pass

        server = await websockets.serve(mock_handler, "127.0.0.1", self.port)
        
        bridge = XiaoZhiMcpBridge(
            endpoint=f"ws://127.0.0.1:{self.port}",
            token="test-reconnect-token"
        )

        bridge_task = asyncio.create_task(bridge.run())

        # Wait for bridge to connect (1st attempt -> drop -> wait 2s -> 2nd attempt -> success)
        start = time.monotonic()
        reconnected = False
        while time.monotonic() - start < 10.0:
            if self.connection_count >= 2:
                # Check status file
                status = bridge_status.read_status()
                if status == "connected":
                    reconnected = True
                    break
            await asyncio.sleep(0.2)

        # Stop bridge
        bridge.is_running = False
        bridge_task.cancel()
        try:
            await bridge_task
        except asyncio.CancelledError:
            pass

        server.close()
        await server.wait_closed()

        self.assertTrue(reconnected, f"Bridge did not reconnect automatically (connection_count={self.connection_count})")
        self.assertGreaterEqual(self.connection_count, 2)
        print("\n===============================")
        print("BRIDGE_AUTO_RECONNECT_PASS")
        print("===============================\n")

if __name__ == "__main__":
    unittest.main()

