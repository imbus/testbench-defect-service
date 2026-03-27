import json
import logging
import re
from time import monotonic
from typing import Any

from sanic.request import Request
from sanic.response import BaseHTTPResponse, HTTPResponse

from testbench_defect_service.log import logger
from testbench_defect_service.utils.auth import check_auth_for_request

_SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "x-auth-token",
    "x-access-token",
    "x-refresh-token",
    "x-csrf-token",
    "proxy-authorization",
}

_SENSITIVE_BODY_KEYS = {
    "password",
    "passwd",
    "token",
    "access_token",
    "refresh_token",
    "id_token",
    "auth_token",
    "session_token",
    "secret",
    "client_secret",
    "api_key",
    "apikey",
    "credit_card",
    "card_number",
    "cvv",
    "cvc",
    "ssn",
    "social_security_number",
    "pin",
    "private_key",
}

_SENSITIVE_QUERY_KEYS = {
    "token",
    "access_token",
    "api_key",
    "apikey",
    "secret",
    "password",
    "auth",
    "key",
}

_FORM_MASK_RE = re.compile(
    r"((?:^|&)(?:" + "|".join(re.escape(k) for k in _SENSITIVE_BODY_KEYS) + r")=)[^&]*",
    re.IGNORECASE,
)


def _mask_headers(headers: dict) -> dict:
    return {k: "***" if k.lower() in _SENSITIVE_HEADERS else v for k, v in headers.items()}


def _mask_query_params(args: dict) -> dict:
    return {k: "***" if k.lower() in _SENSITIVE_QUERY_KEYS else v for k, v in args.items()}


def _mask_value(obj: Any) -> Any:
    """Recursively mask sensitive keys in dicts/lists."""
    if isinstance(obj, dict):
        return {
            k: "***" if k.lower() in _SENSITIVE_BODY_KEYS else _mask_value(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_mask_value(i) for i in obj]
    return obj


def _mask_body_text(text: str) -> str:
    """Mask sensitive fields in JSON or form-urlencoded body text."""
    try:
        return json.dumps(_mask_value(json.loads(text)), ensure_ascii=False)
    except (json.JSONDecodeError, ValueError):
        return _FORM_MASK_RE.sub(r"\1***", text)


def _format_body(body: bytes, max_len: int) -> str:
    """Decode, mask sensitive fields, then truncate."""
    if not body:
        return "<No Body>"
    try:
        text = body.decode("utf-8")
    except Exception:
        return f"<Binary data, {len(body)} bytes>"

    masked = _mask_body_text(text)

    if len(masked) > max_len:
        return f"{masked[:max_len]}... (truncated, {len(masked)} chars total)"
    return masked


async def log_request(req: Request):
    req.ctx.start_time = monotonic()

    if not req.app.debug and not logger.isEnabledFor(logging.DEBUG):
        return

    max_len = getattr(req.app.config, "MAX_LOG_BODY", 1024)

    try:
        body_text = _format_body(req.body, max_len)
    except Exception as e:
        body_text = f"<error reading body: {e}>"

    logger.debug(
        "→ Request: %s %s\n   Query: %s\n   Headers: %s\n   Body: %s",
        req.method,
        req.path,
        _mask_query_params(dict(req.args)),
        _mask_headers(dict(req.headers)),
        body_text,
    )


async def log_response(req: Request, resp: HTTPResponse):
    if not req.app.debug and not logger.isEnabledFor(logging.DEBUG):
        return

    start = getattr(req.ctx, "start_time", None)
    elapsed = f"{round((monotonic() - start) * 1000, 3)}ms" if start is not None else "unknown"

    max_len = getattr(req.app.config, "MAX_LOG_BODY", 1024)

    try:
        body_text = _format_body(getattr(resp, "body", b"") or b"", max_len)
    except Exception as e:
        body_text = f"<error reading response body: {e}>"

    logger.debug(
        "← Response: %s in %s\n   Headers: %s\n   Body: %s",
        resp.status,
        elapsed,
        _mask_headers(dict(resp.headers)) if resp.headers else {},
        body_text,
    )


async def check_request_auth(req: Request):
    if (
        req.path in {"/", "/favicon.ico", "/openapi.yaml", "/settings"}
        or req.path.startswith("/docs")
        or req.path.startswith("/static")
    ):
        return None

    response = check_auth_for_request(req)
    if isinstance(response, BaseHTTPResponse):
        return response
    return None
