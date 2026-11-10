# Supervised observation and recovery gate

Latest bounded approval packet: [A/B/C read-only scope](MONSTER_DESK_READ_ONLY_APPROVAL.md).
Current evidence: [hardware connection report](../../WEWIN_MONSTER_DESK_HARDWARE_CONNECTION_EVIDENCE.md).
Do not infer permission to open Serial or a robot URL from this runbook.

This is a future operator checklist, **not authorization to connect USB, enter
provisioning, reboot/reset, change an endpoint or write any device storage**.
No physical action was performed in this run. Offline work does not need USB.

## Observation before any cutover

Use the least intrusive TanDev-supported status/log interface available. Confirm
the actual Monster Desk/S3, current firmware build/slot, Device-ID and Client-ID,
selected OTA/voice transport and protocol version. Friendly registry names/wire
hashes are not hardware identity. Record only nonsecret fields, event names,
hostname, protocol/audio parameters and timestamp; not bearer tokens, serial
secrets, Wi-Fi passwords, entire NVS images or bootstrap capability URLs.

The historical factory app is2.5.3; historical COM6 and v4 MQTT logs do not identify
the currently running robot. Do not open an assumed COM port. Supported Advanced
UI availability and its show_ota_config flag must be observed without submitting
a form. Do not use raw config dump endpoints that expose credentials merely to
learn a hostname. Request a masked status page or provider-supported diagnostic.

If USB Serial is necessary, first request approval for that specific observation:

1. User is present; identify the actual port/device and approved log method.
2. Preserve normal operation. USB insertion may power/reset the robot; serial
   opening can toggle DTR/RTS even when an application intends read-only. Confirm
   driver/control-line behavior before connection; do not equate read access with
   zero effect. Baud115200 is historical only and needs confirmation.
3. Disable automation that sends reset/BOOT/esptool/activation commands. Do not
   install or run a flasher. Do not press BOOT/reset or change AP mode by inference.
4. Observe an existing normal boot/conversation only if approved; retain a masked
   minimal event transcript. Do not persist raw logs that might contain credentials.
5. Record a stop decision if the observation requires an unapproved reset or write.

## Recovery evidence required

Before changing any OTA URL, prove (on the supported firmware/method, without
deliberately corrupting its configuration) how the user can regain Advanced or
another supported network setup interface when WeWIN is unreachable. Obtain
provider documentation or a previously validated procedure for the exact build,
then decide whether a supervised demonstration is needed and separately approved.
Do not call an available HTML route proof that it is enabled or recoverable.

Record current endpoint/settings through a masked supported mechanism. A full
historical flash backup is not a complete current network/activation backup.
The old Cloud may require its own activation/credentials; changing ota_url alone
does not prove restoration of persisted WS/MQTT configuration. Keep Cloud
credentials separate; never use them to authenticate to WeWIN. No automatic
legacy fallback is an acceptance requirement, not an assumption about factory.

Recovery paths:

| Path | Proof needed | Current status |
|---|---|---|
| Fix/restart WeWIN host while keeping device config | Current endpoint, TLS keypair/DNS, exact source+DB+issuer+revoke ledger; device retry behavior | Host restore dry-run PASS; robot retry unknown |
| Supported Advanced/network UI rollback, without flash | UI reachable in the relevant failure state; exact restore procedure and authorized settings/activation | UNVERIFIED |
| USB serial observation | Driver/power/reset impact and explicit read-log approval | Not performed; optional if other status method suffices |
| USB/ROM/manual flash recovery | Exact hardware/build/storage state, valid backups and a new explicit write approval | Forbidden in this run; not a proven fallback |
| Bootloader auto rollback | Actual bootloader/state evidence | UNVERIFIED; never rely on it |

Backup1/2 and otadata hashes are recorded in the main report. Do not restore them,
erase NVS, change slots or write otadata to test recovery. Upstream code may mark
a pending slot valid after OTA checking and persist returned network settings
even when no firmware URL exists. The user must explicitly review such potential
writes before any future bootstrap; TanDev behavior/current state remain unknown.

Server dry-run restores an isolated latest-revoked QA SQLite snapshot and issuer
using committed security-compatible source on8012; it is **not a physical recovery
or Cloud rollback test**. Old/stale snapshots can revive revoked credentials;
refuse service until the latest ledger is reconciled. After TLS pinning do not
downgrade to code that ignores device_transport_policy.

The first connection checklist and explicit stop-before-endpoint-change are in
WEWIN_MONSTER_DESK_REAL_CONNECTION_GO_NO_GO.md. Without supported recovery evidence,
the physical decision stays NO-GO. Failure never grants permission to flash.
