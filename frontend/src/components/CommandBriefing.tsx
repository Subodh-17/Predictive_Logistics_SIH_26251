import { dd, fx } from '../format'
import { useApp } from '../state'
import { tone, type ActionView } from '../recommend'
import type { Dashboard, InvItem, Loc } from '../types'
import { Btn, Card, LevelTag, StatusTag, Tag } from './ui'

export interface AlertsData { critical: number; warning: number; alerts: { location: string; supply: string; severity: string; days_cover: number; stockout_date: string; lead_days: number }[] }
const TEXT_TONE = { cr: 'text-cr', wr: 'text-wr', ok: 'text-ok' }
const BORDER_TONE = { cr: 'border-cr', wr: 'border-wr', ok: 'border-ok' }

function Tile({ label, value, sub, children, t = '' }: { label: string; value: React.ReactNode; sub?: React.ReactNode; children?: React.ReactNode; t?: 'cr' | 'wr' | 'ok' | '' }) {
  return (
    <div className={`bg-ins border border-ln border-t-2 px-3 py-2 min-w-0 ${t ? BORDER_TONE[t].replace('border-', 'border-t-') : 'border-t-ln'}`}>
      <span className="block font-mono text-[10px] tracking-[.1em] text-mu">{label}</span>
      <span className={`block text-[20px] font-semibold tabular-nums leading-tight mt-0.5 ${t ? TEXT_TONE[t] : ''}`}>{value}</span>
      {sub && <span className="block text-[11px] text-mu mt-0.5">{sub}</span>}
      {children}
    </div>
  )
}

