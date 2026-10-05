import { useApi } from '../api'
import { useApp } from '../state'
import { Async, Card, ErrorBox, Grid2, KV, LevelTag, Note, PageTitle, StatusTag, Table } from '../components/ui'
import LogisticsMap from '../components/LogisticsMap'
import { InsightPanel, RouteComparison, WhyAtRisk } from '../components/Panels'
import RouteSelection, { type Compare } from '../components/RouteSelection'
import type { MapFocus } from '../components/LogisticsMap'
import { fx, riskColor } from '../format'
import type { InvItem, Insight, Loc, Route, Why } from '../types'

interface LocDetail { location: Loc; items: InvItem[]; why_at_risk: Why | null; insight: Insight | null; routes_to: Route[] }

export default function Gis() {
  const { sel, sq, pick, refreshKey } = useApp()
  const locs = useApi<Loc[]>('/api/locations' + sq, refreshKey)
  const routes = useApi<Route[]>('/api/routes' + sq, refreshKey)
  const dest = sel.kind === 'loc' ? sel.id : routes.data?.find(r => r.id === sel.id)?.destination ?? null
  const detail = useApi<LocDetail>(sel.kind === 'loc' ? `/api/locations/${sel.id}` + sq : null, refreshKey)
  const cmp = useApi<Compare>(dest ? '/api/routes/compare' + (sq ? sq + '&' : '?') + 'destination=' + dest : null, refreshKey)
  const selRoute = cmp.data?.routes.find(r => r.id === cmp.data?.selected)
  const focus: MapFocus | undefined = cmp.data && selRoute ? { selected: cmp.data.selected, alternatives: cmp.data.routes.filter(r => r.id !== cmp.data?.selected).map(r => r.id), source: selRoute.depot, dest: cmp.data.destination } : undefined
  const route = sel.kind === 'rt' ? routes.data?.find(r => r.id === sel.id) : undefined
  if (locs.error && !locs.data) return <div><PageTitle>SIMULATED GIS LOGISTICS VIEW · ROUTE RISK</PageTitle><ErrorBox error={locs.error} onRetry={() => { locs.reload(); routes.reload() }} /></div>
  return (
    <div>
      <PageTitle>SIMULATED GIS LOGISTICS VIEW · ROUTE RISK</PageTitle>
      <Grid2>
        <Card title="SIMULATED GIS LOGISTICS VIEW · FICTIONAL LOCATIONS & ROUTES">
          {selRoute && cmp.data && (
            <div data-testid="route-banner" className="mb-2 border border-ln bg-ins px-3 py-1.5 text-[12px]">
              <b className="text-act font-mono">SELECTED ROUTE {selRoute.id}</b> · {selRoute.depot} <span className="text-act">→</span> {selRoute.destination} · {selRoute.distance_km} km · ETA {selRoute.eta_h.toFixed(1)} h · risk <b>{selRoute.risk_level}</b> ({Math.round(selRoute.risk * 100)})
              {focus && focus.alternatives.length > 0 ? <> · alternatives (dotted): {focus.alternatives.join(', ')}</> : <> · single corridor, no alternative</>}
            </div>)}
          <Async state={locs} what="locations">{l => <Async state={routes} what="routes">{r => <LogisticsMap locs={l} routes={r} height={520} focus={focus} />}</Async>}</Async>
          <Note>All depots, forward locations, coordinates, roads and terrain are fictional and generated for this prototype.</Note>
        </Card>
        <div className="grid gap-3 content-start min-w-0">
          {sel.kind === 'loc' && <Async state={detail} what="location detail">{d => { const l = d.location; return (<>
            <Card title={`${l.id} · LOCATION STATUS`}>
              <div className="mb-2"><StatusTag s={l.status} /></div>
              <KV rows={[['Inventory status', `${l.n_critical} critical · ${l.n_warning} warning · ${l.n_normal} normal`], ['Days remaining (min)', `${l.min_days?.toFixed(1)} d (${l.min_supply})`],
                ['Predicted shortage', `${fx(l.short_units)} units / 14 d`], ['Demand', `${fx(l.demand_per_day)} units / day`], ['Risk level', l.status ?? '—']]} />
              <Table head={['SUPPLY', 'DAYS', 'STATUS']}>{d.items.slice(0, 5).map(i => <tr key={i.supply}><td>{i.supply}</td><td>{i.days_left.toFixed(1)}</td><td><StatusTag s={i.status} /></td></tr>)}</Table>
            </Card>
            {d.why_at_risk && <Card title="WHY AT RISK"><WhyAtRisk why={d.why_at_risk} /></Card>}
            <Card title="AI LOGISTICS INSIGHT · RULE-BASED (NOT ML / LLM)" accent><InsightPanel i={d.insight} /></Card></>) }}</Async>}
          {sel.kind === 'rt' && route && (
            <Card title={`${route.id} · ROUTE RISK`}>
              <div className="mb-2"><LevelTag level={route.risk_level} /></div>
              <KV rows={[['Corridor', `${route.depot} → ${route.destination}`], ['Distance', `${route.distance_km} km`], ['Est. travel time', `${route.eta_h.toFixed(1)} h (+${route.delay_h.toFixed(1)} h delay)`],
                ['Terrain type', route.terrain.type], ['Terrain difficulty', `${Math.round(route.terrain.difficulty * 100)} / 100`], ['Elevation category', route.terrain.elevation_label],
                ['Terrain risk score', `${Math.round(route.terrain.risk * 100)} / 100`], ['Effective speed', `${route.effective_speed_kmh.toFixed(0)} km/h (nominal ${route.nominal_speed_kmh})`],
                ['Road condition', route.road_label], ['Weather risk', route.weather_level], ['Vehicle capacity', `${fx(route.vehicle_capacity)} units at ${route.depot}`],
                ['Route risk', <span style={{ color: riskColor(route.risk) }}>{Math.round(route.risk * 100)} / 100</span>], ['PostGIS polyline length', route.geo_length_km ? `${route.geo_length_km} km (straight-line, on the spheroid)` : '—']]} />
              <Note>Route risk = 0.25 × road + 0.25 × weather + 0.30 × terrain + 0.20 × distance factor. Terrain also lowers speed, which raises ETA. Elevation bands are fictional.</Note>
            </Card>)}
          {sel.kind === 'rt' && !route && <Async state={routes}>{() => <Card>Unknown route.</Card>}</Async>}
        </div>
      </Grid2>
      <Async state={cmp} what="route selection">{c => <RouteSelection data={c} />}</Async>
      <div className="mb-3"><Async state={cmp} what="route comparison">{c => <RouteComparison data={c} />}</Async></div>
      <Card title="ROUTES · TRANSPORT"><Async state={routes} what="routes">{rs => (
        <Table head={['ID', 'FROM', 'TO', 'KM', 'ETA H', 'ROAD', 'TERRAIN · RISK', 'WEATHER', 'CAPACITY', 'RISK']}>
          {rs.map(r => (
            <tr key={r.id} className={`row ${sel.kind === 'rt' && sel.id === r.id ? 'sel' : ''}`} onClick={() => pick('rt', r.id)}>
              <td>{r.id}</td><td>{r.depot}</td><td>{r.destination}</td><td>{r.distance_km}</td><td>{r.eta_h.toFixed(1)}</td><td>{r.road_label}</td>
              <td>{r.terrain.type} · {Math.round(r.terrain.risk * 100)}</td><td>{r.weather_level}</td><td>{fx(r.vehicle_capacity)}</td><td><LevelTag level={r.risk_level} /></td></tr>))}
        </Table>)}</Async></Card>
    </div>
  )
}
