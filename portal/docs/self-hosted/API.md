# WeWIN AI private service API

Independent bearer-key management authentication on /v1 routes. Device credential + Device-Id/Client-Id for discovery and WebSocket; no credentials in URL. All paths are implemented by WeWIN, not guessed XiaoZhi Cloud APIs.

| Method | Path | Operation |
| --- | --- | --- |
| GET | `/health` | Health |
| GET | `/v1/runtime` | Admin-only effective staging paths/provider options and startup build proof, never secret values |
| GET | `/v1/agents` | Agents |
| GET | `/v1/devices` | Devices |
| POST | `/v1/devices` | Register |
| POST | `/v1/devices/{device_id}/revoke` | Revoke |
| GET | `/v1/catalog` | Catalog |
| GET | `/v1/agents/{agent_id}` | Get Agent |
| PUT | `/v1/agents/{agent_id}` | Apply |
| GET | `/v1/agents/{agent_id}/history` | History |
| GET | `/v1/agents/{agent_id}/evidence` | Evidence |
| POST | `/xiaozhi/ota/` | Discovery |

WebSocket `/xiaozhi/v1/`: protocol v1, Opus mono input16k/output24k, 60ms. Physical enrollment is disabled in this delivery. Discovery never supplies firmware/assets URLs.

Agent PUT requires expected_revision, operation_id and typed config. Retry with the same operation ID cannot silently create another revision; changed content/expected revision conflicts. GET readback returns loaded runtime, hash/revision/config. Voice/model/language are validated against actual available providers.

Health `build` captures commit/source fingerprint/dirty state/PID/dependency version
at startup. It is not a live reread of Git HEAD. Agent readback also includes
`effective_prompt_hash`, separate from the saved profile hash, so policy code
updates are observable without claiming the stored configuration changed.

Evidence lists revision/hash, frame/timing/kind metadata; it never labels simulator turns physical. Device list omits token hashes; registration returns a new token once; confirmed revoke blocks reconnect and closes an active socket.

## Independent device management (2026-11-09)

The existing Portal now reserves first-party inventory via authenticated admin
`POST /api/portal/managed-robots`. This does not contact a device. Apply a Role or
AI Configuration through the existing candidate/confirmation/readback flow first.
Then `/robots/{id}/device-gateway` exposes diagnostics; its POST actions are
`provision`, `binding`, `rotate`, `revoke`. Mutations require CSRF, admin, explicit
confirmation and (binding/rotate) expected_binding_version. Physical provision,
rotate and binding remain blocked in this Portal release. A global Portal admin
is trusted to administer its single `wewin-local` tenant; this is not multi-tenant
customer isolation or proof of hardware ownership.

AI control API uses its private management bearer plus server-supplied
`X-WeWIN-Owner` / `X-WeWIN-Tenant`. These are trusted BFF delegation headers,
not authentication supplied directly by end-user browsers. Owned Agent writes
and device management require matching scope. Legacy unowned Agents cannot be
implicitly claimed. Scoped GET /v1/agents only lists that owner/tenant.

| Method | Path | Behavior |
|---|---|---|
| POST | `/v1/device-provisions` | Confirmed ownership attestation, unique Device-ID/Client-ID, owned Agent, one-time bootstrap capability |
| GET | `/v1/devices/{id}/diagnostics` | Masked scope, declared version/capabilities, live authenticated HELLO socket, recent sessions/audit |
| POST | `/v1/devices/{id}/binding` | CAS, matching owner/tenant Agent, rotates WS bearer, closes session |
| POST | `/v1/devices/{id}/credentials/rotate` | CAS, new bootstrap capability and WS bearer; old credentials invalid |
| POST | `/v1/devices/{id}/revoke` | Explicit confirmation; blocks bootstrap/reconnect and closes socket |
| POST | `/xiaozhi/ota/bootstrap/{secret}` | WeWIN native device bootstrap; optional trailing slash, no redirect |

Bootstrap accepts bound Device-Id and Client-Id, Activation-Version 1/2 as metadata,
bounded JSON application.version/capabilities. It does **not** implement vendor
activation/eFuse/HMAC. Response contains server_time and WSv1 URL/token only;
**no firmware, activation or download URL**. The capability URL is itself a secret:
SHA256 stored, redacted in ASGI scope, no access logs; upstream proxy/error logs
must suppress that URI too. Use no-store/no-referrer, out-of-band delivery and TLS.
This is revocable shared-secret possession, not hardware attestation. TanDev's
ability to provision this URL is not yet proven. IDs alone never grant access.

WS bearer is domain-separated HMAC-SHA256 using WeWIN's private issuer key and
random per-device nonce plus Device/Client/Agent/owner/tenant. Store only bearer
hash. Repeated bootstrap is idempotent; rebind/rotate invalidates prior WS bearer.
Portal simulator credentials expire after 24h (including rotation). Revoked IDs
cannot be silently reactivated. Back up the issuer independently; if lost after
enrollment, bootstrap fails closed. `WEWIN_AI_DEVICE_ISSUER_KEY_FILE` supports an
explicit secret-file mount; default is beside the management key.

Device-only edge 8013 exposes health/bootstrap/WS, never control API/docs. The LAN
launcher binds a verified local RFC1918 IP or loopback, never wildcard/public IP,
and refuses a physical-enabled backend. LAN HTTP is simulator-only. Physical
bootstrap/WS additionally requires approved HTTPS/WSS, physical flag, trusted TLS
edge and backend loopback peer. HTTP cannot spoof the edge TLS marker. Production
TLS termination is a separate, untested deployment gate, not an enabled feature.
