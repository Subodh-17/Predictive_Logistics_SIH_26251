#!/usr/bin/env python3
"""Stage-1 / v3 parity proof.

1. Executes the ORIGINAL v3 JavaScript (legacy/v3/index.html) in Node for three scenarios and captures its outputs.
2. Checks they are identical to backend/tests/golden_v3.json (the fixture the pytest suite compares the Python engine against).
3. Recomputes the same scenarios with the Python engine and compares item-by-item (days of supply, status, replenishment qty, shortage)
   plus the headline metrics, route ETA/risk, and the 5,500 generated consumption records / stock levels.

    python backend/scripts/verify_v3_parity.py          (needs: node)
"""
import json, re, subprocess, sys, tempfile, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.seed_data import build_dataset, snapshot_from_dataset  # noqa: E402
from app.services import engine  # noqa: E402
from app.services.domain import Params  # noqa: E402

_v3 = ROOT / "legacy" / "v3" / "index.html"
if not _v3.exists():
    raise SystemExit("legacy/v3/index.html is not part of the V7 archive (its on-screen wording predates the terminology rules). The stored fixture "
                     "backend/tests/golden_v3.json is what the test suite compares against. To regenerate it, restore legacy/v3/index.html from the "
                     "V6 archive and run this script again.")
html = _v3.read_text()
js = re.search(r"<script>(.*)</script>", html, re.S).group(1)
js = js.replace("const B0=Date.now();draw();setInterval(clk,1000);", "").replace("document.getElementById('app')", "({})")
harness = "globalThis.document={getElementById:()=>({})};globalThis.window=globalThis;\n" + js + """
const scen=[{d:0,w:0,r:0,v:1},{d:.3,w:1,r:1,v:.6},{d:.5,w:.5,r:.5,v:.5}];
const out=scen.map(p=>{const R=calc(p);return{p,crit:R.crit,warn:R.warn,sloc:R.sloc,short:R.short,cap:R.cap,need:R.need,deficit:R.deficit,
 ar:R.ar,delay:R.delay,risk:R.risk,avgDays:R.avgDays,locs:R.locs.map(l=>[l.id,l.st]),
 rts:R.rts.map(r=>[r.id,r.eta,r.risk,r.v,r.tr]),
 items:R.items.map(i=>[i.l,i.t,i.days,i.st,i.qty,i.short])}});
console.log(JSON.stringify({scenarios:out,items:ITEM.map(i=>({l:i.l,t:i.t,stock:i.stock,safety:i.safety,f7:i.f7})),records:RECS,W:W.slice(0,5)}));
"""
with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
    f.write(harness)
live = json.loads(subprocess.run(["node", f.name], capture_output=True, text=True, check=True).stdout)
golden = json.loads((ROOT / "backend" / "tests" / "golden_v3.json").read_text())

fails = []
def check(name, ok, detail=""):
    print(("PASS" if ok else "FAIL"), name, detail); (not ok) and fails.append(name)

check("golden_v3.json is identical (parsed-JSON equality) to what the ORIGINAL v3 JavaScript produces now", live == golden)
check("v3 generated 5,500 consumption records", live["records"] == 5500)
snap = snapshot_from_dataset(build_dataset())
bad = [i for i in live["items"] if (lambda p: p.stock != i["stock"] or p.safety_stock != i["safety"] or abs(p.f7 - i["f7"]) > 1e-9)(
       next(p for p in snap.positions if p.location_id == i["l"] and p.supply_id == i["t"]))]
check("stock, safety stock and 7-day forecast mean identical for all 50 positions", not bad and len(live["items"]) == 50)
ST = {"CRITICAL": "cr", "WARNING": "wr", "NORMAL": "ok"}
for s in live["scenarios"]:
    p = s["p"]; r = engine.compute(snap, Params(p["d"], p["w"], p["r"], p["v"]))
    head = (r.n_critical, r.n_warning, r.shortage_locations, r.short_total, r.capacity, r.need, r.deficit, r.risk_index) == \
           (s["crit"], s["warn"], s["sloc"], s["short"], s["cap"], s["need"], s["deficit"], s["risk"])
    items = all(abs(i.days - x[2]) < 1e-9 and ST[i.status] == x[3] and i.qty == x[4] and i.short == x[5] for i, x in zip(r.items, s["items"]))
    routes = all(abs(e.eta - x[1]) < 1e-9 and abs(e.risk - x[2]) < 1e-9 and abs(e.speed - x[3]) < 1e-9 and abs(e.terrain_risk - x[4]) < 1e-9 for e, x in zip(r.routes, s["rts"]))
    locs = [[l.id, ST[l.status]] for l in r.locs] == s["locs"]
    check(f"scenario {p}: headline metrics / 50 items / 8 routes (ETA, risk, speed, terrain) / location status", head and items and routes and locs and abs(r.avg_days - s["avgDays"]) < 1e-9)
print("\nV3 PARITY:", "PASS" if not fails else "FAIL " + str(fails)); sys.exit(1 if fails else 0)