/** First-screen summary for judges: overall risk, critical locations, predicted shortages, transport capacity, active alerts, top 3 actions. */
export default function CommandBriefing({ dash, locs, inv, alerts, actions }: { dash: Dashboard | null; locs: Loc[] | null; inv: InvItem[] | null; alerts: AlertsData | null; actions: ActionView[] }) {
  const { pick, scenarioActive } = useApp()
  const k = dash?.kpis
  const risk = k ? Number(k.risk_index) : null
  const crit = locs?.filter(l => l.kind === 'FORWARD' && l.status === 'CRITICAL') ?? []
  const warn = locs?.filter(l => l.kind === 'FORWARD' && l.status === 'WARNING') ?? []
  const worst = inv && inv.length ? inv[0] : null
  const cap = k ? Number(k.transport_capacity) : 0, need = k ? Number(k.transport_need) : 0, deficit = k ? Number(k.capacity_deficit) : 0
  const topAlert = alerts?.alerts.find(a => a.severity === 'CRITICAL') ?? alerts?.alerts[0]
  return (
    <section aria-label="Command briefing" className="mb-3">
      <div className="grid gap-3 lg:grid-cols-[1.15fr_1fr]">
        <Card title={`COMMAND BRIEFING${scenarioActive ? ' · SCENARIO ACTIVE' : ''}`} className="min-w-0">
          <div className="flex flex-wrap items-end gap-x-4 gap-y-1 mb-1">
            <div>
              <span className="block font-mono text-[10px] tracking-[.1em] text-mu">OVERALL RISK</span>
              <span className={`text-[40px] leading-none font-semibold tabular-nums ${k ? TEXT_TONE[k.risk_level as 'ok' | 'wr' | 'cr'] : ''}`} data-testid="briefing-risk">{risk ?? '—'}<span className="text-[18px] text-mu"> / 100</span></span>
            </div>
            {k && <div className="pb-1.5"><LevelTag level={String(k.risk_band)} /></div>}
          </div>
          <div className="relative mt-3 mb-5" role="img" aria-label={`Overall risk ${risk ?? 'unknown'} out of 100`}>
            <div className="flex h-2.5 overflow-hidden border border-ln">
              <i className="bg-ok" style={{ width: '25%' }} /><i className="bg-wrf" style={{ width: '20%' }} /><i className="bg-cr opacity-70" style={{ width: '20%' }} /><i className="bg-cr" style={{ width: '35%' }} />
            </div>
            {risk !== null && <i className="absolute -top-1 w-[3px] h-[18px] bg-hi -translate-x-1/2 border border-bg" style={{ left: Math.min(100, risk) + '%' }} />}
            <div className="flex justify-between font-mono text-[9px] text-mu mt-1"><span>LOW 0</span><span>MODERATE 25</span><span>HIGH 45</span><span>SEVERE 65+</span></div>
          </div>
          <div className="grid gap-2.5 grid-cols-1 sm:grid-cols-2">
            <Tile label="CRITICAL LOCATIONS" t={crit.length ? 'cr' : 'ok'} value={locs ? `${crit.length} of ${locs.filter(l => l.kind === 'FORWARD').length}` : '—'}
              sub={locs ? (crit.length ? crit.map(l => l.id).join(' · ') : 'none') + (warn.length ? ` · warning: ${warn.map(l => l.id).join(', ')}` : '') : undefined} />
            <Tile label="PREDICTED SHORTAGES" t={k && Number(k.critical_shortages) ? 'cr' : 'ok'} value={k ? `${fx(Number(k.supplies_at_risk_units))} units` : '—'}
              sub={k ? `14-day horizon · ${k.critical_shortages} critical items${worst ? ` · soonest ${worst.location} ${worst.supply} in ${worst.days_left.toFixed(1)} d` : ''}` : undefined} />
            <Tile label="TRANSPORT CAPACITY" t={deficit ? 'wr' : 'ok'} value={k ? `${fx(cap)} / ${fx(need)}` : '—'} sub={k ? (deficit ? `deficit ${fx(deficit)} units · ${k.vehicles_available}/${k.vehicles_total} vehicles` : `sufficient · ${k.vehicles_available}/${k.vehicles_total} vehicles`) : undefined}>
              {k && need > 0 && <div className="h-1.5 bg-bar mt-1.5" role="img" aria-label={`Capacity covers ${Math.round(Math.min(1, cap / need) * 100)} percent of need`}><i className={`block h-full ${deficit ? 'bg-wrf' : 'bg-ok'}`} style={{ width: Math.min(100, cap / need * 100) + '%' }} /></div>}
            </Tile>
            <Tile label="ACTIVE ALERTS" t={alerts?.critical ? 'cr' : alerts?.warning ? 'wr' : 'ok'} value={alerts ? `${alerts.critical} critical · ${alerts.warning} warning` : '—'}
              sub={topAlert ? `latest: ${topAlert.location} ${topAlert.supply} · ${topAlert.days_cover.toFixed(1)} d · stock-out ${dd(topAlert.stockout_date)}` : alerts ? 'no active alerts' : undefined} />
          </div>
        </Card>

        <Card title="TOP 3 RECOMMENDED ACTIONS · RULE-BASED DECISION SUPPORT" accent className="min-w-0">
          {actions.length === 0 && <div className="text-mu">Loading recommendations…</div>}
          <ol className="space-y-2 list-none p-0 m-0">
            {actions.map(a => (
              <li key={a.p.location + a.p.supply} className="border-l-[3px] border-ln pl-2.5 py-0.5" style={{ borderLeftColor: 'rgb(var(--' + tone(a.p.status) + '))' }}>
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <b className="font-mono">#{a.p.rank}</b><StatusTag s={a.p.status} /><span className="font-mono text-mu text-[11px]">priority {a.p.score}/100</span>
                </div>
                <div className="text-[13px] mt-0.5">{a.headline}.</div>
                <div className="text-[11px] text-mu mt-0.5">
                  {a.p.supply} runs out in <b className="text-tx">{a.p.days_cover.toFixed(1)} d</b> ({dd(a.p.stockout_date)})
                  {a.route && <> · main route {a.route.id} {a.route.depot} → {a.route.destination}: ETA {a.route.eta_h.toFixed(1)} h, risk <b className="text-tx">{a.route.risk_level}</b></>}
                  {a.unmet > 0 && <> · <span className="text-wr">unmet {fx(a.unmet)} units{a.unmetReason ? ` (${a.unmetReason.toLowerCase()})` : ''}</span></>}
                </div>
                <div className="mt-1"><Btn onClick={() => pick('loc', a.p.location)}>{`SHOW ${a.p.location} ON MAP ›`}</Btn></div>
              </li>
            ))}
          </ol>
          <div className="text-[11px] text-mu mt-2"><Tag>RULE-BASED</Tag> Deterministic rules over forecast, inventory, route and capacity data — not machine learning, not an LLM. Decision support only.</div>
        </Card>
      </div>
    </section>
  )
}
