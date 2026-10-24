#!/usr/bin/env python3
"""V6 browser end-to-end: authentication, roles, user administration, session revocation, risk explanation, shortage-record check,
terminology on the rendered pages, cookie flags, CSP violations and automated accessibility (axe-core).

    APP_URL=http://localhost:8080 E2E_USER=<admin> E2E_PASSWORD=<password> [AXE_JS=/path/to/axe.min.js] python tests/e2e/e2e_v6_security_workflows.py

Creates three throw-away accounts (viewer / operator / admin helper) with random names and deactivates them at the end.
Exit code 0 only if every check passed; skipped checks are counted and listed.
"""
import importlib.util, json, os, re, secrets, sys
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import URL, USER, PASSWORD, login, api, http, preflight

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
spec = importlib.util.spec_from_file_location('audit_terminology', os.path.join(ROOT, 'scripts', 'audit_terminology.py'))
audit = importlib.util.module_from_spec(spec); spec.loader.exec_module(audit)
AXE = os.environ.get('AXE_JS', '')
results = []


def check(area, name, ok, detail=''):
    results.append((area, name, 'PASS' if ok else 'FAIL', str(detail)))
    print(('PASS' if ok else 'FAIL'), f'[{area}]', name, ('· ' + str(detail)) if detail else '', flush=True)


def skip(area, name, reason):
    results.append((area, name, 'SKIP', reason)); print('SKIP', f'[{area}]', name, '·', reason, flush=True)


if not preflight():
    print('ENVIRONMENT NOT READY - no tests were run.'); sys.exit(2)

tag = secrets.token_hex(3)
PW = 'E2e-' + secrets.token_urlsafe(14)
names = {r: f'e2e_{r}_{tag}' for r in ('viewer', 'operator', 'admin2')}
for r, n in names.items():
    http('/api/users', 'POST', {'username': n, 'password': PW, 'role': 'admin' if r == 'admin2' else r})

PAGES = ['Command Dashboard', 'Demand Forecast', 'GIS Logistics', 'Inventory', 'What-If Simulation', 'Model Evaluation', 'System & Account']
ATTR_JS = """() => ({text: document.body.innerText, title: document.title,
  attrs: [...document.querySelectorAll('[title],[aria-label],[placeholder],[alt]')].map(e => [e.getAttribute('title'), e.getAttribute('aria-label'), e.getAttribute('placeholder'), e.getAttribute('alt')].filter(Boolean).join(' | '))})"""


def sign_in(pg, name):
    login(pg, name, PW)


def go(pg, label):
    pg.locator('nav').get_by_role('button', name=label, exact=True).click(); pg.wait_for_timeout(900)


def terminology(pg, area):
    d = pg.evaluate(ATTR_JS)
    blob = '\n'.join([d['title'], d['text']] + d['attrs'])
    hits = audit.find(blob, code=False)
    check(area, 'no prohibited terminology in visible text, title, tooltips or aria labels', not hits, [h[1].group(0) for h in hits][:3])


