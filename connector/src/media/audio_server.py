"""Single-file, finite-lived LAN audio delivery. Does not start on import.

This is a trusted-LAN PoC: client-IP filtering is not cryptographic authentication.
No directory serving, production imports, Cloud credentials, or SQLite access.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import socket
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROUTE = "/wewin-audio/test.ogg"
MAX_BYTES = 256 * 1024
LAN_NETWORKS = tuple(ipaddress.IPv4Network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def lan_address(value: str) -> str:
    try:
        addr = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError as exc:
        raise ValueError("A literal RFC1918 IPv4 address is required") from exc
    if not any(addr in net for net in LAN_NETWORKS) or int(addr) & 255 in (0, 255):
        raise ValueError("Unicast RFC1918 LAN address required")
    return str(addr)


class AudioServer(HTTPServer):
    request_queue_size = 2
    allow_reuse_address = False

    def __init__(self, bind: str, port: int, allowed_client: str, payload: bytes, *,
                 ttl: int = 900, max_requests: int = 12, min_interval: float = 1.0,
                 _host_test: bool = False, audit=None):
        if not _host_test:
            bind, allowed_client = lan_address(bind), lan_address(allowed_client)
            if not 1024 <= port <= 65535:
                raise ValueError("Port must be 1024..65535")
        elif bind != "127.0.0.1":
            raise ValueError("Host tests may bind loopback only")
        if not 1 <= ttl <= 900 or not 1 <= max_requests <= 12 or min_interval < 0:
            raise ValueError("Invalid finite server limits")
        if not 0 < len(payload) <= MAX_BYTES or not payload.startswith(b"OggS"):
            raise ValueError("Approved bounded Ogg asset required")
        self.payload = payload
        self.allowed_client = allowed_client
        self.deadline = time.monotonic() + ttl
        self.max_requests = max_requests
        self.requests_seen = 0
        self.successes = 0
        self.last_success = float("-inf")
        self.min_interval = min_interval
        self.audit = audit
        self.bytes_sent = 0
        self.audio_gets = 0
        self.last_response = None
        self.stop_reason = None
        self.timeout = 0.25
        super().__init__((bind, port), AudioHandler)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(3.0)
        return connection, address

    def run_until_expired(self):
        try:
            while time.monotonic() < self.deadline and self.requests_seen < self.max_requests:
                self.handle_request()
        finally:
            self.stop_reason = 'request_limit' if self.requests_seen >= self.max_requests else 'ttl_expired' if time.monotonic() >= self.deadline else 'interrupted'
            self.server_close()
            self.emit('server_stopped')

    def emit(self, event, **fields):
        """Only controlled categories/counters; never raw path, headers or credentials."""
        if self.audit is None:
            return
        value = {'event': event, 'pid': os.getpid(), 'time': time.time(),
                 'requests_seen': self.requests_seen, 'audio_gets': self.audio_gets,
                 'bytes_sent': self.bytes_sent, 'stop_reason': self.stop_reason, **fields}
        try:
            self.audit(value)
        except (OSError, ValueError):
            pass  # Diagnostics must not break delivery or relax authorization.


class AudioHandler(BaseHTTPRequestHandler):
    server_version = "WeWINAudioLab"
    sys_version = ""
    protocol_version = "HTTP/1.0"

    def handle_one_request(self):
        self.server.requests_seen += 1
        super().handle_one_request()

    def log_message(self, *_args):
        pass  # Never log arbitrary request paths, headers, or local filesystem paths.

    def do_GET(self):
        self._serve(False)

    def do_HEAD(self):
        self._serve(True)

    def _serve(self, head: bool):
        server = self.server
        now = time.monotonic()
        code = 200
        route = 'audio' if self.path == ROUTE else 'health' if self.path == '/health' else 'other'
        client_match = self.client_address[0] == server.allowed_client
        if self.client_address[0] != server.allowed_client:
            code = 403
        elif now >= server.deadline or server.requests_seen > server.max_requests:
            code = 410
        elif self.path not in (ROUTE, '/health'):
            code = 404
        elif self.headers.get("Host") != f"{server.server_address[0]}:{server.server_address[1]}":
            code = 400
        elif now - server.last_success < server.min_interval:
            code = 429
        payload = server.payload
        if self.path == '/health':
            payload = json.dumps({'status':'ready','asset_id':'wewin-test-1',
                                  'expires_in_seconds':max(0,int(server.deadline-now))}).encode()
        self.send_response(code)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(payload) if code == 200 else 0))
        if code == 200:
            self.send_header("Content-Type", "application/json" if self.path=='/health' else "audio/ogg")
        self.end_headers()
        self.close_connection = True
        if code == 200:
            server.last_success = now
            server.successes += 1
            if not head:
                try:
                    self.wfile.write(payload)
                    if route == 'audio':
                        server.bytes_sent += len(payload)
                        server.audio_gets += 1
                except (BrokenPipeError, ConnectionResetError, socket.timeout):
                    server.last_response = {'route': route, 'method': self.command,
                                            'status': code, 'delivery': 'write_failed',
                                            'client_match': client_match}
                    server.emit('http_response', **server.last_response)
                    return
        server.last_response = {'route': route, 'method': self.command, 'status': code,
                                'delivery': 'socket_write_completed' if code == 200 and not head else 'no_body',
                                'body_bytes': len(payload) if code == 200 and not head else 0,
                                'client_match': client_match}
        server.emit('http_response', **server.last_response)


def main():
    from src.media.audio_endpoint import select_lan_address, ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", help="Explicit active LAN IPv4; otherwise select the sole default-gateway LAN")
    parser.add_argument("--client", help="Approved ESP32 LAN IPv4, required before starting")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--file", type=Path)
    parser.add_argument("--sha256", help="Reviewed asset digest")
    parser.add_argument("--ttl", type=int, default=900)
    parser.add_argument("--plan", action='store_true',help='Resolve current Windows LAN address; do not bind, sign or publish')
    parser.add_argument("--manifest",type=Path,default=ROOT/'.maintenance/audio-endpoint.json')
    args = parser.parse_args()
    if not 1024<=args.port<=65535:
        parser.error('Audio port must be 1024..65535')
    chosen = select_lan_address(args.bind)
    if args.plan:
        print(json.dumps({'mode':'PLAN_ONLY','lan_address':chosen,'port':args.port,
                          'audio_url':f'http://{chosen}:{args.port}{ROUTE}',
                          'health_url':f'http://{chosen}:{args.port}/health','listener_started':False}))
        return
    if not args.client or not args.file or not args.sha256:
        parser.error('--client, --file and --sha256 are required to start')
    lan_address(args.client)
    path = args.file.resolve(strict=True)
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        parser.error("File exceeds asset limit")
    with path.open("rb") as source:
        payload = source.read(MAX_BYTES + 1)
    if hashlib.sha256(payload).hexdigest() != args.sha256:
        parser.error("Reviewed asset checksum mismatch")
    # The offline audio preparation/decoder tests establish format and duration.
    if args.manifest.exists():
        existing=json.loads(args.manifest.read_text(encoding='utf-8'))
        if existing.get('active') and existing.get('active_until',0)>time.time():
            parser.error('Active audio manifest exists; inspect its owner before starting')
    diagnostic_path = args.manifest.with_name(args.manifest.stem + '.diagnostics.json')
    def audit(value):
        print(json.dumps(value), flush=True)
        temporary = diagnostic_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(value), encoding='utf-8')
        os.replace(temporary, diagnostic_path)
    server = AudioServer(chosen, args.port, args.client, payload, ttl=args.ttl, audit=audit)
    manifest={'active':True,'pid':os.getpid(),'mode':'lan',
              'base_url':f'http://{chosen}:{server.server_address[1]}',
              'sha256':hashlib.sha256(payload).hexdigest(),'active_until':int(time.time())+args.ttl}
    args.manifest.parent.mkdir(parents=True,exist_ok=True)
    temporary=args.manifest.with_suffix('.tmp')
    temporary.write_text(json.dumps(manifest),encoding='utf-8');os.replace(temporary,args.manifest)
    print(json.dumps({"state": "serving", "asset_id": "wewin-test-1", "ttl": args.ttl,
                      "url": f"http://{chosen}:{args.port}{ROUTE}"}), flush=True)
    server.emit('server_started')
    try:server.run_until_expired()
    finally:
        manifest['active']=False
        temporary.write_text(json.dumps(manifest),encoding='utf-8');os.replace(temporary,args.manifest)


if __name__ == "__main__":
    main()
