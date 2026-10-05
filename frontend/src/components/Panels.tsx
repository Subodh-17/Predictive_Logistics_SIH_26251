import { dd, fx, riskColor } from '../format'
import { useApp } from '../state'
import type { Allocation, Container, Insight, Priority, Route, Why } from '../types'
import { Btn, Card, KV, Kpi, KpiGrid, LevelTag, Note, StatusTag, Table, Tag, Why as WhyBox } from './ui'

export function InsightPanel({ i, showCompare = false }: { i: Insight | null; showCompare?: boolean }) {
  const { pick } = useApp()
  if (!i) return <div className="text-[15px]">No actionable shortages under current conditions.</div>
  return (
    <div>
      <div className="mb-1.5"><Tag>RULE-BASED ENGINE</Tag> <span className="text-[11px] text-mu">not machine learning · not an LLM</span></div>
      <div className="text-[15px] mb-2">{i.headline}</div>
      <KV rows={[['Location', i.location], ['Supply', i.supply], ['Predicted demand (14 d)', `${fx(i.predicted_demand_14d)} units`], ['Current stock', `${fx(i.stock)} units`],
        ['Safety stock', `${fx(i.safety_stock)} units`], ['Expected shortage', <span className="text-cr">{i.days_cover.toFixed(1)} days · {dd(i.stockout_date)}</span>],
        ['Recommended replenishment', `${fx(i.replenish_qty)} units`], ['Source / Vehicle / Route', i.source ? `${i.source} · ${i.vehicle} · ${i.route}` : '—']]} />
      <WhyBox><b>Reason:</b> {i.reason}</WhyBox>
      {showCompare && <div className="mt-2"><Btn onClick={() => pick('loc', i.location)}>VIEW ROUTE COMPARISON →</Btn></div>}
    </div>
  )
}

export function WhyAtRisk({ why }: { why: Why }) {
  return (
    <div className="mb-3">
      <div className="mb-2"><b>{why.location}</b> <StatusTag s={why.status} /> <span className="font-mono text-mu text-[12px] ml-1">weather index {why.weather_index.toFixed(2)} · best route {why.best_route}: {why.best_route_risk_level} ({why.best_route_risk}/100)</span></div>
      <Table head={['SUPPLY', 'DEMAND Δ', 'STOCK', 'COVER', 'SAFETY', 'LEAD TIME']}>
        {why.items.map(x => (
          <tr key={x.supply}><td>{x.supply}</td><td className={x.demand_change_pct > 0 ? 'text-cr' : 'text-ok'}>{x.demand_change_pct > 0 ? '+' : ''}{x.demand_change_pct.toFixed(0)}%</td>
            <td>{fx(x.stock)}</td><td>{x.days_cover.toFixed(1)} d</td><td>{fx(x.safety)}{x.below_safety ? ' ▼' : ''}</td><td>{x.lead_days.toFixed(1)} d</td></tr>
        ))}
      </Table>
      <WhyBox>{why.summary}</WhyBox>
    </div>
  )
}

export function PriorityQueue({ rows }: { rows: Priority[] }) {
  const { pick } = useApp()
  return (
    <Card title="SUPPLY PRIORITY QUEUE · DECISION-SUPPORT PRIORITY SCORE">
      <Table head={['RANK', 'LOCATION', 'SUPPLY', 'RISK', 'PRIORITY SCORE', 'SHORTAGE HORIZON', 'BEST ROUTE', 'REPLEN.']}>
        {rows.slice(0, 10).map(p => (
          <tr key={p.location + p.supply} className="row" onClick={() => pick('loc', p.location)}>
            <td>{p.rank}</td><td>{p.location}</td><td>{p.supply}</td><td><StatusTag s={p.status} /></td>
            <td><b>{p.score}</b><div className="h-[5px] bg-bar min-w-[60px]"><i className="block h-full bg-ac" style={{ width: p.score + '%' }} /></div></td>
            <td>{p.days_cover.toFixed(1)} d · {dd(p.stockout_date)}</td><td>{p.route_feasible ? p.best_route : <span className="text-cr">NO VEHICLE</span>}</td><td>{fx(p.replenish_qty)}</td>
          </tr>
        ))}
        {!rows.length && <tr><td colSpan={8}>No at-risk items.</td></tr>}
      </Table>
      <Note>Showing {Math.min(10, rows.length)} of {rows.length} at-risk items. Score (0–100) = 100 × (0.30 shortage urgency + 0.15 shortage volume + 0.15 stock deficit + 0.15 supply criticality + 0.10 lead-time pressure + 0.10 route feasibility/risk + 0.05 transport capacity). Weights are fixed, documented assumptions of this prototype.</Note>
    </Card>
  )
}

