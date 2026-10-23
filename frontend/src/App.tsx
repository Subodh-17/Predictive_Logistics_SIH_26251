import { lazy, Suspense, useEffect, useState } from 'react'
import { ApiError, get } from './api'
import { AuthProvider, useAuth, type Role } from './auth'
import { AppProvider, useApp, type Tab } from './state'
import { ThemeProvider, useTheme } from './theme'
import type { Health } from './types'
import { Btn, Loading } from './components/ui'
import { roadLabel, weatherLabel } from './format'
import Login from './pages/Login'

const Dashboard = lazy(() => import('./pages/Dashboard'))
const Forecast = lazy(() => import('./pages/Forecast'))
const Gis = lazy(() => import('./pages/Gis'))
const Inventory = lazy(() => import('./pages/Inventory'))
const Simulation = lazy(() => import('./pages/Simulation'))
const Models = lazy(() => import('./pages/Models'))
const System = lazy(() => import('./pages/System'))
const Users = lazy(() => import('./pages/Users'))

const NAV: [Tab, string, Role][] = [
  ['dash', 'Command Dashboard', 'viewer'],
  ['fc', 'Demand Forecast', 'viewer'],
  ['gis', 'GIS Logistics', 'viewer'],
  ['inv', 'Inventory', 'viewer'],
  ['sim', 'What-If Simulation', 'viewer'],
  ['mdl', 'Model Evaluation', 'viewer'],
  ['sys', 'System & Account', 'viewer'],
  ['usr', 'User Administration', 'admin'],
]

const ICONS: Record<Tab, React.ReactNode> = {
  dash: <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" /></svg>,
  fc: <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 12l3-3 3 3 4-4M8 21l4-4 4 4M3 4h18M4 4h16v12a1 1 0 01-1 1H5a1 1 0 01-1-1V4z" /></svg>,
  gis: <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" /></svg>,
  inv: <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" /></svg>,
  sim: <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" /></svg>,
  mdl: <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z" /></svg>,
  sys: <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2m-2-4h.01M17 16h.01" /></svg>,
  usr: <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" /></svg>,
}
const T0 = Date.UTC(2026, 5, 19, 6, 0)
const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']

function SimClock() {
  const [t0] = useState(Date.now())
  const [, tick] = useState(0)
  useEffect(() => { const i = setInterval(() => tick(n => n + 1), 1000); return () => clearInterval(i) }, [])
  // Scenario clock (not real time); only the date is shown so it can never be mistaken for a live timestamp.
  const d = new Date(T0 + (Date.now() - t0) * 60)
  return <b className="text-tx tracking-wider" data-testid="sim-clock">{d.getUTCDate()} {MONTHS[d.getUTCMonth()]} {d.getUTCFullYear()}</b>
}

function ThemeToggle() {
  const { theme, toggle } = useTheme()
  const light = theme === 'light'
  return (
    <button type="button" role="switch" aria-checked={light} data-testid="theme-toggle" onClick={toggle}
      aria-label={light ? 'Light theme active. Switch to dark theme' : 'Dark theme active. Switch to light theme'}
      className="mt-3 md:mt-4 mx-1.5 flex items-center justify-between border border-ln bg-pn2 text-tx px-2.5 py-1.5 rounded-sm cursor-pointer text-[12px] hover:border-mu w-[calc(100%-12px)] transition-colors">
      <span className="font-mono tracking-wider font-semibold text-[11px]">{light ? 'LIGHT THEME' : 'DARK THEME'}</span>
      <span aria-hidden className="inline-block w-7 h-3.5 border border-mu/70 rounded-full relative bg-pn">
        <i className={`absolute top-px w-2.5 h-2.5 rounded-full bg-act transition-all duration-150 ${light ? 'left-[14px]' : 'left-px'}`} />
      </span>
    </button>
  )
}

