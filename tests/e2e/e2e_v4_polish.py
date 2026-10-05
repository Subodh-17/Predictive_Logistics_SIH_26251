#!/usr/bin/env python3
"""E2E for the V4 polish pass: decision-flow strip, advisory recommendation banner, WHY THIS ROUTE?, IoT value flow,
extra What-If response lines, synthetic time label, confidence-index wording, both themes, 390 px. Separate file; the older E2E files are unchanged
except two assertions in e2e_ui_enhancements.py that were updated for the deliberate label changes (header clock, confidence index).

    APP_URL=http://localhost:8080 python tests/e2e/e2e_v4_polish.py

UI numbers are cross-checked against the backend API. Exits 2 (no tests run) if /api/health is not OK.
Prototype uses fictional synthetic logistics data and is intended for decision-support demonstration only.
"""
import json, os, re, sys, urllib.request
from collections import OrderedDict
from playwright.sync_api import sync_playwright

URL = os.environ.get('APP_URL', 'http://localhost:8080').rstrip('/')
SHOTS = os.environ.get('E2E_SHOTS', '/tmp/e2e_v4_shots'); os.makedirs(SHOTS, exist_ok=True)
SCREENS = OrderedDict([('Dashboard', 'Command Dashboard'), ('Forecast', 'Demand Forecast'), ('GIS', 'GIS Logistics'), ('Inventory', 'Inventory'), ('Simulation', 'What-If Simulation')])
results = []

def check(area, name, ok, detail=''):
    results.append((area, name, 'PASS' if ok else 'FAIL', str(detail)))
    print(('PASS' if ok else 'FAIL'), f'[{area}]', name, ('· ' + str(detail)) if detail else '', flush=True)

