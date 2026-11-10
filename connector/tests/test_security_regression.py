"""FIX 01 only: python -B -m unittest tests.test_security_regression -v

All SQLite/JSON/lock/static fixtures live in a temporary directory. No crawler,
Cloud connection, server listener, or existing test suite is started.
"""
import asyncio
import contextlib
import io
import importlib
import json
import logging
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch


class SecurityRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = contextlib.ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.tmp = Path(cls.stack.enter_context(tempfile.TemporaryDirectory(prefix="wewin-security-")))
        cls.admin = secrets.token_urlsafe(32)
        cls.cloud = secrets.token_urlsafe(32)
        cls.query_secret = secrets.token_urlsafe(32)
        cls.stack.enter_context(patch.dict(os.environ, {
            "DATABASE_PATH": str(cls.tmp / "isolated.db"),
            "KNOWLEDGE_JSON_PATH": str(cls.tmp / "isolated.json"),
            "ADMIN_SYNC_TOKEN": cls.admin, "ADMIN_SYNC_TOKEN_FILE": "",
            "AUTO_SYNC_ENABLED": "false", "DEBUG": "false", "CORS_ALLOWED_ORIGINS": "",
            "XIAOZHI_MCP_TOKEN": cls.cloud,
            "XIAOZHI_MCP_ENDPOINT": "wss://fixture.invalid/private/endpoint?token=" + cls.query_secret,
        }))
        logger_module = types.ModuleType("src.utils.logger")
        logger_module.logger = logging.getLogger("security-regression-isolated")
        logger_module.logger.handlers = [logging.NullHandler()]
        logger_module.logger.propagate = False
        cls.stack.enter_context(patch.dict(sys.modules, {"src.utils.logger": logger_module}))
        cls.stack.enter_context(patch("requests.sessions.Session.request", side_effect=AssertionError("Network forbidden in security tests")))
        cls.stack.enter_context(patch("websockets.connect", side_effect=AssertionError("Cloud connections forbidden in security tests")))

        from src.config import settings
        from src.storage.db import DatabaseManager
        import src.storage.db as storage
        app_module = importlib.import_module("src.api.app")
        routes = importlib.import_module("src.api.routes")
        from fastapi.testclient import TestClient
        from src.sync.sync_engine import SyncReport
        cls.settings, cls.app_module, cls.routes = settings, app_module, routes
        cls.stack.enter_context(contextlib.chdir(cls.tmp))  # Even relative log reads are isolated.
        class ClosingConnection(sqlite3.Connection):
            def __exit__(self, *args):
                try:
                    return super().__exit__(*args)
                finally:
                    self.close()
        class IsolatedDatabase(DatabaseManager):
            def get_connection(self):
                connection = sqlite3.connect(str(self.db_path), factory=ClosingConnection)
                connection.row_factory = sqlite3.Row
                self._register_public_policy(connection)
                return connection
        cls.db = IsolatedDatabase(cls.tmp / "isolated.db")
        cls.stack.enter_context(patch.object(storage, "_db_instance", cls.db))
        cls.db.index_records([{
            "url": "https://wewin.edu.vn/fixture/", "title": "Fixture IELTS",
            "category": "ielts", "content": "Isolated WeWIN IELTS searchable fixture content.",
        }])
        cls.stack.enter_context(patch.object(app_module, "get_db", return_value=cls.db))
        lock = MagicMock()
        lock.is_locked.return_value = False
        lock.lock_path = cls.tmp / "never-created.lock"
        cls.stack.enter_context(patch.object(routes, "SyncLock", return_value=lock))
        cls.engine = MagicMock()
        cls.engine.run_sync.return_value = SyncReport(
            started_at="2026-10-25T00:00:00+00:00", completed_at="2026-10-25T00:00:01+00:00",
            status="success", duration_seconds=1, total_discovered=1, pages_unchanged=1,
        )
        cls.stack.enter_context(patch.object(routes, "get_sync_engine", return_value=cls.engine))

        cls.dist = cls.tmp / "site" / "dist"
        (cls.dist / "assets").mkdir(parents=True)
        for name, content in {
            "index.html": "<!doctype html><title>WeWIN AI Control Center</title>",
            "wewin_logo.png": "fixture-image", "assets/index-fixture.js": "console.info('fixture')",
            "assets/index-fixture.css": "body {color: black}",
            ".env": "private-fixture", "assets/.env": "private-fixture",
            "assets/index.js.map": "private-fixture", "assets/source.py": "private-fixture",
            "assets/token.txt": "private-fixture",
        }.items():
            (cls.dist / name).write_text(content, encoding="utf-8")
        cls.outside = cls.tmp / "outside"
        cls.outside.mkdir()
        (cls.outside / "secret.js").write_text("private-outside-fixture", encoding="utf-8")
        (cls.tmp / "site" / ".env").write_text("private-outside-fixture", encoding="utf-8")
        cls.app = app_module.create_app(static_dir=cls.dist)
        cls.client = cls.stack.enter_context(TestClient(cls.app, raise_server_exceptions=False))
        cls.headers = {"Authorization": "Bearer " + cls.admin}

    @classmethod
    def tearDownClass(cls):
        # Windows SQLite connections may otherwise linger until GC.
        import gc
        gc.collect()
        cls.stack.close()

    def test_01_traversal_and_sensitive_files_are_denied(self):
        paths = [
            "/%2e%2e/.env", "/assets/%2e%2e/%2e%2e/.env",
            "/%252e%252e/.env", "/..%5c.env", "/assets/..%5c..%5c.env",
            "/C:%5cWindows%5cwin.ini", "/assets/index-fixture.js::$DATA",
            "/.env", "/.env.example", "/.git/config", "/.secrets/admin_sync_token",
            "/src/config.py", "/run_server.py", "/requirements.txt", "/package.json",
            "/data/wewin_fts.db", "/data/wewin_fts.db-wal", "/logs/connector.log",
            "/assets/.env", "/assets/source.py", "/assets/token.txt", "/assets/index.js.map",
            "/unknown-route", "/assets/missing.js",
        ]
        for path in paths:
            with self.subTest(path=path):
                r = self.client.get(path)
                self.assertEqual(r.status_code, 404)
                self.assertNotIn("private-fixture", r.text)
                self.assertNotIn("private-outside-fixture", r.text)

    def test_02_symlink_or_junction_cannot_escape_static_root(self):
        link = self.dist / "assets" / "escape"
        try:
            link.symlink_to(self.outside, target_is_directory=True)
        except OSError:
            if os.name != "nt":
                raise
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(self.outside)], capture_output=True)
            self.assertEqual(result.returncode, 0, "Unable to construct isolated junction fixture")
        r = self.client.get("/assets/escape/secret.js")
        self.assertEqual(r.status_code, 404)
        self.assertNotIn("private-outside-fixture", r.text)

    def test_03_spa_routes_and_public_assets_still_work(self):
        for path in ["/", "/assistants", "/robots", "/knowledge", "/sync", "/mcp-tools", "/logs", "/settings", "/robots/"]:
            with self.subTest(path=path):
                r = self.client.get(path)
                self.assertEqual(r.status_code, 200)
                self.assertIn("WeWIN AI Control Center", r.text)
                self.assertEqual(r.headers["x-content-type-options"], "nosniff")
        for path in ["/wewin_logo.png", "/assets/index-fixture.js", "/assets/index-fixture.css"]:
            self.assertEqual(self.client.get(path).status_code, 200)

    def test_04_admin_endpoints_deny_missing_wrong_or_query_credentials(self):
        endpoints = [("GET", "/api/dashboard/stats"), ("GET", "/api/knowledge/pages"),
                     ("GET", "/api/system/logs"), ("GET", "/sync/status"),
                     ("GET", "/sync/history"), ("POST", "/sync"), ("POST", "/sync/unlock")]
        self.engine.reset_mock()
        for method, path in endpoints:
            for headers in [{}, {"Authorization": "Bearer invalid"}, {"Authorization": "Basic invalid"}, {"X-Admin-Token": "invalid"}]:
                with self.subTest(method=method, path=path, headers=list(headers)):
                    r = self.client.request(method, path, headers=headers)
                    self.assertEqual(r.status_code, 401)
                    self.assertEqual(r.headers["cache-control"], "no-store")
            self.assertEqual(self.client.request(method, path, params={"token": self.admin}).status_code, 401)
        self.engine.run_sync.assert_not_called()

    def test_05_authorized_admin_access_uses_only_isolated_fixtures(self):
        for path in ["/api/dashboard/stats", "/api/knowledge/pages", "/api/system/logs", "/sync/status", "/sync/history"]:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path, headers=self.headers).status_code, 200)
        self.assertEqual(self.client.get("/sync/history", headers={"X-Admin-Token": self.admin}).status_code, 200)
        self.assertEqual(self.client.post("/sync", headers=self.headers).status_code, 200)
        self.assertEqual(self.client.post("/sync/unlock", headers=self.headers).status_code, 200)
        self.assertTrue(self.db.db_path.is_relative_to(self.tmp))

    def test_06_auth_verification_and_fail_closed_configuration(self):
        for token, expected in [(self.admin, True), ("invalid", False), ("", False)]:
            r = self.client.post("/api/auth/verify", json={"token": token})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["valid"], expected)
            if token:
                self.assertFalse(token in r.text)
        with patch.object(self.settings, "ADMIN_SYNC_TOKEN", ""):
            self.assertEqual(self.client.get("/api/dashboard/stats", headers=self.headers).status_code, 401)
            self.assertFalse(self.client.post("/api/auth/verify", json={"token": ""}).json()["valid"])
        r = self.client.post("/api/auth/verify", json={"token": self.admin * 20})
        self.assertEqual(r.status_code, 422)
        self.assertFalse(self.admin in r.text)
        self.assertNotIn('"input"', r.text)

    def test_07_dashboard_never_returns_connection_credentials(self):
        r = self.client.get("/api/dashboard/stats", headers=self.headers)
        self.assertEqual(r.status_code, 200)
        for forbidden in [self.admin, self.cloud, self.query_secret, "fixture.invalid", '"token_masked"', '"endpoint"', '"token_configured"']:
            self.assertFalse(forbidden in r.text)
        self.assertTrue(r.json()["mcp_bridge"]["connection_configured"])

    def test_08_history_and_log_secrets_are_redacted(self):
        record = {"id": 1, "started_at": "2026-10-25T00:00:00Z", "completed_at": "2026-10-25T00:00:01Z",
                  "status": "failed", "duration_seconds": 1, "total_discovered": 0,
                  "pages_added": 0, "pages_updated": 0, "pages_unchanged": 0, "pages_failed": 1,
                  "trigger_type": "fixture", "error_summary": " ".join([self.admin, self.cloud, self.settings.XIAOZHI_MCP_ENDPOINT])}
        with patch.object(self.db, "get_sync_history", return_value=[record]), patch.object(self.db, "get_last_sync", return_value=record):
            for path in ["/api/dashboard/stats", "/sync/history", "/sync/status", "/api/system/logs"]:
                r = self.client.get(path, headers=self.headers)
                self.assertEqual(r.status_code, 200)
                for secret in [self.admin, self.cloud, self.query_secret]:
                    self.assertFalse(secret in r.text)

    def test_09_public_apis_and_http_tools_remain_public(self):
        for path in ["/health", "/search?q=IELTS", "/programs?age=9", "/contact", "/page?url=https://wewin.edu.vn/fixture/", "/api/mcp/tools"]:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        for name, args in [("wewin_test_connection", {}), ("wewin_search", {"query": "IELTS"}),
                           ("wewin_get_programs", {"age": 9}), ("wewin_get_contact", {}),
                           ("wewin_get_page", {"url": "https://wewin.edu.vn/fixture/"})]:
            self.assertEqual(self.client.post("/api/xiaozhi/tool", json={"tool": name, "arguments": args}).status_code, 200)

    def test_10_local_websocket_mcp_is_unchanged(self):
        with self.client.websocket_connect("/ws/mcp") as ws:
            for msg_id, method, params in [(1, "initialize", {}), (2, "tools/list", {}),
                                          (3, "tools/call", {"name": "wewin_test_connection", "arguments": {}})]:
                ws.send_json({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params})
                response = ws.receive_json()
                self.assertEqual(response["id"], msg_id)
                if method == "tools/list":
                    from src.mcp.tools import TOOL_DEFINITIONS
                    self.assertEqual({t['name'] for t in response['result']['tools']}, {t['name'] for t in TOOL_DEFINITIONS})
                if method == "tools/call": self.assertEqual(response["result"]["content"][0]["text"], "WeWIN MCP OK")

    def test_11_cloud_bridge_message_dispatch_without_cloud_connection(self):
        from src.mcp.xiaozhi_bridge import XiaoZhiMcpBridge
        class Socket:
            messages = []
            async def send(self, data): self.messages.append(json.loads(data))
        async def run():
            bridge, socket = XiaoZhiMcpBridge(endpoint="wss://fixture.invalid/mcp", token=""), Socket()
            await bridge.handle_message(socket, json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}))
            from src.mcp.tools import TOOL_DEFINITIONS
            self.assertEqual({t['name'] for t in socket.messages[-1]['result']['tools']}, {t['name'] for t in TOOL_DEFINITIONS})
            await bridge.handle_message(socket, json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "wewin_test_connection"}}))
            self.assertEqual(socket.messages[-1]["result"]["content"][0]["text"], "WeWIN MCP OK")
        asyncio.run(run())

    def test_12_cors_does_not_allow_untrusted_origins(self):
        r = self.client.options("/api/dashboard/stats", headers={"Origin": "https://untrusted.invalid", "Access-Control-Request-Method": "GET"})
        self.assertEqual(r.status_code, 400)
        self.assertNotIn("access-control-allow-origin", r.headers)
        self.assertNotIn("access-control-allow-credentials", r.headers)

    def test_13_secret_configuration_has_no_default_and_respects_environment(self):
        from src.config import load_admin_token, Settings
        self.assertEqual(load_admin_token({}), "")
        self.assertEqual(load_admin_token({"ADMIN_SYNC_TOKEN": "short-development-credential"}), "")
        secret_file = self.tmp / "credential"
        secret_file.write_text(self.admin, encoding="utf-8")
        self.assertTrue(load_admin_token({"ADMIN_SYNC_TOKEN_FILE": str(secret_file)}) == self.admin)
        self.assertEqual(load_admin_token({"ADMIN_SYNC_TOKEN_FILE": str(secret_file), "ADMIN_SYNC_TOKEN": self.admin}), "")
        self.assertEqual(load_admin_token({"ADMIN_SYNC_TOKEN_FILE": str(self.tmp / "missing")}), "")
        with patch.dict(os.environ, {"ADMIN_SYNC_TOKEN": self.admin, "ADMIN_SYNC_TOKEN_FILE": "", "SERVER_HOST": "127.0.0.2"}):
            configured = Settings()
            self.assertTrue(configured.ADMIN_SYNC_TOKEN == self.admin)
            self.assertEqual(configured.SERVER_HOST, "127.0.0.2")

    def test_14_rotation_is_private_and_never_prints_the_secret(self):
        from scripts.rotate_admin_token import rotate_token
        target = self.tmp / ".secrets" / "admin-token"
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            rotate_token(target)
            original = target.read_text(encoding="utf-8").strip()
            with self.assertRaises(FileExistsError): rotate_token(target)
            rotate_token(target, force=True)
            rotated = target.read_text(encoding="utf-8").strip()
        self.assertTrue(original != rotated and len(rotated) >= 43)
        self.assertFalse(original in captured.getvalue() or rotated in captured.getvalue())
        if os.name != "nt": self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_15_actual_frontend_build_and_security_routes(self):
        from fastapi.testclient import TestClient
        dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
        self.assertTrue((dist / "index.html").exists(), "Run npm run build before this smoke test")
        with TestClient(self.app_module.create_app(static_dir=dist)) as client:
            index = client.get("/")
            self.assertEqual(index.status_code, 200)
            assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', index.text)
            self.assertTrue(assets)
            for asset in assets:
                self.assertEqual(client.get(asset).status_code, 200)
            for forbidden in ["/%2e%2e/%2e%2e/.env", "/.secrets/admin_sync_token", "/src/config.py", "/assets/index.js.map"]:
                self.assertEqual(client.get(forbidden).status_code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
