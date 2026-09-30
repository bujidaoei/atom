"""Strict signed capabilities. Registry admission/revocation are separate checks."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
import hashlib
import json
import re
import time

import jwt
from jwt.utils import base64url_decode

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_REVISION = re.compile(r"[0-9a-f]{64}\Z")
_SEGMENT = re.compile(r"[A-Za-z0-9_-]+\Z")
_HEADER = {"alg": "HS256", "typ": "atom-sandbox+jwt"}
_PURPOSE = {"iss": "atom-control", "aud": "atom-sandbox", "sub": "runtime"}
_FIELDS = {"jti", "org", "project", "run", "attempt", "fence", "base_revision", "profile", "iat", "nbf", "exp", *_PURPOSE}


class GrantError(ValueError):
    def __init__(self, code: str = "invalid_grant"):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Grant:
    jti: str
    org: str
    project: str
    run: str
    attempt: str
    fence: int
    base_revision: str
    iat: int
    exp: int
    profile: str = "files-v1"

    def claims(self) -> dict:
        return {**asdict(self), "nbf": self.iat, **_PURPOSE}

    def fingerprint(self) -> str:
        canonical = json.dumps(self.claims(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def require_scope(self, *, org: str, project: str, run: str, attempt: str, fence: int) -> None:
        if type(fence) is not int or (org, project, run, attempt, fence) != (self.org, self.project, self.run, self.attempt, self.fence):
            raise GrantError("grant_scope_mismatch")


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise GrantError()
        result[key] = value
    return result


def _constant(_value):
    raise GrantError()


def _part(segment: str) -> dict:
    parsed = json.loads(base64url_decode(segment).decode("utf-8"), object_pairs_hook=_unique, parse_constant=_constant)
    if not isinstance(parsed, dict):
        raise GrantError()
    return parsed


def _validate(claims: dict, now: float, lifetime: int, purpose: dict) -> Grant:
    if set(claims) != _FIELDS or any(claims[key] != value for key, value in purpose.items()):
        raise GrantError()
    for key in ("jti", "org", "project", "run", "attempt"):
        if not isinstance(claims[key], str) or not _ID.fullmatch(claims[key]):
            raise GrantError()
    for key, maximum in (("fence", 2**63 - 1), ("iat", 2**53 - 1), ("nbf", 2**53 - 1), ("exp", 2**53 - 1)):
        value = claims[key]
        if type(value) is not int or not 0 <= value <= maximum:
            raise GrantError()
    if claims["fence"] == 0 or claims["profile"] != "files-v1":
        raise GrantError()
    if not isinstance(claims["base_revision"], str) or not _REVISION.fullmatch(claims["base_revision"]):
        raise GrantError()
    if not (claims["nbf"] == claims["iat"] <= now < claims["exp"] and 0 < claims["exp"] - claims["iat"] <= lifetime):
        raise GrantError()
    return Grant(**{key: claims[key] for key in Grant.__dataclass_fields__})


class _CapabilityCodec:
    """Dedicated-key codec; never infer an algorithm or clock from a request."""

    __slots__ = ("_key", "_clock", "_max_lifetime")

    def __init__(self, key: bytes, *, max_lifetime: int = 900, clock: Callable[[], float] = time.time):
        if not isinstance(key, bytes) or not 32 <= len(key) <= 128:
            raise ValueError("invalid_grant_key")
        if type(max_lifetime) is not int or not 1 <= max_lifetime <= 7200:
            raise ValueError("invalid_grant_lifetime")
        self._key = key
        self._clock = clock
        self._max_lifetime = max_lifetime

    def issue(self, grant: Grant) -> str:
        claims = grant.claims()
        claims.update(self._purpose)
        _validate(claims, self._clock(), self._max_lifetime, self._purpose)
        return jwt.encode(claims, self._key, algorithm="HS256", headers={"typ": self._header["typ"]})

    def verify(self, token: str) -> Grant:
        try:
            if not isinstance(token, str) or len(token) > 8192:
                raise GrantError()
            segments = token.split(".")
            if len(segments) != 3 or any(not _SEGMENT.fullmatch(part) for part in segments):
                raise GrantError()
            header, claims = _part(segments[0]), _part(segments[1])
            if header != self._header:
                raise GrantError()
            # Time is validated below with strict integer types and one trusted clock.
            # Signature verification remains enabled; algorithm is fixed, not token-derived.
            jwt.decode(token, self._key, algorithms=["HS256"], issuer=self._purpose["iss"],
                       audience=self._purpose["aud"], subject=self._purpose["sub"],
                       options={"verify_exp": False, "verify_iat": False, "verify_nbf": False, "strict_aud": True})
            return _validate(claims, self._clock(), self._max_lifetime, self._purpose)
        except (ValueError, TypeError, RecursionError, jwt.PyJWTError):
            raise GrantError() from None


class GrantCodec(_CapabilityCodec):
    """Sandbox-only capabilities; never authorize API completion with these."""
    __slots__ = ()
    _purpose = _PURPOSE
    _header = _HEADER


class CompletionGrantCodec(_CapabilityCodec):
    """Execution completion capabilities; rejected by the sandbox broker."""
    __slots__ = ()
    _purpose = {"iss": "atom-control", "aud": "atom-execution", "sub": "runtime"}
    _header = {"alg": "HS256", "typ": "atom-execution+jwt"}
