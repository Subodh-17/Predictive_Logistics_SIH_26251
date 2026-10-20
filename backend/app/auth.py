"""Authentication, role-based authorisation, user management and the audit trail.

Roles (each includes the one before it):
  viewer    read every dashboard, forecast, inventory, route and model view; run the stateless shortage-risk check
  operator  + submit (simulated) inventory events and run/save What-If simulations
  admin     + reset the scenario inventory, recompute forecasts, manage users, read the audit log

Sessions: the browser receives an HttpOnly, SameSite=Strict cookie (Secure in production) and must echo a CSRF token in the
``X-CSRF-Token`` header on every state-changing request. API clients may instead send ``Authorization: Bearer <token>`` (no cookie, so no CSRF).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import config, models as m, security as sec
from .database import SessionLocal, get_db
from .observability import metrics

log = logging.getLogger("logistics.auth")
COOKIE_NAME = "plsd_session"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
Role = Literal["viewer", "operator", "admin"]

_login_failures = sec.SlidingWindowLimiter(config.settings.login_max_failures, config.settings.login_window_seconds)
_login_ip_failures = sec.SlidingWindowLimiter(config.settings.login_max_failures * 4, config.settings.login_window_seconds)


def configure_limiters(max_failures: int, window_seconds: float) -> None:
    """Used by tests to tighten/relax the lockout without touching module state elsewhere."""
    global _login_failures, _login_ip_failures
    _login_failures = sec.SlidingWindowLimiter(max_failures, window_seconds)
    _login_ip_failures = sec.SlidingWindowLimiter(max_failures * 4, window_seconds)


@dataclass(frozen=True)
class Principal:
    id: int
    username: str
    role: str
    jti: str
    via: str                 # "cookie" | "bearer"

    def can(self, role: str) -> bool:
        return sec.ROLE_RANK.get(self.role, -1) >= sec.ROLE_RANK[role]


def get_client_ip(request: Request) -> str:
    peer = request.client.host if request.client else None
    return sec.client_ip(peer, request.headers.get("x-forwarded-for"), config.settings.trusted_proxy_hops)


# ------------------------------------------------------------------------------------------------------------- audit trail
def audit(actor: str | None, action: str, outcome: str, *, target: str | None = None, ip: str | None = None, detail: dict | None = None,
          db: Session | None = None) -> None:
    """Append one audit row. Never raises into the request: a failed audit write is logged loudly and counted."""
    try:
        own = db is None
        s = db or SessionLocal()
        try:
            s.add(m.AuditLogRow(actor=actor, action=action, outcome=outcome, target=target, client_ip=ip, detail=sec.redact(detail or {})))
            s.commit()
        finally:
            if own:
                s.close()
    except Exception as e:  # noqa: BLE001
        metrics.inc("audit_write_failures")
        log.error("audit write failed for %s (%s): %s", action, outcome, type(e).__name__)


# ----------------------------------------------------------------------------------------------------------- dependencies
def _extract_token(request: Request) -> tuple[str | None, str]:
    h = request.headers.get("authorization", "")
    if h.lower().startswith("bearer ") and h[7:].strip():
        return h[7:].strip(), "bearer"
    c = request.cookies.get(COOKIE_NAME)
    return (c, "cookie") if c else (None, "none")


def _resolve(request: Request, db: Session) -> Principal | None:
    token, via = _extract_token(request)
    if not token:
        return None
    try:
        claims = sec.decode_token(config.settings.jwt_secret, token)
    except sec.TokenError:
        return None
    user = db.get(m.UserRow, claims.user_id)
    if user is None or not user.is_active or user.token_version != claims.token_version:
        return None
    if via == "cookie" and request.method not in SAFE_METHODS:
        if not sec.csrf_ok(config.settings.jwt_secret, claims.jti, request.headers.get("x-csrf-token")):
            metrics.inc("csrf_rejections")
            audit(user.username, "csrf_rejected", "denied", target=request.url.path, ip=get_client_ip(request))
            raise HTTPException(403, detail={"code": "CSRF_FAILED", "detail": "Missing or invalid CSRF token. Reload the page and try again."})
    return Principal(user.id, user.username, user.role, claims.jti, via)


def authenticated(request: Request, db: Session = Depends(get_db)) -> Principal:
    p = _resolve(request, db)
    if p is None:
        raise HTTPException(401, detail={"code": "AUTH_REQUIRED", "detail": "Authentication required."}, headers={"WWW-Authenticate": "Bearer"})
    request.state.principal = p
    return p


def optional_principal(request: Request, db: Session = Depends(get_db)) -> Principal | None:
    try:
        p = _resolve(request, db)
    except HTTPException:
        return None
    if p:
        request.state.principal = p
    return p


def require_role(role: str):
    def dep(request: Request, p: Principal = Depends(authenticated)) -> Principal:
        if not p.can(role):
            audit(p.username, "forbidden", "denied", target=f"{request.method} {request.url.path}", ip=get_client_ip(request), detail={"required": role, "has": p.role})
            raise HTTPException(403, detail={"code": "FORBIDDEN", "detail": f"This action requires the {role} role."})
        return p
    return dep


viewer, operator, admin = require_role("viewer"), require_role("operator"), require_role("admin")


# ---------------------------------------------------------------------------------------------------------------- schemas
class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class UserCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=1, max_length=256)
    role: Role = "viewer"


class UserPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = Field(None, min_length=1, max_length=256)


def _user_dict(u: m.UserRow) -> dict:
    return {"id": u.id, "username": u.username, "role": u.role, "is_active": u.is_active,
            "created_at": u.created_at.isoformat() if u.created_at else None, "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None}


def _set_session(response: Response, user: m.UserRow) -> dict:
    s = config.settings
    token, claims = sec.issue_token(s.jwt_secret, user_id=user.id, role=user.role, token_version=user.token_version, minutes=s.access_token_minutes)
    response.set_cookie(COOKIE_NAME, token, max_age=s.access_token_minutes * 60, httponly=True, secure=s.cookie_secure, samesite="strict", path="/")
    return {"user": _user_dict(user), "csrf_token": sec.csrf_token(s.jwt_secret, claims.jti), "access_token": token, "token_type": "bearer",
            "expires_at": datetime.fromtimestamp(claims.expires_at, timezone.utc).isoformat(timespec="seconds")}


def _policy(password: str, username: str) -> None:
    try:
        sec.validate_new_password(password, username)
    except sec.PasswordPolicyError as e:
        raise HTTPException(422, detail={"code": "WEAK_PASSWORD", "detail": str(e)})


# ------------------------------------------------------------------------------------------------------------------ users
def create_user(db: Session, username: str, password: str, role: str) -> m.UserRow:
    username = username.strip().lower()
    if not sec.USERNAME_RE.match(username):
        raise ValueError("User name must be 3-40 characters: lower-case letters, digits, '.', '_' or '-', starting with a letter or digit.")
    sec.validate_new_password(password, username)
    if role not in sec.ROLES:
        raise ValueError("Unknown role.")
    u = m.UserRow(username=username, password_hash=sec.hash_password(password, config.settings.password_scrypt_log_n), role=role, is_active=True, token_version=0)
    db.add(u)
    db.commit()
    return u


def ensure_bootstrap_admin(db: Session) -> str:
    """First-run administrator from BOOTSTRAP_ADMIN_USERNAME / _PASSWORD (only when the users table is empty)."""
    s = config.settings
    if db.scalar(select(func.count()).select_from(m.UserRow)):
        return "users-exist"
    if not s.bootstrap_admin_username:
        log.error("no users exist and BOOTSTRAP_ADMIN_USERNAME/PASSWORD are not set: nobody can sign in. Create one with: python -m app.cli create-user")
        return "no-users"
    create_user(db, s.bootstrap_admin_username, s.bootstrap_admin_password or "", "admin")
    audit(None, "bootstrap_admin_created", "success", target=s.bootstrap_admin_username.lower())
    log.warning("bootstrap administrator %r created; remove BOOTSTRAP_ADMIN_PASSWORD from the environment", s.bootstrap_admin_username)
    return "created"


# ----------------------------------------------------------------------------------------------------------------- routers
router = APIRouter(prefix="/api/auth", tags=["authentication"])
users_router = APIRouter(prefix="/api", tags=["user-management"])


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip, name = get_client_ip(request), body.username.strip().lower()
    key = f"{ip}|{name}"
    for lim, k in ((_login_failures, key), (_login_ip_failures, ip)):
        if lim.count(k) >= lim.limit:
            metrics.inc("login_locked")
            audit(name, "login", "denied", ip=ip, detail={"reason": "rate_limited"})
            raise HTTPException(429, detail={"code": "TOO_MANY_ATTEMPTS", "detail": "Too many failed sign-in attempts. Try again later."},
                                headers={"Retry-After": str(config.settings.login_window_seconds)})
    user = db.scalar(select(m.UserRow).where(m.UserRow.username == name))
    ok = False
    if user is not None and user.is_active:
        ok = sec.verify_password(body.password, user.password_hash)
    else:
        sec.burn_password_check(body.password, config.settings.password_scrypt_log_n)
    if not ok:
        _login_failures.hit(key)
        _login_ip_failures.hit(ip)
        metrics.inc("login_failures")
        audit(name, "login", "failure", ip=ip)
        raise HTTPException(401, detail={"code": "INVALID_CREDENTIALS", "detail": "Invalid user name or password."})   # same answer for unknown user / bad password / inactive
    _login_failures.reset(key)
    if sec.needs_rehash(user.password_hash, config.settings.password_scrypt_log_n):
        user.password_hash = sec.hash_password(body.password, config.settings.password_scrypt_log_n)
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    metrics.inc("logins")
    audit(user.username, "login", "success", ip=ip, db=db)
    response.headers["Cache-Control"] = "no-store"
    return _set_session(response, user)


@router.get("/session")
def session(request: Request, response: Response, p: Principal | None = Depends(optional_principal), db: Session = Depends(get_db)):
    """Session probe for the single-page app: always 200 (so a signed-out visit is not logged as a failed request)."""
    response.headers["Cache-Control"] = "no-store"
    if p is None:
        return {"authenticated": False}
    return {"authenticated": True, "user": _user_dict(db.get(m.UserRow, p.id)), "csrf_token": sec.csrf_token(config.settings.jwt_secret, p.jti), "auth_via": p.via}


@router.get("/me")
def me(request: Request, response: Response, p: Principal = Depends(authenticated), db: Session = Depends(get_db)):
    user = db.get(m.UserRow, p.id)
    response.headers["Cache-Control"] = "no-store"
    return {"user": _user_dict(user), "csrf_token": sec.csrf_token(config.settings.jwt_secret, p.jti), "auth_via": p.via}


@router.post("/logout")
def logout(request: Request, response: Response, p: Principal = Depends(authenticated), db: Session = Depends(get_db)):
    user = db.get(m.UserRow, p.id)
    user.token_version += 1          # server-side revocation: every token issued to this user so far stops working
    db.commit()
    audit(p.username, "logout", "success", ip=get_client_ip(request), db=db)
    response.delete_cookie(COOKIE_NAME, path="/", samesite="strict", secure=config.settings.cookie_secure, httponly=True)
    return {"signed_out": True}


@router.post("/change-password")
def change_password(body: ChangePasswordIn, request: Request, response: Response, p: Principal = Depends(authenticated), db: Session = Depends(get_db)):
    user = db.get(m.UserRow, p.id)
    ip = get_client_ip(request)
    if not sec.verify_password(body.current_password, user.password_hash):
        audit(p.username, "change_password", "failure", ip=ip, db=db)
        raise HTTPException(403, detail={"code": "INVALID_CREDENTIALS", "detail": "Current password is incorrect."})
    _policy(body.new_password, user.username)
    user.password_hash = sec.hash_password(body.new_password, config.settings.password_scrypt_log_n)
    user.token_version += 1
    user.updated_at = datetime.now(timezone.utc)
    db.commit()
    audit(p.username, "change_password", "success", ip=ip, db=db)
    return _set_session(response, user)          # the current browser keeps a valid session; every other session is revoked


@users_router.get("/users")
def list_users(_: Principal = Depends(admin), db: Session = Depends(get_db)):
    return [_user_dict(u) for u in db.scalars(select(m.UserRow).order_by(m.UserRow.id))]


@users_router.post("/users", status_code=201)
def add_user(body: UserCreateIn, request: Request, p: Principal = Depends(admin), db: Session = Depends(get_db)):
    name = body.username.strip().lower()
    if not sec.USERNAME_RE.match(name):
        raise HTTPException(422, detail={"code": "INVALID_USERNAME", "detail": "User name must be 3-40 characters: lower-case letters, digits, '.', '_' or '-', starting with a letter or digit."})
    _policy(body.password, name)
    try:
        u = create_user(db, name, body.password, body.role)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, detail={"code": "USER_EXISTS", "detail": "A user with that name already exists."})
    audit(p.username, "user_create", "success", target=name, ip=get_client_ip(request), detail={"role": body.role}, db=db)
    return _user_dict(u)


@users_router.patch("/users/{user_id}")
def patch_user(user_id: int, body: UserPatchIn, request: Request, p: Principal = Depends(admin), db: Session = Depends(get_db)):
    u = db.get(m.UserRow, user_id)
    if u is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "detail": "Unknown user."})
    changes: dict = {}
    losing_admin = (u.role == "admin" and u.is_active) and ((body.role is not None and body.role != "admin") or body.is_active is False)
    if losing_admin:
        others = db.scalar(select(func.count()).select_from(m.UserRow).where(m.UserRow.role == "admin", m.UserRow.is_active.is_(True), m.UserRow.id != u.id))
        if not others:
            raise HTTPException(409, detail={"code": "LAST_ADMIN", "detail": "At least one active administrator must remain."})
    if body.role is not None and body.role != u.role:
        changes["role"] = [u.role, body.role]
        u.role = body.role
        u.token_version += 1
    if body.is_active is not None and body.is_active != u.is_active:
        changes["is_active"] = [u.is_active, body.is_active]
        u.is_active = body.is_active
        u.token_version += 1
    if body.password is not None:
        _policy(body.password, u.username)
        u.password_hash = sec.hash_password(body.password, config.settings.password_scrypt_log_n)
        u.token_version += 1
        changes["password"] = "reset"
    u.updated_at = datetime.now(timezone.utc)
    db.commit()
    audit(p.username, "user_update", "success", target=u.username, ip=get_client_ip(request), detail=changes, db=db)
    return _user_dict(u)


@users_router.get("/audit-log")
def audit_log(limit: int = 100, _: Principal = Depends(admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(m.AuditLogRow).order_by(m.AuditLogRow.id.desc()).limit(max(1, min(limit, 500))))
    return [{"id": r.id, "ts": r.ts.isoformat(), "actor": r.actor, "action": r.action, "target": r.target, "outcome": r.outcome, "client_ip": r.client_ip,
             "detail": r.detail} for r in rows]
