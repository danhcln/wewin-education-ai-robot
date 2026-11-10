# Private-CA TLS staging — 09/11/2026

User approved a separate test CA, not a public domain, trust-store installation or
robot enrollment. HTTPS/WSS is now available at `192.168.2.10:8014`, device-only,
to loopback AI8010. HTTP8013 remains for old simulators; new managed credentials
cannot downgrade to it. No firewall, DNS, Windows/ESP32 CA store or firmware changed.

Generate a NEW test certificate directory only, using already installed Portal
cryptography47.0.0; never overwrite a live leaf/key:

```powershell
.\.venv\Scripts\python.exe scripts/staging_tls.py --host 192.168.2.10 --out artifacts/NEW-RUN/tls-private
```

This creates an RSA3072 CA, RSA2048 server key, SHA256 certificates, exact IP SAN
and `wewin-staging.invalid` DNS SAN. CA validity30days, leaf7days. CA private key
is not persisted. An intentionally expired leaf is a negative-test artifact only.
No ACME/network request, trust installation or global environment mutation occurs.
The `.invalid` hostname is not DNS provisioning; the actual tested origin is IP.

For a planned idle staging restart, set these process environment variables before
the existing owned AI launcher; this is **server configuration**, never robot NVS:

```powershell
$env:WEWIN_AI_DEVICE_ORIGIN='https://192.168.2.10:8014'
$env:WEWIN_AI_TRUST_TLS_EDGE='1'
$env:WEWIN_AI_ALLOW_REAL_DEVICES='0'
```

Back up DB/issuer/source first and check idle/owned PID. Do not stop services by
port alone. Start TLS after backend runtime reports that exact origin:

```powershell
.\Start-WeWIN-Device-TLS.ps1 `
  -Certificate artifacts/real-connection-gate/tls-private/server.pem `
  -PrivateKey artifacts/real-connection-gate/tls-private/server-key.pem `
  -CaFile artifacts/real-connection-gate/tls-private/ca.pem
```

Launcher refuses a public/wildcard/non-local bind, occupied8014, physical-enabled
backend or origin/trust mismatch. It verifies the chain/IP SAN with an explicit
client CA, records PID/start-time and never installs trust. Stop only its record
with `Stop-WeWIN-Device-TLS.ps1`. `device_tls_server.py` enforces TLS>=1.2, secure
ECDHE suites, one worker, no proxy-header trust/access log/TLS key logging. A normal
browser without this CA is expected to reject it. Do not bypass validation using
verify=False, TLS downgrade or certificate-warning clickthrough.

The device edge withholds bootstrap credentials if an HTTPS request would receive
WS or another authority; an HTTP request for WSS-managed bootstrap returns426.
AI rejects plaintext WS admission for managed TLS credentials. TLS pins persist
in device_transport_policy so a later missing/HTTP environment does not remove
that requirement. Changing the pinned origin requires explicit authorized TLS
credential rotation; plaintext rotation is refused. Diagnostics reports the pin.
Existing managed rows are upgraded to TLS pin when starting with HTTPS origin.

Public deployment still requires a WeWIN-owned approved domain and valid chain
trusted by the exact TanDev firmware, DNS/Wi-Fi/clock verification, private control
ingress, credential-URI redaction on every proxy, retention and monitoring. A test
CA working on Python clients does not establish firmware trust. Do not install it
in ESP32 NVS/assets or flash it to make a test pass. Keep physical flags off.

The existing Compose/Caddy blueprint is still NOT an approved physical deployment;
do not assume direct-TLS Windows tests certify Linux, reverse proxy trust or ACME.
Back up the leaf/key/CA certificate alongside DB+issuer, keep the latest revoke
ledger, and use security-compatible source at least82e053d after TLS pinning.

Primary references: [Python SSL contexts](https://docs.python.org/3.12/library/ssl.html#ssl.SSLContext),
[Uvicorn SSL implementation](https://github.com/Kludex/uvicorn/blob/0.42.0/uvicorn/config.py).
Installed Uvicorn0.42.0/Python3.12.13 were also inspected/tested locally.
