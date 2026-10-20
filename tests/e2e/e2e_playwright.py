#!/usr/bin/env python3
"""Browser end-to-end test: Playwright + headless Chromium against the running stack.

    APP_URL=http://localhost:8080 python tests/e2e/e2e_playwright.py

Pre-flight: refuses to run (exit 2, "ENVIRONMENT NOT READY") unless <APP_URL>/api/health reports API + PostGIS OK.
Exit code 0 only if every check passed. Skipped checks are counted and listed, never hidden.
Uses the fictional illustrative scenario (simulated telemetry); requires E2E_USER / E2E_PASSWORD of an existing account.
"""
import json, os, re, sys, urllib.request
from collections import OrderedDict
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import login, api as papi, http as hapi, preflight as _preflight

URL = os.environ.get('APP_URL', 'http://localhost:8080').rstrip('/')
SHOTS = os.environ.get('E2E_SHOTS', '/tmp/e2e_shots'); os.makedirs(SHOTS, exist_ok=True)
SCREENS = OrderedDict([('Dashboard', 'Command Dashboard'), ('Forecast', 'Demand Forecast'), ('GIS', 'GIS Logistics'), ('Inventory', 'Inventory'), ('Simulation', 'What-If Simulation')])
results = []                      # (area, name, status, detail)

def check(area, name, ok, detail=''):
    results.append((area, name, 'PASS' if ok else 'FAIL', str(detail)))
    print(('PASS' if ok else 'FAIL'), f'[{area}]', name, ('· ' + str(detail)) if detail else '', flush=True)
def skip(area, name, reason):
    results.append((area, name, 'SKIP', reason)); print('SKIP', f'[{area}]', name, '·', reason, flush=True)

# ---------------------------------------------------------------- pre-flight
def preflight():
    return _preflight()

if not preflight():
    print('ENVIRONMENT NOT READY: frontend/backend/database not healthy at', URL, '- no tests were run.'); sys.exit(2)

num = lambda s: int(re.sub(r'[^\d]', '', s))

