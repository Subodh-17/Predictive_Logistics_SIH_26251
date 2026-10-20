#!/usr/bin/env python3
"""V7.1 browser checks against the real built frontend, real API and database: blocked-corridor explanation, map degradation (tiles unavailable),
empty/malformed/failed route responses, map resizing, 390 px layout of the scenario comparison, keyboard focus visibility, persistence across reload.

    APP_URL=... E2E_USER=<admin> E2E_PASSWORD=<password> python tests/e2e/e2e_v71_gis_resilience.py
"""
import os, re, sys
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import URL, login, http, preflight

results = []


def check(area, name, ok, detail=''):
    results.append(('PASS' if ok else 'FAIL', area, name))
    print(('PASS' if ok else 'FAIL'), f'[{area}]', name, ('· ' + str(detail)) if detail else '', flush=True)


def nav(pg, label):
    pg.locator('nav').get_by_role('button', name=label, exact=True).click(); pg.wait_for_timeout(900)


SET = "([id, v]) => { const e = document.getElementById(id); const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; s.call(e, v); e.dispatchEvent(new Event('input', {bubbles: true})) }"
if not preflight():
    sys.exit(2)
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={'width': 1440, 'height': 1000}); pg = ctx.new_page()
    errors = []
    pg.on('pageerror', lambda e: errors.append(str(e)))
    # tiles are blocked on purpose: graceful degradation
    ctx.route(re.compile(r'https://[a-z]*\.?tile\.openstreetmap\.org/.*'), lambda r: r.abort())
    login(pg)
    nav(pg, 'GIS Logistics'); pg.wait_for_selector('[data-testid=leaflet-map]'); pg.wait_for_timeout(2500)
    check('Map', 'with every tile request failing, an explanatory notice appears', pg.locator('text=tiles unavailable').count() >= 1)
    check('Map', 'locations and corridors are still drawn without tiles', pg.locator('.leaflet-interactive').count() >= 8, pg.locator('.leaflet-interactive').count())
    # resizing
    w1 = pg.evaluate("document.querySelector('.leaflet-container').getBoundingClientRect().width")
    pg.set_viewport_size({'width': 700, 'height': 900}); pg.wait_for_timeout(800)
    w2 = pg.evaluate("document.querySelector('.leaflet-container').getBoundingClientRect().width")
    pw = pg.evaluate("document.querySelector('[data-testid=leaflet-map]').getBoundingClientRect().width")
    check('Map', 'map container follows the viewport when resized (no fixed width)', w2 < w1 and abs(w2 - pw) <= 4, (round(w1), round(w2), round(pw)))
    pg.set_viewport_size({'width': 1440, 'height': 1000}); pg.wait_for_timeout(500)

    # leaving the map immediately after opening it must never throw (a deferred Leaflet resize used to run on a removed map)
    errors.clear()
    for _ in range(12):
        pg.locator('nav').get_by_role('button', name='GIS Logistics', exact=True).click()
        pg.locator('nav').get_by_role('button', name='Command Dashboard', exact=True).click()
    pg.wait_for_timeout(3000)  # allow API rate limit bucket to refill after 24 rapid navigations
    check('Map', 'opening and immediately leaving the map 12 times raises no uncaught error', not errors, errors[:1])
    nav(pg, 'GIS Logistics'); pg.wait_for_selector('[data-testid=leaflet-map]')

    # blocked corridor: maximum weather severity closes R07, the only corridor serving Base_05
    nav(pg, 'What-If Simulation'); pg.wait_for_selector('#sw')
    pg.evaluate(SET, ['sw', '100']); pg.click('button:has-text("APPLY TO ALL SCREENS")'); pg.wait_for_selector('text=SCENARIO ACTIVE', timeout=20000)
    nav(pg, 'GIS Logistics'); pg.wait_for_selector('[data-testid=leaflet-map]')
    pg.locator('tr.row', has_text='R07').first.click(); pg.wait_for_selector('[data-testid=no-feasible-route]', timeout=15000)
    msg = pg.inner_text('[data-testid=no-feasible-route]')
    check('Blocked corridor', 'no feasible route to Base_05 is stated with its reason', 'no feasible route' in msg.lower() and 'closed' in msg.lower(), msg[:90])
    api = pg.evaluate("fetch('/api/routes/compare?destination=Base_05&weather=1').then(r => r.json())")
    check('Blocked corridor', 'the page agrees with the API (no route selected, R07 ROUTE CLOSED)', api['selected'] is None and any(r['id'] == 'R07' and r['decision'] == 'ROUTE CLOSED' for r in api['routes']))
    check('Blocked corridor', 'route table marks the corridor as closed', 'ROUTE CLOSED' in pg.inner_text('main') or 'closed' in pg.inner_text('main').lower())
    nav(pg, 'What-If Simulation'); pg.get_by_role('button', name='Clear', exact=True).click() if pg.get_by_role('button', name='Clear', exact=True).count() else None

    # empty / failed / malformed responses must degrade, never crash
    errors.clear()
    ctx.route(re.compile(r'.*/api/routes(\?.*)?$'), lambda r: r.fulfill(status=200, content_type='application/json', body='[]'))
    pg.reload(); pg.wait_for_selector('[data-testid=user-name]'); nav(pg, 'GIS Logistics'); pg.wait_for_timeout(1500)
    txt = pg.inner_text('main')
    check('Resilience', 'an empty route list renders without errors or placeholder garbage', not errors and 'undefined' not in txt and 'NaN' not in txt, errors[:1])
    ctx.unroute(re.compile(r'.*/api/routes(\?.*)?$'))
    ctx.route(re.compile(r'.*/api/routes/compare.*'), lambda r: r.fulfill(status=500, content_type='application/json', body='{"code":"INTERNAL_ERROR","detail":"Unexpected server error. Quote reference abcd1234 when reporting it."}'))
    pg.reload(); pg.wait_for_selector('[data-testid=user-name]'); nav(pg, 'GIS Logistics'); pg.wait_for_timeout(800)
    pg.locator('tr.row').first.click(); pg.wait_for_timeout(1200)
    check('Resilience', 'a failing comparison call shows a generic error with its reference, not a stack trace', 'abcd1234' in pg.inner_text('main') and 'Traceback' not in pg.inner_text('main') and not errors, errors[:1])
    ctx.unroute(re.compile(r'.*/api/routes/compare.*'))
    ctx.route(re.compile(r'.*/api/routes/compare.*'), lambda r: r.fulfill(status=200, content_type='application/json', body='{"destination": "Base_01", "routes": [{"id":"RX"'))
    pg.reload(); pg.wait_for_selector('[data-testid=user-name]'); nav(pg, 'GIS Logistics'); pg.wait_for_timeout(800)
    pg.locator('tr.row').first.click(); pg.wait_for_timeout(1200)
    check('Resilience', 'a truncated (malformed) JSON response does not crash the page', not errors and pg.locator('nav').count() == 1, errors[:1])
    ctx.unroute(re.compile(r'.*/api/routes/compare.*'))

    # scenario comparison: two runs, 390 px, no horizontal overflow, visible keyboard focus
    pg.reload(); pg.wait_for_selector('[data-testid=user-name]'); nav(pg, 'What-If Simulation'); pg.wait_for_selector('#sw')
    pg.click('button:has-text("RUN SIMULATION")'); pg.wait_for_selector('text=Critical items', timeout=20000)
    pg.evaluate(SET, ['sw', '90']); pg.click('button:has-text("RUN SIMULATION")'); pg.wait_for_timeout(1500)
    pg.wait_for_selector('[data-testid=cmp-a] option:nth-child(3)', state='attached', timeout=15000)
    opts = [o.get_attribute('value') for o in pg.locator('[data-testid=cmp-a] option').all()][1:3]
    pg.select_option('[data-testid=cmp-a]', opts[0]); pg.select_option('[data-testid=cmp-b]', opts[1]); pg.wait_for_selector('[data-testid=cmp-result]', timeout=15000)
    pg.set_viewport_size({'width': 390, 'height': 844}); pg.wait_for_timeout(800)
    sw, iw = pg.evaluate('[document.documentElement.scrollWidth, window.innerWidth]')
    check('Layout 390px', 'scenario comparison with a result shows no horizontal page scroll', sw <= iw, f'scrollWidth={sw} innerWidth={iw}')
    pg.set_viewport_size({'width': 1440, 'height': 1000})
    pg.focus('[data-testid=cmp-a]'); pg.keyboard.press('Tab'); pg.keyboard.press('Shift+Tab')
    out = pg.evaluate("(() => { const s = getComputedStyle(document.activeElement); return [document.activeElement.getAttribute('data-testid'), s.outlineStyle, s.outlineWidth] })()")
    check('Keyboard', 'the focused scenario selector has a visible focus outline', out[0] == 'cmp-a' and out[1] != 'none' and out[2] != '0px', out)
    # the saved runs are real database rows
    runs = pg.evaluate("fetch('/api/simulation/runs?limit=5').then(r => r.json())")
    pg.reload(); pg.wait_for_selector('[data-testid=user-name]'); nav(pg, 'What-If Simulation'); pg.wait_for_selector('[data-testid=cmp-a]', timeout=15000)
    check('Persistence', 'saved scenarios are still offered after a reload', pg.locator('[data-testid=cmp-a] option').count() - 1 >= min(len(runs), 2))
    check('Console', 'no uncaught page errors during the whole run', not errors, errors[:2])
    b.close()
http('/api/iot/reset', 'POST')
f = sum(r[0] == 'FAIL' for r in results)
print(f'\ntests collected: {len(results)} | passed: {len(results) - f} | failed: {f} | skipped: 0')
sys.exit(1 if f else 0)
