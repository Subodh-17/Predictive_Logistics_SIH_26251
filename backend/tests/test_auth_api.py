"""Authentication, role-based authorisation, sessions, CSRF, lockout, user management and audit trail (real FastAPI app + PostgreSQL)."""
import time

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import auth, config, models as m, security as sec
from app.database import SessionLocal
from .conftest import TEST_PASSWORD

IOT = dict(device_id="ESP32-SIM-01", tag_id="RFID-SIM-1234", event_type="COUNT", location_id="Base_04", supply_id="Medical", quantity=1234)


def login(app, name="t_viewer", password=TEST_PASSWORD, **kw):
    c = TestClient(app, raise_server_exceptions=False, **kw)
    return c, c.post("/api/auth/login", json={"username": name, "password": password})


@pytest.fixture()
def app(app_ctx):
    return app_ctx[0]


@pytest.fixture(autouse=True)
def fresh_limiters():
    auth.configure_limiters(5, 900)
    yield
    auth.configure_limiters(config.settings.login_max_failures, config.settings.login_window_seconds)


# ------------------------------------------------------------------------------------------------------- evaluator & auth matrix
PUBLIC_EVALUATOR_ENDPOINTS = [
    "/api/dashboard", "/api/locations", "/api/locations/Base_04", "/api/inventory",
    "/api/inventory/projection?location=Base_04&supply=Medical",
    "/api/inventory/risk-basis", "/api/alerts", "/api/forecast", "/api/forecast/challenger",
    "/api/vehicles", "/api/routes", "/api/routes/compare?destination=Base_04",
    "/api/priority", "/api/priority/weights", "/api/allocation", "/api/insights",
    "/api/iot/events", "/api/iot/feed", "/api/simulation/runs",
    "/api/ml/models", "/api/ml/evaluation", "/api/health/detail",
]

PROTECTED_ENDPOINTS = [
    ("get", "/api/auth/me", None),
    ("post", "/api/auth/logout", None),
    ("post", "/api/auth/change-password", {"current_password": "x", "new_password": "y"}),
    ("post", "/api/iot/update", IOT),
    ("post", "/api/iot/simulate", {"count": 1}),
    ("post", "/api/iot/reset", None),
    ("post", "/api/forecast/recompute", None),
    ("post", "/api/simulation/run", {"demand_increase": 0.1}),
    ("post", "/api/ml/shortage-risk", {"demand": [1] * 28, "on_hand": [1] * 28, "in_transit": [1] * 28, "backlog": [0] * 28, "new_backlog": [0] * 28}),
    ("get", "/api/users", None),
    ("post", "/api/users", {"username": "x_user", "password": "Aa1-long-enough-pw"}),
    ("patch", "/api/users/1", {"role": "viewer"}),
    ("get", "/api/audit-log", None),
]


@pytest.mark.parametrize("url", PUBLIC_EVALUATOR_ENDPOINTS)
def test_every_evaluator_read_endpoint_allows_anonymous_access(anon_client, url):
    r = anon_client.get(url)
    assert r.status_code == 200, (url, r.status_code, r.text[:100])


@pytest.mark.parametrize("method,url,body", PROTECTED_ENDPOINTS)
def test_every_protected_endpoint_rejects_anonymous_access(anon_client, method, url, body):
    r = getattr(anon_client, method)(url, **({"json": body} if body is not None else {}))
    assert r.status_code == 401, (url, r.status_code)
    assert r.json().get("code") == "AUTH_REQUIRED", (url, r.json())
    assert r.headers.get("www-authenticate") == "Bearer"


def test_health_detail_redacts_target_for_evaluator_and_viewer(anon_client, viewer_client, client):
    anon_hd = anon_client.get("/api/health/detail").json()
    assert "target" not in anon_hd["database"], "Database target host string leaked to anonymous evaluator"
    assert anon_hd["environment"] == "test"

    v_hd = viewer_client.get("/api/health/detail").json()
    assert "target" not in v_hd["database"], "Database target host string leaked to viewer"

    a_hd = client.get("/api/health/detail").json()
    assert "target" in a_hd["database"], "Database target missing for administrator"