def api(path, method='GET', body=None):
    req = urllib.request.Request(URL + path, method=method, data=None if body is None else json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r: return json.loads(r.read())

def inr(n):                      # en-IN digit grouping, as the UI prints it
    s = str(int(round(n))); neg = s.startswith('-'); s = s.lstrip('-')
    if len(s) > 3: s = (re.sub(r'(\d)(?=(\d\d)+$)', r'\1,', s[:-3]) + ',' + s[-3:])
    return ('-' if neg else '') + s

try:
    h = api('/api/health'); ok = h['status'] == 'ok' and h['database']['connected']
except Exception as e: ok = False; print('preflight failed:', e)
if not ok: print('ENVIRONMENT NOT READY - no tests were run.'); sys.exit(2)
api('/api/iot/reset', 'POST')

with sync_playwright() as p:
    browser = p.chromium.launch(); BROWSER = f'{browser.browser_type.name} {browser.version} (headless)'
    ctx = browser.new_context(viewport={'width': 1440, 'height': 1000}); pg = ctx.new_page()
    console_err, osm, page_err, bad_api = [], [], [], []
    pg.on('console', lambda m: (osm if 'openstreetmap' in (m.location.get('url', '') + m.text) else console_err).append(m.text[:150]) if m.type == 'error' else None)
    pg.on('pageerror', lambda e: page_err.append(str(e)[:150]))
    pg.on('response', lambda r: bad_api.append((r.status, r.url)) if '/api/' in r.url and r.status >= 400 else None)
    go = lambda s: (pg.click(f'nav >> text={SCREENS[s]}'), pg.wait_for_timeout(1500))
    theme = lambda: pg.evaluate("document.documentElement.getAttribute('data-theme')")
    setr = "(el,v)=>{const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;s.call(el,v);el.dispatchEvent(new Event('input',{bubbles:true}))}"
    pg.goto(URL); pg.wait_for_selector('[data-testid=decision-flow]'); pg.wait_for_timeout(1800)

    # ---------------------------------------------------------------- 2. decision flow on the dashboard
    flow = pg.inner_text('[data-testid=decision-flow]'); dash, prio, alloc = api('/api/dashboard'), api('/api/priority'), api('/api/allocation')
    names = ['DATA', 'FORECAST', 'RISK', 'PRIORITY', 'ALLOCATION', 'ROUTE', 'DECISION']
    pos = [flow.find(f'{i + 1} · {n}') for i, n in enumerate(names)]
    check('Flow', 'Dashboard shows the 7 steps DATA → … → DECISION in order', all(x >= 0 for x in pos) and pos == sorted(pos), pos)
    k = dash['kpis']
    check('Flow', 'live values equal the backend (risk index, top priority, allocated/need)', f"{k['risk_index']}/100" in flow and f"#1 {prio[0]['location']} · {prio[0]['supply']}" in flow and f"{inr(alloc['allocated'])} of {inr(alloc['total_need'])} units" in flow, flow.replace('\n', ' ')[:200])
    check('Flow', 'states that the last step is human decision support', 'authorized personnel' in pg.inner_text('main') and 'nothing is dispatched automatically' in pg.inner_text('main'))
    brief = pg.inner_text('[aria-label="Command briefing"]')
    check('Flow', 'briefing still shows risk, critical locations, shortages, capacity, alerts and 3 actions', all(t in brief for t in ['OVERALL RISK', 'CRITICAL LOCATIONS', 'PREDICTED SHORTAGES', 'TRANSPORT CAPACITY', 'ACTIVE ALERTS', 'TOP 3 RECOMMENDED ACTIONS']))
    check('Flow', 'compact: the flow card is shorter than 260 px on desktop', pg.locator('[data-testid=decision-flow]').bounding_box()['height'] < 260, pg.locator('[data-testid=decision-flow]').bounding_box()['height'])

    # ---------------------------------------------------------------- 3. why-this-recommendation banner
    wb = pg.inner_text('[data-testid=why-recommendation]'); row = next(r for r in alloc['rows'] if r['location'] == prio[0]['location'] and r['supply'] == prio[0]['supply'])
    legs = row['legs']; corridors = OrderedDict()
    for l in legs: corridors[(l['depot'], l['route'])] = 1
    check('Why', 'recommendation banner names source depot → destination via route (from the allocation legs)', all(f"{d} → {prio[0]['location']} via {r}" in wb for d, r in corridors) and bool(corridors), wb[:140].replace('\n', ' '))
    check('Why', 'banner says advisory / not an autonomous command', 'not an autonomous command' in wb and 'authorized personnel' in wb)

    # ---------------------------------------------------------------- 7. time label
    hd = pg.inner_text('main > div:first-child')
    check('Header', 'SIMULATION TIME · <date> and DATA · SYNTHETIC; no HH:MMZ timestamp', bool(re.search(r'SIMULATION TIME · \d{1,2} [A-Z]{3} 2026', hd)) and 'DATA · SYNTHETIC' in hd and not re.search(r'\d\d:\d\dZ', hd), hd[:160].replace('\n', ' '))
    check('Header', 'synthetic-data disclaimer footer visible', pg.locator('text=Prototype uses fictional synthetic logistics data').first.is_visible())

    # ---------------------------------------------------------------- 4. GIS: WHY THIS ROUTE?
    go('GIS'); pg.wait_for_selector('[data-testid=route-selected]'); pg.wait_for_timeout(1500)
    cmp_ = api('/api/routes/compare?destination=Base_04'); sel = next(r for r in cmp_['routes'] if r['id'] == cmp_['selected']); alts = [r for r in cmp_['routes'] if r['id'] != cmp_['selected']]
    body = pg.inner_text('body')
    check('GIS', 'WHY THIS ROUTE? heading above the backend reason', 'WHY THIS ROUTE?' in pg.inner_text('[data-testid=why-this-route]') and cmp_['reason'][:60] in pg.inner_text('[data-testid=route-reason]'))
    check('GIS', 'selected route, ETA, terrain/road/weather/total risk, capacity, alternatives all shown', all(t in body for t in ['TERRAIN RISK', 'ROAD CONDITION', 'WEATHER RISK', 'TOTAL ROUTE RISK', 'VEHICLE CAPACITY', 'ALTERNATIVES']) and f"{round(sel['risk'] * 100)}/100" in body and f"ETA {sel['eta_h']:.1f} h" in body)
    check('GIS', 'ALTERNATIVES tile lists the backend alternatives', all(a['id'] in pg.inner_text('main') for a in alts) and bool(alts), [a['id'] for a in alts])

    # ---------------------------------------------------------------- 1. confidence index
    go('Forecast'); pg.wait_for_selector('[data-testid=confidence-value]'); pg.wait_for_timeout(1200)
    cv = api('/api/forecast?horizon=14')['confidence']; ft = pg.inner_text('main')
    check('Confidence', 'no "NN% HIGH" style display remains', not re.search(r'\b\d{1,3}%\s*(HIGH|MODERATE|LOW|MEDIUM)\b', ft) and not re.search(r'(HIGH|MODERATE|LOW|MEDIUM)\s*·\s*\d{1,3}%', ft), None)
    check('Confidence', 'KPI shows V/100 and the card shows "Confidence Index: V/100 — LABEL"', f"{cv['value']}/100" in pg.inner_text('main') and f"Confidence Index: {cv['value']}/100 — {cv['label']}" in ft, cv)
    check('Confidence', 'tooltip text present on the KPI and the card', pg.locator('[data-testid=info-tip]').count() >= 2 and all('not a probability of forecast correctness' in (pg.locator('[data-testid=info-tip]').nth(i).get_attribute('aria-label') or '') for i in range(2)))
    pg.locator('[data-testid=confidence-value] [data-testid=info-tip]').focus(); pg.wait_for_timeout(200)
    check('Confidence', 'keyboard focus reveals the tooltip', pg.locator('[data-testid=confidence-value] [role=tooltip]').is_visible())

    # ---------------------------------------------------------------- 5. IoT value flow
    go('Inventory'); pg.wait_for_selector('[data-testid=iot-value-flow]'); vf = pg.inner_text('[data-testid=iot-value-flow]')
    seq = ['ESP32 / RFID TELEMETRY', 'API', 'PostgreSQL', 'INVENTORY / RISK', 'DECISION SUPPORT']; ps = [vf.find(x) for x in seq]
    check('IoT', 'value flow ESP32/RFID TELEMETRY → API → PostgreSQL → INVENTORY/RISK → DECISION SUPPORT', all(x >= 0 for x in ps) and ps == sorted(ps), ps)
    check('IoT', 'states telemetry is simulated and needs no hardware', 'simulated' in vf.lower() and 'no ESP32 or RFID hardware' in vf)

    # ---------------------------------------------------------------- 6. what-if recommended response
    go('Simulation'); pg.wait_for_selector('text=SCENARIO CONTROLS')
    for i, v in (('sd', 30), ('sw', 100), ('sr', 100), ('sv', 40)): pg.eval_on_selector('#' + i, setr, str(v))
    pg.click('button:has-text("RUN SIMULATION")'); pg.wait_for_selector('[data-testid=response-list]', timeout=20000); pg.wait_for_timeout(1500)
    sim = api('/api/simulation/run', 'POST', {'demand_increase': .3, 'weather_severity': 1, 'road_degradation': 1, 'vehicle_availability': .6})
    rt = pg.inner_text('[data-testid=response-list]'); n = pg.locator('[data-testid=response-list] > li').count(); rise = sim['after']['mean_route_risk'] - sim['before']['mean_route_risk']
    check('Response', 'RECOMMENDED RESPONSE heading + still 3-7 points', 'RECOMMENDED RESPONSE' in pg.inner_text('main') and 3 <= n <= 7, n)
    check('Response', 'route-risk line appears iff the backend mean route risk rose by >= 1', ('prefer the feasible route with the lowest combined' in rt) == (rise >= 1), f'rise {rise:.1f}')
    check('Response', 'rerun note points to APPLY TO ALL SCREENS', 'APPLY TO ALL SCREENS to rerun priority, allocation and route selection' in pg.inner_text('main'))
    pg.click('button:has-text("RESET")'); pg.wait_for_timeout(500)

    # ---------------------------------------------------------------- 8. themes (persist, both render, mobile 390 px)
    for th in ('dark', 'light'):
        if theme() != th: pg.click('[data-testid=theme-toggle]'); pg.wait_for_timeout(400)
        check('Theme', f'{th} active and persisted in localStorage', theme() == th and (pg.evaluate("localStorage.getItem('plsd-theme')") == th or (th == 'dark' and pg.evaluate("localStorage.getItem('plsd-theme')") is None)))
        pg.set_viewport_size({'width': 1440, 'height': 1000}); go('Dashboard'); pg.wait_for_selector('[data-testid=decision-flow]')
        check('Theme', f'{th}: decision flow visible and readable', pg.locator('[data-testid=decision-flow]').is_visible())
        pg.screenshot(path=f'{SHOTS}/{th}_dashboard.png')
        pg.set_viewport_size({'width': 390, 'height': 844}); pg.wait_for_timeout(500)
        for s in SCREENS:
            go(s); pg.wait_for_timeout(1300); w = pg.evaluate('document.documentElement.scrollWidth')
            check('Mobile 390px', f'{th}/{s}: no horizontal page scroll', w <= 392, f'scrollWidth={w}')
    pg.set_viewport_size({'width': 1440, 'height': 1000})
    if theme() != 'dark': pg.click('[data-testid=theme-toggle]')

    check('Console', 'no uncaught page errors', not page_err, page_err[:2])
    check('Console', 'no failed /api calls', not bad_api, bad_api[:3])
    check('Console', 'no console errors other than blocked OSM tile loads', not console_err, f'unexpected={console_err[:3]} | OSM tile errors={len(osm)}')
    browser.close()
api('/api/iot/reset', 'POST')
P = [r for r in results if r[2] == 'PASS']; F = [r for r in results if r[2] == 'FAIL']
print('\n================ V4 POLISH E2E SUMMARY ================')
print(f'base URL: {URL} | browser: {BROWSER}\ntests collected: {len(results)} | passed: {len(P)} | failed: {len(F)} | skipped: 0')
for r in F: print('FAILED:', r[0], '|', r[1], '|', r[3])
sys.exit(0 if not F else 1)
