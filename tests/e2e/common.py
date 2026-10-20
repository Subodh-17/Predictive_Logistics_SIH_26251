"""Shared helpers for the browser end-to-end scripts: sign-in through the real login form, CSRF-aware API calls, readiness pre-flight."""
import json, os, urllib.request

URL = os.environ.get('APP_URL', 'http://localhost:8080').rstrip('/')
USER = os.environ.get('E2E_USER', '')
PASSWORD = os.environ.get('E2E_PASSWORD', '')


def preflight():
    """True only when the service answers /api/health/ready (database reachable and start-up complete)."""
    try:
        with urllib.request.urlopen(URL + '/api/health/ready', timeout=10) as r:
            h = json.loads(r.read())
        print(f"preflight: {URL}/api/health/ready -> {h}")
        if h.get('status') == 'ready' and USER and PASSWORD:
            http('/api/iot/reset', 'POST')        # the suites assert the seeded baseline: start from it (needs an admin account)
            print('inventory reset to the seeded baseline')
        return h.get('status') == 'ready'
    except Exception as e:
        print('preflight failed:', e)
        return False


def login(pg, user=None, password=None):
    """Open the app, sign in through the login form and wait for the dashboard shell."""
    user, password = user or USER, password or PASSWORD
    if not user or not password:
        raise SystemExit('Set E2E_USER and E2E_PASSWORD (an existing account) to run the browser tests.')
    pg.goto(URL)
    pg.wait_for_selector('[data-testid=login-form]', timeout=20000)
    pg.fill('#lu', user); pg.fill('#lp', password); pg.click('button[type=submit]')
    pg.wait_for_selector('[data-testid=user-name]', timeout=20000)


class _Resp:
    def __init__(self, d): self.status, self._d = d['status'], d['body']
    @property
    def ok(self): return 200 <= self.status < 300
    def json(self): return self._d


def api(pg, method, path, body=None):
    """API call made from INSIDE the page (same cookies, same origin, CSRF header) - exactly what the single-page app does.
    (Playwright's out-of-page request client refuses to send Secure cookies over plain http, so it is not used here.)"""
    return _Resp(pg.evaluate("""async ([m, p, b]) => {
        const me = await (await fetch('/api/auth/session')).json();
        const r = await fetch(p, {method: m.toUpperCase(), credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': me.csrf_token},
                                  body: b === null ? undefined : JSON.stringify(b)});
        let body = null; try { body = await r.json(); } catch (e) {}
        return {status: r.status, body};
    }""", [method, path, body]))


_token = None


def http(path, method='GET', body=None):
    """Server-side API helper with a Bearer token (signs in once). Used by the scripts for set-up and for reading the expected values."""
    global _token
    if _token is None:
        req = urllib.request.Request(URL + '/api/auth/login', method='POST', data=json.dumps({'username': USER, 'password': PASSWORD}).encode(), headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=30) as r:
            _token = json.loads(r.read())['access_token']
    req = urllib.request.Request(URL + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + _token})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())
