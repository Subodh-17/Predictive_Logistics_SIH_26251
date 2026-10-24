import { useState } from 'react'
import { ApiError, post, useApi } from '../api'
import { useApp } from '../state'
import { useAuth } from '../auth'
import { BASELINE, type Scenario, type SimResult } from '../types'
import { Btn, Card, ErrorBox, Grid2, Loading, Note, PageTitle, StatusTag, Table } from '../components/ui'
import { fx, roadLabel, weatherLabel } from '../format'
import RecommendedResponse from '../components/RecommendedResponse'

interface SavedRun { id: number; created_at: string; params: { demand: number; weather: number; road: number; vehicles: number } }
interface Cmp { a: { id: number }; b: { id: number }; same_baseline: boolean; note: string
  metrics: { metric: string; label: string; a: number; b: number; delta: number; delta_pct: number | null; better: 'a' | 'b' | 'same' }[] }
const runLabel = (r: SavedRun) => `#${r.id} · demand +${Math.round(r.params.demand * 100)}% · weather ${r.params.weather} · road ${r.params.road} · fleet ${Math.round(r.params.vehicles * 100)}%`

/** Compare two saved scenario runs (stored results, nothing is re-simulated); warns when their starting state differed. */
function CompareRuns({ tick }: { tick: number }) {
  const runs = useApi<SavedRun[]>('/api/simulation/runs?limit=20', tick)
  const [ids, setIds] = useState<{ a: string; b: string }>({ a: '', b: '' })
  const ready = ids.a !== '' && ids.b !== '' && ids.a !== ids.b
  const cmp = useApi<Cmp>(ready ? `/api/simulation/compare?a=${ids.a}&b=${ids.b}` : null)
  const list = runs.data ?? []
  return (
    <Card title="COMPARE SAVED SCENARIOS" className="mb-3">
      {runs.loading ? <Loading what="saved scenarios" /> : runs.error ? <ErrorBox error={runs.error} /> : list.length < 2 ? <p className="text-mu" data-testid="cmp-empty">Run at least two simulations to compare them side by side.</p> : (<>
        <div className="grid gap-3 md:grid-cols-2 mb-2 min-w-0">
          {(['a', 'b'] as const).map(k => (
            <label key={k} className="text-[11px] text-mu min-w-0 block">SCENARIO {k.toUpperCase()}<br />
              <select className="w-full max-w-full min-w-0 truncate" value={ids[k]} onChange={e => setIds({ ...ids, [k]: e.target.value })} data-testid={`cmp-${k}`}><option value="">choose…</option>{list.map(r => <option key={r.id} value={r.id}>{runLabel(r)}</option>)}</select></label>))}
        </div>
        {ids.a !== '' && ids.a === ids.b && <p role="alert" className="text-wr text-[12px]">Choose two different runs.</p>}
        {ready && cmp.loading && <Loading what="scenario comparison" />}
        {ready && !cmp.loading && cmp.error && <ErrorBox error={cmp.error} />}
        {ready && !cmp.loading && !cmp.error && cmp.data && (<div data-testid="cmp-result">
          <p role="status" className={`text-[12px] mb-2 ${cmp.data.same_baseline ? 'text-mu' : 'text-wr'}`}>{cmp.data.note}</p>
          <Table head={['METRIC', 'A', 'B', 'B − A', 'BETTER']}>
            {cmp.data.metrics.map(m => <tr key={m.metric}><td>{m.label}</td><td>{m.a}</td><td>{m.b}</td><td>{m.delta > 0 ? '+' : ''}{m.delta}{m.delta_pct !== null ? ` (${m.delta_pct > 0 ? '+' : ''}${m.delta_pct}%)` : ''}</td>
              <td>{m.better === 'same' ? '—' : m.better.toUpperCase()}</td></tr>)}
          </Table></div>)}
      </>)}
    </Card>
  )
}

