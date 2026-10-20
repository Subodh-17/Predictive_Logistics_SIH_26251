import { Fragment, useEffect, useState } from 'react'
import { CircleMarker, MapContainer, Marker, Polyline, Popup, TileLayer, Tooltip, useMap } from 'react-leaflet'
import L from 'leaflet'
import type { Loc, Route } from '../types'
import { fx, riskColor, riskLevel, statusColor } from '../format'
import { useApp } from '../state'
import { usePalette } from '../theme'

// Tile provider configuration.
// Set VITE_TILE_URL at build time to use an alternative provider (e.g. Stadia Maps).
// Set VITE_TILE_ATTRIBUTION to the corresponding attribution HTML.
// Defaults to OpenStreetMap standard tiles, which require a valid HTTP Referer header
// (the nginx Referrer-Policy must be 'strict-origin-when-cross-origin', not 'no-referrer').
const TILE_URL = import.meta.env.VITE_TILE_URL || 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const TILE_ATTRIBUTION = import.meta.env.VITE_TILE_ATTRIBUTION ||
  '\u00a9 <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors \u00b7 fictional overlay'


const depotIcon = L.divIcon({ className: '', html: '<div class="depot-icon"></div>', iconSize: [14, 14], iconAnchor: [7, 7] })
export interface MapFocus { selected: string | null; alternatives: string[]; source?: string; dest?: string }

/** Point `frac` of the way along a polyline and the screen bearing (deg, clockwise from east) of the segment there. */
function along(coords: [number, number][], frac: number) {
  const k = Math.cos((coords[0][0] * Math.PI) / 180)
  const seg = coords.slice(1).map((c, i) => ({ a: coords[i], b: c, len: Math.hypot((c[1] - coords[i][1]) * k, c[0] - coords[i][0]) }))
  let want = seg.reduce((t, x) => t + x.len, 0) * frac
  for (const x of seg) {
    if (want <= x.len || x === seg[seg.length - 1]) {
      const t = x.len ? Math.min(1, want / x.len) : 0
      return { pos: [x.a[0] + (x.b[0] - x.a[0]) * t, x.a[1] + (x.b[1] - x.a[1]) * t] as [number, number], angle: -(Math.atan2(x.b[0] - x.a[0], (x.b[1] - x.a[1]) * k) * 180) / Math.PI }
    }
    want -= x.len
  }
  return { pos: coords[0], angle: 0 }
}
const arrowIcon = (color: string, angle: number, big: boolean) => L.divIcon({ className: '', iconSize: [18, 18], iconAnchor: [9, 9],
  html: `<div class="route-arrow" style="color:${color};transform:rotate(${angle}deg);font-size:${big ? 20 : 13}px">&#9654;</div>` })
const labelIcon = (text: string, color: string) => L.divIcon({ className: '', iconSize: [150, 16], iconAnchor: [75, 8], html: `<div class="route-label" style="color:${color};display:inline-block">${text}</div>` })
const ELEV_COLOR = ['#27413a', '#3d5a3f', '#6b6a3a', '#8a5a3a']

function Fit({ locs }: { locs: Loc[] }) {
  const map = useMap()
  useEffect(() => {
    if (locs.length) map.fitBounds(L.latLngBounds(locs.map(l => [l.lat, l.lon] as [number, number])).pad(0.18), { animate: false })
    // The size refresh is deferred; if the page is left before it fires, the map has already been removed and Leaflet would throw
    // ("_leaflet_pos" of undefined). Cancel on unmount and re-check that the container is still in the document.
    const t = window.setTimeout(() => { if (map.getContainer().isConnected) map.invalidateSize({ animate: false }) }, 50)
    return () => window.clearTimeout(t)
  }, [locs, map])
  return null
}

/** Leaflet map of the fictional network. Tile failures degrade to a plain background; the overlay keeps working.
 * Tile provider: OSM by default (requires Referrer-Policy strict-origin-when-cross-origin in nginx);
 * configurable via VITE_TILE_URL / VITE_TILE_ATTRIBUTION build-time environment variables. */
