"""Admin setup/status/action only. No descriptors leave the backend through these routes."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from src.api.browser_sessions import get_store
from .device_control import get_control
from .orchestration import get_session

router = APIRouter(prefix='/api/media/voice')


class Configuration(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool
    capture_name: str = Field(max_length=200)
    system_mix_consent: bool = False
    local_route_confirmed: bool = False


class Approval(BaseModel):
    model_config = ConfigDict(extra='forbid')
    device_id: str = Field(pattern='^[a-f0-9]{32}$')
    fingerprint: str = Field(pattern='^[a-f0-9]{64}$')


class Action(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: str = Field(max_length=16)
    request_id: str = Field(pattern='^[A-Za-z0-9_-]{8,64}$')
    query: str | None = Field(default=None, max_length=160)
    utterance: str | None = Field(default=None, max_length=200)
    video_id: str | None = Field(default=None, pattern='^[A-Za-z0-9_-]{11}$')
    value: int | None = Field(default=None, ge=0, le=100)
    delta: int | None = Field(default=None, ge=-100, le=100)
    endpoint: int | None = Field(default=None, ge=-1, le=10000)


@router.get('/status')
def status(request: Request):
    get_store().authorize(request)
    return {'configuration': get_control().status(), 'media': get_session().status()}


@router.post('/configure')
def configure(body: Configuration, request: Request):
    get_store().authorize(request, True)
    session = get_session()
    if body.enabled and session.status()['state'] not in ('IDLE', 'ENDED', 'ERROR'):
        raise HTTPException(409, 'Dừng MediaSession trước khi đổi cấu hình capture.')
    if not body.enabled:
        session.submit({'action': 'stop', 'request_id': __import__('uuid').uuid4().hex})
    try:
        return get_control().configure(**body.model_dump())
    except (ValueError, OSError):
        raise HTTPException(409, 'Chưa bật control LAN: kiểm tra endpoint, consent, địa chỉ hoặc port.') from None


@router.post('/approve')
def approve(body: Approval, request: Request):
    get_store().authorize(request, True)
    if get_session().status()['state'] not in ('IDLE', 'ENDED', 'ERROR'):
        raise HTTPException(409, 'Dừng MediaSession trước khi đổi ghép nối thiết bị.')
    raise HTTPException(409, 'Physical enrollment required: use /api/devices/enrollments and signed native proof.')


@router.post('/action')
def action(body: Action, request: Request):
    get_store().authorize(request, True)
    control = get_control()
    if control.socket is None and not control.config.get('enabled'):
        try:
            control.start()
        except Exception:
            pass
    if not (control.config.get('enabled') or control.socket is not None):
        raise HTTPException(409, 'Wi-Fi Speaker orchestration chưa được cấu hình.')
    return get_session().submit(body.model_dump(exclude_none=True))
