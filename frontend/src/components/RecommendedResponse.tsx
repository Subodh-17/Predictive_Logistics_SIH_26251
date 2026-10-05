import { qs, scenarioQs, useApi } from '../api'
import { fx } from '../format'
import { legsText } from '../recommend'
import type { Allocation, Priority, Scenario, SimResult } from '../types'
import { Card, Tag } from './ui'

type Sev = 'ACT NOW' | 'PLAN' | 'OK'
interface Line { sev: Sev; text: string }
const SEV_TONE = { 'ACT NOW': 'cr', PLAN: 'wr', OK: 'ok' } as const
const WORSE = { NORMAL: 0, WARNING: 1, CRITICAL: 2 } as const

/** Concise response derived ONLY from the backend simulation result plus the scenario's own /api/priority and /api/allocation output. */
export default function RecommendedResponse({ res }: { res: SimResult }) {
  const sc: Scenario = { demand: res.params.demand, weather: res.params.weather, road: res.params.road, vehicles: res.params.vehicles }
  const q = qs(scenarioQs(sc))
  const prio = useApi<Priority[]>(`/api/priority${q}${q ? '&' : '?'}limit=3`)
  const alloc = useApi<Allocation>('/api/allocation' + q)
  const b = res.before, a = res.after
  const lines: Line[] = []
  const worsened = res.locations.filter(l => WORSE[l.after] > WORSE[l.before])
  const critNow = res.locations.filter(l => l.after === 'CRITICAL')
  if (worsened.length) lines.push({ sev: 'ACT NOW', text: `Escalate attention to ${worsened.map(l => `${l.id} (${l.before.toLowerCase()} → ${l.after.toLowerCase()}, ${l.days_after.toFixed(1)} d of cover)`).join('; ')}.` })
  else if (critNow.length) lines.push({ sev: 'ACT NOW', text: `Already critical and unchanged: ${critNow.map(l => `${l.id} (${l.days_after.toFixed(1)} d of cover)`).join('; ')} — keep these first in the dispatch order.` })
  if (a.capacity_deficit > 0) {
    const fleet = res.params.vehicles < 1 ? `Restore fleet availability toward 100% (scenario: ${Math.round(res.params.vehicles * 100)}%) or request surge transport` : 'Request surge transport or stage loads from the nearest depot'
    lines.push({ sev: a.capacity_deficit > b.capacity_deficit ? 'ACT NOW' : 'PLAN', text: `Transport shortfall: ${fx(a.transport_need)} units needed vs ${fx(a.transport_capacity)} capacity (deficit ${fx(a.capacity_deficit)}, was ${fx(b.capacity_deficit)}). ${fleet}.` })
  }
  const slow = [...res.routes].sort((x, y) => (y.eta_after - y.eta_before) - (x.eta_after - x.eta_before))[0]
  if (slow && slow.eta_after - slow.eta_before >= 0.5) lines.push({ sev: slow.risk_after >= 50 ? 'ACT NOW' : 'PLAN', text: `Plan for ${slow.id} to take ${(slow.eta_after - slow.eta_before).toFixed(1)} h longer (${slow.eta_before.toFixed(1)} → ${slow.eta_after.toFixed(1)} h, route risk ${slow.risk_before} → ${slow.risk_after}); compare alternatives on the GIS screen before dispatch.` })
  if (a.mean_route_risk - b.mean_route_risk >= 1) lines.push({ sev: 'PLAN', text: `Mean route risk rose from ${fx(b.mean_route_risk)} to ${fx(a.mean_route_risk)} (0–100): prefer the feasible route with the lowest combined risk/ETA score rather than the shortest one.` })
  if (res.params.vehicles < 1 && a.capacity_deficit <= 0) lines.push({ sev: 'PLAN', text: `Fleet availability is ${Math.round(res.params.vehicles * 100)}%: capacity is ${fx(a.transport_capacity)} units (was ${fx(b.transport_capacity)}), still covering the ${fx(a.transport_need)}-unit need; the allocation only assigns vehicles that are available.` })
  const top = (prio.data ?? []).map(p => {
    const r = alloc.data?.rows.find(x => x.location === p.location && x.supply === p.supply)
    const how = r && r.legs.length ? `${fx(r.allocated)} of ${fx(r.need)} units — ${legsText(r.legs)}` : 'no vehicle can serve it'
    return `${p.location} ${p.supply} — ${how} (priority ${p.score})`
  })
  if (top.length) lines.push({ sev: 'ACT NOW', text: `Dispatch first under this scenario: ${top.map((t, i) => `${i + 1}. ${t}`).join(' · ')}.` })
  if (a.unmet_after_allocation > 0) lines.push({ sev: a.unmet_after_allocation > b.unmet_after_allocation ? 'ACT NOW' : 'PLAN', text: `${fx(a.unmet_after_allocation)} units remain unserved after allocation (was ${fx(b.unmet_after_allocation)}): defer low-criticality supplies and pre-position stock for the next cycle.` })
  if (!lines.length) lines.push({ sev: 'OK', text: 'No change from baseline: no additional action is needed beyond routine monitoring.' })
  const verdict = a.overall_risk_index - b.overall_risk_index
  return (
    <Card title="RECOMMENDED RESPONSE · DERIVED FROM THE SIMULATION RESULT" className="mb-3" accent>
      <div className="mb-2 text-[14px]" data-testid="response-verdict">Overall risk <b>{b.overall_risk_index} → {a.overall_risk_index}</b> ({verdict > 0 ? '+' : ''}{verdict}); critical items {b.critical_items} → {a.critical_items}; unserved after allocation {fx(b.unmet_after_allocation)} → {fx(a.unmet_after_allocation)} units.</div>
      <ul className="list-none p-0 m-0 space-y-1.5" data-testid="response-list">
        {lines.map((l, i) => <li key={i} className="flex gap-2 items-start"><span className="shrink-0 mt-px"><Tag tone={SEV_TONE[l.sev]}>{l.sev}</Tag></span><span>{l.text}</span></li>)}
      </ul>
      <div className="text-[11px] text-mu mt-2">After changing the scenario, use APPLY TO ALL SCREENS to rerun priority, allocation and route selection on every screen.</div>
      {(prio.error || alloc.error) && <div className="text-wr text-[12px] mt-2">Dispatch detail for this scenario could not be loaded ({(prio.error ?? alloc.error)?.message}); the points above use the simulation result only.</div>}
      <div className="text-[11px] text-mu mt-2"><Tag>RULE-BASED</Tag> Plain rules over the backend's simulation output and the scenario's priority/allocation (GET /api/priority, /api/allocation). Not machine learning, not an LLM. Decision support only.</div>
    </Card>
  )
}
