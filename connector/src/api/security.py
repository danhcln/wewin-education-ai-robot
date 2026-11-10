"""Shared admin authentication and response redaction. Never log credentials."""
import re
import secrets
from typing import Optional
from urllib.parse import parse_qs, urlsplit

from fastapi import Header, HTTPException, Request, status
from src.config import settings


def is_valid_admin_token(token: str) -> bool:
    expected = settings.ADMIN_SYNC_TOKEN
    if not expected or not token or len(token) > 512:
        return False
    return secrets.compare_digest(token.encode("utf-8"), expected.encode("utf-8"))


def verify_admin_token(
    request: Request = None,
    authorization: Optional[str] = Header(None),
    x_admin_token: Optional[str] = Header(None),
):
    token = ""
    if authorization:
        scheme, separator, value = authorization.partition(" ")
        if separator and scheme.lower() == "bearer":
            token = value.strip()
    elif x_admin_token:
        token = x_admin_token.strip()
    if not authorization and not x_admin_token and request is not None and request.cookies.get('wewin_browser'):
        from .browser_sessions import get_store
        return get_store().authorize(request,request.method not in ('GET','HEAD','OPTIONS'))
    if not is_valid_admin_token(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid or missing admin token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def redact_sensitive_text(value: str) -> str:
    endpoint = settings.XIAOZHI_MCP_ENDPOINT
    secret_values = [endpoint, settings.XIAOZHI_MCP_TOKEN, settings.ADMIN_SYNC_TOKEN]
    try:
        parsed = urlsplit(endpoint)
        secret_values.extend(v for values in parse_qs(parsed.query).values() for v in values)
        secret_values.extend([parsed.username, parsed.password])
    except ValueError:
        pass
    for secret in sorted((s for s in secret_values if s), key=len, reverse=True):
        value = value.replace(secret, "[REDACTED]")
    value = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[REDACTED]", value)
    value = re.sub(r"(?i)((?:token|password|secret|api_key|access_token)=)[^&\s\"']+", r"\1[REDACTED]", value)
    return re.sub(r"\beyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[REDACTED]", value)


def redact_sensitive_data(value):
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, dict):
        return {key: redact_sensitive_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_sensitive_data(item) for item in value]
    return value