export function AllocationPanel({ a }: { a: Allocation }) {
  const { pick } = useApp()
  const reasons = Object.entries(a.unmet_by_reason)
  return (
    <Card title="ALLOCATION PLAN">
      <div className="font-mono text-act mb-2">{a.label}</div>
      <KpiGrid>
        <Kpi label="TOTAL NEED" value={fx(a.total_need)} sub="units" /><Kpi label="FLEET CAPACITY" value={fx(a.fleet_capacity)} sub="units" />
        <Kpi label="ALLOCATED" value={fx(a.allocated)} sub="units" tone="ok" /><Kpi label="UNMET" value={fx(a.unmet)} sub={reasons.map(([k, v]) => `${k.toLowerCase()}: ${fx(v)}`).join(' · ') || 'units'} tone={a.unmet ? 'cr' : 'ok'} />
        <Kpi label="CAPACITY LEFT" value={fx(a.capacity_left)} sub="units" />
      </KpiGrid>
      <Table head={['RANK', 'LOCATION', 'SUPPLY', 'SCORE', 'SAFETY DEFICIT', 'LEAD TIME', 'NEED', 'ALLOCATED', 'UNMET', 'DISPATCH (VEHICLE VIA ROUTE)', 'STATUS']}>
        {a.rows.map(o => (
          <tr key={o.location + o.supply} className="row" onClick={() => pick('loc', o.location)}>
            <td>{o.rank}</td><td>{o.location}</td><td>{o.supply}</td><td>{o.score}</td><td>{fx(o.safety_deficit)}</td><td>{o.lead_days.toFixed(1)} d</td>
            <td>{fx(o.need)}</td><td>{fx(o.allocated)}</td><td>{fx(o.unmet)}</td><td>{o.legs.map(g => `${g.vehicle} via ${g.route}: ${fx(g.quantity)}`).join('; ') || '—'}</td>
            <td>{o.unmet === 0 ? <Tag tone="ok">FULL</Tag> : o.allocated ? <Tag tone="wr">PARTIAL</Tag> : <Tag tone="cr">NOT SERVED</Tag>}</td>
          </tr>
        ))}
        {!a.rows.length && <tr><td colSpan={11}>No allocation required.</td></tr>}
      </Table>
      <Note>
        <span>Order = priority score. NEED = safety-stock deficit + predicted demand over lead time + 5-day buffer. Routes are tried in combined-score order, only if the depot has an available vehicle; each shipment is limited by the depot's actual stock of that supply and loaded within effective vehicle capacity (smallest sufficient vehicle first).</span>
        {a.notes.map(n => <span key={n}>{n}</span>)}
      </Note>
    </Card>
  )
}

export function IotFeed({ containers, notice }: { containers: Container[]; notice: string }) {
  return (
    <Card title="SIMULATED IoT INVENTORY FEED · SYNTHETIC SENSOR DATA">
      <div className="text-wr text-[12px] mb-2">{notice}</div>
      <Table head={['CONTAINER ID', 'SOURCE', 'DESTINATION', 'SUPPLY', 'QUANTITY', 'STATUS', 'SIMULATED LAST UPDATE']}>
        {containers.map(c => (
          <tr key={c.container_id}><td className="font-mono">{c.container_id}</td><td>{c.source}</td><td>{c.destination}</td><td>{c.supply}</td><td>{fx(c.quantity)}</td>
            <td><Tag>{c.status}</Tag></td><td className="font-mono">{c.last_update_sim.slice(11, 16)}Z (sim)</td></tr>
        ))}
        {!containers.length && <tr><td colSpan={7}>No containers in the feed.</td></tr>}
      </Table>
      <Note>Simulated sensor data only. Container IDs, statuses and timestamps are generated from the allocation plan and the simulation clock.</Note>
    </Card>
  )
}

export function RouteComparison({ data }: { data: { destination: string; routes: Route[]; selected: string | null; reason: string; formula: string } }) {
  return (
    <Card title={`ROUTE OPTIMIZATION COMPARISON · FEASIBLE ROUTES TO ${data.destination}`}>
      <Table head={['ROUTE', 'FROM', 'KM', 'ETA H', 'SPEED', 'VEHICLE CAP.', 'ROAD', 'TERRAIN', 'ELEVATION', 'TERRAIN RISK', 'WEATHER RISK', 'ROUTE RISK', 'COMBINED SCORE', 'DECISION']}>
        {data.routes.map(r => (
          <tr key={r.id} className={r.id === data.selected ? 'sel' : ''}>
            <td>{r.id}</td><td>{r.depot}</td><td>{r.distance_km}</td><td>{r.eta_h.toFixed(1)}</td><td>{r.effective_speed_kmh.toFixed(0)} km/h</td><td>{fx(r.vehicle_capacity)}</td>
            <td>{r.road_label}</td><td>{r.terrain.type}</td><td>{r.terrain.elevation_label.split(' ')[0]}</td><td>{Math.round(r.terrain.risk * 100)}</td><td>{r.weather_level}</td>
            <td><LevelTag level={r.risk_level} /></td><td>{r.combined_score?.toFixed(2)}</td>
            <td>{r.decision === 'NO VEHICLE' ? <span className="text-cr">NO VEHICLE</span> : r.decision === 'SELECTED' ? <b className="text-ok">SELECTED</b> : 'Alternative'}</td>
          </tr>
        ))}
      </Table>
      <div className="mt-2"><WhyBox><b>Why selected:</b> {data.reason} {data.formula}. Only routes whose depot has an available vehicle are feasible; the same rule drives the recommendation engine.</WhyBox></div>
    </Card>
  )
}

export const riskStyle = (r: number) => ({ color: riskColor(r) })
