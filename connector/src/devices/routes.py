"""HTTP API endpoints for device enrollment, management, and status."""
import time
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from src.api.browser_sessions import get_store
from src.devices.enrollment import get_enrollment_engine
from src.devices import registry as registry_mod
from src.media.device_control import get_control

router = APIRouter(prefix="/api/devices", tags=["devices"])


class EnrollmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_wire_id: str = Field(pattern="^[a-f0-9]{32}$")
    site_id: str = Field(default="default-site", max_length=64)
    name: str | None = Field(default=None, max_length=120)


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str | None = Field(default=None, max_length=16)
    codes_match: bool = False
    device_signature: str | None = Field(default=None, pattern="^[a-f0-9]{128}$")
    name: str | None = Field(default=None, max_length=120)


class UnpairRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(default="operator_unpair", max_length=64)


@router.get("")
def list_devices(request: Request, site_id: str | None = None):
    """Lists registered robots with durable enrollment and live status."""
    get_store().authorize(request)
    registry = registry_mod.get_robot_registry()
    control = get_control()
    robots = registry.list_robots(site_id=site_id)

    # Attach live status from DeviceControl
    ctrl_status = control.status()
    live_devices = {d["device_id"]: d for d in ctrl_status.get("devices", [])}

    result = []
    for r in robots:
        wire_id = r["wire_id"]
        live = live_devices.get(wire_id, {})
        result.append({
            "id": r["id"],
            "wire_id": wire_id,
            "name": r["name"],
            "site_id": r["site_id"],
            "pairing_state": r["pairing_state"],
            "enrollment_epoch": r["enrollment_epoch"],
            "default_speaker": bool(r["default_speaker"]),
            "fingerprint": r.get("fingerprint"),
            "online": live.get("online", False),
            "ip": live.get("ip") or r.get("last_ip"),
            "firmware_version": r.get("firmware_version"),
            "stream_state": live.get("stream", {}).get("state", "IDLE"),
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "revoked_at": r.get("revoked_at")
        })

    return {"status": "success", "robots": result}


@router.get("/discovery")
def list_discovery(request: Request):
    """Lists currently discovered but unenrolled device candidates."""
    get_store().authorize(request)
    control = get_control()
    registry = registry_mod.get_robot_registry()
    ctrl_status = control.status()

    candidates = []
    for p in ctrl_status.get("pending", []):
        wire_id = p["device_id"]
        # Skip if already active in registry
        existing = registry.get_robot_by_wire_id(wire_id)
        if existing and existing["pairing_state"] == "active":
            continue
        candidates.append({
            "wire_id": wire_id,
            "fingerprint": p["fingerprint"],
            "status": "pending_enrollment"
        })

    return {"status": "success", "candidates": candidates}


@router.get("/{robot_id}/status")
def get_device_status(robot_id: str, request: Request):
    get_store().authorize(request)
    registry = registry_mod.get_robot_registry()
    control = get_control()
    robot = registry.get_robot(robot_id)
    if not robot:
        raise HTTPException(404, "Robot not found")

    ctrl_status = control.status()
    live_devices = {d["device_id"]: d for d in ctrl_status.get("devices", [])}
    live = live_devices.get(robot["wire_id"], {})

    return {
        "status": "success",
        "robot": robot,
        "live": {
            "online": live.get("online", False),
            "ip": live.get("ip") or robot.get("last_ip"),
            "stream": live.get("stream", {}),
            "file_active": live.get("file_active", False),
            "ack": live.get("ack")
        }
    }


@router.post("/enrollments")
def create_enrollment(body: EnrollmentRequest, request: Request):
    """Initiates enrollment challenge for a candidate device."""
    principal = get_store().authorize(request, mutating=True)
    control = get_control()
    engine = get_enrollment_engine()

    # Look up pending candidate in control
    with control.lock:
        pending_item = control.pending.get(body.candidate_wire_id)
        if not pending_item or (time.monotonic() - pending_item.get("seen", 0)) > 30:
            raise HTTPException(404, "Candidate device not found or discovery expired. Ensure device is powered on.")
        fingerprint = pending_item["fingerprint"]
        public_key = pending_item.get("public_key", "")

    try:
        challenge = engine.create_challenge(
            site_id=body.site_id,
            principal_id=principal,
            candidate_wire_id=body.candidate_wire_id,
            candidate_fingerprint=fingerprint,
            candidate_public_key=public_key,
            name=body.name
        )
        return {"status": "challenge_created", "challenge": challenge}
    except Exception as e:
        raise HTTPException(409, str(e)) from None


@router.post("/enrollments/{challenge_id}/confirm")
def confirm_enrollment(challenge_id: str, body: ConfirmRequest, request: Request):
    """Confirms the browser challenge with a locally armed robot signature."""
    principal = get_store().authorize(request, mutating=True)
    engine = get_enrollment_engine()

    try:
        enrolled = engine.confirm_challenge(
            challenge_id=challenge_id,
            principal_id=principal,
            submitted_code=body.code,
            codes_match=body.codes_match,
            robot_name=body.name,
            device_signature=body.device_signature
        )
        # Also mark approved in DeviceControl config for backward compatibility
        control = get_control()
        with control.lock:
            control.config["approved"][enrolled["wire_id"]] = enrolled["fingerprint"]
            if not control.config.get("default_device"):
                control.config["default_device"] = enrolled["wire_id"]
            control.save()

        return {"status": "enrolled", "robot": enrolled}
    except ValueError as e:
        raise HTTPException(409, str(e)) from None


@router.post("/{robot_id}/unpair")
def unpair_device(robot_id: str, body: UnpairRequest, request: Request):
    """Revokes device ownership server-side."""
    principal = get_store().authorize(request, mutating=True)
    registry = registry_mod.get_robot_registry()
    control = get_control()

    robot = registry.get_robot(robot_id)
    if not robot:
        raise HTTPException(404, "Robot not found")

    wire_id = robot["wire_id"]
    registry.revoke_robot(robot_id, reason=body.reason, principal_id=principal)

    # Immediately invalidate active control lease and approved entry
    with control.lock:
        if wire_id in control.config.get("approved", {}):
            del control.config["approved"][wire_id]
        if control.config.get("default_device") == wire_id:
            control.config["default_device"] = None
        for lease in control.leases.values():
            if lease.get("device_id") == wire_id:
                lease["revoked"] = True
        control.save()

    return {"status": "revoked", "robot_id": robot_id, "wire_id": wire_id}


@router.post("/{robot_id}/set-default")
def set_default_speaker(robot_id: str, request: Request):
    get_store().authorize(request, mutating=True)
    registry = registry_mod.get_robot_registry()
    control = get_control()

    robot = registry.get_robot(robot_id)
    if not robot:
        raise HTTPException(404, "Robot not found")

    registry.set_default_speaker(robot_id)
    with control.lock:
        control.config["default_device"] = robot["wire_id"]
        control.save()

    return {"status": "default_updated", "robot_id": robot_id}