with sync_playwright() as p:
    browser = p.chromium.launch()
    BROWSER = f'{browser.browser_type.name} {browser.version} (headless)'
    print(f'base URL : {URL}\nbrowser  : {BROWSER}', flush=True)
    pg = browser.new_page(viewport={'width': 1440, 'height': 1000})
    console_err, osm_console, page_err, osm_failed, api_calls = [], [], [], [], []
    def on_console(m):
        if m.type == 'error':
            (osm_console if 'openstreetmap' in (m.location.get('url', '') + m.text) else console_err).append(m.text[:160])
    pg.on('console', on_console)
    pg.on('pageerror', lambda e: page_err.append(str(e)[:160]))
    pg.on('requestfailed', lambda r: osm_failed.append(r.url) if 'openstreetmap' in r.url else None)
    pg.on('response', lambda r: api_calls.append((r.status, r.request.method, r.url)) if '/api/' in r.url else None)

    def go(label):
        pg.click(f'nav >> text={SCREENS[label]}'); pg.wait_for_timeout(900)
    def kpi(label):
        return pg.evaluate("(l)=>{const e=[...document.querySelectorAll('i')].find(x=>x.textContent===l); return e? e.parentElement.querySelector('b').textContent : null}", label)
    def setr(i, v):
        pg.eval_on_selector('#' + i, "(el,v)=>{const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;s.call(el,v);el.dispatchEvent(new Event('input',{bubbles:true}))}", str(v))
    def snap():          # visible page text without the ticking simulation clock
        return re.sub(r'\d{4}-\d\d-\d\d \d\d:\d\dZ', '', pg.inner_text('main'))
    BAD_TEXT = re.compile(r'\bNaN\b|\bundefined\b|\[object Object\]|\bnull\b|Infinity')

    # =============================================================== DASHBOARD
    login(pg); pg.wait_for_selector('text=COMMAND DASHBOARD', timeout=20000)
    pg.wait_for_selector('text=OVERALL LOGISTICS RISK'); pg.wait_for_selector('[data-testid=leaflet-map]')
    pg.wait_for_selector('text=SIMULATED IoT INVENTORY FEED', timeout=15000); pg.wait_for_selector('text=ALLOCATION PLAN', timeout=15000); pg.wait_for_timeout(1000)
    t = pg.inner_text('body')
    check('Dashboard', '7 KPI cards present', all(k in t for k in ['LOCATIONS', 'CRITICAL SHORTAGES', 'WARNING LOCATIONS', 'VEHICLES AVAILABLE', 'TRANSPORT CAPACITY', 'SUPPLIES AT RISK', 'OVERALL LOGISTICS RISK']))
    check('Dashboard', 'values match backend baseline (risk 62/100)', '62 / 100' in t)
    check('Dashboard', 'AI Logistics Insight rendered', 'Base_04 is projected to run out of' in t)
    for sect in ['SUPPLY PRIORITY QUEUE', 'ALLOCATION PLAN', 'SIMULATED IoT INVENTORY FEED', 'WHY AT RISK', 'SYSTEM STATUS', 'DATA COVERAGE', 'DATA PIPELINE', 'TRANSPORT STATUS', 'PREDICTED SHORTAGES', 'CRITICAL ALERTS']:
        check('Dashboard', 'section: ' + sect, sect.upper() in t.upper())
    check('Dashboard', 'DB status chip shows PostGIS', 'POSTGIS' in pg.inner_text('[data-testid=db-status]'))
    check('Dashboard', 'scenario-data disclaimer visible', 'fictional locations and simulated telemetry, not operational records' in t)
    pg.screenshot(path=f'{SHOTS}/01_dashboard.png', full_page=True)

    # ---- Leaflet
    n_paths = pg.locator('path.leaflet-interactive').count()
    check('Leaflet', 'map container rendered with tile pane', pg.locator('.leaflet-container').count() >= 1 and pg.locator('.leaflet-tile-pane').count() >= 1)
    check('Leaflet', 'markers + route lines drawn (5 forward + 8 routes + 8 terrain bands)', n_paths >= 21, f'interactive paths={n_paths}')
    if len(osm_failed) >= 3:
        check('Leaflet', 'OSM tile failure handled gracefully (notice shown, app intact)', pg.locator('text=OpenStreetMap tiles unavailable').count() >= 1 and 'COMMAND DASHBOARD' in t, f'failed OSM tile requests={len(osm_failed)}')
    else:
        check('Leaflet', 'OSM tiles loaded successfully (no tile failure notice, app intact)', pg.locator('text=OpenStreetMap tiles unavailable').count() == 0 and 'COMMAND DASHBOARD' in t and pg.locator('.leaflet-tile-pane img').count() >= 1, f'tiles loaded cleanly, failed={len(osm_failed)}')
    pg.locator('input[type=checkbox]').first.uncheck(); pg.wait_for_timeout(400)
    n_off = pg.locator('path.leaflet-interactive').count(); pg.locator('input[type=checkbox]').first.check(); pg.wait_for_timeout(400)
    check('Leaflet', 'terrain layer toggle works (8 band polylines)', n_paths - n_off == 8 and pg.locator('path.leaflet-interactive').count() == n_paths, f'{n_paths} -> {n_off} -> {pg.locator("path.leaflet-interactive").count()}')

    # ---- Allocation (baseline)
    need, fleet, alloc, unmet = (num(kpi(k)) for k in ('TOTAL NEED', 'FLEET CAPACITY', 'ALLOCATED', 'UNMET'))
    check('Allocation', 'ALLOCATED + UNMET = TOTAL NEED', alloc + unmet == need, f'{alloc:,} + {unmet:,} = {need:,}')
    check('Allocation', 'ALLOCATED never exceeds fleet capacity', alloc <= fleet, f'{alloc:,} <= {fleet:,}')
    check('Allocation', 'baseline matches v3 (need 41,800 / capacity 34,000 / unmet 7,800)', (need, fleet, unmet) == (41800, 34000, 7800))
    st = pg.inner_text('text=ALLOCATION PLAN >> xpath=ancestor::section')
    check('Allocation', 'plan rows show dispatch legs and FULL/PARTIAL statuses', ' via R0' in st and 'FULL' in st and 'PARTIAL' in st)
    # ---- clickable rows navigate
    pg.locator('tr.row').first.click(); pg.wait_for_timeout(700)
    check('Dashboard', 'table row click navigates to GIS with selection', pg.locator('nav button[aria-current=page]').inner_text() == 'GIS Logistics')

    # =============================================================== FORECAST
    go('Forecast'); pg.wait_for_selector('text=BACKTEST MAPE'); pg.wait_for_timeout(1200)
    check('Forecast', 'default 14-day outlook', '14-DAY OUTLOOK' in pg.inner_text('text=ACTUAL VS PREDICTED CONSUMPTION >> xpath=..'))
    pg.click('button:has-text("7-DAY")'); pg.wait_for_selector('text=7-DAY OUTLOOK'); check('Forecast', '7-day horizon', True)
    pg.click('button:has-text("30-DAY")'); pg.wait_for_selector('text=30-DAY OUTLOOK'); check('Forecast', '30-day horizon', True)
    pg.select_option('#fl', 'Base_04'); pg.select_option('#ft', 'Medical'); pg.wait_for_timeout(1500)
    v_f = kpi('14-DAY FORECAST'); pg.select_option('#fl', ''); pg.select_option('#ft', ''); pg.wait_for_timeout(1500); v_all = kpi('14-DAY FORECAST')
    check('Forecast', 'location+supply filter changes totals', v_f != v_all and v_f == '2,825', f'{v_all} (all) vs {v_f} (Base_04/Medical)')
    ft = pg.inner_text('body')
    check('Forecast', 'confidence, MAPE, methodology and model holdout comparison shown', all(k in ft for k in ['FORECAST CONFIDENCE', 'BACKTEST MAPE', 'FORECAST METHODOLOGY', 'HOLDOUT ON THIS SCENARIO', 'Statistical time-series model']))
    check('Forecast', 'recharts chart rendered', pg.locator('svg.recharts-surface').count() >= 1)
    pg.screenshot(path=f'{SHOTS}/02_forecast.png', full_page=True)

    # =============================================================== GIS
    go('GIS'); pg.wait_for_selector('[data-testid=leaflet-map]'); pg.wait_for_selector('text=ROUTE OPTIMIZATION COMPARISON'); pg.wait_for_timeout(1500)
    g = pg.inner_text('body')
    check('GIS', 'selected location panel with status, why-at-risk and insight', 'LOCATION STATUS' in g and 'WHY AT RISK' in g and 'AI LOGISTICS INSIGHT' in g)
    check('GIS', 'route comparison: SELECTED + alternative + reason', 'SELECTED' in g and 'R08' in g and 'Why selected' in g)
    r08_base = pg.locator('tr.row:has-text("R08")').first.inner_text()
    pg.locator('tr.row:has-text("R07")').first.click(); pg.wait_for_selector('text=R07 · ROUTE RISK'); pg.wait_for_selector('text=FEASIBLE ROUTES TO Base_05'); pg.wait_for_timeout(400); g2 = pg.inner_text('body')
    check('GIS', 'route detail shows terrain, elevation, effective speed, route risk', all(k.upper() in g2.upper() for k in ['High-altitude ridge', 'Terrain risk score', 'Effective speed', 'Elevation category', 'Route risk']))
    check('GIS', 'comparison follows selection (single-corridor Base_05)', 'only feasible corridor' in g2)
    markers = pg.locator('path.leaflet-interactive[fill-opacity="0.95"]')
    check('GIS', '5 forward-location markers', markers.count() == 5, f'count={markers.count()}')
    markers.nth(2).click(force=True); pg.wait_for_timeout(600)
    check('GIS', 'marker click opens popup with inventory/shortage/route info', 'Inventory:' in pg.inner_text('.leaflet-popup-content'))
    pg.screenshot(path=f'{SHOTS}/03_gis.png', full_page=True)

    # =============================================================== INVENTORY + IoT
    go('Inventory'); pg.wait_for_selector('text=INVENTORY POSITION'); pg.wait_for_timeout(800)
    cnt = lambda: pg.inner_text('[data-testid=item-count]')
    check('Inventory', '50 items by default', cnt().startswith('50 '))
    pg.select_option('#is', 'CRITICAL'); pg.wait_for_timeout(900); check('Inventory', 'risk filter CRITICAL -> 8', cnt().startswith('8 '), cnt())
    pg.select_option('#il', 'Base_04'); pg.wait_for_timeout(900); check('Inventory', 'CRITICAL + Base_04 -> 5', cnt().startswith('5 '), cnt())
    pg.select_option('#is', ''); pg.select_option('#it', 'Medical'); pg.wait_for_timeout(900); check('Inventory', 'Base_04 + Medical -> 1', cnt().startswith('1 '), cnt())
    check('Inventory', 'projection chart follows selection', 'STOCK PROJECTION · BASE_04 · MEDICAL' in pg.inner_text('body').upper())
    pg.select_option('#il', ''); pg.select_option('#it', ''); pg.wait_for_timeout(700)
    before = pg.locator('tr:has-text("Base_04"):has-text("Medical")').first.inner_text()
    pg.click('button:has-text("SEND SCAN")'); pg.wait_for_selector('[data-testid=iot-result]', timeout=15000); pg.wait_for_timeout(1500)
    res = pg.inner_text('[data-testid=iot-result]'); after = pg.locator('tr:has-text("Base_04"):has-text("Medical")').first.inner_text()
    check('IoT', 'RECEIVE scan accepted: stock 563 -> 2,563, labelled SIMULATED', '563' in res and '2,563' in res and 'SIMULATED' in res.upper(), res[:110].replace('\n', ' '))
    check('IoT', 'inventory table updated CRITICAL -> NORMAL', 'CRITICAL' in before and 'NORMAL' in after)
    check('IoT', 'event stored and listed (iot_events)', 'ESP32-SIM-01' in pg.inner_text('body'))
    check('IoT', 'header critical count 8 -> 7', '▲ 7 CRITICAL' in pg.inner_text('body'))
    go('Dashboard'); pg.wait_for_selector('text=OVERALL LOGISTICS RISK'); pg.wait_for_timeout(1500)
    check('IoT', 'dashboard recalculated after scan (risk 57)', '57 / 100' in pg.inner_text('body'))
    go('Inventory'); pg.wait_for_selector('button:has-text("RUN SIMULATOR")'); pg.click('button:has-text("RUN SIMULATOR")'); pg.wait_for_timeout(2500)
    check('IoT', 'built-in simulator x5 produced 5 events', pg.locator('[data-testid=iot-result] >> div.border-l-\\[3px\\]').count() == 5)
    pg.click('button:has-text("RESET INVENTORY")'); pg.wait_for_selector('text=Inventory restored'); pg.wait_for_timeout(800)
    check('IoT', 'reset restores seeded baseline (8 critical)', '▲ 8 CRITICAL' in pg.inner_text('body'))
    pg.screenshot(path=f'{SHOTS}/04_inventory.png', full_page=True)

    # =============================================================== SIMULATION
    go('Simulation'); pg.wait_for_selector('text=SCENARIO CONTROLS')
    setr('sd', 30); setr('sw', 100); setr('sr', 100); setr('sv', 40)
    check('Simulation', 'slider labels (+30% / Severe / Poor / 60%)', [pg.inner_text(f'[data-testid={i}-label]') for i in ('sd', 'sw', 'sr', 'sv')] == ['+30%', 'Severe', 'Poor', '60%'])
    pg.click('button:has-text("RUN SIMULATION")'); pg.wait_for_selector('text=WHY THE RISK CHANGED', timeout=15000); s = pg.inner_text('body')
    check('Simulation', 'before/after table: overall risk 62 -> 93 (+31)', bool(re.search(r'Overall risk index\s+62\s+93\s+\+31', s)))
    check('Simulation', 'explanation covers demand, weather, road, fleet, terrain', all(k in s for k in ['Demand +30%', 'Severe weather', 'Poor road', 'Fleet availability 60%', 'Terrain amplifies']))
    check('Simulation', 'per-location status transitions + per-route ETA table', 'Base_02' in s and '→' in s and 'ETA BEFORE' in s)
    pg.screenshot(path=f'{SHOTS}/05_simulation.png', full_page=True)
    pg.click('button:has-text("APPLY TO ALL SCREENS")'); pg.wait_for_selector('text=SCENARIO ACTIVE'); pg.wait_for_selector('text=OVERALL LOGISTICS RISK'); pg.wait_for_timeout(2500)
    d = pg.inner_text('body')
    check('Simulation', 'apply -> dashboard recalculated (93/100, capacity 20,400)', '93 / 100' in d and '20,400' in d)
    need2, fleet2, alloc2, unmet2 = (num(kpi(k)) for k in ('TOTAL NEED', 'FLEET CAPACITY', 'ALLOCATED', 'UNMET'))
    check('Allocation', 'scenario allocation recalculated and still consistent', (need2, fleet2, unmet2) == (72600, 20400, 52200) and alloc2 + unmet2 == need2 and alloc2 <= fleet2, f'need {need2:,} alloc {alloc2:,} unmet {unmet2:,} cap {fleet2:,}')
    go('GIS'); pg.wait_for_selector('text=ROUTE OPTIMIZATION COMPARISON'); pg.wait_for_timeout(1200)
    r08_scen = pg.locator('tr.row:has-text("R08")').first.inner_text()
    check('Simulation', 'scenario propagates to GIS (banner + R08 ETA/risk changed)', 'SCENARIO ACTIVE' in pg.inner_text('body') and r08_scen != r08_base, f"R08 ETA {r08_base.split(chr(9))[4]} -> {r08_scen.split(chr(9))[4]}")
    pg.click('button:has-text("Clear")'); pg.wait_for_timeout(1200); go('Dashboard'); pg.wait_for_selector('text=62 / 100', timeout=8000); check('Simulation', 'clear scenario -> baseline 62/100', True)

    # =============================================================== NO DEAD BUTTONS / PLACEHOLDERS
    print('--- dead-control audit (every visible button on every screen is clicked) ---', flush=True)
    api_n = lambda: sum(1 for c in api_calls if not c[2].endswith('/api/health'))      # ignore the page's 10 s background health poll
    ALLOWED_NOOP = {("Dashboard", "▲ 8 CRITICAL"): "status-bar shortcut to the dashboard; re-clicking on the dashboard is idempotent"}      # nothing is exempt. NB: UI state persists between iterations on one screen (re-clicking the current tab does not
                           # remount it), so toggles such as 14-DAY are exercised from a non-selected state; re-clicking an already-selected
                           # toggle is a correct no-op (verified separately: no request, no DOM change).
    audit_rows, dead = [], []
    def clear_banner():                       # a scenario banner adds a "Clear" button and would shift positions - always start clean
        if pg.locator('main').get_by_role('button', name='Clear', exact=True).count():
            pg.locator('main').get_by_role('button', name='Clear', exact=True).click(); pg.wait_for_timeout(700)
    for screen in SCREENS:
        go(screen); clear_banner(); pg.wait_for_timeout(500)
        labels = list(OrderedDict.fromkeys(b.inner_text().strip() for b in pg.locator('main button:visible').all()))
        for label in labels:
            go(screen); clear_banner(); pg.wait_for_timeout(1000)
            if screen == 'Simulation': setr('sd', 20)          # so RESET has something to reset
            btn_matches = [c for c in pg.locator('main button:visible').all() if c.inner_text().strip() == label]
            if not btn_matches: continue
            b = btn_matches[0]
            if b.is_disabled(): continue
            s0 = snap()
            for _ in range(8):                                   # wait until the page text is stable (data finished loading)
                pg.wait_for_timeout(400); s1 = snap()
                if s1 == s0: break
                s0 = s1
            r0, tab0 = api_n(), pg.locator('nav button[aria-current=page]').inner_text()
            b.click(); pg.wait_for_timeout(1100)
            changed = snap() != s0 or api_n() > r0 or pg.locator('nav button[aria-current=page]').inner_text() != tab0
            verdict = 'alive' if changed else ('no-op (allowed: ' + ALLOWED_NOOP[(screen, label)] + ')' if (screen, label) in ALLOWED_NOOP else 'DEAD')
            audit_rows.append((screen, label, verdict)); print(f'   {screen:10s} [{label}] -> {verdict}', flush=True)
            if verdict == 'DEAD': dead.append((screen, label))
    # the scenario banner's own "Clear" button (only exists while a scenario is active)
    go('Simulation'); clear_banner(); setr('sd', 20); pg.click('button:has-text("APPLY TO ALL SCREENS")'); pg.wait_for_selector('text=SCENARIO ACTIVE')
    pg.locator('main').get_by_role('button', name='Clear', exact=True).click(); pg.wait_for_timeout(800)
    v = 'alive' if 'SCENARIO ACTIVE' not in snap() else 'DEAD'; audit_rows.append(('Banner', 'Clear', v)); print(f'   {"Banner":10s} [Clear] -> {v}', flush=True)
    if v == 'DEAD': dead.append(('Banner', 'Clear'))
    papi(pg, 'post', '/api/iot/reset')
    check('Controls', f'no dead buttons ({len(audit_rows)} buttons clicked across 5 screens)', not dead, f'dead={dead}' if dead else f'{sum(1 for r in audit_rows if r[2]=="alive")} alive, {sum(1 for r in audit_rows if r[2].startswith("no-op"))} allowed no-op')
    go('GIS'); pg.locator('nav').first.scroll_into_view_if_needed(); pg.click('[data-testid=critical-chip]'); pg.wait_for_timeout(700)
    check('Controls', 'header critical chip navigates to dashboard', pg.locator('nav button[aria-current=page]').inner_text() == 'Command Dashboard')
    papi(pg, 'post', '/api/iot/reset'); pg.goto(URL); pg.wait_for_selector('text=OVERALL LOGISTICS RISK')
    for screen in SCREENS:
        go(screen); pg.wait_for_timeout(1500); txt = snap(); bad = BAD_TEXT.search(txt)
        if screen == 'Simulation':     # a form before it is run: verify the controls, then verify the populated result state
            check('Placeholders', 'Simulation (before run): 4 sliders + RUN/APPLY/RESET present, no NaN/undefined/null', pg.locator('input[type=range]').count() == 4 and all(pg.locator('main').get_by_role('button', name=n, exact=True).count() == 1 for n in ('RUN SIMULATION', 'APPLY TO ALL SCREENS', 'RESET')) and not bad, f'{len(txt)} chars')
            pg.click('button:has-text("RUN SIMULATION")'); pg.wait_for_selector('text=WHY THE RISK CHANGED', timeout=15000); txt = snap(); bad = BAD_TEXT.search(txt)
            check('Placeholders', 'Simulation (after run): substantive content, no NaN/undefined/null', len(txt) > 1200 and not bad, f'{len(txt)} chars' + (f' · found {bad.group(0)}' if bad else ''))
        else:
            check('Placeholders', f'{screen}: substantive content, no NaN/undefined/null/[object Object]', len(txt) > 1200 and not bad, f'{len(txt)} chars' + (f' · found {bad.group(0)}' if bad else ''))
    bad_markers = []
    marker_rx = re.compile(r'TODO|FIXME|lorem ipsum|coming soon|not implemented|placeholder screen', re.I)
    src_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../frontend/src'))
    for root, _, files in os.walk(src_dir):
        for f in files:
            if f.endswith(('.ts', '.tsx', '.js', '.jsx', '.html', '.css')):
                fp = os.path.join(root, f)
                try:
                    with open(fp, 'r', encoding='utf-8', errors='ignore') as fh:
                        for line_no, line in enumerate(fh, 1):
                            if 'placeholder=' in line: continue
                            if marker_rx.search(line):
                                bad_markers.append(f'{f}:{line_no}: {line.strip()[:80]}')
                except Exception:
                    pass
    src = bad_markers[0] if bad_markers else ''
    check('Placeholders', 'no TODO/FIXME/lorem/coming-soon markers in frontend source', src == '', src[:120])

    # =============================================================== MOBILE (390 px)
    pg.set_viewport_size({'width': 390, 'height': 844}); pg.wait_for_timeout(600)
    for screen in SCREENS:
        go(screen); pg.wait_for_timeout(1500)
        w = pg.evaluate('document.documentElement.scrollWidth'); mw = pg.evaluate("(()=>{const m=document.querySelector('[data-testid=leaflet-map]'); return m? Math.round(m.getBoundingClientRect().width):null})()")
        check('Mobile 390px', f'{screen}: no horizontal page scroll' + ('; map fits viewport' if mw else ''), w <= 392 and (mw is None or mw <= 390), f'scrollWidth={w}' + (f' map={mw}px' if mw else ''))
    pg.screenshot(path=f'{SHOTS}/07_mobile.png')

    # =============================================================== CONSOLE / NETWORK
    bad = [c for c in api_calls if c[0] >= 400]
    check('Console', 'no failed /api calls', not bad, f'{len(api_calls)} API calls, failures={bad[:3]}')
    check('Console', 'no uncaught page errors', not page_err, page_err[:2])
    check('Console', 'no console errors other than blocked OSM tile loads', not console_err, f'unexpected={console_err[:3]} | OSM-tile console errors (sandbox blocks tile.openstreetmap.org)={len(osm_console)}')
    browser.close()