def test_session_probe_is_always_200_and_reports_state(app, anon_client):
    assert anon_client.get("/api/auth/session").json() == {"authenticated": False}
    c, r = login(app)
    j = c.get("/api/auth/session").json()
    assert j["authenticated"] is True and j["user"]["username"] == "t_viewer" and j["csrf_token"] == r.json()["csrf_token"]


def test_public_health_endpoints(anon_client):
    assert anon_client.get("/api/health/live").status_code == 200
    assert anon_client.get("/api/health/ready").status_code == 200
    h = anon_client.get("/api/health")
    assert h.status_code == 200 and h.json()["database"] == {"connected": True}      # anonymous: no versions, no row counts
    assert "postgis" not in h.text and "counts" not in h.text


# ------------------------------------------------------------------------------------------------------------------------ roles
def test_role_matrix(viewer_client, operator_client, client):
    v, o, a = viewer_client, operator_client, client
    # viewer: read-only (and the stateless model check)
    assert v.get("/api/dashboard").status_code == 200 and v.get("/api/health/detail").status_code == 200
    assert v.post("/api/ml/shortage-risk", json={"demand": [1] * 28, "on_hand": [1] * 28, "in_transit": [1] * 28, "backlog": [0] * 28, "new_backlog": [0] * 28}).status_code in (200, 503)
    for method, url, body in [("post", "/api/iot/update", IOT), ("post", "/api/iot/simulate", {"count": 1}), ("post", "/api/simulation/run", {}),
                              ("post", "/api/iot/reset", None), ("post", "/api/forecast/recompute", None), ("get", "/api/users", None)]:
        r = getattr(v, method)(url, **({"json": body} if body is not None else {}))
        assert r.status_code == 403 and r.json()["code"] == "FORBIDDEN", (url, r.status_code)
    # operator: events and simulations, but no admin functions
    assert o.post("/api/simulation/run", json={"demand_increase": 0.1}).status_code == 200
    assert o.post("/api/iot/update", json=IOT).status_code == 200
    for method, url, body in [("post", "/api/iot/reset", None), ("post", "/api/forecast/recompute", None), ("get", "/api/users", None), ("get", "/api/audit-log", None)]:
        r = getattr(o, method)(url, **({"json": body} if body is not None else {}))
        assert r.status_code == 403, (url, r.status_code)
    assert a.post("/api/iot/reset").status_code == 200 and a.get("/api/users").status_code == 200


def test_denied_actions_are_audited(viewer_client, client):
    viewer_client.post("/api/iot/reset")
    rows = client.get("/api/audit-log?limit=20").json()
    assert any(r["action"] == "forbidden" and r["actor"] == "t_viewer" and r["outcome"] == "denied" for r in rows)


# ---------------------------------------------------------------------------------------------------------------------- login
def test_login_success_sets_hardened_cookie_and_returns_csrf(app):
    c, r = login(app)
    assert r.status_code == 200
    j = r.json()
    assert j["user"]["username"] == "t_viewer" and j["user"]["role"] == "viewer" and "password" not in r.text and "hash" not in r.text
    sc = r.headers["set-cookie"].lower()
    assert "httponly" in sc and "samesite=strict" in sc and "path=/" in sc and r.headers["cache-control"] == "no-store"
    assert j["csrf_token"] and j["expires_at"]


def test_login_failures_are_uniform_and_do_not_reveal_which_part_was_wrong(app):
    _, bad_pw = login(app, "t_viewer", "wrong-password-xyz")
    _, no_user = login(app, "no_such_user_zz", "wrong-password-xyz")
    assert bad_pw.status_code == no_user.status_code == 401 and bad_pw.json() == no_user.json()
    assert bad_pw.json()["code"] == "INVALID_CREDENTIALS"