export default function LogisticsMap({ locs, routes, height = 460, focus }: { locs: Loc[]; routes: Route[]; height?: number; focus?: MapFocus }) {
  const { sel, pick } = useApp()
  const pal = usePalette()
  const [tilesFailed, setTilesFailed] = useState(0)
  const [terrain, setTerrain] = useState(true)
  const failed = tilesFailed >= 3
  return (
    <div>
      <div className="flex flex-wrap items-center gap-3 mb-2 text-[11px] text-mu">
        <label className="flex items-center gap-1.5 cursor-pointer"><input type="checkbox" checked={terrain} onChange={e => setTerrain(e.target.checked)} />Terrain / elevation layer</label>
        {failed && <span role="status" className="text-wr border border-wr px-2 py-0.5">Map tiles unavailable (offline, blocked, or provider not configured) — fictional overlay still shown on a plain background.</span>}
      </div>
      <div className="border border-ln" style={{ height }} data-testid="leaflet-map">
        <MapContainer center={[22.3, 79.0]} zoom={9} style={{ height: '100%', width: '100%' }} scrollWheelZoom>
          <TileLayer attribution={TILE_ATTRIBUTION}
            url={TILE_URL} eventHandlers={{ tileerror: () => setTilesFailed(n => n + 1), tileload: () => setTilesFailed(0) }} />
          <Fit locs={locs} />
          {terrain && routes.map(r => (
            <Polyline key={'t' + r.id} positions={r.coordinates} pathOptions={{ color: ELEV_COLOR[r.terrain.elevation_band], weight: 16 + r.terrain.difficulty * 14, opacity: 0.45, lineCap: 'round' }}>
              <Tooltip sticky>{r.terrain.type} · {r.terrain.elevation_label} · terrain risk {Math.round(r.terrain.risk * 100)}</Tooltip>
            </Polyline>
          ))}
          {routes.map(r => {
            const on = sel.kind === 'rt' && sel.id === r.id
            const isSel = !!focus && focus.selected === r.id, isAlt = !!focus && focus.alternatives.includes(r.id), dim = !!focus && !isSel && !isAlt
            const col = riskColor(r.risk), mid = along(r.coordinates, 0.62), lab = along(r.coordinates, 0.4)
            return (
              <Fragment key={r.id}>
                {isSel && <Polyline positions={r.coordinates} interactive={false} pathOptions={{ color: pal.ttBg, weight: 12, opacity: 0.9, lineCap: 'round' }} />}
                <Polyline positions={r.coordinates} eventHandlers={{ click: () => pick('rt', r.id) }}
                  pathOptions={{ color: col, weight: isSel ? 7 : isAlt ? 4 : on ? 6 : 3, dashArray: isAlt ? '3 9' : r.road_condition > 0.4 ? '7 6' : undefined, opacity: dim ? 0.3 : 0.95 }}>
                  <Popup>
                    <b>{r.id} · {r.depot} → {r.destination}</b>{isSel ? ' · SELECTED' : isAlt ? ' · alternative' : ''}<br />
                    {r.distance_km} km · ETA {r.eta_h.toFixed(1)} h (+{r.delay_h.toFixed(1)} h)<br />
                    Road {r.road_label} · weather {r.weather_level} · risk <b style={{ color: col }}>{riskLevel(r.risk)} ({Math.round(r.risk * 100)})</b><br />
                    {r.terrain.type} · {r.terrain.elevation_label} · terrain risk {Math.round(r.terrain.risk * 100)}<br />
                    Effective speed {r.effective_speed_kmh.toFixed(0)} km/h (nominal {r.nominal_speed_kmh}) · capacity {fx(r.vehicle_capacity)} units
                  </Popup>
                  <Tooltip sticky>{r.id} · {r.eta_h.toFixed(1)} h · risk {Math.round(r.risk * 100)}</Tooltip>
                </Polyline>
                {!dim && <Marker position={mid.pos} icon={arrowIcon(col, mid.angle, isSel)} interactive={false} keyboard={false} zIndexOffset={400} />}
                {(isSel || isAlt) && <Marker position={lab.pos} icon={labelIcon(`${r.id} ${isSel ? '· SELECTED' : '· alt'} · ${r.eta_h.toFixed(1)} h`, col)} interactive={false} keyboard={false} zIndexOffset={500} />}
              </Fragment>
            )
          })}
          {locs.filter(l => l.kind === 'DEPOT').map(l => (
            <Marker key={l.id} position={[l.lat, l.lon]} icon={depotIcon} title={`${l.name} (depot)`} alt={`${l.name} (depot)`}>
              <Tooltip permanent direction="bottom" offset={[0, 6]}>{l.id}{focus?.source === l.id ? ' · SOURCE' : ''}</Tooltip>
              <Popup><b>{l.name}</b><br />Depot · available vehicle capacity {fx(l.available_capacity)} units</Popup>
            </Marker>
          ))}
          {locs.filter(l => l.kind === 'FORWARD').map(l => {
            const on = sel.kind === 'loc' && sel.id === l.id
            return (
              <CircleMarker key={l.id} center={[l.lat, l.lon]} radius={on ? 14 : 11} eventHandlers={{ click: () => pick('loc', l.id) }}
                pathOptions={{ color: '#fff', weight: on ? 3 : 1.5, fillColor: statusColor(l.status), fillOpacity: 0.95 }}>
                <Tooltip permanent direction="top" offset={[0, -8]}>{l.id}{focus?.dest === l.id ? ' · DESTINATION' : ''}</Tooltip>
                <Popup>
                  <b>{l.name}</b> · <b style={{ color: statusColor(l.status) }}>{l.status}</b><br />
                  Inventory: {l.n_critical} critical · {l.n_warning} warning · {l.n_normal} normal<br />
                  Min cover {l.min_days?.toFixed(1)} d ({l.min_supply})<br />
                  Predicted shortage {fx(l.short_units)} units / 14 d · demand {fx(l.demand_per_day)} /day<br />
                  Best route {l.best_route} (risk {l.best_route_risk !== null ? Math.round(l.best_route_risk * 100) : '—'})
                </Popup>
              </CircleMarker>
            )
          })}
        </MapContainer>
      </div>
      <Note>
        <span><i className="inline-block w-2.5 h-2.5 rounded-full bg-ok mr-1" />Normal</span><span><i className="inline-block w-2.5 h-2.5 rounded-full bg-wr mr-1" />Warning</span>
        <span><i className="inline-block w-2.5 h-2.5 rounded-full bg-cr mr-1" />Critical</span><span><i className="inline-block w-2.5 h-2.5 bg-ac mr-1" />Depot</span>
        <span>▶ arrows point source → destination · route colour = route risk · dashed = poor road · wide band = terrain (darker/redder = higher elevation){focus ? ' · thick = selected route · dotted = alternative · faded = other corridors' : ''} · all locations, routes and terrain are fictional</span>
      </Note>
    </div>
  )
}
function Note({ children }: { children: React.ReactNode }) { return <div className="flex flex-wrap gap-x-3.5 text-[11px] text-mu mt-2">{children}</div> }