function Shell() {
  const { tab, go, scenario, scenarioActive, resetScenario, refreshKey } = useApp()
  const { user, logout, can } = useAuth()
  const [outErr, setOutErr] = useState<string | null>(null)
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
  const [model, setModel] = useState<{ id: string; family: string } | null>(null)
  useEffect(() => { get<{ active_forecast_model: { model_id: string; family: string } }>('/api/ml/models').then(m => setModel({ id: m.active_forecast_model.model_id, family: m.active_forecast_model.family })).catch(() => setModel(null)) }, [refreshKey])
  useEffect(() => { document.title = `${NAV.find(n => n[0] === tab)?.[1] ?? ''} · Predictive Logistics Decision Support` }, [tab])
  const down = hErr !== null || (health !== null && health.status !== 'ok')
  const fcStatus = health?.components?.forecast_model?.status
  const page = {
    dash: <Dashboard />,
    fc: <Forecast />,
    gis: <Gis />,
    inv: <Inventory />,
    sim: <Simulation />,
    mdl: <Models />,
    sys: <System />,
    usr: can('admin') ? <Users /> : <div role="alert" className="border border-wr bg-warnbg p-4 rounded-sm text-wr">User administration requires the admin role.</div>
  }[tab]

  return (
    <>
    <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:z-[2000] focus:bg-pn focus:text-tx focus:px-3 focus:py-2 focus:border focus:border-ac">Skip to main content</a>
    <div className="grid min-h-screen grid-cols-1 md:grid-cols-[210px_1fr]">
      <aside className="bg-side border-b md:border-b-0 md:border-r border-ln p-3.5 md:px-2.5 flex flex-col justify-between">
        <div>
          <div className="flex items-center gap-2 mx-1.5 mb-4 pb-2 border-b border-ln/60">
            <span className="w-2.5 h-2.5 rounded-sm bg-ac shadow-[0_0_8px_rgba(206,168,78,0.7)] flex-shrink-0" />
            <h1 className="text-[12px] tracking-[.14em] text-act leading-tight font-bold font-mono uppercase">
              PREDICTIVE LOGISTICS<br />
              <span className="text-[10px] text-mu font-normal tracking-wider">DECISION SUPPORT</span>
            </h1>
          </div>
          <nav className="flex flex-wrap md:block gap-1" aria-label="Modules">
            <small className="hidden md:block font-mono text-mu text-[10px] tracking-[.14em] uppercase mx-1.5 mt-2 mb-1.5 font-semibold">MODULES</small>
            {NAV.filter(n => can(n[2])).map(([k, label]) => (
              <button key={k} onClick={() => go(k)} aria-current={tab === k ? 'page' : undefined}
                className={`flex items-center gap-2.5 md:w-full text-left border-l-2 px-2.5 py-2 cursor-pointer text-[12.5px] rounded-r-sm transition-all duration-100 ${tab === k ? 'border-ac bg-hov text-hi font-semibold shadow-[inset_0_1px_0_0_rgba(255,255,255,0.05)]' : 'border-transparent text-tx/80 hover:bg-pn2 hover:text-tx'}`}>
                <span className={tab === k ? 'text-act' : 'text-mu'}>{ICONS[k]}</span>
                <span>{label}</span>
              </button>))}
            <small className="hidden md:block font-mono text-mu text-[10px] tracking-[.14em] uppercase mx-1.5 mt-4 mb-1 font-semibold">DATA</small>
            <div className="hidden md:block px-2 text-mu text-[11px] leading-relaxed">Illustrative scenario.<br />Not operational records.</div>
          </nav>
        </div>
        <div>
          <ThemeToggle />
          <div className="mt-4 mx-1.5 text-[12px] border-t border-ln pt-3 bento-card p-2.5" data-testid="user-box">
            <div className="text-mu text-[10px] tracking-[.14em] font-mono uppercase font-semibold">SIGNED IN</div>
            <div className="text-tx font-bold break-all mt-0.5" data-testid="user-name">{user?.username}</div>
            <div className="text-mu text-[11px] font-mono uppercase mb-2" data-testid="user-role">{user?.role}</div>
            <Btn onClick={() => { setOutErr(null); logout().catch(() => setOutErr('Sign-out failed. Try again.')) }}>SIGN OUT</Btn>
            {outErr && <div role="alert" className="text-cr mt-1 text-[11.5px]">{outErr}</div>}
          </div>
        </div>
      </aside>
      <main id="main" tabIndex={-1} className="min-w-0 flex flex-col outline-none">
        <div className="flex flex-wrap gap-x-4 gap-y-1.5 items-center px-4 py-2 border-b border-ln bg-side/95 backdrop-blur-md font-mono text-[11px] text-mu sticky top-0 z-[1000] shadow-sm">
          <span className="flex items-center">
            <span className={`inline-block w-2 h-2 rounded-full mr-2 ${down ? 'bg-cr' : 'bg-ok animate-pulse shadow-[0_0_6px_rgba(52,199,123,0.6)]'}`} />
            <b className="text-tx">{hErr?.code === 'BACKEND_UNREACHABLE' ? 'SERVICE UNREACHABLE' : hErr?.code === 'NOT_READY' ? 'STARTING UP' : down ? 'DATABASE OFFLINE' : fcStatus === 'fallback_to_statistical' ? 'FALLBACK ACTIVE' : health ? 'ENGINE NOMINAL' : 'CONNECTING…'}</b>
          </span>
          <span>API <b className="text-tx">{hErr ? 'DOWN' : health ? 'UP' : '…'}</b></span>
          <span>DB <b className="text-tx" data-testid="db-status">{health?.database.connected ? 'POSTGIS ' + (health.database.postgis?.split(' ')[0] ?? '') : hErr || health ? 'DOWN' : '…'}</b></span>
          <span className="px-2 py-0.5 border border-ln/60 rounded-sm bg-pn2/40" title="Fictional clock anchored at 2026-06-19 06:00 UTC and advancing at 60x. It is NOT the real time.">SIMULATION TIME · <SimClock /></span>
          <span>DATA · <b className="text-tx">ILLUSTRATIVE SCENARIO</b></span>
          <span>IoT <b className="text-tx">SIMULATED</b></span>
          <span title="Forecast model driving inventory, alerts and recommendations">FORECAST · <b className="text-tx" data-testid="active-model">{model ? (model.family === 'machine_learning' ? 'TRAINED ML MODEL' : 'STATISTICAL BASELINE') : '…'}</b></span>
          {crit !== null && (
            <button type="button" onClick={() => go('dash')} data-testid="critical-chip" title="Open the command dashboard"
              className="cursor-pointer border border-cr/80 text-cr px-2.5 py-0.5 rounded-sm bg-cr/10 hover:bg-cr/20 transition-colors font-mono text-[11px] font-semibold flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-cr animate-ping" />
              ▲ {crit} CRITICAL
            </button>
          )}
        </div>
        {down && <div role="alert" className="bg-errbg border-b border-cr text-errtx px-4 py-1.5 text-[12px]">
          {hErr?.code === 'BACKEND_UNREACHABLE' ? 'The service is unreachable. Data on screen may be out of date.' : hErr?.code === 'NOT_READY' ? 'The service is still starting up (database migrations and forecasts).' : 'The database is not responding. Data on screen may be out of date.'}</div>}
        {fcStatus === 'fallback_to_statistical' && <div role="alert" className="bg-warnbg border-b border-wr text-wr px-4 py-1.5 text-[12px]" data-testid="fallback-banner">The trained forecasting model failed and the statistical model is being used instead. See System &amp; Account for details.</div>}
        {scenarioActive && <div className="bg-warnbg border-b border-wr text-wr px-4 py-1.5 text-[12px] flex gap-3 items-center flex-wrap">
          SCENARIO ACTIVE — demand +{Math.round(scenario.demand * 100)}% · weather {weatherLabel(scenario.weather)} · road {roadLabel(scenario.road)} · fleet {Math.round(scenario.vehicles * 100)}%
          <Btn onClick={resetScenario}>Clear</Btn></div>}
        <div className="px-4 pt-3.5 pb-8 flex-1">
          <Suspense fallback={<Loading what="module view" />}>
            {page}
          </Suspense>
        </div>
        <div className="md:sticky md:bottom-0 bg-footbg border-t border-ac/60 text-act px-4 py-1.5 text-[12px] z-[1000] flex items-center justify-between flex-wrap gap-2">
          <div>
            <b>Decision Support Only</b> — Illustrative scenario: fictional locations and simulated telemetry, not operational records. Final logistics decisions remain with authorised personnel.
          </div>
          <div className="font-mono text-[10px] text-mu">V8.0 COMMAND CENTRE</div>
        </div>
      </main>
    </div>
    </>
  )
}
function Gate() {
  const { user, checking } = useAuth()
  if (checking) return <div role="status" className="min-h-screen grid place-items-center text-mu font-mono text-[12px]">Checking session…</div>
  if (!user) return <Login />
  return <AppProvider><Shell /></AppProvider>
}
export default function App() { return <ThemeProvider><AuthProvider><Gate /></AuthProvider></ThemeProvider> }
