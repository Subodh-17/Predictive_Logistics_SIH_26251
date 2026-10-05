import { useEffect, useState } from 'react'
import { ApiError, get } from './api'
import { AppProvider, useApp, type Tab } from './state'
import { ThemeProvider, useTheme } from './theme'
import type { Health } from './types'
import { Btn } from './components/ui'
import { roadLabel, weatherLabel } from './format'
import Dashboard from './pages/Dashboard'
import Forecast from './pages/Forecast'
import Gis from './pages/Gis'
import Inventory from './pages/Inventory'
import Simulation from './pages/Simulation'

const NAV: [Tab, string][] = [['dash', 'Command Dashboard'], ['fc', 'Demand Forecast'], ['gis', 'GIS Logistics'], ['inv', 'Inventory'], ['sim', 'What-If Simulation']]
const T0 = Date.UTC(2026, 5, 19, 6, 0)
const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']

function SimClock() {
  const [t0] = useState(Date.now())
  const [, tick] = useState(0)
  useEffect(() => { const i = setInterval(() => tick(n => n + 1), 1000); return () => clearInterval(i) }, [])
  // Same underlying synthetic clock as before; only the label is date-level so it can never be mistaken for a live timestamp.
  const d = new Date(T0 + (Date.now() - t0) * 60)
  return <b className="text-tx" data-testid="sim-clock">{d.getUTCDate()} {MONTHS[d.getUTCMonth()]} {d.getUTCFullYear()}</b>
}

function ThemeToggle() {
  const { theme, toggle } = useTheme()
  const light = theme === 'light'
  return (
    <button type="button" role="switch" aria-checked={light} data-testid="theme-toggle" onClick={toggle}
      aria-label={light ? 'Light theme active. Switch to dark theme' : 'Dark theme active. Switch to light theme'}
      className="mt-3 md:mt-4 mx-1.5 flex items-center gap-2 border border-ln bg-pn2 text-tx px-2.5 py-1.5 cursor-pointer text-[12px] hover:border-mu w-[calc(100%-12px)]">
      <span aria-hidden className="inline-block w-7 h-3.5 border border-mu rounded-full relative"><i className={`absolute top-px w-2.5 h-2.5 rounded-full bg-act ${light ? 'left-[14px]' : 'left-px'}`} /></span>
      <span className="font-mono tracking-wide">{light ? 'LIGHT THEME' : 'DARK THEME'}</span>
    </button>
  )
}