with sync_playwright() as p:
    browser = p.chromium.launch()
    print(f'base URL: {URL} | browser: chromium {browser.version} (headless)', flush=True)

    # ------------------------------------------------------------------ signed-out state
    ctx = browser.new_context(viewport={'width': 1440, 'height': 1000}); pg = ctx.new_page()
    csp, console_err = [], []
    pg.on('console', lambda m: (csp.append(m.text) if 'Content Security Policy' in m.text else console_err.append(m.text)) if m.type == 'error' and 'openstreetmap' not in (m.location.get('url', '') + m.text) else None)
    pg.goto(URL); pg.wait_for_selector('[data-testid=login-form]', timeout=20000)
    body = pg.inner_text('body')
    check('Signed out', 'login form is shown and no operational data is rendered', 'SIGN IN' in body and 'CRITICAL' not in body and 'Command Dashboard' not in body)
    r = pg.evaluate("fetch('/api/dashboard').then(r => r.status)")
    check('Signed out', 'API refuses unauthenticated data requests from the page', r == 401, r)
    check('Signed out', 'sign-in button disabled until both fields are filled', pg.locator('button[type=submit]').is_disabled())
    pg.fill('#lu', names['viewer']); pg.fill('#lp', 'definitely-wrong-password'); pg.click('button[type=submit]')
    pg.wait_for_selector('[data-testid=login-error]')
    check('Signed out', 'wrong password gives a generic error and no session', 'Invalid user name or password' in pg.inner_text('[data-testid=login-error]') and pg.locator('[data-testid=user-name]').count() == 0)
    check('Signed out', 'password field masks input and has autocomplete hint', pg.get_attribute('#lp', 'type') == 'password' and pg.get_attribute('#lp', 'autocomplete') == 'current-password')
    terminology(pg, 'Signed out')
    ctx.close()

    # ------------------------------------------------------------------ viewer
    ctx = browser.new_context(viewport={'width': 1440, 'height': 1000}); pg = ctx.new_page()
    pg.on('console', lambda m: (csp.append(m.text) if 'Content Security Policy' in m.text else console_err.append(m.text)) if m.type == 'error' and 'openstreetmap' not in (m.location.get('url', '') + m.text) else None)
    sign_in(pg, names['viewer'])
    check('Viewer', 'role is shown in the sidebar', pg.inner_text('[data-testid=user-role]') == 'viewer' and names['viewer'] in pg.inner_text('[data-testid=user-name]'))
    navs = [b.inner_text() for b in pg.locator('nav button').all()]
    check('Viewer', 'user administration is not offered', 'User Administration' not in navs, navs)
    cookies = {c['name']: c for c in ctx.cookies()}
    sc = cookies.get('plsd_session')
    check('Cookie', 'session cookie is HttpOnly, SameSite=Strict and Secure', bool(sc) and sc['httpOnly'] and sc['sameSite'] == 'Strict' and sc['secure'], {k: sc.get(k) for k in ('httpOnly', 'sameSite', 'secure')} if sc else None)
    check('Cookie', 'session cookie is invisible to page scripts', 'plsd_session' not in pg.evaluate('document.cookie'))
    check('Storage', 'no token or credential is kept in web storage', not re.search(r'eyJ|password|token', pg.evaluate('JSON.stringify([localStorage, sessionStorage].map(s => Object.entries(s)))'), re.I))
    for label in PAGES:
        go(pg, label); terminology(pg, f'Viewer/{label}')
    # inventory: read-only
    go(pg, 'Inventory')
    check('Viewer', 'inventory page explains that recording events needs the operator role', pg.locator('[data-testid=iot-readonly]').count() == 1 and pg.locator('button:has-text("SEND SCAN")').count() == 0)
    pg.locator('[data-testid=risk-basis] summary').click(); pg.wait_for_selector('[data-testid=risk-basis] >> text=Horizon')
    rb = pg.inner_text('[data-testid=risk-basis]')
    check('Risk basis', 'risk explanation states method, 14-day horizon, rules and limitations', all(x in rb for x in ('Method', '14 days', 'CRITICAL', 'Limitations', 'not probabilities')))
    check('Risk basis', 'trained shortage-onset model is reported as NOT used for these statuses', 'Not used for these statuses' in pg.inner_text('[data-testid=shortage-model-status]'))
    # simulation: viewer can apply but not run/save
    go(pg, 'What-If Simulation')
    check('Viewer', 'run simulation is disabled with an explanation', pg.locator('button:has-text("RUN SIMULATION")').is_disabled() and pg.locator('[data-testid=sim-readonly]').count() == 1)
    pg.fill('#sd', '30') if False else pg.evaluate("() => { const e = document.getElementById('sd'); const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; s.call(e, '30'); e.dispatchEvent(new Event('input', {bubbles: true})) }")
    pg.click('button:has-text("APPLY TO ALL SCREENS")'); pg.wait_for_selector('text=SCENARIO ACTIVE', timeout=15000)
    check('Viewer', 'viewer can apply a scenario to every screen (read-only calculation)', True)
    pg.get_by_role('button', name='Clear', exact=True).click()
    # write attempts are refused by the server even if the UI were bypassed
    st = pg.evaluate("""async () => { const me = await (await fetch('/api/auth/session')).json(); const out = {};
        for (const [m, p] of [['POST', '/api/iot/reset'], ['POST', '/api/forecast/recompute'], ['GET', '/api/users']]) {
          const r = await fetch(p, {method: m, headers: {'X-CSRF-Token': me.csrf_token, 'Content-Type': 'application/json'}}); out[p] = r.status } return out }""")
    check('Viewer', 'server returns 403 for admin actions attempted from the page', all(v == 403 for v in st.values()), st)
    nocsrf = pg.evaluate("fetch('/api/simulation/run', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'}).then(r => r.status)")
    check('CSRF', 'state-changing request without the CSRF token is rejected', nocsrf == 403, nocsrf)
    # models page: shortage check
    go(pg, 'Model Evaluation')
    pg.wait_for_selector('[data-testid=shortage-form]')
    series = {'demand': ' '.join(['120'] * 30), 'on_hand': ' '.join(['400'] * 30), 'in_transit': ' '.join(['0'] * 30), 'backlog': ' '.join(['0'] * 30), 'new_backlog': ' '.join(['0'] * 30)}
    areas = pg.locator('[data-testid=shortage-form] textarea')
    check('Shortage check', 'score button disabled until all five series are entered', pg.locator('button:has-text("SCORE RECORD")').is_disabled())
    for i, v in enumerate(series.values()): areas.nth(i).fill(v)
    pg.click('button:has-text("SCORE RECORD")'); pg.wait_for_selector('[data-testid=shortage-result]', timeout=20000)
    res = pg.inner_text('[data-testid=shortage-result]')
    m = re.search(r'within 7 days: ([\d.]+)%', res)
    check('Shortage check', 'valid record returns a probability, threshold and decision', bool(m) and 0 <= float(m.group(1)) <= 100 and 'THRESHOLD' in res, res[:120])
    areas.nth(0).fill('1 2 3'); pg.click('button:has-text("SCORE RECORD")'); pg.wait_for_selector('[role=alert]', timeout=10000)
    check('Shortage check', 'too-short record is rejected with a readable message', 'demand' in pg.inner_text('[role=alert]').lower() or 'least' in pg.inner_text('[role=alert]').lower(), pg.inner_text('[role=alert]')[:120])
    areas.nth(0).fill('a b c'); pg.click('button:has-text("SCORE RECORD")'); pg.wait_for_timeout(500)
    check('Shortage check', 'non-numeric input is caught in the browser', 'must be a number' in pg.inner_text('main'))
    # system page
    go(pg, 'System & Account')
    pg.wait_for_selector('[data-testid=sys-active-model]')
    sysxt = pg.inner_text('main')
    check('System', 'shows database, schema version, active model, last model load and data coverage', all(x in sysxt for x in ('CONNECTED', 'Schema version', 'Active model', 'Last model load', 'Consumption history through')))
    # keyboard navigation
    pg.reload(); pg.wait_for_selector('[data-testid=user-name]')
    pg.keyboard.press('Tab')
    focus = pg.evaluate('document.activeElement.textContent')
    check('Keyboard', 'first Tab stop is the skip link', 'Skip to main content' in focus, focus[:40])
    pg.keyboard.press('Tab'); pg.keyboard.press('Tab')
    nav_focus = pg.evaluate('document.activeElement.closest("nav") !== null')
    check('Keyboard', 'navigation buttons are reachable by keyboard', nav_focus)
    pg.keyboard.press('Enter'); pg.wait_for_timeout(700)
    check('Keyboard', 'Enter activates the focused navigation item', pg.locator('nav button[aria-current=page]').count() == 1)
    # sign out
    pg.click('button:has-text("SIGN OUT")'); pg.wait_for_selector('[data-testid=login-form]')
    after = pg.evaluate("fetch('/api/dashboard').then(r => r.status)")
    check('Session', 'after sign-out the login form returns and the API refuses the old cookie', after == 401, after)
    pg.reload(); pg.wait_for_selector('[data-testid=login-form]')
    check('Session', 'reload after sign-out stays signed out', True)
    ctx.close()

    # ------------------------------------------------------------------ operator
    ctx = browser.new_context(viewport={'width': 1440, 'height': 1000}); pg = ctx.new_page()
    sign_in(pg, names['operator']); go(pg, 'Inventory')
    check('Operator', 'scanner controls are available, reset inventory is not', pg.locator('button:has-text("SEND SCAN")').count() == 1 and pg.locator('button:has-text("RESET INVENTORY")').count() == 0)
    pg.click('button:has-text("SEND SCAN")'); pg.wait_for_selector('[data-testid=iot-result]', timeout=20000)
    check('Operator', 'sending a scan updates stock and shows the recalculated impact', 'stock' in pg.inner_text('[data-testid=iot-result]'))
    go(pg, 'What-If Simulation')
    check('Operator', 'run simulation is enabled', pg.locator('button:has-text("RUN SIMULATION")').is_enabled())
    pg.click('button:has-text("RUN SIMULATION")'); pg.wait_for_selector('text=Critical items', timeout=20000)
    check('Operator', 'simulation returns before/after results', True)
    forb = pg.evaluate("""async () => { const me = await (await fetch('/api/auth/session')).json();
        return (await fetch('/api/iot/reset', {method: 'POST', headers: {'X-CSRF-Token': me.csrf_token}})).status }""")
    check('Operator', 'server refuses inventory reset (admin only)', forb == 403, forb)
    ctx.close()

    # ------------------------------------------------------------------ admin: users, audit, revocation
    ctx = browser.new_context(viewport={'width': 1440, 'height': 1000}); pg = ctx.new_page()
    sign_in(pg, names['admin2'])
    go(pg, 'User Administration'); pg.wait_for_selector('[data-testid=user-form]')
    newname = f'e2e_new_{tag}'
    pg.fill('[data-testid=user-form] input:not([type=password])', newname); pg.fill('[data-testid=user-form] input[type=password]', PW)
    pg.click('[data-testid=user-form] button[type=submit]'); pg.wait_for_selector(f'text=User {newname} created')
    check('Admin', 'new user can be created from the form', pg.locator(f'td:has-text("{newname}")').count() >= 1)
    pg.fill('[data-testid=user-form] input:not([type=password])', newname); pg.fill('[data-testid=user-form] input[type=password]', PW)
    pg.click('[data-testid=user-form] button[type=submit]'); pg.wait_for_timeout(800)
    check('Admin', 'duplicate user name is rejected with a message', 'already exists' in pg.inner_text('main'))
    pg.fill('[data-testid=user-form] input:not([type=password])', f'e2e_weak_{tag}'); pg.fill('[data-testid=user-form] input[type=password]', 'short')
    valid = pg.evaluate("document.querySelector('[data-testid=user-form]').checkValidity()")
    check('Admin', 'short password is blocked by form validation', valid is False)
    row = pg.locator('tr', has=pg.locator(f'td:has-text("{newname}")')).first
    row.locator('select').select_option('operator'); pg.wait_for_selector(f'text=Role of {newname} changed')
    check('Admin', 'role can be changed', True)
    row.locator('button:has-text("RESET PASSWORD")').click(); pg.wait_for_selector('[data-testid=reset-form]')
    pg.fill('[data-testid=reset-form] input', PW + 'x'); pg.click('[data-testid=reset-form] button[type=submit]'); pg.wait_for_selector('text=reset; their sessions were signed out')
    check('Admin', 'password reset uses a masked inline form (no browser prompt)', True)
    check('Admin', 'audit trail lists the administrative actions', all(x in pg.inner_text('main') for x in ('user create', 'user update')))
    check('Admin', 'audit trail never shows credentials', not re.search(r'eyJ|scrypt\$|' + re.escape(PW), pg.inner_text('main')))
    terminology(pg, 'Admin/User administration')
    # last admin protection: deactivate every other admin first is intrusive; verify via API that self-lockout is blocked when only one admin exists is covered by pytest
    skip('Admin', 'last-administrator protection in the browser', 'covered by the API test suite; not exercised here to avoid locking the e2e account')
    # session revocation: viewer signs in elsewhere, admin deactivates them, the viewer's next request returns them to the login form with a notice
    vctx = browser.new_context(); vpg = vctx.new_page(); sign_in(vpg, names['viewer'])
    vrow = pg.locator('tr', has=pg.locator(f'td:has-text("{names["viewer"]}")')).first
    vrow.locator('button:has-text("DEACTIVATE")').click(); pg.wait_for_selector(f'text={names["viewer"]} deactivated')
    try:                                         # the next request the viewer makes is refused (401) and the app returns to the login form
        vpg.locator('nav').get_by_role('button', name='Inventory', exact=True).click(timeout=4000)
    except Exception:
        pass                                     # the page may already have noticed and replaced the shell
    vpg.wait_for_selector('[data-testid=login-form]', timeout=20000)
    check('Session', 'deactivating a user ends their open session; they see a notice at the login form', 'session has ended' in vpg.inner_text('body').lower())
    vctx.close()
    # axe accessibility on key pages (admin context, so every page type is covered)
    if AXE and os.path.exists(AXE):
        ax = browser.new_context(viewport={'width': 1440, 'height': 1000}, bypass_csp=True); apg = ax.new_page(); sign_in(apg, names['admin2'])
        for label in PAGES + ['User Administration']:
            go(apg, label); apg.wait_for_timeout(1200)
            apg.add_script_tag(path=AXE)
            v = apg.evaluate("axe.run(document, {runOnly: ['wcag2a', 'wcag2aa']}).then(r => r.violations.map(x => ({id: x.id, impact: x.impact, n: x.nodes.length, ex: x.nodes[0].html.slice(0, 90)})))")
            serious = [x for x in v if x['impact'] in ('serious', 'critical')]
            check('Accessibility', f'axe (WCAG 2 A/AA): no serious or critical violations on "{label}"', not serious, serious[:2])
        ax.close()
    else:
        skip('Accessibility', 'axe-core scan', 'AXE_JS not set')
    ctx.close()
    browser.close()

check('Console', 'no Content-Security-Policy violations on any page', not csp, csp[:2])
unexpected = [c for c in console_err if not re.search(r'status of (401|403|409|422)', c)]
check('Console', 'no unexpected console errors (deliberately provoked 401/403/409/422 responses excluded)', not unexpected, unexpected[:3])
try:
    http('/api/iot/reset', 'POST')              # leave the seeded baseline behind (the operator scan above changed stock)
except Exception as e:
    print('reset note:', type(e).__name__)
for n in names.values():                        # tidy up: deactivate the throw-away accounts
    try:
        for u in http('/api/users'):
            if u['username'] == n and u['is_active']:
                http(f"/api/users/{u['id']}", 'PATCH', {'is_active': False})
    except Exception as e:
        print('cleanup note:', type(e).__name__)
p_, f_, s_ = (sum(1 for r in results if r[2] == k) for k in ('PASS', 'FAIL', 'SKIP'))
print(f'\ntests collected: {len(results)} | passed: {p_} | failed: {f_} | skipped: {s_}')
for r in results:
    if r[2] == 'SKIP': print('  skipped:', r[0], r[1], '-', r[3])
sys.exit(1 if f_ else 0)
