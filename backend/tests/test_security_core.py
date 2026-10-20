"""Security primitives without a database or HTTP layer."""
import time

import jwt
import pytest

from app import security as sec

SECRET = "k3J9-vB2mQx7LpZ4tR8nW1yH6cF0dS5aG-uE"


def test_password_hash_roundtrip_salting_and_rejection():
    h1, h2 = sec.hash_password("correct horse battery", 10), sec.hash_password("correct horse battery", 10)
    assert h1 != h2 and h1.startswith("scrypt$") and "correct" not in h1          # per-user salt, no plain text
    assert sec.verify_password("correct horse battery", h1)
    assert not sec.verify_password("correct horse batterY", h1)
    for bad in ("", "scrypt$1$2", "md5$x$y$z$a$b", "scrypt$99999999$8$3$AAAA$AAAA", "scrypt$1024$8$3$%%%$%%%"):
        assert not sec.verify_password("x", bad)             # malformed / hostile stored values fail closed, never raise


def test_rehash_detects_weaker_parameters():
    assert sec.needs_rehash(sec.hash_password("a-long-enough-pass", 10), 15)
    assert not sec.needs_rehash(sec.hash_password("a-long-enough-pass", 10), 10)
    assert sec.needs_rehash("garbage", 10)


@pytest.mark.parametrize("pw,ok", [("short", False), ("a" * 129, False), ("aaaaaaaaaaaa", False), ("password1234", False), ("Valid-pass-9876", True)])
def test_password_policy(pw, ok):
    if ok:
        sec.validate_new_password(pw, "alice")
    else:
        with pytest.raises(sec.PasswordPolicyError):
            sec.validate_new_password(pw, "alice")


def test_password_must_not_contain_username():
    with pytest.raises(sec.PasswordPolicyError):
        sec.validate_new_password("xx-alice-12345-xx", "alice")


def test_token_roundtrip_and_claims():
    tok, c = sec.issue_token(SECRET, user_id=7, role="operator", token_version=3, minutes=5)
    d = sec.decode_token(SECRET, tok)
    assert (d.user_id, d.role, d.token_version, d.jti) == (7, "operator", 3, c.jti)


def test_token_rejections():
    tok, _ = sec.issue_token(SECRET, user_id=1, role="admin", token_version=0, minutes=5)
    with pytest.raises(sec.TokenError):
        sec.decode_token("another-secret-another-secret-another", tok)                                    # wrong key
    with pytest.raises(sec.TokenError):
        sec.decode_token(SECRET, tok[:-3] + ("AAA" if not tok.endswith("AAA") else "BBB"))                 # tampered signature
    expired, _ = sec.issue_token(SECRET, user_id=1, role="admin", token_version=0, minutes=1, now=time.time() - 3600)
    with pytest.raises(sec.TokenError):
        sec.decode_token(SECRET, expired)
    none_alg = jwt.encode({"sub": "1", "role": "admin"}, key=None, algorithm="none")                       # alg=none forgery
    with pytest.raises(sec.TokenError):
        sec.decode_token(SECRET, none_alg)
    wrong_aud = jwt.encode({"sub": "1", "iss": sec.ISSUER, "aud": "other", "exp": int(time.time()) + 60, "iat": 1, "nbf": 1, "jti": "x"}, SECRET, algorithm="HS256")
    with pytest.raises(sec.TokenError):
        sec.decode_token(SECRET, wrong_aud)
    missing = jwt.encode({"sub": "1", "iss": sec.ISSUER, "aud": sec.AUDIENCE}, SECRET, algorithm="HS256")   # no exp
    with pytest.raises(sec.TokenError):
        sec.decode_token(SECRET, missing)
    with pytest.raises(sec.TokenError):
        sec.decode_token(SECRET, "not.a.jwt")


def test_csrf_token_is_bound_to_the_session():
    t = sec.csrf_token(SECRET, "jti-1")
    assert sec.csrf_ok(SECRET, "jti-1", t)
    assert not sec.csrf_ok(SECRET, "jti-2", t) and not sec.csrf_ok(SECRET, "jti-1", None) and not sec.csrf_ok(SECRET, "jti-1", "")
    assert not sec.csrf_ok("other-secret-other-secret-other-secret", "jti-1", t)


def test_sliding_window_limiter_blocks_then_recovers():
    now = [0.0]
    lim = sec.SlidingWindowLimiter(3, 10, clock=lambda: now[0])
    assert [lim.hit("a")[0] for _ in range(3)] == [True] * 3
    ok, wait = lim.hit("a")
    assert not ok and 1 <= wait <= 11
    assert lim.hit("b")[0]                                  # keys are independent
    now[0] = 11
    assert lim.hit("a")[0]                                  # window slid
    lim.reset("a")
    assert lim.count("a") == 0


def test_client_ip_trusts_only_the_configured_proxy_hops():
    assert sec.client_ip("10.0.0.5", "1.2.3.4", 0) == "10.0.0.5"                       # header ignored when no proxy is trusted
    assert sec.client_ip("10.0.0.5", "6.6.6.6, 1.2.3.4", 1) == "1.2.3.4"               # spoofed left-hand entry ignored
    assert sec.client_ip("10.0.0.5", "1.2.3.4", 2) == "10.0.0.5"                       # fewer hops than trusted: fall back to peer
    assert sec.client_ip(None, None, 0) == "unknown"


def test_redact_masks_credentials_recursively():
    out = sec.redact({"user": "a", "password": "p", "nested": {"Authorization": "Bearer x", "ok": 1}, "list": [{"api_key": "k"}]})
    assert out == {"user": "a", "password": "***", "nested": {"Authorization": "***", "ok": 1}, "list": [{"api_key": "***"}]}