def test_login_lockout_after_repeated_failures_and_audit(app, client):
    for _ in range(5):
        assert login(app, "t_operator", "nope-nope-nope-1")[1].status_code == 401
    r = login(app, "t_operator", TEST_PASSWORD)[1]            # even the right password is refused during the lockout
    assert r.status_code == 429 and r.json()["code"] == "TOO_MANY_ATTEMPTS" and "retry-after" in r.headers
    assert any(a["action"] == "login" and a["outcome"] in ("failure", "denied") for a in client.get("/api/audit-log?limit=30").json())


def test_login_validation_does_not_echo_submitted_password(app):
    c = TestClient(app, raise_server_exceptions=False)
    secret = "p" * 300
    r = c.post("/api/auth/login", json={"username": "t_viewer", "password": secret})
    assert r.status_code == 422 and secret not in r.text and "input" not in r.text
    assert c.post("/api/auth/login", json={"username": "t_viewer", "password": "x", "role": "admin"}).status_code == 422     # unknown field refused


# --------------------------------------------------------------------------------------------------------------- tokens / sessions
def test_bearer_and_cookie_sessions_work_and_me_returns_identity(app):
    c, r = login(app)
    assert c.get("/api/auth/me").json()["user"]["username"] == "t_viewer"                       # cookie jar
    b = TestClient(app, headers={"Authorization": "Bearer " + r.json()["access_token"]})
    assert b.get("/api/auth/me").json()["auth_via"] == "bearer"


def test_cookie_sessions_require_csrf_token_on_state_changes(app):
    c, r = login(app, "t_operator")
    csrf = r.json()["csrf_token"]
    assert c.post("/api/simulation/run", json={}).status_code == 403                                   # cookie, no token
    assert c.post("/api/simulation/run", json={}).json()["code"] == "CSRF_FAILED"
    assert c.post("/api/simulation/run", json={}, headers={"X-CSRF-Token": "0" * 40}).status_code == 403
    assert c.post("/api/simulation/run", json={}, headers={"X-CSRF-Token": csrf}).status_code == 200
    assert c.get("/api/dashboard").status_code == 200                                                  # reads never need it


def test_csrf_token_of_one_session_does_not_work_for_another(app):
    c1, r1 = login(app, "t_operator")
    c2, r2 = login(app, "t_operator")
    assert c2.post("/api/simulation/run", json={}, headers={"X-CSRF-Token": r1.json()["csrf_token"]}).status_code == 403


def test_forged_expired_and_garbage_tokens_are_rejected(app):
    secret = config.settings.jwt_secret
    cases = ["garbage",
             jwt.encode({"sub": "1", "role": "admin"}, "wrong-key-wrong-key-wrong-key-wrong-key", algorithm="HS256"),
             sec.issue_token(secret, user_id=1, role="admin", token_version=0, minutes=1, now=time.time() - 7200)[0],
             jwt.encode({"sub": "1", "role": "admin"}, key=None, algorithm="none")]
    for t in cases:
        assert TestClient(app, headers={"Authorization": "Bearer " + t}).get("/api/auth/me").status_code == 401


def test_role_claim_in_token_is_not_trusted_the_database_role_wins(app, app_ctx):
    with SessionLocal() as db:
        uid = db.scalar(select(m.UserRow.id).where(m.UserRow.username == "t_viewer"))
        ver = db.scalar(select(m.UserRow.token_version).where(m.UserRow.username == "t_viewer"))
    forged, _ = sec.issue_token(config.settings.jwt_secret, user_id=uid, role="admin", token_version=ver, minutes=5)    # validly signed, lies about role
    c = TestClient(app, headers={"Authorization": "Bearer " + forged}, raise_server_exceptions=False)
    assert c.get("/api/users").status_code == 403


