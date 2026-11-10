"""
Local MCP Server Endpoint for WebSocket and SSE clients.
Enables local agents or XiaoZhi to connect directly to this backend as an MCP Server.
"""
import json
import asyncio
from typing import Dict, Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.utils.logger import logger
from .tools import TOOL_DEFINITIONS, execute_tool

mcp_router = APIRouter()

@mcp_router.websocket("/ws/mcp")
async def websocket_mcp_server(websocket: WebSocket):
    """
    Direct WebSocket MCP Server Endpoint.
    Clients connect to ws://<host>:<port>/ws/mcp and send JSON-RPC 2.0 requests.
    """
    await websocket.accept()
    logger.info("New client connected to local /ws/mcp endpoint.")

    try:
        while True:
            raw_text = await websocket.receive_text()
            try:
                data = json.loads(raw_text)
            except json.JSONDecodeError:
                continue

            msg_id = data.get("id")
            method = data.get("method")
            params = data.get("params", {})

            if method == "initialize":
                resp = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {"listChanged": False}},
                        "serverInfo": {"name": "wewin-mcp-server", "version": "1.0.0"}
                    }
                }
                await websocket.send_text(json.dumps(resp))

            elif method == "tools/list":
                resp = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"tools": TOOL_DEFINITIONS}
                }
                await websocket.send_text(json.dumps(resp))

            elif method == "tools/call":
                tool_name = params.get("name", "")
                arguments = params.get("arguments", {})
                # Public URL reads must not block event-loop heartbeat/other clients.
                tool_output = await asyncio.to_thread(execute_tool, tool_name, arguments)
                resp = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{"type": "text", "text": tool_output}],
                        "isError": False
                    }
                }
                await websocket.send_text(json.dumps(resp))

            elif method == "ping":
                resp = {"jsonrpc": "2.0", "id": msg_id, "result": {}}
                await websocket.send_text(json.dumps(resp))

    except WebSocketDisconnect:
        logger.info("Client disconnected from /ws/mcp.")
    except Exception as e:
        logger.error("Error in /ws/mcp handler (%s)", type(e).__name__)
