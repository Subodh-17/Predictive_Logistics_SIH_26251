#!/usr/bin/env python3
"""E2E for the UI/UX enhancement pass (theme, command briefing, why-this-recommendation, GIS route explanation, forecast model roles,
simulation recommended response, IoT data flow, header wording). Separate from e2e_playwright.py, which is left unchanged.

    APP_URL=http://localhost:8080 python tests/e2e/e2e_ui_enhancements.py

Every UI number is cross-checked against the backend API. Exits 2 (no tests run) if /api/health is not OK.
Uses the fictional illustrative scenario (simulated telemetry); requires E2E_USER / E2E_PASSWORD of an existing account.
"""
import colorsys, json, math, os, re, sys, urllib.request
from collections import OrderedDict
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import login, http as api, preflight as _preflight

URL = os.environ.get('APP_URL', 'http://localhost:8080').rstrip('/')
SHOTS = os.environ.get('E2E_SHOTS', '/tmp/e2e_ui_shots'); os.makedirs(SHOTS, exist_ok=True)
SCREENS = OrderedDict([('Dashboard', 'Command Dashboard'), ('Forecast', 'Demand Forecast'), ('GIS', 'GIS Logistics'), ('Inventory', 'Inventory'), ('Simulation', 'What-If Simulation')])
results = []

def check(area, name, ok, detail=''):
    results.append((area, name, 'PASS' if ok else 'FAIL', str(detail)))
    print(('PASS' if ok else 'FAIL'), f'[{area}]', name, ('· ' + str(detail)) if detail else '', flush=True)

def inr(n):                      # en-IN digit grouping, as the UI prints it
    s = str(int(round(n))); neg = s.startswith('-'); s = s.lstrip('-')
    if len(s) > 3: s = (re.sub(r'(\d)(?=(\d\d)+$)', r'\1,', s[:-3]) + ',' + s[-3:])
    return ('-' if neg else '') + s

try:
    h = api('/api/health'); ok = h['status'] == 'ok' and h['database']['connected'] and _preflight()
except Exception as e: ok = False; print('preflight failed:', e)
if not ok: print('ENVIRONMENT NOT READY - no tests were run.'); sys.exit(2)
api('/api/iot/reset', 'POST')

# ---- contrast helpers (WCAG 2.x)
def lum(c):
    f = lambda v: v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(c[0] / 255) + 0.7152 * f(c[1] / 255) + 0.0722 * f(c[2] / 255)
def ratio(a, b):
    la, lb = lum(a), lum(b); hi, lo = max(la, lb), min(la, lb); return (hi + 0.05) / (lo + 0.05)
def parse(c): return [float(x) for x in re.findall(r'[\d.]+', c)[:3]]
JS_COLORS = """(sel)=>{const el=document.querySelector(sel); if(!el) return null; const fg=getComputedStyle(el).color; let n=el,bg=null;
  while(n){const c=getComputedStyle(n).backgroundColor; if(c && c!=='transparent' && !/,\\s*0\\)$/.test(c)){bg=c;break} n=n.parentElement}
  return [fg,bg||getComputedStyle(document.body).backgroundColor]}"""