def test_logout_revokes_the_token_server_side(app):
    c, r = login(app, "t_operator")
    tok = r.json()["access_token"]
    csrf = r.json()["csrf_token"]
    assert c.post("/api/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
    assert TestClient(app, headers={"Authorization": "Bearer " + tok}).get("/api/auth/me").status_code == 401     # copied token is dead too
    # restore a working session for the remaining tests in this module
    assert login(app, "t_operator")[1].status_code == 200


def test_change_password_revokes_old_tokens_and_enforces_policy(app, client):
    created = client.post("/api/users", json={"username": "t_pwchange", "password": "Initial-pass-1234", "role": "viewer"})
    assert created.status_code == 201
    c, r = login(app, "t_pwchange", "Initial-pass-1234")
    old = r.json()["access_token"]
    h = {"X-CSRF-Token": r.json()["csrf_token"]}
    assert c.post("/api/auth/change-password", json={"current_password": "bad", "new_password": "New-pass-98765"}, headers=h).status_code == 403
    assert c.post("/api/auth/change-password", json={"current_password": "Initial-pass-1234", "new_password": "short"}, headers=h).status_code == 422
    ok = c.post("/api/auth/change-password", json={"current_password": "Initial-pass-1234", "new_password": "New-pass-98765"}, headers=h)
    assert ok.status_code == 200
    assert TestClient(app, headers={"Authorization": "Bearer " + old}).get("/api/auth/me").status_code == 401
    assert login(app, "t_pwchange", "Initial-pass-1234")[1].status_code == 401
    assert login(app, "t_pwchange", "New-pass-98765")[1].status_code == 200


# ----------------------------------------------------------------------------------------------------------- user administration
def test_user_management_rules(client, app):
    assert client.post("/api/users", json={"username": "t_new", "password": "Brand-new-pass-1", "role": "operator"}).status_code == 201
    dup = client.post("/api/users", json={"username": "T_NEW", "password": "Brand-new-pass-1", "role": "viewer"})
    assert dup.status_code == 409 and dup.json()["code"] == "USER_EXISTS"                                   # case-insensitive uniqueness
    assert client.post("/api/users", json={"username": "x", "password": "Brand-new-pass-1"}).status_code == 422
    assert client.post("/api/users", json={"username": "bad name!", "password": "Brand-new-pass-1"}).status_code == 422
    assert client.post("/api/users", json={"username": "t_weak", "password": "short"}).json()["code"] == "WEAK_PASSWORD"
    assert client.post("/api/users", json={"username": "t_extra", "password": "Brand-new-pass-1", "is_admin": True}).status_code == 422   # mass assignment refused
    users = client.get("/api/users").json()
    assert all("password" not in u and "password_hash" not in u for u in users)
    uid = next(u["id"] for u in users if u["username"] == "t_new")
    assert client.patch(f"/api/users/{uid}", json={"role": "superuser"}).status_code == 422
    assert client.patch(f"/api/users/{uid}", json={"is_active": False}).json()["is_active"] is False
    assert login(app, "t_new", "Brand-new-pass-1")[1].status_code == 401                                   # deactivated users cannot sign in
    assert client.patch("/api/users/999999", json={"role": "viewer"}).status_code == 404


def test_the_last_active_administrator_cannot_be_removed(app, client):
    with SessionLocal() as db:
        admins = list(db.scalars(select(m.UserRow).where(m.UserRow.role == "admin", m.UserRow.is_active.is_(True))))
        spare = [a for a in admins if a.username != "t_admin"]
        for a in spare:
            a.is_active = False                                  # leave t_admin as the only active administrator
        db.commit()
        admin_id = db.scalar(select(m.UserRow.id).where(m.UserRow.username == "t_admin"))
    try:
        r = client.patch(f"/api/users/{admin_id}", json={"role": "viewer"})
        assert r.status_code == 409 and r.json()["code"] == "LAST_ADMIN"
        assert client.patch(f"/api/users/{admin_id}", json={"is_active": False}).status_code == 409
    finally:
        with SessionLocal() as db:
            for a in spare:
                db.get(m.UserRow, a.id).is_active = True
            db.commit()


def test_audit_log_never_contains_secrets(client):
    text = client.get("/api/audit-log?limit=500").text
    assert TEST_PASSWORD not in text and "scrypt$" not in text and "eyJ" not in text


def test_bootstrap_admin_is_created_only_when_no_users_exist(prepared_db, monkeypatch):
    from app import config as cfg
    with SessionLocal() as db:
        assert auth.ensure_bootstrap_admin(db) == "users-exist"            # the test users exist: nothing is created, nothing is overwritten
