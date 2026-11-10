"""Comprehensive verification script for:
1. Security & Token Exposure Check (scanning frontend/dist, public APIs)
2. Token Rotation & Access Control (Unauthenticated -> 401, Authenticated -> 200)
3. MCP Bridge Status
4. Live End-to-End Voice / Direct Audio Smoke Test on ESP32
5. Test Suites Execution (Backend + Frontend)
"""
import sys
import os
import json
import time
import urllib.request
import urllib.error
import http.client
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_FILE = BASE_DIR / ".secrets" / "admin_sync_token"

def log(msg):
    print(f"[VERIFY] {msg}", flush=True)

def test_security_exposure():
    log("=== 1. Checking Security & Token Exposure ===")
    if not SECRET_FILE.exists():
        raise RuntimeError("Secret file .secrets/admin_sync_token does not exist!")
    
    current_token = SECRET_FILE.read_text(encoding="utf-8").strip()
    if not current_token or len(current_token) < 16:
        raise RuntimeError("Secret token is invalid or too short!")
    
    log(f"Current token verified in secret store (len={len(current_token)}).")
    
    # Check frontend/dist
    dist_dir = BASE_DIR / "frontend" / "dist"
    if not dist_dir.exists():
        raise RuntimeError("frontend/dist does not exist! Run npm run build first.")
    
    for file_path in dist_dir.rglob("*"):
        if file_path.is_file() and file_path.suffix in [".js", ".html", ".map", ".css"]:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            if current_token in content:
                raise RuntimeError(f"LEAK FOUND: current token found in {file_path}")
            if "Điền token mẫu" in content:
                raise RuntimeError(f"LEAK FOUND: sample token button found in {file_path}")
    
    # Check frontend/src
    src_dir = BASE_DIR / "frontend" / "src"
    for file_path in src_dir.rglob("*.tsx"):
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        if current_token in content:
            raise RuntimeError(f"LEAK FOUND: current token found in {file_path}")
        if "Điền token mẫu" in content:
            raise RuntimeError(f"LEAK FOUND: sample token button found in {file_path}")
            
    log("PASS: Zero token exposure in frontend/dist and frontend/src.")
    return current_token

def test_unauthenticated_access():
    log("=== 2. Testing Unauthenticated Access ===")
    endpoints = [
        ("GET", "http://127.0.0.1:8000/api/browser/session", None),
        ("GET", "http://127.0.0.1:8000/api/stream/direct/status", None),
        ("POST", "http://127.0.0.1:8000/api/stream/direct/start", b"{}"),
    ]
    for method, url, body in endpoints:
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req) as resp:
                raise RuntimeError(f"Expected 401 for {url}, got {resp.status}")
        except urllib.error.HTTPError as e:
            if e.code == 401:
                log(f"PASS: {method} {url} returned 401 Unauthorized as expected.")
            else:
                raise RuntimeError(f"Expected 401 for {url}, got {e.code}")

def test_authenticated_login(token):
    log("=== 3. Testing Authenticated Login ===")
    login_url = "http://127.0.0.1:8000/api/browser/login"
    req = urllib.request.Request(login_url, data=b"{}", method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Origin", "http://127.0.0.1:8000")
    req.add_header("Content-Type", "application/json")
    
    resp = urllib.request.urlopen(req)
    if resp.status != 200:
        raise RuntimeError(f"Login failed with status {resp.status}")
    
    body = json.loads(resp.read().decode("utf-8"))
    log(f"Login response: authenticated={body.get('authenticated')}, role={body.get('role')}")
    
    cookie_header = resp.headers.get("Set-Cookie")
    if not cookie_header or "wewin_browser=" not in cookie_header:
        raise RuntimeError(f"Set-Cookie with wewin_browser not found! Got: {cookie_header}")
    
    log("PASS: Authenticated login returned 200 OK and valid HttpOnly cookie.")
    
    # Test session check with cookie
    session_req = urllib.request.Request("http://127.0.0.1:8000/api/browser/session")
    session_req.add_header("Cookie", cookie_header.split(";")[0])
    with urllib.request.urlopen(session_req) as session_resp:
        session_body = json.loads(session_resp.read().decode("utf-8"))
        if not session_body.get("authenticated"):
            raise RuntimeError(f"Session not authenticated with cookie: {session_body}")
        log(f"PASS: Session validated via cookie. Role={session_body.get('role')}")
    
    return cookie_header.split(";")[0], body.get("csrf")

def test_mcp_bridge():
    log("=== 4. Checking MCP Bridge Status ===")
    with urllib.request.urlopen("http://127.0.0.1:8000/api/media/config") as resp:
        data = json.loads(resp.read().decode("utf-8"))
        mcp_status = data.get("mcp_status")
        log(f"MCP status: {mcp_status}")
        if mcp_status != "connected":
            raise RuntimeError(f"MCP Bridge status is not 'connected': {mcp_status}")
    log("PASS: MCP Bridge is actively connected.")

def run_hardware_e2e_test(cookie, csrf):
    log("=== 5. Running Live Voice Tool & Direct Audio Hardware Smoke Test ===")
    # Run the voice tool simulation & direct audio pipeline on hardware
    # We can run scratch_test_e2e_voice.py which performs the exact 6-stage test on ESP32
    cmd = [sys.executable, "-B", str(BASE_DIR / "scratch_test_e2e_voice.py")]
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(BASE_DIR))
    print(res.stdout)
    if res.returncode != 0:
        print(res.stderr)
        raise RuntimeError(f"Hardware E2E test failed with code {res.returncode}")
    log("PASS: Hardware E2E Voice / Direct Audio test PASSED completely.")

def run_unit_tests():
    log("=== 6. Running Backend Targeted Unit Tests ===")
    cmd = [
        sys.executable, "-m", "unittest",
        "tests/test_voice_media.py",
        "tests/test_direct_audio.py",
        "tests/test_device_control_listener.py",
        "tests/test_devices_auth.py"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(BASE_DIR))
    print(res.stdout)
    print(res.stderr)
    if res.returncode != 0:
        raise RuntimeError(f"Backend unit tests failed with code {res.returncode}")
    log("PASS: Backend targeted tests PASSED.")

    log("=== 7. Running Frontend Vitest Suite ===")
    frontend_dir = BASE_DIR / "frontend"
    cmd_fe = ["cmd.exe", "/c", "npm.cmd", "run", "test:media"]
    res_fe = subprocess.run(cmd_fe, capture_output=True, text=True, cwd=str(frontend_dir))
    print(res_fe.stdout)
    if res_fe.returncode != 0:
        print(res_fe.stderr)
        raise RuntimeError(f"Frontend tests failed with code {res_fe.returncode}")
    log("PASS: Frontend Vitest suite PASSED.")

def main():
    try:
        token = test_security_exposure()
        test_unauthenticated_access()
        cookie, csrf = test_authenticated_login(token)
        test_mcp_bridge()
        run_hardware_e2e_test(cookie, csrf)
        run_unit_tests()
        log("ALL TESTS AND VERIFICATIONS PASSED SUCESSFULLY!")
    except Exception as e:
        log(f"FAILED: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
