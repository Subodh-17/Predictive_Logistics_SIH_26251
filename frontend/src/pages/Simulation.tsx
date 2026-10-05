import { useState } from 'react'
import { ApiError, post } from '../api'
import { useApp } from '../state'
import { BASELINE, type Scenario, type SimResult } from '../types'
import { Btn, Card, ErrorBox, Grid2, Note, PageTitle, StatusTag, Table } from '../components/ui'
import { fx, roadLabel, weatherLabel } from '../format'
import RecommendedResponse from '../components/RecommendedResponse'

export default function Simulation() {
  const { scenario, applyScenario, resetScenario } = useApp()
  const [p, setP] = useState<Scenario>(scenario)
  const [res, setRes] = useState<SimResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<ApiError | null>(null)

  async function run(): Promise<SimResult | null> {
    setBusy(true); setErr(null)
    try {
      const r = await post<SimResult>('/api/simulation/run', { demand_increase: p.demand, weather_severity: p.weather, road_degradation: p.road, vehicle_availability: p.vehicles })
      setRes(r); return r
    } catch (e) { setErr(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', String(e))); return null } finally { setBusy(false) }
  }
  const slider = (label: string, id: string, min: number, max: number, val: number, set: (n: number) => void, text: string) => (
    <div className="grid gap-2.5 items-center mb-3 sm:grid-cols-[150px_1fr_80px]">
      <label htmlFor={id}>{label}</label>
      <input id={id} type="range" min={min} max={max} step={1} value={val} onChange={e => set(Number(e.target.value))} />
      <b className="font-mono" data-testid={id + '-label'}>{text}</b>
    </div>)
  const row = (l: string, k: string, f: (x: number) => string = x => fx(x), bad = 1) => {
    if (!res) return null
    const b = res.before[k], a = res.after[k], dv = a - b
    return <tr key={k}><td>{l}</td><td>{f(b)}</td><td>{f(a)}</td><td className={dv * bad > 0 ? 'text-cr' : dv * bad < 0 ? 'text-ok' : ''}>{dv > 0 ? '+' : ''}{f(dv)}</td></tr>
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
            <Btn primary disabled={busy} onClick={() => { void run() }}>{busy ? 'RUNNING…' : 'RUN SIMULATION'}</Btn>
            <Btn disabled={busy} onClick={async () => { const r = res ?? await run(); if (r) applyScenario(p) }}>APPLY TO ALL SCREENS</Btn>
            <Btn disabled={busy} onClick={() => { setP(BASELINE); setRes(null); resetScenario() }}>RESET</Btn>
          </div>
          {err && <div className="mt-3"><ErrorBox error={err} /></div>}
          <Note>The scenario is evaluated by the FastAPI backend (POST /api/simulation/run) against the live PostgreSQL inventory and stored in simulation_runs.</Note>
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
    </div>
  )
}
