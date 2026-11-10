# Windows native USB Serial/JTAG collector — validation and physical checklist

Latest update, 09/11/2026: the separately approved exact-device runner
`scripts/monster_desk_once.py` completed the single COM6 session: 1 exclusive
CreateFile, 59.968 seconds, 0 bytes, closed, no retry. User reported no visible
reset/interruption and normal operation afterward. See hardware report appendix G.
The durable ledger has been consumed. **Do not run again or delete the ledger.**
The lab guards below remain unchanged; older NO-GO statements describe the
pre-session baseline. No TanDev transport/version was established by the empty read.

09/11/2026, Asia/Bangkok. COM6/Monster Desk remains NO-GO. No device was opened.

Source: `scripts/windows_readonly_collector.py`; tests:
`tests/test_windows_readonly_collector.py`. The CLI exposes only `simulate` and
`windows-check`. There is no CLI real capture mode, port option or force bypass.

## Run the two safe modes

From `E:/WeWIN_Firmware_Lab/wewin_education_portal`, use a new artifact filename;
existing files are refused. These commands never open a serial port:

```powershell
.\.venv-ai\Scripts\python.exe scripts/windows_readonly_collector.py --mode simulate --out artifacts/serial-collector-validation/example-simulation.json
& '..\idf-tools\python_env\idf6.1_py3.12_env\Scripts\python.exe' scripts/windows_readonly_collector.py --mode windows-check --out artifacts/serial-collector-validation/example-closed-check.json
```

The Portal environment has no pySerial dependency. The second command uses the
existing IDF Python with reviewed pySerial 3.5; it does not run IDF monitor or
esptool. No package or driver installation is required for these validations.

`windows-check` constructs `Serial(port=None)` and configures its closed object;
it also enumerates existing SetupAPI/registry metadata. It never measures DTR/RTS
on USB and never calls open. A reviewed backend source hash is required.

## Collector behavior and limits

- DTR/RTS False, hardware/software flow control False, read timeout 100 ms, before
  open. No settings are changed by the collector after open. This mitigates
  application behavior; it does not prove driver line transitions are safe.
- No application transmit call, command/input loop, reset sequence, retry or
  automatic reconnect. `PySerialReader` exposes open/read/close, without write.
  pySerial itself opens a READ+WRITE Windows handle and configures/purges buffers;
  this is application read-only, not an OS access-mode security boundary.
- Read window at most 60 seconds, default 32 KiB, hard ceiling 64 KiB, at most
  256 evidence facts, 2,048 bytes per line, 256 bytes per read and 1,000 read calls.
  A read is not started if its 100 ms timeout budget would exceed the deadline.
  Open time counts toward the window. Driver open/read/close can hang or ignore
  timeouts: total process/cleanup duration is not guaranteed to be <=60 seconds.
- Exactly one open attempt. Errors, interruption and bounds lead to one cleanup
  attempt; no forced reset/kill/reopen. Close errors are recorded explicitly.
- Complete lines only; oversized lines discarded through their newline; binary,
  incomplete lines and arbitrary conversational text are never copied to output.
- Whitelist: numeric app version, protocol event enums, known public host/port,
  bounded hello/audio fields and in-session ID aliases. Unknown hosts, URL paths,
  userinfo/query, full identities and raw exception messages are omitted. A known
  host does not establish the full OTA URL/bootstrap or the direction of a hello.
- Boot/download markers stop collection, including on sensitive lines. A marker
  could be buffered old output: neither its presence nor absence proves whether
  open caused a reset. Every report leaves reset/transport attestation UNVERIFIED.

`collect_lab(port, fingerprint, confirmed_spare_board, limits)` is a library-only
entry point for a **separately authorized spare board**. It checks exact native
ESP VID/PID and serial fingerprint twice before open. COM6 and the recorded
Monster Desk USB fingerprint are denied, including if that identity moves to
another COM number. This attestation is not inferred from a device being present.
Do not call it until the exact board is confirmed and its test is authorized.
Inventory checks are cached snapshots, not an atomic USB-identity condition on
CreateFile. Freeze cabling/device assignments during any approved test; the
checks reduce target mistakes but cannot guarantee against every remapping race.