function Shell() {
  const { tab, go, scenario, scenarioActive, resetScenario, refreshKey } = useApp()
  const [health, setHealth] = useState<Health | null>(null)
  const [hErr, setHErr] = useState<ApiError | null>(null)
  const [crit, setCrit] = useState<number | null>(null)
  useEffect(() => {
    let alive = true
    const poll = () => get<Health>('/api/health').then(h => { if (alive) { setHealth(h); setHErr(null) } }).catch(e => { if (alive) { setHErr(e); setHealth(null) } })
    poll(); const i = setInterval(poll, 10000)
    return () => { alive = false; clearInterval(i) }
  }, [])
  useEffect(() => { get<{ kpis: { critical_shortages: number } }>('/api/dashboard').then(d => setCrit(d.kpis.critical_shortages)).catch(() => setCrit(null)) }, [refreshKey])
  const down = hErr !== null || (health !== null && health.status !== 'ok')
  const page = { dash: <Dashboard />, fc: <Forecast />, gis: <Gis />, inv: <Inventory />, sim: <Simulation /> }[tab]
  return (
    <div className="grid min-h-screen grid-cols-1 md:grid-cols-[200px_1fr]">
      <aside className="bg-side border-b md:border-b-0 md:border-r border-ln p-3.5 md:px-2.5">
        <h1 className="text-[12px] tracking-[.14em] text-act mx-1.5 mb-3.5 leading-tight font-semibold">PREDICTIVE LOGISTICS<br />DECISION SUPPORT</h1>
        <nav className="flex flex-wrap md:block gap-1" aria-label="Modules">
          <small className="hidden md:block font-mono text-mu text-[10px] tracking-[.12em] mx-1.5 mt-3 mb-1">MODULES</small>
          {NAV.map(([k, label]) => (
            <button key={k} onClick={() => go(k)} aria-current={tab === k ? 'page' : undefined}
              className={`md:block md:w-full text-left border-l-2 px-2.5 py-2 cursor-pointer text-[13px] ${tab === k ? 'border-ac bg-hov text-hi' : 'border-transparent hover:bg-pn2'}`}>{label}</button>))}
          <small className="hidden md:block font-mono text-mu text-[10px] tracking-[.12em] mx-1.5 mt-3 mb-1">DATA</small>
          <div className="hidden md:block px-2 text-mu text-[11px]">Synthetic / fictional.<br />No real operational data.</div>
        </nav>
        <ThemeToggle />
      </aside>
      <main className="min-w-0 flex flex-col">
        <div className="flex flex-wrap gap-x-4 gap-y-1 items-center px-4 py-2 border-b border-ln bg-side font-mono text-[11px] text-mu sticky top-0 z-[1000]">
          <span><span className={`inline-block w-2 h-2 rounded-full mr-1.5 ${down ? 'bg-cr' : 'bg-ok'}`} /><b className="text-tx">{hErr?.code === 'BACKEND_UNREACHABLE' ? 'BACKEND OFFLINE' : down ? 'DATABASE OFFLINE' : health ? 'ENGINE NOMINAL' : 'CONNECTING…'}</b></span>
          <span>API <b className="text-tx">{hErr ? 'DOWN' : health ? 'UP' : '…'}</b></span>
          <span>DB <b className="text-tx" data-testid="db-status">{health?.database.connected ? 'POSTGIS ' + (health.database.postgis?.split(' ')[0] ?? '') : hErr || health ? 'DOWN' : '…'}</b></span>
          <span title="Fictional clock anchored at 2026-06-19 06:00 UTC and advancing at 60x. It is NOT the real time.">SIMULATION TIME · <SimClock /></span><span>DATA · <b className="text-tx">SYNTHETIC</b></span><span>IoT <b className="text-tx">SIMULATED</b></span>
          {crit !== null && <span role="button" tabIndex={0} onClick={() => go('dash')} className="cursor-pointer border border-cr text-cr px-2 rounded-sm">▲ {crit} CRITICAL</span>}
        </div>
        {down && <div role="alert" className="bg-errbg border-b border-cr text-errtx px-4 py-1.5 text-[12px]">
          {hErr?.code === 'BACKEND_UNREACHABLE' ? 'Backend unavailable — start it with `docker compose up --build`.' : 'Database unavailable — the API is up but PostgreSQL/PostGIS is not responding.'}</div>}
        {scenarioActive && <div className="bg-warnbg border-b border-wr text-wr px-4 py-1.5 text-[12px] flex gap-3 items-center flex-wrap">
          SCENARIO ACTIVE — demand +{Math.round(scenario.demand * 100)}% · weather {weatherLabel(scenario.weather)} · road {roadLabel(scenario.road)} · fleet {Math.round(scenario.vehicles * 100)}%
          <Btn onClick={resetScenario}>Clear</Btn></div>}
        <div className="px-4 pt-3.5 pb-8 flex-1">{page}</div>
        <div className="sticky bottom-0 bg-footbg border-t border-ac text-act px-4 py-1.5 text-[12px] z-[1000]">
          <b>Decision Support Only</b> — Prototype uses fictional synthetic logistics data and is intended for decision-support demonstration only. Final logistics decisions remain with authorized personnel.</div>
      </main>
    </div>
  )
}
export default function App() { return <ThemeProvider><AppProvider><Shell /></AppProvider></ThemeProvider> }
