import { useState, type FormEvent } from 'react'
import { ApiError, post, useApi } from '../api'
import { useAuth } from '../auth'
import { Async, Btn, Card, ErrorBox, GridHalf, KV, Note, PageHeader, Tag } from '../components/ui'

interface Detail {
  environment: string; api_version: string
  database: { connected: boolean; target?: string; schema_version: string | null }
  startup: { complete: boolean; attempts: number; last_error: string | null; last_success_at: string | null }
  models: { mode: string; demand_forecast: { loaded: boolean; error: string | null; loaded_at: string | null; artefact?: { model_id: string; created_utc: string; sha256?: string } | null; promotion?: { status: string } | null }
    shortage_risk: { loaded: boolean; error: string | null; loaded_at: string | null; artefact?: { model_id: string } | null } }
  model_state: { active_model_id: string; fallback_reason: string | null }
  data_freshness?: { history_through: string | null; last_inventory_event_at: string | null; forecasts_generated_at: string | null }
  operational: { counters: Record<string, number>; timestamps: Record<string, string>; process_started_at: string; uptime_seconds: number }
}
const when = (s: string | null | undefined) => s ? new Date(s).toLocaleString() : 'not recorded'
const dur = (n: number) => n >= 3600 ? `${Math.floor(n / 3600)} h ${Math.floor(n % 3600 / 60)} min` : `${Math.floor(n / 60)} min`

function ChangePassword() {
  const { adopt } = useAuth()
  const [v, setV] = useState({ cur: '', next: '', again: '' })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<ApiError | null>(null)
  const [ok, setOk] = useState(false)
  const mismatch = v.again !== '' && v.next !== v.again
  async function submit(e: FormEvent) {
    e.preventDefault()
    if (mismatch) return
    setBusy(true); setErr(null); setOk(false)
    try { adopt(await post('/api/auth/change-password', { current_password: v.cur, new_password: v.next })); setOk(true); setV({ cur: '', next: '', again: '' }) }
    catch (x) { setErr(x instanceof ApiError ? x : new ApiError(0, 'UNKNOWN', String(x))) } finally { setBusy(false) }
  }
  return (
    <Card title="CHANGE PASSWORD">
      <form onSubmit={submit} className="grid gap-3 max-w-sm" data-testid="password-form">
        <label className="text-[11px] text-mu font-mono uppercase tracking-wide block">
          CURRENT PASSWORD
          <input type="password" autoComplete="current-password" required className="w-full mt-1.5" value={v.cur} onChange={e => setV({ ...v, cur: e.target.value })} />
        </label>
        <label className="text-[11px] text-mu font-mono uppercase tracking-wide block">
          NEW PASSWORD (12+ characters)
          <input type="password" autoComplete="new-password" required minLength={12} className="w-full mt-1.5" value={v.next} onChange={e => setV({ ...v, next: e.target.value })} />
        </label>
        <label className="text-[11px] text-mu font-mono uppercase tracking-wide block">
          REPEAT NEW PASSWORD
          <input type="password" autoComplete="new-password" required className="w-full mt-1.5" aria-invalid={mismatch} value={v.again} onChange={e => setV({ ...v, again: e.target.value })} />
        </label>
        {mismatch && <div role="alert" className="text-cr text-[12px] bg-cr/10 border border-cr/30 px-2.5 py-1.5 rounded-sm">The two new passwords do not match.</div>}
        {err && <ErrorBox error={err} />}
        {ok && <div role="status" className="text-ok text-[12px] bg-ok/10 border border-ok/30 px-2.5 py-1.5 rounded-sm">Password changed. Sessions on other devices were signed out.</div>}
        <div className="pt-1"><Btn type="submit" primary disabled={busy || mismatch || !v.cur || !v.next}>{busy ? 'SAVING…' : 'CHANGE PASSWORD'}</Btn></div>
      </form>
    </Card>
  )
}

export default function System() {
  const { user } = useAuth()
  const d = useApi<Detail>('/api/health/detail')
  return (
    <div>
      <PageHeader title="SYSTEM STATUS & ACCOUNT" subtitle="Operational state of the service, the forecasting models and the data, as reported by the backend. Counters cover the current server process only." />
      <Async state={d} what="system status">{s => (<>
        <GridHalf>
          <Card title="SERVICE">
            <KV rows={[['Environment', s.environment], ['API version', s.api_version],
              ['Database', <span data-testid="sys-db"><Tag tone={s.database.connected ? 'ok' : 'cr'}>{s.database.connected ? 'CONNECTED' : 'DOWN'}</Tag> {s.database.target ?? ''}</span>],
              ['Schema version', s.database.schema_version ?? 'unknown'],
              ['Start-up', <Tag tone={s.startup.complete ? 'ok' : 'wr'}>{s.startup.complete ? 'COMPLETE' : 'PENDING'}</Tag>],
              ['Process uptime', dur(s.operational.uptime_seconds)]]} />
            {s.startup.last_error && <Note>Last start-up error: {s.startup.last_error}</Note>}
          </Card>
          <Card title="DATA COVERAGE">
            <KV rows={[['Consumption history through', s.data_freshness?.history_through ?? 'not recorded'],
              ['Forecasts generated', when(s.data_freshness?.forecasts_generated_at)], ['Last inventory event', when(s.data_freshness?.last_inventory_event_at)]]} />
            <Note>The scenario is a fixed history, so this shows what the stored data covers, not how recent it is in real time.</Note>
          </Card>
        </GridHalf>
        <GridHalf>
          <Card title="FORECASTING MODEL">
            <KV rows={[['Active model', <span data-testid="sys-active-model">{s.model_state.active_model_id}</span>], ['Configured mode', s.models.mode],
              ['Trained demand model', s.models.demand_forecast.loaded ? `${s.models.demand_forecast.artefact?.model_id} · ${s.models.demand_forecast.promotion?.status ?? 'no decision'}` : `unavailable (${s.models.demand_forecast.error ?? 'not loaded yet'})`],
              ['Last model load', when(s.models.demand_forecast.loaded_at)],
              ['Shortage-onset model', s.models.shortage_risk.loaded ? `${s.models.shortage_risk.artefact?.model_id} (benchmark-format scoring only)` : `unavailable (${s.models.shortage_risk.error ?? 'not loaded yet'})`]]} />
            {s.model_state.fallback_reason && <Note><span data-testid="sys-fallback">{s.model_state.fallback_reason}</span></Note>}
          </Card>
          <Card title="OPERATIONAL COUNTERS (THIS PROCESS)">
            {Object.keys(s.operational.counters).length === 0 ? <p className="text-mu">No failures, fallbacks or throttled requests recorded.</p>
              : <KV rows={Object.entries(s.operational.counters).map(([k, v]) => [k.replace(/_/g, ' '), v])} />}
            <Note>Failures, fallbacks and rejected requests are counted here and written to the structured server log.</Note>
          </Card>
        </GridHalf></>)}</Async>
      {user ? (
        <>
          <Card title="SIGNED IN AS" className="mb-3"><KV rows={[['User', user.username], ['Role', user.role]]} /></Card>
          <ChangePassword />
        </>
      ) : (
        <Card title="CURRENT SESSION" className="mb-3">
          <KV rows={[['Session Mode', 'Public Evaluator (Read-Only)'], ['Access', 'Command Centre & Model Insights View']]} />
          <Note>You are viewing this system in public evaluator mode. Password management and account modifications require signing in with an authorized administrator or operator account.</Note>
        </Card>
      )}
    </div>
  )
}