## Spare board test checklist — not executed

| Stage | Required evidence / stop condition |
|---|---|
| Approval | Identify the exact spare board/COM/serial fingerprint and explicit permission. It must not be Monster Desk. No inference from VID/PID alone. |
| Existing firmware | Use a board already emitting benign uptime/counter output and known application state. No flash, reset, new firmware, wiring or driver changes in this scope. If this evidence is unavailable, log-only testing cannot prove reset absence. |
| Host match | Record Windows build, usbser version, pySerial source hash, USB topology/power policy, and collector hash. Compare them with Monster Desk's host. Differences limit transfer of results. |
| Before open | Observe pre-existing independent uptime/state and cached enumeration. If a USB observer is already available and separately authorized, record actual control transfers without changing USB configuration; otherwise mark transitions unmeasured. |
| Open once | One bounded open, no line sweep or repeated attempts. Observe external state/uptime, boot/download markers, driver errors and enumeration. Stop at any anomaly. |
| Read <=60s | Confirm benign output received, no application transmit calls and bounded sanitized artifacts. Silence is inconclusive. Do not type/send commands or force reconnect. |
| Close once | Observe independent state/uptime and enumeration after close. A final PnP snapshot misses transient loss; continuous observation is required to rule that out. |
| Result | Separate observed no reset at open/close, download mode, enumeration continuity and output reception. “No marker” is insufficient for PASS. Never label mock data as physical evidence. |

No spare board has been identified and authorized in the current inventory.
No physical test is reported. A matching spare-board result reduces uncertainty,
but is not an absolute guarantee for TanDev firmware/Monster Desk.

## Future Monster Desk checklist — blocked; no runnable command

1. Obtain separate approval of the specific one-shot experiment and its residual
   risk, independent of the general USB read-only approval. User present; confirm
   the existing cable/physical identity without disconnect/reconnect.
2. Review spare-board results or provider procedure; record all differences and
   missing proof. Do not silently reuse a lab confirmation for Monster Desk.
3. Prepare and review an exact-device, one-use implementation change if approved:
   the current collector deliberately rejects COM6 and Monster Desk's fingerprint.
   No force flag, blanket removal of the deny list or endpoint/config change.
4. Review the collector/dependency hash and sanitized output destination. Agree on
   a <=60s read window, <=32 KiB default, no raw log, no interactive input and no
   retries. Explain that faulty driver calls/close cannot be given a hard deadline.
5. Capture only naturally occurring activity. Do not reboot, wake/reset through
   Serial, unplug USB, provoke Wi-Fi/Cloud reconnect or change logging level.
6. Stop at boot/download marker, driver error, user interruption, byte/event/read
   bound or deadline. Cleanup once; no extra toggles or automatic recovery.
7. Observe normal robot/Cloud operation and enumeration after close without new
   robot commands. Missing output/markers remains inconclusive. Do not claim
   TanDev transport/bootstrap/identity unless actual sanitized evidence supports it.

For this delivery: **GO software/mock validation; NO-GO COM6/real Monster Desk.**

## Approved exclusive-open revision — completed, not available for replay

The latest user request explicitly authorized replacing the PID-scan precondition
with the sole approved exclusive CreateFile attempt. This does not add a probe or
relax target, no-write, no-retry or duration/data guards. Microsoft specifies
share mode 0 and OPEN_EXISTING for COM; the OS arbitrates access atomically.
Access failure is recorded with its Windows code and consumes the attempt, without
PID attribution, Handle, elevation, driver installation or forced resource release.

The separate runner checks exact COM6/native USB fingerprint and closed settings,
claims its fixed durable ledger before open, audits native CreateFile arguments/
count, blocks WriteFile and reuses collector limits/allowlist. A local stop.request
file allows supervised cancellation without a Serial command. Lab guard paths
still reject Monster Desk. Target cannot be changed by CLI arguments.

10 targeted one-shot tests and 26 collector regression tests passed before this
hardware session. Actual result/provenance is in
`artifacts/monster-desk-once-20261109/result.json`, with a separate user observation.
Presence after close and lack of visible reset do not establish independent reset
telemetry or rule out transient enumeration loss. No further test was performed.