export default function Simulation() {
  const { scenario, applyScenario, resetScenario } = useApp()
  const { can } = useAuth()
  const canRun = can('operator')
  const [p, setP] = useState<Scenario>(scenario)
  const [res, setRes] = useState<SimResult | null>(null)
  const [runCount, setRunCount] = useState(0)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<ApiError | null>(null)

  async function run(): Promise<SimResult | null> {
    setBusy(true); setErr(null)
    try {
      const r = await post<SimResult>('/api/simulation/run', { demand_increase: p.demand, weather_severity: p.weather, road_degradation: p.road, vehicle_availability: p.vehicles })
      setRes(r); setRunCount(c => c + 1); return r
    } catch (e) { setErr(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', String(e))); return null } finally { setBusy(false) }
  }
  const slider = (label: string, id: string, min: number, max: number, val: number, set: (n: number) => void, text: string) => (
    <div className="grid gap-2.5 items-center mb-3.5 sm:grid-cols-[160px_1fr_90px]">
      <label htmlFor={id} className="text-[12.5px] font-medium text-tx">{label}</label>
      <input id={id} type="range" min={min} max={max} step={1} value={val} onChange={e => set(Number(e.target.value))} />
      <div className="bg-ins/90 border border-ln/70 px-2 py-0.5 rounded-sm text-center">
        <b className="font-mono text-[12px] text-act" data-testid={id + '-label'}>{text}</b>
      </div>
    </div>)
  const row = (l: string, k: string, f: (x: number) => string = x => fx(x), bad = 1) => {
    if (!res) return null
    const b = res.before[k], a = res.after[k], dv = a - b
    const isWorse = dv * bad > 0, isBetter = dv * bad < 0
    return (
      <tr key={k}>
        <td>{l}</td>
        <td className="tabular-nums">{f(b)}</td>
        <td className="tabular-nums font-semibold">{f(a)}</td>
        <td>
          <span className={`inline-block px-1.5 py-0.5 rounded-xs font-mono text-[11.5px] font-semibold tabular-nums ${isWorse ? 'bg-cr/10 text-cr border border-cr/30' : isBetter ? 'bg-ok/10 text-ok border border-ok/30' : 'text-mu'}`}>
            {dv > 0 ? '+' : ''}{f(dv)}
          </span>
        </td>
      </tr>
    )
  }
  return (
    <div>
      <PageTitle>WHAT-IF SIMULATION · SIMULATION</PageTitle>
      <Grid2 className="lg:grid-cols-[1fr_1fr]">
        <Card title="SCENARIO CONTROLS">
          {slider('Demand increase', 'sd', 0, 50, Math.round(p.demand * 100), n => setP({ ...p, demand: n / 100 }), '+' + Math.round(p.demand * 100) + '%')}
          {slider('Weather severity', 'sw', 0, 100, Math.round(p.weather * 100), n => setP({ ...p, weather: n / 100 }), weatherLabel(p.weather))}
          {slider('Road condition', 'sr', 0, 100, Math.round(p.road * 100), n => setP({ ...p, road: n / 100 }), roadLabel(p.road))}
          {slider('Vehicle availability', 'sv', 0, 50, Math.round((1 - p.vehicles) * 100), n => setP({ ...p, vehicles: 1 - n / 100 }), Math.round(p.vehicles * 100) + '%')}
          <div className="flex flex-wrap gap-2">
            <Btn primary disabled={busy || !canRun} onClick={() => { void run() }}>{busy ? 'RUNNING…' : 'RUN SIMULATION'}</Btn>
            <Btn disabled={busy} onClick={async () => { if (!canRun) { applyScenario(p); return } const r = res ?? await run(); if (r) applyScenario(p) }}>APPLY TO ALL SCREENS</Btn>
            <Btn disabled={busy} onClick={() => { setP(BASELINE); setRes(null); resetScenario() }}>RESET</Btn>
          </div>
          {err && <div className="mt-3"><ErrorBox error={err} /></div>}
          {!canRun && <p role="note" data-testid="sim-readonly" className="mt-3 text-wr text-[12px]">Running and saving a before/after simulation requires the operator role. You can still apply these settings to every screen to see the recalculated figures.</p>}
          <Note>Each run is evaluated by the backend against the current inventory and stored as a simulation record.</Note>
        </Card>
        {!res ? (
          <Card title="BEFORE VS AFTER"><p>Set the controls and press RUN SIMULATION. The engine recalculates shortage locations, inventory risk, ETA, route risk, transport capacity, allocation and recommendations against the baseline.</p></Card>
        ) : (
          <Card title="BEFORE VS AFTER">
            <Table head={['METRIC', 'BEFORE', 'AFTER', 'Δ']}>
              {row('Critical items', 'critical_items')}{row('Warning items', 'warning_items')}{row('Shortage-risk locations', 'shortage_locations')}
              {row('Expected shortage (units, 14 d)', 'expected_shortage_units')}{row('Transport capacity (units)', 'transport_capacity', undefined, -1)}
              {row('Replenishment need (units)', 'transport_need')}{row('Capacity deficit (units)', 'capacity_deficit')}
              {row('Mean route risk (0–100)', 'mean_route_risk', x => fx(x, 0))}{row('Mean ETA delay (h)', 'mean_eta_delay_h', x => fx(x, 1))}
              {row('Overall risk index', 'overall_risk_index')}{row('Allocated units', 'allocated_units', undefined, -1)}{row('Unmet after allocation (units)', 'unmet_after_allocation')}
            </Table>
            <Note>{res.locations.map(l => <span key={l.id}>{l.id}: <StatusTag s={l.before} /> → <StatusTag s={l.after} /> ({l.days_before.toFixed(1)} → {l.days_after.toFixed(1)} d)</span>)}</Note>
          </Card>)}
      </Grid2>
      {res && <>
        <RecommendedResponse res={res} />
        <Card title="WHY THE RISK CHANGED · DECISION SUPPORT" className="mb-3"><ul className="list-disc pl-5 mt-1.5 space-y-1.5" data-testid="sim-why">{res.explanation.map((x, i) => <li key={i}>{x}</li>)}</ul></Card>
        <Card title="ROUTE ETA AND RISK · BEFORE VS AFTER" className="mb-3">
          <Table head={['ROUTE', 'ETA BEFORE (H)', 'ETA AFTER (H)', 'Δ ETA', 'RISK BEFORE', 'RISK AFTER']}>
            {res.routes.map(r => <tr key={r.id}><td>{r.id}</td><td>{r.eta_before.toFixed(1)}</td><td>{r.eta_after.toFixed(1)}</td><td className={r.eta_after > r.eta_before ? 'text-cr' : ''}>{(r.eta_after - r.eta_before >= 0 ? '+' : '') + (r.eta_after - r.eta_before).toFixed(1)}</td><td>{r.risk_before}</td><td>{r.risk_after}</td></tr>)}
          </Table>
          <Note>Apply the scenario to all screens to see the recalculated recommendations, allocation plan and route comparison on the Dashboard and GIS screens.</Note>
        </Card></>}
      <CompareRuns tick={runCount} />
    </div>
  )
}
