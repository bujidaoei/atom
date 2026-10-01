from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt

from .config import get_settings

_ITERATIONS = 200_000
_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$")
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
    )
    return hmac.compare_digest(digest.hex(), digest_hex)


def issue_session(user_id: str) -> str:
    settings = get_settings()
    if settings.session_mode == 'durable':
        from .console_auth import credentials
        codec = credentials()
        source = codec.repository.create_console_session(user_id=user_id,lifetime_seconds=settings.session_days*86400)
        return codec.sign(user_id=user_id,session_id=source.id)
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=settings.session_days)).timestamp()),
    }
    return jwt.encode(payload, settings.secret, algorithm=_ALGORITHM)


def read_session(token: str) -> str | None:
    if get_settings().session_mode == 'durable':
        from .console_auth import credentials
        source = credentials().authenticate(token)
        return source.user_id if source else None
    try:
        payload = jwt.decode(token, get_settings().secret, algorithms=[_ALGORITHM])
    except jwt.PyJWTError:
        return None
    subject = payload.get("sub")
    return subject if isinstance(subject, str) else None
