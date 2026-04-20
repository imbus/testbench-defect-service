import base64
import hashlib
import hmac
import os
from functools import wraps
from pathlib import Path
from typing import Final

from sanic import ServerError, Unauthorized
from sanic.request import Request

from testbench_defect_service.utils.config import update_config_files

PBKDF2_ALG: Final[str] = "sha256"
PBKDF2_ITERATIONS: Final[int] = 100_000
DEFAULT_PEPPER: Final[bytes] = b"\xfb\x0e\xbb\x1cg\x15'\x8f6\x15\xcc\x14\x81\xd8\xfe\x93"


def _payload(username: str, password: str) -> str:
    """Create a payload for hashing from username and password."""
    return username + password


def _create_cache_key(username: str, password: str) -> str:
    """Generate a cache key for a given username and password."""
    payload = _payload(username, password)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _get_pepper() -> bytes:
    """Get the pepper value from environment variable or use default."""
    env_pepper = os.getenv("PASSWORD_PEPPER")
    if env_pepper:
        try:
            return base64.b64decode(env_pepper)
        except Exception as e:
            raise ServerError("Invalid server configuration.") from e
    return DEFAULT_PEPPER


def hash_password(password: str, salt: bytes) -> str:
    """Hashes a password with a given salt using PBKDF2-HMAC with SHA256."""
    pepper = _get_pepper()
    return hashlib.pbkdf2_hmac(
        PBKDF2_ALG,
        password.encode("utf-8") + pepper,
        salt,
        PBKDF2_ITERATIONS,
    ).hex()


def create_credentials(username: str, password: str) -> tuple[str, str]:
    """Create a password hash and salt for given username and password."""
    salt = os.urandom(16)
    payload = _payload(username, password)
    password_hash = hash_password(payload, salt)
    salt_encoded = base64.b64encode(salt).decode()
    return password_hash, salt_encoded


def save_credentials(password_hash: str, salt: str, config_path: Path):
    """Save credentials to a config file."""
    update_config_files(config_path, updates={"password_hash": password_hash, "salt": salt})


def check_credentials(request: Request, username: str, password: str) -> bool:
    """Check if a username/password combination is valid and stores that if so."""
    app = request.app

    cache_key = _create_cache_key(username, password)
    cached_key = getattr(app.ctx, "valid_auth_cache_key", None)
    if cached_key and hmac.compare_digest(cached_key, cache_key):
        return True

    stored_hash = getattr(app.config, "PASSWORD_HASH", None)
    stored_salt = getattr(app.config, "SALT", None)
    if not stored_hash or not stored_salt:
        raise ServerError("Invalid server configuration.")

    try:
        salt_bytes = base64.b64decode(stored_salt)
    except Exception as e:
        raise ServerError("Invalid server configuration.") from e

    payload = _payload(username, password)
    candidate_hash = hash_password(payload, salt_bytes)

    is_valid = hmac.compare_digest(candidate_hash, stored_hash)
    if is_valid:
        app.ctx.valid_auth_cache_key = cache_key

    return is_valid


def check_auth_for_request(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Basic "):
        raise Unauthorized("Missing or invalid Authorization header")

    try:
        auth_decoded = base64.b64decode(auth_header.split(" ")[1]).decode("utf-8")
        username, password = auth_decoded.split(":", 1)
    except Exception as e:
        raise Unauthorized("Invalid Authorization header format") from e

    is_valid = check_credentials(request, username, password)
    if not is_valid:
        raise Unauthorized("Invalid credentials")


def protected(wrapped):
    def decorator(f):
        @wraps(f)
        async def decorated_function(request: Request, *args, **kwargs):
            check_auth_for_request(request)
            return await f(request, *args, **kwargs)

        return decorated_function

    return decorator(wrapped)
