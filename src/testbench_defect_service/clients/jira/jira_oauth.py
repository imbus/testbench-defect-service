import asyncio
import json
import os
import sys
import threading
import time
from pathlib import Path
from urllib import error, request

import tomli_w

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

token_store = {
    "access_token": "YOUR_CURRENT_ACCESS_TOKEN",
    "refresh_token": "YOUR_CURRENT_REFRESH_TOKEN",
    "expires_at": time.time() + 3600,
}

_TOKEN_CACHE_PATH = Path("tmp/oauth2_tokens.toml")
_TOKEN_CACHE_SECTION = "oauth2"

refresh_lock = asyncio.Lock()
refresh_lock_sync = threading.Lock()

_CLIENT_ID = os.getenv("JIRA_OAUTH2_CLIENT_ID", "YOUR_CLIENT_ID")
_CLIENT_SECRET = os.getenv("JIRA_OAUTH2_CLIENT_SECRET", "YOUR_CLIENT_SECRET")
_oauth2_settings = {
    "client_id": _CLIENT_ID,
    "client_secret": _CLIENT_SECRET,
}


def _load_token_store_from_disk() -> None:
    """Load persisted OAuth2 tokens from tmp/oauth2_tokens.toml when available."""
    if not _TOKEN_CACHE_PATH.exists():
        return

    try:
        with _TOKEN_CACHE_PATH.open("rb") as cache_file:
            data = tomllib.load(cache_file)
    except (OSError, tomllib.TOMLDecodeError):
        return

    section = data.get(_TOKEN_CACHE_SECTION, data)
    if not isinstance(section, dict):
        return

    access_token = section.get("access_token")
    refresh_token = section.get("refresh_token")
    expires_at = section.get("expires_at")

    if isinstance(access_token, str) and access_token:
        token_store["access_token"] = access_token
    if isinstance(refresh_token, str) and refresh_token:
        token_store["refresh_token"] = refresh_token
    if isinstance(expires_at, int | float):
        token_store["expires_at"] = float(expires_at)


def _persist_token_store_to_disk() -> None:
    """Persist OAuth2 runtime tokens to tmp/oauth2_tokens.toml atomically."""
    access_token = str(token_store.get("access_token", ""))
    refresh_token = str(token_store.get("refresh_token", ""))
    expires_at = float(str(token_store.get("expires_at", 0)))

    if not access_token or not refresh_token:
        return
    if _is_placeholder(access_token) or _is_placeholder(refresh_token):
        return

    payload = {
        _TOKEN_CACHE_SECTION: {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": int(expires_at),
        }
    }

    _TOKEN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _TOKEN_CACHE_PATH.with_suffix(".tmp")

    try:
        with tmp_path.open("wb") as cache_file:
            tomli_w.dump(payload, cache_file)
        tmp_path.replace(_TOKEN_CACHE_PATH)
    except OSError:
        return


def _is_placeholder(value: str) -> bool:
    return value.startswith("YOUR_")


class JiraAuthExpiredError(Exception):
    """Raised when Jira OAuth refresh fails due to invalid or expired authorization."""


def configure_oauth2_runtime(
    *,
    access_token: str | None = None,
    refresh_token: str | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
    expires_at: int | None = None,
) -> None:
    """Apply OAuth2 runtime values from config/environment to token refresh state."""
    _load_token_store_from_disk()

    if access_token:
        token_store["access_token"] = access_token
    if refresh_token:
        token_store["refresh_token"] = refresh_token
    if expires_at is not None:
        token_store["expires_at"] = float(expires_at)
    if client_id:
        _oauth2_settings["client_id"] = client_id
    if client_secret:
        _oauth2_settings["client_secret"] = client_secret

    _persist_token_store_to_disk()


def _refresh_jira_token_sync() -> dict[str, object]:
    client_id = str(_oauth2_settings.get("client_id", ""))
    client_secret = str(_oauth2_settings.get("client_secret", ""))
    if _is_placeholder(client_id) or _is_placeholder(client_secret):
        raise JiraAuthExpiredError("Missing OAuth2 client credentials for Jira token refresh")

    payload = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": token_store["refresh_token"],
    }
    req = request.Request(
        "https://auth.atlassian.com/oauth/token",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=20) as resp:
            raw_data = resp.read().decode("utf-8")
    except error.HTTPError as exc:
        if exc.code in {400, 401}:
            raise JiraAuthExpiredError from exc
        raise

    data = json.loads(raw_data)
    if not isinstance(data, dict):
        raise RuntimeError("Unexpected token response format from Jira OAuth endpoint")
    return data


def get_valid_jira_token_sync(
    fallback_token: str | None = None, is_first_call: bool = False
) -> str:
    """Returns a valid access token for synchronous callers.

    If refresh credentials are not configured, the provided fallback token is used.
    """
    expires_at = float(str(token_store.get("expires_at", 0)))
    access_token = str(token_store.get("access_token", ""))

    if fallback_token and (_is_placeholder(access_token) or not access_token):
        access_token = fallback_token

    if time.time() < (expires_at - 300) and access_token and not is_first_call:
        return access_token

    with refresh_lock_sync:
        _load_token_store_from_disk()

        expires_at = float(str(token_store.get("expires_at", 0)))
        access_token = str(token_store.get("access_token", ""))

        if fallback_token and (_is_placeholder(access_token) or not access_token):
            access_token = fallback_token

        # Check one more time in case the disk load yielded a fresh, valid token
        if time.time() < (expires_at - 300) and access_token and not is_first_call:
            return access_token

        refresh_token = str(token_store.get("refresh_token", ""))
        if _is_placeholder(refresh_token) or not refresh_token:
            if fallback_token:
                return fallback_token
            raise JiraAuthExpiredError("Jira OAuth2 refresh token is not configured")

        data = _refresh_jira_token_sync()

        token_store["access_token"] = str(data["access_token"])
        token_store["refresh_token"] = str(data["refresh_token"])
        token_store["expires_at"] = time.time() + int(str(data.get("expires_in", 0)))
        _persist_token_store_to_disk()

        return str(token_store.get("access_token", ""))
