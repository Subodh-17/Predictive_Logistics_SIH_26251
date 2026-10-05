import { fx } from '../format'
import type { Route } from '../types'
import { Card, LevelTag, Table, Tag } from './ui'

export interface Compare { destination: string; required_units: number; routes: Route[]; selected: string | null; reason: string; formula: string }

/** Why the optimiser chose a route: source → destination, the criteria, and a per-alternative "why not". Differences are shown, never recomputed. */
export function whyNot(r: Route, sel: Route | undefined): string {
  if (!sel) return '—'
  if (r.decision === 'NO VEHICLE') return `No available vehicle at ${r.depot}`
  if (r.id === sel.id) return 'Lowest combined score'
  const bits: string[] = []
  const ds = (r.combined_score ?? 0) - (sel.combined_score ?? 0)
  bits.push(`score +${ds.toFixed(2)}`)
  const dr = Math.round((r.risk - sel.risk) * 100), de = r.eta_h - sel.eta_h, dc = r.vehicle_capacity - sel.vehicle_capacity
  if (dr !== 0) bits.push(`risk ${dr > 0 ? '+' : ''}${dr} pts`)
  if (Math.abs(de) >= 0.05) bits.push(`ETA ${de > 0 ? '+' : ''}${de.toFixed(1)} h`)
  if (dc < 0) bits.push(`capacity ${fx(dc)} units`)
  const tdr = Math.round((r.terrain.risk - sel.terrain.risk) * 100)
  if (tdr > 0) bits.push(`terrain risk +${tdr}`)
  return bits.join(' · ')
}

export default function RouteSelection({ data }: { data: Compare }) {
  const sel = data.routes.find(r => r.id === data.selected)
  const alts = data.routes.filter(r => r.id !== data.selected)
  return (
    <Card title="ROUTE SELECTION EXPLAINED · SOURCE → DESTINATION" className="mb-3" accent>
      {sel ? (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mb-2 text-[15px]" data-testid="route-selected">
          <span className="font-mono"><b>{sel.depot}</b> <span className="text-act">→</span> <b>{sel.destination}</b></span>
          <Tag tone="ok">SELECTED {sel.id}</Tag><LevelTag level={sel.risk_level} />
          <span className="text-mu text-[12px]">{sel.distance_km} km · ETA {sel.eta_h.toFixed(1)} h · {fx(data.required_units)} units to move</span>
        </div>
      ) : <div className="text-cr mb-2">No feasible route: no vehicle is available at any serving depot.</div>}
      <div className="font-mono text-[11px] tracking-[.12em] text-act mb-1" data-testid="why-this-route">WHY THIS ROUTE?</div>
      <div className="mb-3 text-[13px] text-soft" data-testid="route-reason"><b>Decision:</b> {data.reason}</div>
      {sel && (
        <div className="grid gap-2.5 grid-cols-[repeat(auto-fit,minmax(170px,1fr))] mb-3">
          {[['DISTANCE & TIME', `${sel.distance_km} km · ETA ${sel.eta_h.toFixed(1)} h`, `effective ${sel.effective_speed_kmh.toFixed(0)} km/h vs nominal ${sel.nominal_speed_kmh} (delay +${sel.delay_h.toFixed(1)} h)`],
            ['VEHICLE CAPACITY', `${fx(sel.vehicle_capacity)} units`, `available at ${sel.depot}`], ['ROAD CONDITION', sel.road_label, 'slows the convoy'],
            ['WEATHER RISK', sel.weather_level, 'amplified by terrain exposure'], ['TERRAIN RISK', `${sel.terrain.type} · ${Math.round(sel.terrain.risk * 100)}/100`, `${sel.terrain.elevation_label} — lowers speed, raises ETA`],
            ['TOTAL ROUTE RISK', `${sel.risk_level} · ${Math.round(sel.risk * 100)}/100`, 'road + weather + terrain + distance, weighted'],
            ['ALTERNATIVES', alts.length ? alts.map(a => a.id).join(', ') : 'None (single corridor)', alts.length ? alts.map(a => `${a.id}: ${whyNot(a, sel)}`).join(' | ') : 'no other route serves this destination']].map(([l, v, s]) => (
            <div key={l} className="bg-ins border border-ln px-3 py-2"><span className="block font-mono text-[10px] tracking-[.1em] text-mu">{l}</span><span className="block font-semibold">{v}</span><span className="block text-[11px] text-mu">{s}</span></div>))}
        </div>)}
      <Table head={['ROUTE', 'FROM → TO', 'COMBINED SCORE', 'ETA H', 'ROUTE RISK', 'CAPACITY', 'VERDICT', 'WHY / WHY NOT']}>
        {data.routes.map(r => (
          <tr key={r.id} className={r.id === data.selected ? 'sel' : ''}>
            <td><b>{r.id}</b></td><td>{r.depot} → {r.destination}</td><td>{r.combined_score?.toFixed(2)}</td><td>{r.eta_h.toFixed(1)}</td>
            <td><LevelTag level={r.risk_level} /> {Math.round(r.risk * 100)}</td><td>{fx(r.vehicle_capacity)}</td>
            <td>{r.decision === 'SELECTED' ? <b className="text-ok">SELECTED</b> : r.decision === 'NO VEHICLE' ? <span className="text-cr">NO VEHICLE</span> : 'Alternative'}</td>
            <td className="whitespace-normal min-w-[220px]">{r.id === data.selected ? 'Lowest combined score' : whyNot(r, sel)}</td>
          </tr>))}
      </Table>
      {alts.length === 0 && <div className="text-[12px] text-mu mt-2">Only one corridor serves this location, so there is no alternative to compare.</div>}
      <div className="text-[11px] text-mu mt-2">{data.formula}. “score +x” is how much higher an alternative's combined score is than the selected route (lower is better).</div>
    </Card>
  )
}
