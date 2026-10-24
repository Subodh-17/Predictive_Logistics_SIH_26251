import { useState } from 'react'
import { useApi } from '../api'
import { dd, fx } from '../format'
import { corridorText, criticalityLabel, FACTOR_LABEL, legsText, mainRoute, tone } from '../recommend'
import type { Allocation, InvItem, Priority, Route, Vehicle } from '../types'
import { Card, LevelTag, StatusTag, Tag } from './ui'

const TT = { cr: 'text-cr', wr: 'text-wr', ok: 'text-ok', '': '' }
function Fact({ label, value, sub, t = '' }: { label: string; value: React.ReactNode; sub?: React.ReactNode; t?: 'cr' | 'wr' | 'ok' | '' }) {
  return (
    <div className="bg-ins/90 border border-ln/70 px-3 py-2.5 min-w-0 rounded-sm">
      <span className="block font-mono text-[10px] tracking-[.12em] text-mu uppercase">{label}</span>
      <span className={`block text-[18px] font-bold tabular-nums mt-0.5 ${TT[t]}`}>{value}</span>
      {sub && <span className="block text-[11px] text-soft mt-0.5 leading-snug">{sub}</span>}
    </div>
  )
}

/** "Why this recommendation?" for a selected priority: stock-out horizon, shortage, lead time, criticality, route risk, vehicle + the score breakdown. */
export default function WhyRecommendation({ prio, inv, alloc, routes, vehicles }: { prio: Priority[] | null; inv: InvItem[] | null; alloc: Allocation | null; routes: Route[] | null; vehicles: Vehicle[] | null }) {
  const weights = useApi<{ weights: Record<string, number> }>('/api/priority/weights')
  const options = (prio ?? []).slice(0, 10)
  const [key, setKey] = useState('')
  const p = options.find(o => o.location + '|' + o.supply === key) ?? options[0]
  if (!p) return <Card title="WHY THIS RECOMMENDATION?"><div className="text-mu">{prio ? 'No at-risk items: no recommendation is needed.' : 'Loading…'}</div></Card>
  const item = inv?.find(i => i.location === p.location && i.supply === p.supply)
  const row = alloc?.rows.find(r => r.location === p.location && r.supply === p.supply)
  const mainId = (row && mainRoute(row.legs)) ?? p.best_route
  const route = routes?.find(r => r.id === mainId) ?? null
  const otherRoutes = Array.from(new Set((row?.legs ?? []).map(l => l.route))).filter(id => id !== mainId)
  const lead = item?.lead_days ?? row?.lead_days ?? 0
  const margin = p.days_cover - lead
  const W = weights.data?.weights
  const parts = W ? Object.keys(W).map(f => ({ f, w: W[f], v: p.components[f] ?? 0, pts: W[f] * (p.components[f] ?? 0) * 100 })) : []
  const crit = p.components.criticality ?? 0
  return (
    <Card title="WHY THIS RECOMMENDATION?" className="mb-3">
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <label htmlFor="why-select" className="text-mu text-[11px] font-mono tracking-wide">SELECTED PRIORITY</label>
        <select id="why-select" data-testid="why-select" value={p.location + '|' + p.supply} onChange={e => setKey(e.target.value)}>
          {options.map(o => <option key={o.location + o.supply} value={o.location + '|' + o.supply}>{`#${o.rank} ${o.location} · ${o.supply} — score ${o.score}`}</option>)}
        </select>
        <StatusTag s={p.status} /><span className="font-mono text-mu text-[11px]">priority score {p.score} / 100</span>
      </div>
      <div data-testid="why-recommendation" className="border border-ac bg-ins/90 px-3.5 py-2.5 mb-3 text-[13px] rounded-sm shadow-xs">
        <b className="font-mono text-[11px] tracking-[.12em] text-act uppercase">RECOMMENDATION · DECISION SUPPORT</b>
        <div className="mt-0.5">
          {row && row.legs.length
            ? <>Source depot → destination: <b>{corridorText(row.legs, p.location)}</b> — {fx(row.allocated)} of {fx(row.need)} units of {p.supply}.</>
            : <>No dispatch is possible for <b>{p.supply}</b> at <b>{p.location}</b> ({(row?.unmet_reason || 'no feasible route').toLowerCase()}) — escalate the transport allocation.</>}
        </div>
        <div className="text-[11px] text-mu mt-0.5">Advisory only: a suggestion for authorized personnel to review and approve. It is not an autonomous command and nothing is dispatched automatically.</div>
      </div>
      <div className="grid gap-2.5 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3" data-testid="why-facts">
        <Fact label="STOCK-OUT HORIZON" t={tone(p.status)} value={`${p.days_cover.toFixed(1)} days`} sub={`stock-out ${dd(p.stockout_date)} · ${margin >= 0 ? margin.toFixed(1) + ' d after' : Math.abs(margin).toFixed(1) + ' d before'} the replenishment lead time`} />
        <Fact label="PREDICTED SHORTAGE" t={item && item.shortage_14d > 0 ? 'cr' : 'ok'} value={item ? `${fx(item.shortage_14d)} units / 14 d` : '—'} sub={item ? `stock ${fx(item.stock)} vs safety ${fx(item.safety_stock)}${item.below_safety ? ' — below safety stock' : ''}` : undefined} />
        <Fact label="LEAD TIME" value={`${lead.toFixed(1)} days`} sub="1 d handling + ETA of the fastest route" />
        <Fact label="SUPPLY CRITICALITY" value={`${Math.round(crit * 100)} / 100`} sub={`${criticalityLabel(crit)} · fixed configured weight for ${p.supply}`} />
        <Fact label="ROUTE RISK" t={route ? (route.risk < 0.3 ? 'ok' : route.risk < 0.5 ? 'wr' : 'cr') : 'cr'} value={route ? <>{route.id}{otherRoutes.length ? ` (+${otherRoutes.join(', ')})` : ''} · <LevelTag level={route.risk_level} /></> : 'No feasible route'}
          sub={route ? `main route ${route.depot} → ${route.destination} · ETA ${route.eta_h.toFixed(1)} h · ${route.terrain.type} (terrain risk ${Math.round(route.terrain.risk * 100)}) · risk ${Math.round(route.risk * 100)}/100` : 'no available vehicle serves this location'} />
        <Fact label="VEHICLE / DISPATCH" t={row && row.unmet > 0 ? 'wr' : 'ok'}
          value={row && row.legs.length ? Array.from(new Set(row.legs.map(l => l.vehicle))).join(' + ') : 'None assigned'}
          sub={row ? (row.legs.length ? `${legsText(row.legs)} · ${fx(row.allocated)} of ${fx(row.need)} units · fleet capacity ${fx(row.legs.reduce((t, l) => t + (vehicles?.find(v => v.id === l.vehicle)?.effective_capacity ?? 0), 0))}` : `unmet ${fx(row.unmet)} units · ${row.unmet_reason.toLowerCase()}`) : undefined} />
      </div>
      <div className="mt-3">
        <div className="font-mono text-[10px] tracking-[.1em] text-mu mb-1">HOW THE PRIORITY SCORE IS BUILT · Σ weight × factor</div>
        {weights.error && <div className="text-wr text-[12px]">Score weights unavailable ({weights.error.message}).</div>}
        <div className="overflow-x-auto">
          <table data-testid="why-breakdown"><thead><tr><th>FACTOR</th><th>VALUE (0–1)</th><th>WEIGHT</th><th>CONTRIBUTION</th></tr></thead>
            <tbody>
              {parts.map(x => (
                <tr key={x.f}><td>{FACTOR_LABEL[x.f] ?? x.f}</td><td>{x.v.toFixed(2)}</td><td>{Math.round(x.w * 100)}%</td>
                  <td><div className="flex items-center gap-2"><div className="h-[6px] bg-bar w-24"><i className="block h-full bg-ac" style={{ width: Math.min(100, x.pts / 30 * 100) + '%' }} /></div><span className="tabular-nums">{x.pts.toFixed(1)} pts</span></div></td></tr>
              ))}
              {parts.length > 0 && <tr><td colSpan={3}><b>Total priority score</b></td><td><b className="tabular-nums" data-testid="why-total">{parts.reduce((a, x) => a + x.pts, 0).toFixed(0)}</b> / 100</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
      <div className="text-[11px] text-mu mt-2"><Tag>RULE-BASED</Tag> Fixed, documented weights; every number above comes from the backend (priority, inventory, allocation, routes). No machine learning is involved in this recommendation.</div>
    </Card>
  )
}
