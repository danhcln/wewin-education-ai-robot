"""
XiaoZhi Cloud MCP WebSocket Bridge.
Connects to XiaoZhi Cloud MCP Endpoint (e.g. wss://api.xiaozhi.me/mcp/?token=...)
and exposes WeWIN tools via JSON-RPC 2.0.
"""
import asyncio
import contextlib
from .bridge_status import publish
import json
import re
import time
import urllib.parse
from typing import Dict, Any, Optional
import websockets

from src.config import settings
from src.utils.logger import logger
from .tools import TOOL_DEFINITIONS, execute_tool as execute_public_tool
from src.media.tools import MEDIA_NAMES, relay_cloud_media_tool

def execute_tool(name,arguments):
    if name in MEDIA_NAMES:return json.dumps(relay_cloud_media_tool(name,arguments),ensure_ascii=False)
    return execute_public_tool(name,arguments)

class XiaoZhiMcpBridge:
    def __init__(self, endpoint: Optional[str] = None, token: Optional[str] = None):
        # Refresh settings from .env
        settings.reload()
        self.endpoint = endpoint if endpoint is not None else settings.XIAOZHI_MCP_ENDPOINT
        self.token = token if token is not None else settings.XIAOZHI_MCP_TOKEN
        self.is_running = False

    @staticmethod
    def mask_url(url: str) -> str:
        """Safely masks sensitive token from URL for logging or display."""
        if not url:
            return ""
        try:
            parsed = urllib.parse.urlsplit(url)
            return urllib.parse.urlunsplit((parsed.scheme, parsed.hostname or "", parsed.path, "[REDACTED]" if parsed.query else "", ""))
        except ValueError:
            return "[REDACTED_ENDPOINT]"

    def get_full_url(self) -> str:
        """
        Constructs target WebSocket URL with token parameter cleanly.
        Prevents duplicate token concatenation and normalizes ws/wss schemes.
        """
        raw_endpoint = (self.endpoint or "").strip()
        raw_token = (self.token or "").strip()

        if not raw_endpoint:
            return ""

        # Normalize URL scheme: http:// -> ws://, https:// -> wss://
        if raw_endpoint.startswith("http://"):
            raw_endpoint = "ws://" + raw_endpoint[7:]
        elif raw_endpoint.startswith("https://"):
            raw_endpoint = "wss://" + raw_endpoint[8:]
        elif not (raw_endpoint.startswith("ws://") or raw_endpoint.startswith("wss://")):
            raw_endpoint = "wss://" + raw_endpoint

        # Parse URL components
        parsed = urllib.parse.urlparse(raw_endpoint)
        query_params = urllib.parse.parse_qs(parsed.query)

        # Check if token is already present in query parameters
        if "token" in query_params and query_params["token"]:
            # Token already in endpoint URL, do not duplicate
            final_url = raw_endpoint
        elif raw_token:
            # Token provided separately, attach it cleanly
            query_params["token"] = [raw_token]
            path = parsed.path or "/"
            new_query = urllib.parse.urlencode(query_params, doseq=True)
            new_parsed = parsed._replace(path=path, query=new_query)
            final_url = urllib.parse.urlunparse(new_parsed)
        else:
            final_url = raw_endpoint

        return final_url

    async def handle_message(self, ws: websockets.WebSocketClientProtocol, raw_msg: str):
        """Processes incoming JSON-RPC 2.0 messages from XiaoZhi."""
        try:
            data = json.loads(raw_msg)
        except json.JSONDecodeError:
            logger.error("Received invalid JSON from XiaoZhi broker (payload omitted)")
            return

        msg_id = data.get("id")
        method = data.get("method")
        params = data.get("params") or {}

        # 1. Handle incoming server responses or errors (where method is None)
        if method is None:
            if "error" in data:
                logger.info("MCP protocol event (payload omitted)")
            elif "result" in data:
                logger.info("MCP protocol event (payload omitted)")
            else:
                logger.info("MCP protocol event (payload omitted)")
            return

        # 2. MCP Handshake / Initialize
        if method == "initialize":
            logger.info("MCP protocol event (payload omitted)")
            resp = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {
                            "listChanged": True
                        }
                    },
                    "serverInfo": {
                        "name": "wewin-ai-connector",
                        "version": "1.0.0"
                    }
                }
            }
            await ws.send(json.dumps(resp))
            logger.info("📤 [SENT] MCP initialize response to XiaoZhi broker.")

        # 3. Notifications (e.g. initialized)
        elif method == "notifications/initialized":
            logger.info("✅ [NOTIF] XiaoZhi initialized notification received. MCP handshake completed!")

        # 4. List available tools
        elif method == "tools/list":
            logger.info("MCP protocol event (payload omitted)")
            resp = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "tools": TOOL_DEFINITIONS
                }
            }
            await ws.send(json.dumps(resp))
            tool_names = [t["name"] for t in TOOL_DEFINITIONS]
            logger.info(f"📤 [SENT] Registered {len(TOOL_DEFINITIONS)} WeWIN tools with XiaoZhi: {tool_names}")

        # 5. Execute tool call (CRITICAL ACTION)
        elif method == "tools/call":
            start_time = time.time()
            tool_name = params.get("name", "")
            arguments = params.get("arguments") or {}

            logger.info("\n" + "=" * 70)
            logger.info(f"🔔 [XIAOZHI TOOLS/CALL RECEIVED!]")
            logger.info(f"   Tool Name: {tool_name}")
            if isinstance(arguments, dict) and ('action' in arguments or 'query' in arguments):
                logger.info(f"   Param: action={arguments.get('action', '')}, query={arguments.get('query', '')}")
            logger.info("=" * 70)

            try:
                tool_output = await asyncio.to_thread(execute_tool, tool_name, arguments)
                duration_ms = round((time.time() - start_time) * 1000, 2)
                resp = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": tool_output
                            }
                        ],
                        "isError": False
                    }
                }
                logger.info("MCP protocol event (payload omitted)")
                logger.info(f"   Output length: {len(tool_output)} chars")
                logger.info("MCP protocol event (payload omitted)")
            except Exception as e:
                duration_ms = round((time.time() - start_time) * 1000, 2)
                logger.info("MCP protocol event (payload omitted)")
                resp = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": "Lỗi khi thực thi công cụ. Vui lòng thử lại sau."
                            }
                        ],
                        "isError": True
                    }
                }

            await ws.send(json.dumps(resp))
            logger.info("MCP protocol event (payload omitted)")

        # 6. Ping / Keepalive
        elif method == "ping":
            resp = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {}
            }
            await ws.send(json.dumps(resp))

        else:
            logger.info("MCP protocol event (payload omitted)")
            if msg_id is not None:
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method '{method}' not found"
                    }
                }
                await ws.send(json.dumps(err_resp))

    async def run(self):
        """One connection, bounded exponential retries, private liveness evidence."""
        full_url = self.get_full_url()
        if not full_url:
            publish("not_connected")
            logger.warning("Bridge endpoint is not configured")
            return
        self.is_running = True
        retry_delay = 2
        headers = {"Authorization": f"Bearer {self.token.strip()}"} if (self.token or "").strip() else None

        async def heartbeat():
            while True:
                publish("connected")
                await asyncio.sleep(15)

        try:
            while self.is_running:
                publish("not_connected")
                connected_at = None
                try:
                    async with websockets.connect(full_url, additional_headers=headers, proxy=None,
                            open_timeout=15, ping_interval=20, ping_timeout=20, close_timeout=10,
                            max_size=1024 * 1024) as ws:
                        connected_at = time.monotonic()
                        publish("connected")
                        task = asyncio.create_task(heartbeat())
                        try:
                            async for message in ws:
                                await self.handle_message(ws, message)
                        finally:
                            task.cancel()
                            with contextlib.suppress(asyncio.CancelledError):
                                await task
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    logger.warning("Bridge disconnected (%s); retry in %ss", type(error).__name__, retry_delay)
                publish("not_connected")
                if connected_at is not None and time.monotonic() - connected_at >= 60:
                    retry_delay = 2
                if self.is_running:
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 60)
        finally:
            self.is_running = False
            publish("not_connected")