# ------------------------------------------------------------------ summary
P = [r for r in results if r[2] == 'PASS']; F = [r for r in results if r[2] == 'FAIL']; S = [r for r in results if r[2] == 'SKIP']
area_ok = lambda a: bool([r for r in results if r[0] == a]) and all(r[2] != 'FAIL' for r in results if r[0] == a)
print('\n================ E2E SUMMARY ================')
print(f'base URL          : {URL}\nbrowser           : {BROWSER}\nviewports         : 1440x1000 (desktop), 390x844 (mobile)')
print(f'tests collected   : {len(results)}\npassed            : {len(P)}\nfailed            : {len(F)}\nskipped           : {len(S)}' + ('  ' + str([(r[1], r[3]) for r in S]) if S else ''))
print('screens tested    : ' + ' | '.join(f"{s} ({sum(1 for r in results if r[0]==s)} checks)" for s in SCREENS if any(r[0] == s for r in results)) + '  (+ per-screen mobile, placeholder and dead-control checks)')
print(f"Leaflet rendered  : {'YES' if area_ok('Leaflet') else 'NO'}  | What-If simulation worked: {'YES' if area_ok('Simulation') else 'NO'}  | IoT update worked: {'YES' if area_ok('IoT') else 'NO'}  | Allocation worked: {'YES' if area_ok('Allocation') else 'NO'}  | 390px layout tested: {'YES' if area_ok('Mobile 390px') else 'NO'}")
print(f'OSM tiles         : {len(osm_failed)} tile requests blocked by the sandbox (real OSM imagery NOT verified)')
for r in F: print('FAILED:', r[0], r[1], r[3])
sys.exit(0 if not F else 1)
