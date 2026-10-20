import { Fragment } from 'react'
import { useApp } from '../state'
import { usePalette } from '../theme'
import { useApi } from '../api'
import type { Allocation, Container, Dashboard as Dash, Insight, Loc, Priority, Route, Why } from '../types'
import { Async, Card, ErrorBox, Grid2, GridHalf, Kpi, KpiGrid, PageTitle, StatusTag, Table, act } from '../components/ui'
import { dd, fx } from '../format'
import { LineChartBox } from '../components/Charts'
import LogisticsMap from '../components/LogisticsMap'
import { AllocationPanel, InsightPanel, IotFeed, PriorityQueue, WhyAtRisk } from '../components/Panels'
import CommandBriefing, { type AlertsData } from '../components/CommandBriefing'
import DecisionFlow from '../components/DecisionFlow'
import WhyRecommendation from '../components/WhyRecommendation'
import { buildActions } from '../recommend'
import type { InvItem, Vehicle } from '../types'

export default function Dashboard() {
  const pal = usePalette()
  const { sq, refreshKey, pick } = useApp()
  const dash = useApi<Dash>('/api/dashboard' + sq, refreshKey)
  const locs = useApi<Loc[]>('/api/locations' + sq, refreshKey)
  const routes = useApi<Route[]>('/api/routes' + sq, refreshKey)
  const alerts = useApi<AlertsData>('/api/alerts' + sq, refreshKey)
  const inv = useApi<InvItem[]>('/api/inventory' + sq, refreshKey)
  const ins = useApi<{ top: Insight | null; dispatch: Insight[]; why_at_risk: Why[]; engine: string }>('/api/insights' + sq, refreshKey)
  const veh = useApi<Vehicle[]>('/api/vehicles' + sq, refreshKey)
  const prio = useApi<Priority[]>('/api/priority' + sq, refreshKey)
  const alloc = useApi<Allocation>('/api/allocation' + sq, refreshKey)
  const feed = useApi<{ notice: string; containers: Container[] }>('/api/iot/feed' + sq, refreshKey)
  const actions = buildActions(prio.data, alloc.data, routes.data)
  if (dash.error && !dash.data) return <div><PageTitle>COMMAND DASHBOARD · PREDICTIVE LOGISTICS</PageTitle><ErrorBox error={dash.error} onRetry={dash.reload} /></div>
  return (
    <div>
      <PageTitle>COMMAND DASHBOARD · PREDICTIVE LOGISTICS</PageTitle>
      <DecisionFlow dash={dash.data} prio={prio.data} alloc={alloc.data} actions={actions} />
      <CommandBriefing dash={dash.data} locs={locs.data} inv={inv.data} alerts={alerts.data} actions={actions} />
      <WhyRecommendation prio={prio.data} inv={inv.data} alloc={alloc.data} routes={routes.data} vehicles={veh.data} />
      <Async state={dash} what="dashboard">{d => { const k = d.kpis; return (<>
        <KpiGrid>
          <Kpi label="LOCATIONS" value={fx(k.locations as number)} sub={`${k.depots} depots · ${k.forward} forward`} />
          <Kpi label="CRITICAL SHORTAGES" value={fx(k.critical_shortages as number)} sub="items < 3 d cover" tone="cr" />
          <Kpi label="WARNING LOCATIONS" value={fx(k.warning_locations as number)} sub={`${k.critical_locations} critical`} tone="wr" />
          <Kpi label="VEHICLES AVAILABLE" value={`${k.vehicles_available} / ${k.vehicles_total}`} sub="fleet" />
          <Kpi label="TRANSPORT CAPACITY" value={fx(k.transport_capacity as number)} sub="units / dispatch" />
          <Kpi label="SUPPLIES AT RISK" value={fx(k.supplies_at_risk_units as number)} sub="units short · 14 d" />
          <Kpi label="OVERALL LOGISTICS RISK" value={`${k.risk_index} / 100`} sub={k.risk_band as string} tone={k.risk_level as 'ok' | 'wr' | 'cr'} />
        </KpiGrid></>) }}</Async>

      <Grid2>
        <Card title="GIS OVERVIEW · SUPPLY RISK (FICTIONAL · SIMULATED)">
          <Async state={locs} what="locations">{l => <Async state={routes} what="routes">{r => <LogisticsMap locs={l} routes={r} height={380} />}</Async>}</Async>
        </Card>
        <Card title="CRITICAL ALERTS · TOP URGENT" action={<Async state={alerts}>{a => <span className="font-mono text-[10px] bg-cr/10 text-cr border border-cr/30 px-2 py-0.5 rounded-xs font-semibold">{a.critical} TOTAL</span>}</Async>}>
          <Async state={alerts} what="alerts">{a => {
            const allCrit = a.alerts.filter(x => x.severity === 'CRITICAL')
            const crit = allCrit.slice(0, 6)
            return crit.length ? <>
              {crit.map(x => (
                <div key={x.location + x.supply} className="p-2.5 border-l-[3px] border-cr bg-ins/90 hover:bg-hov rounded-sm mb-2 cursor-pointer transition-all duration-75" {...act(() => pick('loc', x.location))}>
                  <div className="flex items-center justify-between">
                    <b className="font-medium text-tx">{x.location} · {x.supply}</b>
                    <span className="font-mono text-[10px] text-cr uppercase font-semibold">CRITICAL</span>
                  </div>
                  <small className="block text-soft text-[11px] mt-1">{x.days_cover.toFixed(1)} d cover · stock-out {dd(x.stockout_date)} · lead {x.lead_days.toFixed(1)} d</small>
                </div>))}
              {allCrit.length > 6 && (
                <div className="text-[11px] text-mu mt-2 border-t border-ln/60 pt-1.5 flex items-center justify-between">
                  <span>Showing top 6 of {allCrit.length} critical items</span>
                  <span className="font-mono text-[10px] text-act">RANKED BY COVER</span>
                </div>
              )}
            </> : <div className="p-3 border-l-[3px] border-ok bg-ins/90 rounded-sm text-soft text-[12px]">No critical alerts</div>
          }}</Async>
        </Card>
      </Grid2>

      <Grid2>
        <Card title="PREDICTED SHORTAGES · SUPPLY RISK">
          <Async state={inv} what="inventory">{items => (
            <Table head={['LOCATION', 'SUPPLY', 'STOCK', 'PRED. DEMAND (14 D)', 'SAFETY', 'SHORTAGE DATE', 'REPLEN.']}>
              {items.filter(i => i.status !== 'NORMAL').slice(0, 8).map(i => (
                <tr key={i.location + i.supply} className="row" {...act(() => pick('loc', i.location))}>
                  <td>{i.location}</td><td>{i.supply}</td><td>{fx(i.stock)}</td><td>{fx(i.daily_use * 14)}</td><td>{fx(i.safety_stock)}</td>
                  <td>{dd(i.stockout_date)} <StatusTag s={i.status} /></td><td>{fx(i.replenish_qty)}</td></tr>))}
            </Table>)}</Async>
        </Card>
        <Card title="AI LOGISTICS INSIGHT · RULE-BASED DECISION SUPPORT (NOT ML / LLM)" accent>
          <Async state={ins} what="insight">{i => <InsightPanel i={i.top} showCompare />}</Async>
        </Card>
      </Grid2>

      <Grid2>
        <Card title="DEMAND FORECAST · ALL LOCATIONS · 14 D">
          <Async state={dash} what="forecast">{d => <LineChartBox zoom data={d.forecast_chart as never} lines={[{ key: 'actual', name: 'Actual', color: pal.tx }, { key: 'forecast', name: d.scenario_active ? 'Predicted (scenario)' : 'Predicted', color: pal.accent, dashed: true }]} />}</Async>
        </Card>
        <Card title="TRANSPORT STATUS">
          <Async state={veh} what="vehicles">{vs => (<>
            {vs.map(v => (
              <div key={v.id} className="mb-2"><span className="font-mono">{v.id}</span> · {v.depot_id} <span className="float-right">{v.available ? `${fx(v.effective_capacity)} / ${fx(v.capacity)}` : <span className="text-cr">MAINTENANCE</span>}</span>
                <div className="h-1.5 bg-bar mt-1"><i className="block h-full bg-ac" style={{ width: (v.capacity ? v.effective_capacity / v.capacity * 100 : 0) + '%' }} /></div></div>))}
            <Async state={dash}>{d => <div className="border-t border-dashed border-ln pt-2">Replenishment need <b>{fx(d.kpis.transport_need as number)}</b> vs capacity <b>{fx(d.kpis.transport_capacity as number)}</b> units · {(d.kpis.capacity_deficit as number) ? <span className="text-cr">deficit {fx(d.kpis.capacity_deficit as number)}</span> : <span className="text-ok">sufficient</span>}</div>}</Async></>)}</Async>
        </Card>
      </Grid2>

      <Card title="RULE-BASED INSIGHTS · PRIORITISED DISPATCH" className="mb-3">
        <Async state={ins} what="insights">{i => i.dispatch.length ? <>{i.dispatch.map(x => (
          <div key={x.location + x.supply} className={`p-2 border-l-[3px] bg-ins mb-1.5 ${x.status === 'CRITICAL' ? 'border-cr' : 'border-wr'}`}>
            <b>{x.location} · {x.supply}</b> — {x.days_cover.toFixed(1)} d cover. Dispatch {fx(x.replenish_qty)} units from {x.source ?? '—'} using {x.vehicle ?? '—'} on {x.route ?? '—'}.<small className="block text-mu">{x.reason}</small></div>))}
          <div className="text-[11px] text-mu">{i.engine}</div></> : 'No actions required.'}</Async>
      </Card>

      <div className="mb-3"><Async state={prio} what="priority queue">{p => <PriorityQueue rows={p} />}</Async></div>
      <div className="mb-3"><Async state={alloc} what="allocation">{a => <AllocationPanel a={a} />}</Async></div>
      <div className="mb-3"><Async state={feed} what="IoT feed">{f => <IotFeed containers={f.containers} notice={f.notice} />}</Async></div>

      <GridHalf>
        <Card title="WHY AT RISK · EXPLAINABLE RISK"><Async state={ins} what="explanations">{i => i.why_at_risk.length ? <>{i.why_at_risk.map(w => <WhyAtRisk key={w.location} why={w} />)}</> : 'No locations at warning or critical level.'}</Async></Card>
        <div className="grid gap-3 content-start">
          <Card title="SYSTEM STATUS"><Async state={dash}>{d => (
            <Table head={['ENGINE', 'STATE', 'DETAIL']}>{d.system_status.map(h => (
              <tr key={h.engine}><td>{h.engine}</td><td><span className={`inline-block w-2 h-2 rounded-full mr-1.5 ${h.ok ? 'bg-ok' : 'bg-cr'}`} />{h.ok ? 'OPERATIONAL' : 'DEGRADED'}</td><td>{h.detail}</td></tr>))}</Table>)}</Async></Card>
          <Card title="DATA COVERAGE"><Async state={dash}>{d => (
            <div className="grid grid-cols-[auto_1fr] gap-x-3.5 gap-y-1">{Object.entries(d.data_coverage).map(([k, v]) => <Fragment key={k}><span className="text-mu">{k.replace(/_/g, ' ')}</span><div>{fx(v)}</div></Fragment>)}</div>)}</Async></Card>
        </div>
      </GridHalf>

      <Card title="DATA PIPELINE"><Async state={dash}>{d => (
        <div className="flex flex-wrap gap-2.5 items-stretch">{d.pipeline.map((p, idx) => (
          <div key={p.stage} className="border border-ln/70 bg-pn2/80 rounded-sm px-3 py-2 flex-1 min-w-[130px] shadow-xs">
            <span className="block font-mono text-[9px] text-mu uppercase tracking-wider mb-0.5">{`STAGE 0${idx + 1}`}</span>
            <b className="block text-[12.5px] font-semibold text-tx">{p.stage}</b>
            <small className="text-soft text-[11px] block mt-0.5">{p.detail}</small>
          </div>))}</div>)}</Async></Card>
    </div>
  )
}
