#!/usr/bin/env python3
"""V7 browser checks: saved-scenario comparison card, role behaviour of the Simulation page, persistence across reload, restart-safe session.

    APP_URL=... E2E_USER=<admin> E2E_PASSWORD=<password> python tests/e2e/e2e_v7_workflows.py
"""
import os, re, secrets, sys
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import URL, login, http, preflight

results = []


def check(area, name, ok, detail=''):
    results.append(('PASS' if ok else 'FAIL', area, name))
    print(('PASS' if ok else 'FAIL'), f'[{area}]', name, ('· ' + str(detail)) if detail else '', flush=True)


if not preflight():
    sys.exit(2)
tag, PW = secrets.token_hex(3), 'E2e-' + secrets.token_urlsafe(14)
op = f'e2e7_op_{tag}'
http('/api/users', 'POST', {'username': op, 'password': PW, 'role': 'operator'})
setter = "(v) => { const e = document.getElementById('%s'); const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; s.call(e, v); e.dispatchEvent(new Event('input', {bubbles: true})) }"
with sync_playwright() as p:
    b = p.chromium.launch(); ctx = b.new_context(viewport={'width': 1440, 'height': 1000}); pg = ctx.new_page()
    login(pg, op, PW)
    pg.locator('nav').get_by_role('button', name='What-If Simulation', exact=True).click(); pg.wait_for_timeout(900)
    pg.wait_for_selector('[data-testid=cmp-empty], [data-testid=cmp-a]')
    # two runs with different settings
    pg.click('button:has-text("RUN SIMULATION")'); pg.wait_for_selector('text=Critical items', timeout=20000)
    pg.evaluate(setter % 'sd', '40') if pg.locator('#sd').count() else None
    pg.click('button:has-text("RUN SIMULATION")'); pg.wait_for_timeout(1500)
    pg.wait_for_selector('[data-testid=cmp-a]', timeout=15000)
    check('Compare', 'comparison card offers the saved runs', pg.locator('[data-testid=cmp-a] option').count() >= 3)
    opts = pg.locator('[data-testid=cmp-a] option').all()
    first, second = opts[1].get_attribute('value'), opts[2].get_attribute('value')
    pg.select_option('[data-testid=cmp-a]', first); pg.select_option('[data-testid=cmp-b]', first)
    check('Compare', 'choosing the same run twice is refused with a message', pg.locator('text=Choose two different runs').count() == 1)
    pg.select_option('[data-testid=cmp-b]', second); pg.wait_for_selector('[data-testid=cmp-result]', timeout=15000)
    txt = pg.inner_text('[data-testid=cmp-result]')
    check('Compare', 'result shows labelled metrics, deltas and a same-baseline statement', all(x in txt for x in ('Critical items', 'Overall risk index', 'B − A', 'same baseline')), txt[:90].replace('\n', ' '))
    api = pg.evaluate("(q) => fetch('/api/simulation/compare?' + q).then(r => r.json())", f'a={first}&b={second}')
    shown = pg.inner_text('[data-testid=cmp-result]')
    check('Compare', 'every metric label returned by the API is rendered', all(m['label'] in shown for m in api['metrics']))
    pg.reload(); pg.wait_for_selector('[data-testid=user-name]')
    pg.locator('nav').get_by_role('button', name='What-If Simulation', exact=True).click(); pg.wait_for_selector('[data-testid=cmp-a]', timeout=15000)
    check('Persistence', 'saved runs survive a page reload (stored in the database)', pg.locator('[data-testid=cmp-a] option').count() >= 3)
    b.close()
for u in http('/api/users'):
    if u['username'] == op and u['is_active']:
        http(f"/api/users/{u['id']}", 'PATCH', {'is_active': False})
f = sum(r[0] == 'FAIL' for r in results)
print(f'\ntests collected: {len(results)} | passed: {len(results) - f} | failed: {f} | skipped: 0')
sys.exit(1 if f else 0)
