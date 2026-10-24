"""Security primitives (no framework or database imports, so they are unit-testable in isolation).

* Passwords: scrypt (hashlib, no extra dependency) with a per-user random salt; parameters are stored in the hash string so
  they can be raised later and old hashes are transparently re-hashed on the next successful login.
* Tokens: HS256 JWT (PyJWT) with exp / iat / nbf / iss / aud / jti / token-version claims; every claim is verified on decode.
* CSRF: a token derived from the session's ``jti`` with HMAC-SHA-256. It is only required for browser (cookie) sessions.
* Rate limiting: in-memory sliding window. It is per process: behind several workers or replicas, enforce limits at the proxy too.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Callable

import jwt

ISSUER, AUDIENCE, ALGORITHM = "plsd-backend", "plsd-api", "HS256"
ROLES = ("viewer", "operator", "admin")
ROLE_RANK = {r: i for i, r in enumerate(ROLES)}
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,39}$")
MIN_PASSWORD, MAX_PASSWORD = 12, 128
_COMMON_PASSWORDS = {"password1234", "123456789012", "qwertyuiop12", "administrator", "changeme1234", "letmein123456", "welcome12345"}


class PasswordPolicyError(ValueError):
    pass


def validate_new_password(password: str, username: str = "") -> None:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD:
        raise PasswordPolicyError(f"Password must be at least {MIN_PASSWORD} characters.")
    if len(password) > MAX_PASSWORD:
        raise PasswordPolicyError(f"Password must be at most {MAX_PASSWORD} characters.")
    low = password.lower()
    if username and username.lower() in low:
        raise PasswordPolicyError("Password must not contain the user name.")
    if low in _COMMON_PASSWORDS or len(set(password)) < 5:
        raise PasswordPolicyError("Password is too common or too repetitive.")


# ------------------------------------------------------------------------------------------------------------ passwords
_SCRYPT_R, _SCRYPT_P = 8, 3


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def hash_password(password: str, log_n: int = 15) -> str:
    salt = secrets.token_bytes(16)
    n = 1 << log_n
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=_SCRYPT_R, p=_SCRYPT_P, maxmem=256 * 1024 * 1024, dklen=32)
    return f"scrypt${n}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time verification; any malformed stored hash simply fails."""
    try:
        scheme, n, r, p, salt, expected = stored.split("$")
        if scheme != "scrypt":
            return False
        n, r, p = int(n), int(r), int(p)
        if n > (1 << 20) or r > 32 or p > 16:          # refuse absurd parameters from a corrupted row
            return False
        dk = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt), n=n, r=r, p=p, maxmem=1024 * 1024 * 1024, dklen=len(base64.b64decode(expected)))
        return hmac.compare_digest(dk, base64.b64decode(expected))
    except (ValueError, TypeError, OverflowError, MemoryError):
        return False


def needs_rehash(stored: str, log_n: int) -> bool:
    try:
        _, n, r, p, _, _ = stored.split("$")
        return int(n) < (1 << log_n) or int(r) < _SCRYPT_R or int(p) < _SCRYPT_P
    except ValueError:
        return True


_DUMMY_HASH: dict[int, str] = {}


def burn_password_check(password: str, log_n: int) -> None:
    """Spend the same time as a real verification (used for unknown user names so timing does not reveal them)."""
    h = _DUMMY_HASH.setdefault(log_n, hash_password(secrets.token_urlsafe(12), log_n))
    verify_password(password, h)


# ------------------------------------------------------------------------------------------------------------------ JWT
@dataclass(frozen=True)
class TokenClaims:
    user_id: int
    role: str
    token_version: int
    jti: str
    expires_at: int


def issue_token(secret: str, *, user_id: int, role: str, token_version: int, minutes: int, now: float | None = None) -> tuple[str, TokenClaims]:
    now_i = int(now if now is not None else time.time())
    jti = uuid.uuid4().hex
    payload = {"sub": str(user_id), "role": role, "tv": token_version, "jti": jti, "iss": ISSUER, "aud": AUDIENCE,
               "iat": now_i, "nbf": now_i, "exp": now_i + minutes * 60}
    return jwt.encode(payload, secret, algorithm=ALGORITHM), TokenClaims(user_id, role, token_version, jti, payload["exp"])


class TokenError(Exception):
    pass


def decode_token(secret: str, token: str) -> TokenClaims:
    try:
        p = jwt.decode(token, secret, algorithms=[ALGORITHM], audience=AUDIENCE, issuer=ISSUER, leeway=5,
                       options={"require": ["exp", "iat", "nbf", "sub", "iss", "aud", "jti"]})
        return TokenClaims(int(p["sub"]), str(p.get("role", "")), int(p.get("tv", -1)), str(p["jti"]), int(p["exp"]))
    except (jwt.PyJWTError, ValueError, TypeError) as e:
        raise TokenError(type(e).__name__) from e


def csrf_token(secret: str, jti: str) -> str:
    return hmac.new(secret.encode(), b"csrf:" + jti.encode(), hashlib.sha256).hexdigest()[:40]


def csrf_ok(secret: str, jti: str, presented: str | None) -> bool:
    return bool(presented) and hmac.compare_digest(csrf_token(secret, jti), presented or "")


# --------------------------------------------------------------------------------------------------------- rate limiting
class SlidingWindowLimiter:
    """``hit(key)`` returns (allowed, retry_after_seconds). Thread-safe; stale keys are purged opportunistically."""

    def __init__(self, limit: int, window_seconds: float, clock: Callable[[], float] = time.monotonic):
        self.limit, self.window, self.clock = limit, window_seconds, clock
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()
        self._last_purge = clock()

    def _trim(self, q: deque, now: float) -> None:
        while q and q[0] <= now - self.window:
            q.popleft()

    def hit(self, key: str, cost: int = 1) -> tuple[bool, int]:
        now = self.clock()
        with self._lock:
            if now - self._last_purge > self.window:
                for k in [k for k, q in self._hits.items() if not q or q[-1] <= now - self.window]:
                    del self._hits[k]
                self._last_purge = now
            q = self._hits[key]
            self._trim(q, now)
            if len(q) + cost > self.limit:
                return False, max(1, int(q[0] + self.window - now) + 1) if q else 1
            for _ in range(cost):
                q.append(now)
            return True, 0

    def count(self, key: str) -> int:
        now = self.clock()
        with self._lock:
            q = self._hits.get(key)
            if q is None:
                return 0
            self._trim(q, now)
            return len(q)

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)


def client_ip(peer: str | None, forwarded_for: str | None, trusted_hops: int) -> str:
    """The client address. X-Forwarded-For is honoured only for the configured number of trusted proxy hops, counted from the right
    (the left part of the header is attacker-controlled)."""
    if trusted_hops <= 0 or not forwarded_for:
        return peer or "unknown"
    parts = [p.strip() for p in forwarded_for.split(",") if p.strip()]
    if len(parts) < trusted_hops:
        return peer or "unknown"
    return parts[-trusted_hops]


SENSITIVE_KEYS = re.compile(r"(pass(word)?|secret|token|authorization|cookie|api[-_]?key|csrf)", re.I)


def redact(obj):
    """Return a copy of a (nested) structure with values of sensitive-looking keys masked - used before anything is logged."""
    if isinstance(obj, dict):
        return {k: ("***" if isinstance(k, str) and SENSITIVE_KEYS.search(k) else redact(v)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact(v) for v in obj]
    return obj
