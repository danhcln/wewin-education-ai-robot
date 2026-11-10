"""Short-lived, signed audio descriptors. No server starts and no network on import.

Separate from browser/YouTube authority; contains no Cloud/admin credentials.
The development issuer only signs the one reviewed Ogg file on its active server.
"""
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
ASSET_ID = "wewin-test-1"
ROUTE = "/wewin-audio/test.ogg"
MAX_URL = 512
MAX_TTL = 300


def lan_ipv4(value):
    address = ipaddress.IPv4Address(value)
    ranges = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    if not any(address in ipaddress.IPv4Network(net) for net in ranges) or address.packed[-1] in (0, 255):
        raise ValueError("Explicit unicast RFC1918 IPv4 required")
    return str(address)


_cached_lan = None
_cached_lan_time = 0.0

def windows_lan_addresses():
    """Read default-gateway interfaces; refuse to guess between multiple LANs."""
    if os.name != "nt":
        raise ValueError("Specify --bind explicitly on non-Windows hosts")
    global _cached_lan, _cached_lan_time
    now = time.monotonic()
    if _cached_lan is not None and now - _cached_lan_time < 60.0:
        return list(_cached_lan)
    script = ("@(Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.IPv4Address } | "
              "ForEach-Object { $_.IPv4Address.IPAddress }) | ConvertTo-Json -Compress")
    try:
        result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                                capture_output=True, text=True, timeout=15, check=True)
    except (subprocess.SubprocessError, OSError):
        raise ValueError('LAN interface discovery unavailable') from None
    values = json.loads(result.stdout) if result.stdout.strip() else []
    if isinstance(values, str):
        values = [values]
    addresses = set()
    for value in values:
        try:
            addresses.add(lan_ipv4(value))
        except ValueError:
            continue
    _cached_lan = sorted(addresses)
    _cached_lan_time = now
    return sorted(addresses)


def select_lan_address(explicit=None):
    addresses = windows_lan_addresses()
    if explicit:
        chosen = lan_ipv4(explicit)
        if chosen not in addresses:
            raise ValueError("Requested LAN IP is not on an active default-gateway interface")
        return chosen
    if len(addresses) != 1:
        raise ValueError("Select an active --bind address explicitly; LAN is absent or ambiguous")
    return addresses[0]


def validate_audio_url(url, mode):
    if not isinstance(url, str) or not 1 <= len(url) <= MAX_URL or not url.isascii():
        raise ValueError("Invalid audio URL")
    if any(ord(c) <= 32 or ord(c) == 127 for c in url) or any(c in url for c in "\\%@?#"):
        raise ValueError("URL must not contain escapes, credentials, query or fragment")
    parsed = urlsplit(url)
    if parsed.path != ROUTE or parsed.username or parsed.password:
        raise ValueError("Only the audio asset route is allowed")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if mode == "lan":
        if parsed.scheme != "http" or not 1024 <= port <= 65535:
            raise ValueError("LAN development requires HTTP and an unprivileged explicit port")
        lan_ipv4(parsed.hostname)
        if parsed.netloc != f"{parsed.hostname}:{port}":
            raise ValueError("LAN origin must be canonical")
    elif mode == "https":
        host = parsed.hostname or ""
        if parsed.scheme != "https" or port != 443 or ":" in parsed.netloc or parsed.netloc != host:
            raise ValueError("Production uses HTTPS default port 443")
        if host != host.lower() or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", host):
            raise ValueError("Invalid HTTPS hostname")
        if "." not in host or any(not label or len(label)>63 or label.startswith('-') or label.endswith('-') for label in host.split('.')):
            raise ValueError("Fully qualified hostname required")
        if host.endswith((".local", ".localhost", ".internal", ".lan", ".home", ".test", ".invalid")):
            raise ValueError("Internal HTTPS hostname forbidden")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError("Production requires a trusted DNS hostname")
    else:
        raise ValueError("Unknown source mode")
    return url


def canonical_descriptor(asset_id, audio_url, mode, sha256, expires_at):
    validate_audio_url(audio_url, mode)
    if asset_id != ASSET_ID or not re.fullmatch(r"[a-f0-9]{64}", sha256):
        raise ValueError("Invalid audio asset/digest")
    if type(expires_at) is not int or not 0 < expires_at <= 2147483647:
        raise ValueError("Invalid expiration")
    return f"wewin-audio-v1\n{asset_id}\n{audio_url}\n{mode}\n{sha256}\n{expires_at}".encode("ascii")


def sign_descriptor(key_file, *, asset_id, audio_url, mode, sha256, expires_at):
    # Lazy import: old connector tools remain usable even if the new dependency is absent.
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, utils
    payload = canonical_descriptor(asset_id, audio_url, mode, sha256, expires_at)
    key = serialization.load_pem_private_key(Path(key_file).read_bytes(), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ValueError("Audio authority key must be dedicated P-256")
    der = key.sign(payload, ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(der)
    return {"asset_id": asset_id, "audio_url": audio_url, "mode": mode, "sha256": sha256,
            "expires_at": expires_at, "signature": (r.to_bytes(32, "big") + s.to_bytes(32, "big")).hex()}


def prepare_audio_descriptor(asset_id, config_file=None, key_file=None, now=None):
    """Read private active-server manifest; never sign caller-supplied URLs or content."""
    if asset_id != ASSET_ID:
        return {"status": "invalid_asset"}
    config_file = Path(config_file or os.environ.get("WEWIN_AUDIO_ENDPOINT_FILE", str(ROOT / ".maintenance/audio-endpoint.json")))
    key_file = Path(key_file or os.environ.get("WEWIN_AUDIO_SIGNING_KEY_FILE", str(ROOT / ".secrets/audio-signing/private.pem")))
    now = int(time.time()) if now is None else now
    try:
        if config_file.stat().st_size > 4096:
            raise ValueError("Manifest too large")
        config = json.loads(config_file.read_text(encoding="utf-8"))
        if config.get('active_until', 0) <= now or not config.get('active'):
            return {"status": "audio_server_not_ready"}
        from src.sync.locking import is_pid_active
        if not is_pid_active(config.get('pid')):
            return {"status": "audio_server_not_ready"}
        mode = config['mode']
        url = validate_audio_url(config['base_url'] + ROUTE, mode)
        if mode == 'lan' and urlsplit(url).hostname not in windows_lan_addresses():
            return {"status": "audio_server_network_changed"}
        expires = min(now + MAX_TTL, int(config['active_until']))
        descriptor = sign_descriptor(key_file, asset_id=asset_id, audio_url=url, mode=mode,
                                     sha256=config['sha256'], expires_at=expires)
        return {"status": "prepared", "descriptor": descriptor,
                "instruction": "Pass descriptor fields unchanged to self.wewin_audio.play with a fresh request_id. Prepared is not playback confirmation."}
    except (OSError, ValueError, KeyError, TypeError, ImportError):
        return {"status": "audio_server_not_ready"}


AUDIO_TOOL_DEFINITION = {
    "name": "wewin_prepare_audio",
    "description": "Prepare a signed, short-lived URL for the approved original WeWIN audio. Call before self.wewin_audio.play. Does not start a server, play audio, or accept arbitrary URLs. Never use for YouTube.",
    "inputSchema": {"type": "object", "properties": {"asset_id": {"type": "string", "enum": [ASSET_ID]}},
                    "required": ["asset_id"], "additionalProperties": False},
}