with sync_playwright() as p:
    browser = p.chromium.launch(); BROWSER = f'{browser.browser_type.name} {browser.version} (headless)'
    print(f'base URL : {URL}\nbrowser  : {BROWSER}', flush=True)
    ctx = browser.new_context(viewport={'width': 1440, 'height': 1000}); pg = ctx.new_page()
    console_err, osm_console, page_err, bad_api = [], [], [], []
    pg.on('console', lambda m: (osm_console if 'openstreetmap' in (m.location.get('url', '') + m.text) else console_err).append(m.text[:150]) if m.type == 'error' else None)
    pg.on('pageerror', lambda e: page_err.append(str(e)[:150]))
    pg.on('response', lambda r: bad_api.append((r.status, r.url)) if '/api/' in r.url and r.status >= 400 else None)
    go = lambda s: (pg.click(f'nav >> text={SCREENS[s]}'), pg.wait_for_timeout(1500))
    theme = lambda: pg.evaluate("document.documentElement.getAttribute('data-theme')")
    BAD = re.compile(r'\bNaN\b|\bundefined\b|\[object Object\]|\bnull\b|Infinity')
    setr = "(el,v)=>{const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;s.call(el,v);el.dispatchEvent(new Event('input',{bubbles:true}))}"

    # =============================================================== THEME
    login(pg); pg.wait_for_selector('text=OVERALL LOGISTICS RISK'); pg.wait_for_timeout(1500)
    check('Theme', 'Dark is the default (fresh browser profile, empty storage)', theme() == 'dark' and 'DARK THEME' in pg.inner_text('[data-testid=theme-toggle]'))
    tg = pg.locator('[data-testid=theme-toggle]')
    check('Theme', 'toggle is an accessible switch (role=switch, aria-checked, label)', tg.get_attribute('role') == 'switch' and tg.get_attribute('aria-checked') == 'false' and 'Switch to light' in (tg.get_attribute('aria-label') or ''))
    pg.keyboard.press('Tab'); tg.focus(); pg.keyboard.press('Enter'); pg.wait_for_timeout(400)
    check('Theme', 'toggle works from the keyboard -> Light', theme() == 'light' and tg.get_attribute('aria-checked') == 'true')
    check('Theme', 'choice persisted in localStorage', pg.evaluate("localStorage.getItem('plsd-theme')") == 'light')
    pg.reload(); pg.wait_for_selector('text=OVERALL LOGISTICS RISK'); check('Theme', 'Light survives a reload (applied before first paint)', theme() == 'light')
    tg.click(); pg.wait_for_timeout(300); pg.reload(); pg.wait_for_selector('text=OVERALL LOGISTICS RISK'); check('Theme', 'back to Dark and persisted after reload', theme() == 'dark' and pg.evaluate("localStorage.getItem('plsd-theme')") == 'dark')

    def contrast_suite(th):
        pg.wait_for_timeout(600); bad = []
        pairs = [('page title', '[class*="text-act"]'), ('card title', 'section h3'), ('table text', 'td'), ('muted text', 'section .text-mu'), ('critical (red) text', '.text-cr'),
                 ('warning (yellow) text', '.text-wr'), ('ok (green) text', '.text-ok'), ('nav item', 'aside nav button:not([aria-current])'), ('active nav item', 'aside nav button[aria-current]'),
                 ('header strip', 'main > div:first-child'), ('footer banner', 'main > div:last-child'), ('theme toggle', '[data-testid=theme-toggle]'), ('select', 'select')]
        rows = []
        for name, sel in pairs:
            r = pg.evaluate(JS_COLORS, sel)
            if not r: rows.append((name, 'n/a')); continue
            c = ratio(parse(r[0]), parse(r[1])); rows.append((name, round(c, 1)))
            if c < 4.5: bad.append((name, round(c, 2)))
        check(f'Contrast ({th})', 'all sampled text/background pairs >= 4.5:1 (WCAG AA)', not bad, f'{rows}' if not bad else f'FAILING {bad} of {rows}')
        hues = {}
        for cls, lo_hi in (('text-ok', [(95, 175)]), ('text-wr', [(25, 62)]), ('text-cr', [(0, 14), (346, 360)])):
            r = pg.evaluate(JS_COLORS, '.' + cls)
            if r:
                rgb = [v / 255 for v in parse(r[0])]; hh = colorsys.rgb_to_hls(*rgb)[0] * 360; hues[cls] = round(hh)
        sem = all(any(a <= hues.get(c, -1) <= b for a, b in rng) for c, rng in (('text-ok', [(95, 175)]), ('text-wr', [(25, 62)]), ('text-cr', [(0, 14), (346, 360)])))
        check(f'Semantics ({th})', 'GREEN / YELLOW(amber) / RED text keep their hue', sem, f'hues(deg) {hues}')
    contrast_suite('dark'); pg.screenshot(path=f'{SHOTS}/dark_dashboard.png')
    tg.click(); pg.wait_for_timeout(500); check('Theme', 'toggled to Light for the Light contrast run', theme() == 'light'); contrast_suite('light'); pg.screenshot(path=f'{SHOTS}/light_dashboard.png')
    go('Simulation'); r = pg.evaluate(JS_COLORS, 'button.bg-ac'); cr_ = ratio(parse(r[0]), parse(r[1]))
    check('Contrast (light)', 'primary button (RUN SIMULATION) text on accent >= 4.5:1', cr_ >= 4.5, round(cr_, 1))
    tg.click(); pg.wait_for_timeout(400); go('Simulation'); r = pg.evaluate(JS_COLORS, 'button.bg-ac'); cr2 = ratio(parse(r[0]), parse(r[1]))
    check('Contrast (dark)', 'primary button text on accent >= 4.5:1', cr2 >= 4.5, round(cr2, 1)); go('Dashboard')

    # =============================================================== HEADER
    hd = pg.inner_text('main > div:first-child'); clock_title = pg.locator('text=SIMULATION TIME').first.get_attribute('title') or ''
    check('Header', 'clock reads SIMULATION TIME · <date> and DATA · ILLUSTRATIVE SCENARIO (no live-looking timestamp)', bool(re.search(r'SIMULATION TIME · \d{1,2} [A-Z]{3} 20\d\d', hd)) and 'DATA · ILLUSTRATIVE SCENARIO' in hd and not re.search(r'\bSIM TIME\b', hd) and not re.search(r'\d\d:\d\dZ', hd), hd[:200].replace('\n', ' '))
    check('Header', 'tooltip explains it is a fictional clock, not real time', 'NOT the real time' in clock_title and '2026-06-19' in clock_title)

    # =============================================================== DASHBOARD BRIEFING
    pg.wait_for_selector('[aria-label="Command briefing"]'); pg.wait_for_timeout(1200)
    brief = pg.inner_text('[aria-label="Command briefing"]')
    dash, prio, alloc, alerts = api('/api/dashboard'), api('/api/priority'), api('/api/allocation'), api('/api/alerts')
    k = dash['kpis']; crit_locs = [l['id'] for l in api('/api/locations') if l['kind'] == 'FORWARD' and l['status'] == 'CRITICAL']
    check('Briefing', 'overall risk shown and equals the API (risk index)', pg.inner_text('[data-testid=briefing-risk]').replace(' ', '').startswith(str(k['risk_index']) + '/100'), f"UI {pg.inner_text('[data-testid=briefing-risk]')!r} vs API {k['risk_index']}")
    check('Briefing', 'critical locations listed and equal the API', all(c in brief for c in crit_locs) and f'{len(crit_locs)} of 5' in brief, crit_locs)
    check('Briefing', 'predicted shortages equal the API (units, 14 d)', inr(k['supplies_at_risk_units']) + ' units' in brief, inr(k['supplies_at_risk_units']))
    check('Briefing', 'transport capacity vs need equals the API', f"{inr(k['transport_capacity'])} / {inr(k['transport_need'])}" in brief.replace('\n', ' ') and inr(k['capacity_deficit']) in brief, f"{k['transport_capacity']} / {k['transport_need']}")
    check('Briefing', 'active alerts equal the API (critical / warning)', f"{alerts['critical']} critical · {alerts['warning']} warning" in brief, f"{alerts['critical']}/{alerts['warning']}")
    lis = pg.locator('[aria-label="Command briefing"] ol > li'); check('Briefing', 'exactly 3 recommended actions', lis.count() == 3, lis.count())
    t1 = lis.nth(0).inner_text()
    check('Briefing', 'action #1 matches the API top priority (location, supply, score)', prio[0]['location'] in t1 and prio[0]['supply'] in t1 and f"priority {prio[0]['score']}/100" in t1, f"{prio[0]['location']} {prio[0]['supply']} {prio[0]['score']}")
    # leg-grouping accuracy: every vehicle must appear under ITS OWN depot + route
    row = next(r for r in alloc['rows'] if r['location'] == prio[0]['location'] and r['supply'] == prio[0]['supply'])
    groups = OrderedDict()
    for l in row['legs']: groups.setdefault((l['depot'], l['route']), []).append(l['vehicle'])
    ok_groups = True
    for (d, rt), vs in groups.items():
        m = re.search(re.escape(f'{d} via {rt} (') + r'([^:]*):', t1); ok_groups &= bool(m) and sorted(x.strip() for x in m.group(1).split('+')) == sorted(set(vs))
    check('Briefing', 'dispatch text groups vehicles under their own depot + route (no cross-depot merge)', ok_groups, dict(groups))
    check('Briefing', 'baseline action #1 really spans 2 depots (so the grouping fix is exercised)', len({d for d, _ in groups}) >= 2, sorted({d for d, _ in groups}))
    check('Briefing', 'labelled RULE-BASED, not machine learning / LLM', 'RULE-BASED' in brief and 'not machine learning' in brief and 'not an LLM' in brief)
    pg.locator('[aria-label="Command briefing"] button').first.click(); pg.wait_for_timeout(900)
    check('Briefing', 'SHOW ... ON MAP opens GIS for that location', pg.locator('nav button[aria-current=page]').inner_text() == 'GIS Logistics' and f"{prio[0]['location']} · LOCATION STATUS" in pg.inner_text('body'))
    go('Dashboard')

    # =============================================================== WHY THIS RECOMMENDATION
    inv = {(i['location'], i['supply']): i for i in api('/api/inventory')}; pg.wait_for_selector('[data-testid=why-facts]'); pg.wait_for_timeout(800)
    sel = pg.locator('[data-testid=why-select]'); opts = sel.locator('option').all_inner_texts()
    check('Why', 'selector lists the top priorities (<=10), #1 selected by default', 1 <= len(opts) <= 10 and opts[0].startswith('#1 ') and sel.input_value() == f"{prio[0]['location']}|{prio[0]['supply']}", len(opts))
    def why_checks(idx, tag):
        pr = prio[idx]; it = inv[(pr['location'], pr['supply'])]; txt = pg.inner_text('[data-testid=why-facts]'); tot = pg.inner_text('[data-testid=why-total]')
        labels = ['STOCK-OUT HORIZON', 'PREDICTED SHORTAGE', 'LEAD TIME', 'SUPPLY CRITICALITY', 'ROUTE RISK', 'VEHICLE / DISPATCH']
        check('Why', f'{tag}: shows stock-out horizon, shortage, lead time, criticality, route risk, vehicle', all(l in txt for l in labels))
        check('Why', f'{tag}: values equal the API', f"{pr['days_cover']:.1f} days" in txt and inr(it['shortage_14d']) + ' units / 14 d' in txt and f"{it['lead_days']:.1f} days" in txt and f"{round(pr['components']['criticality'] * 100)} / 100" in txt,
              f"cover {pr['days_cover']:.1f} d, shortage {it['shortage_14d']}, lead {it['lead_days']:.1f}, crit {round(pr['components']['criticality'] * 100)}")
        check('Why', f'{tag}: score breakdown sums to the API priority score', abs(int(tot) - pr['score']) <= 1, f'{tot} vs {pr["score"]}')
    why_checks(0, 'priority #1'); facts_1 = pg.inner_text('[data-testid=why-facts]'); sel.select_option(index=2); pg.wait_for_timeout(500); facts_3 = pg.inner_text('[data-testid=why-facts]'); why_checks(2, 'priority #3')
    check('Why', 'changing the selection updates the facts', facts_1 != facts_3 and sel.input_value() == f"{prio[2]['location']}|{prio[2]['supply']}", f"{prio[0]['location']} {prio[0]['supply']} -> {prio[2]['location']} {prio[2]['supply']}")
    check('Why', 'states it is rule-based with transparent weights', 'RULE-BASED' in pg.inner_text('body') and 'No machine learning' in pg.inner_text('body'))
    dtxt = pg.inner_text('body')
    check('Why', 'insight card title says RULE-BASED (NOT ML / LLM)', 'AI LOGISTICS INSIGHT · RULE-BASED DECISION SUPPORT (NOT ML / LLM)' in dtxt)
    check('Why', 'no page text claims the engine is AI-powered/generated', not re.search(r'AI[- ](powered|generated|driven)|artificial intelligence|LLM[- ]generated', dtxt, re.I))

    # =============================================================== GIS
    go('GIS'); pg.wait_for_selector('[data-testid=route-selected]'); pg.wait_for_timeout(1500)
    cmp_ = api('/api/routes/compare?destination=Base_04'); selr = next(r for r in cmp_['routes'] if r['id'] == cmp_['selected']); alt = [r for r in cmp_['routes'] if r['id'] != cmp_['selected']]
    banner = pg.inner_text('[data-testid=route-banner]')
    check('GIS', 'banner shows source -> destination, selected route and alternatives', f"SELECTED ROUTE {selr['id']}" in banner and f"{selr['depot']} → {selr['destination']}" in banner and all(a['id'] in banner for a in alt), banner[:110])
    labels = pg.locator('.route-label').all_inner_texts()
    check('GIS', 'map labels the selected route and the alternative(s)', any('SELECTED' in l and selr['id'] in l for l in labels) and all(any(a['id'] in l and 'alt' in l for l in labels) for a in alt), labels)
    check('GIS', 'map tags SOURCE depot and DESTINATION base', pg.locator('.leaflet-tooltip', has_text=f"{selr['depot']} · SOURCE").count() == 1 and pg.locator('.leaflet-tooltip', has_text=f"{selr['destination']} · DESTINATION").count() == 1)
    arrows = pg.locator('.route-arrow'); check('GIS', 'direction arrows drawn on the selected + alternative routes only', arrows.count() == 1 + len(alt), arrows.count())
    # arrow direction: rotation must agree (within 90 deg) with the source->destination chord taken from the API geometry
    co = selr['coordinates']; lat0, lon0, lat1, lon1 = co[0][0], co[0][1], co[-1][0], co[-1][1]
    chord = -math.degrees(math.atan2(lat1 - lat0, (lon1 - lon0) * math.cos(math.radians(lat0))))
    rots = pg.evaluate("[...document.querySelectorAll('.route-arrow')].map(e=>parseFloat((e.style.transform.match(/rotate\\((-?[\\d.]+)deg/)||[0,NaN])[1]))")
    check('GIS', 'selected-route arrow points source -> destination (within 90 deg of the chord)', any(math.cos(math.radians(r - chord)) > 0 for r in rots), f'chord {chord:.0f} deg, arrows {[round(r) for r in rots]}')
    pn = pg.inner_text('[data-testid=route-selected]'); rs = pg.inner_text('[data-testid=route-reason]')
    check('GIS', 'explanation panel: SELECTED route, source -> destination, ETA, distance', f"SELECTED {selr['id']}" in pn and selr['depot'] in pn and selr['destination'] in pn and f"{selr['eta_h']:.1f} h" in pn, pn[:100].replace('\n', ' '))
    check('GIS', 'explanation text equals the backend reason', cmp_['reason'][:60] in rs, cmp_['reason'][:70])
    body = pg.inner_text('body')
    check('GIS', 'alternatives get a "why not" with score / risk / ETA deltas', all(re.search(re.escape(a['id']) + r'.*score \+\d', body.replace('\n', ' ')) for a in alt), [a['id'] for a in alt])
    check('GIS', 'criteria shown: distance/time, capacity, road, weather, terrain', all(c in body for c in ['DISTANCE & TIME', 'VEHICLE CAPACITY', 'ROAD CONDITION', 'WEATHER RISK', 'TERRAIN RISK']))
    pg.locator('tr.row:has-text("R07")').first.click(); pg.wait_for_selector('text=FEASIBLE ROUTES TO Base_05'); pg.wait_for_timeout(700)
    check('GIS', 'single-corridor case (Base_05) explained, no fake alternative', 'Only one corridor serves this location' in pg.inner_text('body') and pg.locator('.route-label').count() == 1)
    pg.screenshot(path=f'{SHOTS}/gis_single.png')

    # =============================================================== FORECAST
    go('Forecast'); pg.wait_for_selector('[data-testid=model-roles]'); pg.wait_for_timeout(1500)
    fr = pg.inner_text('[data-testid=model-roles]'); ch_ = api('/api/forecast/challenger'); fc_ = api('/api/forecast?horizon=14')
    check('Forecast', 'three distinct model cards: active model / trained model / scenario holdout', all(x in fr for x in ['ACTIVE FORECAST MODEL', 'TRAINED MODEL', 'HOLDOUT ON THIS SCENARIO']))
    check('Forecast', 'roles are explicit: active model drives the application; trained model is opt-in and its promotion status is shown', 'DRIVES THE APPLICATION' in fr and 'OPT-IN' in fr and 'NOT PROMOTED' in fr)
    mt = pg.inner_text('[data-testid=model-metrics]')
    check('Forecast', 'holdout WAPE shown for the statistical and trained models', 'Statistical baseline' in mt and '%' in mt and 'Trained model' in mt, mt[:120].replace(chr(10), ' '))
    cv = fc_['confidence']; CNOTE = 'Heuristic confidence index derived from historical backtest error; not a probability of forecast correctness.'
    check('Forecast', 'confidence shown as \"Confidence Index: V/100 — LABEL\" and equals the API (no ambiguous %)', pg.inner_text('[data-testid=confidence-value] [data-testid=confidence-index]') == f"Confidence Index: {cv['value']}/100 — {cv['label']}" and 'WAPE' in fr and 'scenario' in fr.lower(), cv)
    check('Forecast', 'confidence explanation is visible and available as an accessible tooltip', pg.inner_text('[data-testid=confidence-note]') == CNOTE and CNOTE in (pg.locator('[data-testid=confidence-value] [data-testid=info-tip]').get_attribute('aria-label') or ''))
    check('Forecast', 'states what is and is not AI (rule-based engine is NOT ML / LLM)', 'WHAT IS AND IS NOT' in fr and 'deterministic rule-based engine' in fr and 'not machine learning, not an LLM and not generative AI' in fr)
    check('Forecast', 'model attribution is stated per forecast row', 'Every forecast row records which model produced it' in fr)
    pg.screenshot(path=f'{SHOTS}/forecast_roles.png', full_page=True)

    # =============================================================== SIMULATION
    go('Simulation'); pg.wait_for_selector('text=SCENARIO CONTROLS')
    for i, v in (('sd', 30), ('sw', 100), ('sr', 100), ('sv', 40)): pg.eval_on_selector('#' + i, setr, str(v))
    pg.click('button:has-text("RUN SIMULATION")'); pg.wait_for_selector('[data-testid=response-list]', timeout=20000); pg.wait_for_timeout(1500)
    sim = api('/api/simulation/run', 'POST', {'demand_increase': .3, 'weather_severity': 1, 'road_degradation': 1, 'vehicle_availability': .6})
    rl = pg.locator('[data-testid=response-list] > li'); rt = pg.inner_text('[data-testid=response-list]'); vd = pg.inner_text('[data-testid=response-verdict]')
    check('Response', 'concise Recommended Response (3-7 points) with severity tags', 3 <= rl.count() <= 7 and 'ACT NOW' in rt, rl.count())
    check('Response', 'verdict line equals the backend before/after risk', f"{sim['before']['overall_risk_index']} → {sim['after']['overall_risk_index']}" in vd, vd[:90])
    check('Response', 'transport shortfall numbers equal the backend result', f"{inr(sim['after']['transport_need'])} units needed vs {inr(sim['after']['transport_capacity'])}" in rt and inr(sim['after']['capacity_deficit']) in rt, f"need {sim['after']['transport_need']} cap {sim['after']['transport_capacity']} deficit {sim['after']['capacity_deficit']}")
    esc = [l for l in sim['locations'] if l['before'] != l['after']]
    check('Response', 'names the locations the backend says escalated', all(l['id'] in rt for l in esc) and bool(esc), [l['id'] for l in esc])
    sprio = api('/api/priority?limit=3&demand=0.3&weather=1&road=1&vehicles=0.6')
    check('Response', 'dispatch-first list equals the scenario priority queue from the API', all(f"{q['location']} {q['supply']}" in rt and f"priority {q['score']}" in rt for q in sprio), [(q['location'], q['supply'], q['score']) for q in sprio])
    salloc = api('/api/allocation?demand=0.3&weather=1&road=1&vehicles=0.6'); checked, all_ok, nolegs = 0, True, []
    for q in sprio:
        srow = next(r for r in salloc['rows'] if r['location'] == q['location'] and r['supply'] == q['supply'])
        if not srow['legs']: nolegs.append(f"{q['location']} {q['supply']}"); continue
        g2 = OrderedDict()
        for l in srow['legs']: g2.setdefault((l['depot'], l['route']), []).append(l['vehicle'])
        seg = rt[rt.find(f"{q['location']} {q['supply']}"):]; checked += 1
        for (d, r), vs in g2.items():
            m = re.search(re.escape(f'{d} via {r} (') + r'([^:]*):', seg); all_ok &= bool(m) and sorted(x.strip() for x in m.group(1).split('+')) == sorted(set(vs))
    check('Response', 'every top-3 item that has vehicles lists them under their own depot + route', checked >= 1 and all_ok, f'{checked} items verified; items with no feasible vehicle (stated as such in the UI): {nolegs}')
    check('Response', 'items with no feasible vehicle are said so, never given an invented one', all(f'{n} — no vehicle can serve it' in rt for n in nolegs))
    check('Response', 'labelled RULE-BASED, not ML/LLM; derived from simulation + priority/allocation', 'RULE-BASED' in pg.inner_text('body') and 'Not machine learning, not an LLM' in pg.inner_text('body'))
    pg.screenshot(path=f'{SHOTS}/sim_response.png', full_page=True)

    # =============================================================== IoT FLOW
    go('Inventory'); pg.wait_for_selector('[data-testid=iot-flow]'); pg.wait_for_timeout(800)
    idle = pg.inner_text('[data-testid=iot-flow]')
    check('IoT flow', 'idle state explains Telemetry -> Database -> Inventory/Risk impact', all(s in idle for s in ['1 · TELEMETRY', '2 · DATABASE', '3 · INVENTORY / RISK IMPACT', 'iot_events']) and 'ALL SIMULATED' in pg.inner_text('body'))
    pg.click('button:has-text("SEND SCAN")'); pg.wait_for_selector('[data-testid=iot-result]'); pg.wait_for_timeout(1500)
    s1, s2, s3 = (pg.inner_text(f'[data-testid=iot-stage-{n}]') for n in (1, 2, 3)); ev = api('/api/iot/events')[0]
    check('IoT flow', 'stage 1 Telemetry: SIMULATED RECEIVE Base_04/Medical x2,000 with device + tag', 'SIMULATED' in s1 and 'RECEIVE Base_04 / Medical' in s1 and '2,000' in s1 and 'ESP32-SIM-01' in s1 and ev['tag_id'] in s1, ev['tag_id'])
    check('IoT flow', 'stage 2 Database: event id equals iot_events row; stock 563 -> 2,563', f"#{ev['id']}" in s2 and '563 → 2,563' in s2 and 'iot_events' in s2, f"event #{ev['id']}")
    check('IoT flow', 'stage 3 Impact: cover, CRITICAL -> NORMAL, critical items 8 -> 7, risk 62 -> 57', 'CRITICAL' in s3 and 'NORMAL' in s3 and '8 → 7' in s3 and '62 → 57' in s3 and 'was 2.8 d' in s3, s3.replace('\n', ' ')[:140])
    check('IoT flow', 'flow numbers agree with the database via the API', api('/api/inventory?location=Base_04&supply=Medical')[0]['stock'] == 2563 and api('/api/dashboard')['kpis']['risk_index'] == 57)
    pg.locator('[data-testid=iot-flow]').screenshot(path=f'{SHOTS}/iot_flow.png')
    pg.click('button:has-text("RUN SIMULATOR")'); pg.wait_for_timeout(2500)
    check('IoT flow', 'simulator batch shows "latest of 5 scans"', 'latest of 5 scans' in pg.inner_text('[data-testid=iot-flow]'))
    pg.click('button:has-text("RESET INVENTORY")'); pg.wait_for_selector('text=Inventory restored'); pg.wait_for_timeout(900)
    check('IoT flow', 'reset returns the flow to idle and the baseline to 8 critical', 'Waiting for a scan' in pg.inner_text('[data-testid=iot-flow]') and api('/api/dashboard')['kpis']['risk_index'] == 62)

    # =============================================================== BOTH THEMES: placeholders, mobile 390px, screenshots
    for th in ('dark', 'light'):
        if theme() != th: pg.click('[data-testid=theme-toggle]'); pg.wait_for_timeout(400)
        pg.set_viewport_size({'width': 1440, 'height': 1000})
        for s in SCREENS:
            go(s); pg.wait_for_timeout(1200)
            if s == 'Simulation': pg.click('button:has-text("RUN SIMULATION")'); pg.wait_for_selector('[data-testid=response-list]', timeout=20000); pg.wait_for_timeout(800)
            txt = re.sub(r'\d{4}-\d\d-\d\d \d\d:\d\dZ', '', pg.inner_text('main')); b_ = BAD.search(txt)
            check(f'Both themes', f'{th}/{s}: renders, no NaN/undefined/null', len(txt) > 800 and not b_, f'{len(txt)} chars' + (f' found {b_.group(0)}' if b_ else ''))
            pg.screenshot(path=f'{SHOTS}/{th}_{s.lower()}.png')
        pg.set_viewport_size({'width': 390, 'height': 844}); pg.wait_for_timeout(500)
        for s in SCREENS:
            go(s); pg.wait_for_timeout(1300); w = pg.evaluate('document.documentElement.scrollWidth')
            check('Mobile 390px', f'{th}/{s}: no horizontal page scroll', w <= 392, f'scrollWidth={w}')
    pg.set_viewport_size({'width': 1440, 'height': 1000})

    # =============================================================== CONSOLE / NETWORK
    check('Console', 'no uncaught page errors', not page_err, page_err[:2])
    check('Console', 'no failed /api calls', not bad_api, bad_api[:3])
    check('Console', 'no console errors other than blocked OSM tile loads', not console_err, f'unexpected={console_err[:3]} | OSM tile errors={len(osm_console)}')
    browser.close()
api('/api/iot/reset', 'POST')
P = [r for r in results if r[2] == 'PASS']; F = [r for r in results if r[2] == 'FAIL']
print('\n================ UI ENHANCEMENT E2E SUMMARY ================')
print(f'base URL: {URL} | browser: {BROWSER}\ntests collected: {len(results)} | passed: {len(P)} | failed: {len(F)} | skipped: 0')
for r in F: print('FAILED:', r[0], '|', r[1], '|', r[3])
sys.exit(0 if not F else 1)
