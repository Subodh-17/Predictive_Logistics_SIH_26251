import { Fragment, type ReactNode } from 'react'
import { ApiError, type ApiState } from '../api'
import type { Status } from '../types'

export const Card = ({ title, children, className = '', accent = false, action }: { title?: ReactNode; children: ReactNode; className?: string; accent?: boolean; action?: ReactNode }) => (
  <section className={`${accent ? 'bento-card-accent' : 'bento-card'} p-3.5 min-w-0 ${className}`}>
    {title && (
      <div className="flex items-center justify-between gap-2 mb-3 pb-2 border-b border-ln/60">
        <div className="flex items-center gap-2">
          <span className={`inline-block w-1.5 h-1.5 rounded-full ${accent ? 'bg-ac shadow-[0_0_6px_rgba(206,168,78,0.8)]' : 'bg-mu'}`} />
          <h3 className={`font-mono text-[11px] tracking-[.14em] font-semibold uppercase ${accent ? 'text-act' : 'text-mu'}`}>{title}</h3>
        </div>
        {action && <div>{action}</div>}
      </div>
    )}
    {children}
  </section>
)

export const PageTitle = ({ children }: { children: ReactNode }) => (
  <div className="flex items-center gap-2 font-mono font-semibold text-[11px] tracking-[.14em] text-act mb-3">
    <span className="inline-block w-2 h-2 bg-ac rounded-sm" />
    <span>{children}</span>
  </div>
)

const KT: Record<string, string> = {
  cr: 'border-t-cr shadow-[inset_0_2px_0_0_rgb(var(--cr))] [&_b]:text-cr',
  wr: 'border-t-wr shadow-[inset_0_2px_0_0_rgb(var(--wr))] [&_b]:text-wr',
  ok: 'border-t-ok shadow-[inset_0_2px_0_0_rgb(var(--ok))] [&_b]:text-ok',
  '': 'border-t-ln'
}
export const Kpi = ({ label, value, sub, tone = '' }: { label: string; value: ReactNode; sub?: ReactNode; tone?: 'cr' | 'wr' | 'ok' | '' }) => (
  <div className={`bento-card px-3.5 py-3 border-t-2 ${KT[tone]}`}>
    <div className="flex items-baseline justify-between gap-1">
      <b className="block text-[24px] font-bold tracking-tight tabular-nums leading-none">{value}</b>
      {tone && <span className={`inline-block w-1.5 h-1.5 rounded-full ${tone === 'cr' ? 'bg-cr' : tone === 'wr' ? 'bg-wr' : 'bg-ok'}`} />}
    </div>
    <i className="block font-mono text-[10px] tracking-[.12em] text-mu uppercase not-italic mt-1.5">{label}</i>
    {sub && <u className="no-underline block text-[11px] text-soft mt-1 leading-snug">{sub}</u>}
  </div>
)
export const KpiGrid = ({ children }: { children: ReactNode }) => <div className="grid gap-3 mb-3 grid-cols-[repeat(auto-fit,minmax(135px,1fr))]">{children}</div>

const TG: Record<string, string> = {
  ok: 'text-ok border-ok/50 bg-ok/10',
  wr: 'text-wr border-wr/50 bg-wr/10',
  cr: 'text-cr border-cr/50 bg-cr/10',
  '': 'text-tx border-ln bg-pn2'
}
export const Tag = ({ tone = '', children }: { tone?: 'ok' | 'wr' | 'cr' | ''; children: ReactNode }) => (
  <span className={`inline-flex items-center gap-1 font-mono text-[10px] tracking-[.08em] px-2 py-0.5 border rounded-sm whitespace-nowrap uppercase font-semibold ${TG[tone]}`}>{children}</span>
)
export const StatusTag = ({ s }: { s: Status | string | null }) =>
  s === 'CRITICAL' ? <Tag tone="cr">CRITICAL</Tag> : s === 'WARNING' ? <Tag tone="wr">WARNING</Tag> : <Tag tone="ok">NORMAL</Tag>
export const LevelTag = ({ level }: { level: string }) => <Tag tone={level === 'LOW' ? 'ok' : level === 'MODERATE' ? 'wr' : 'cr'}>{level}</Tag>

export const Grid2 = ({ children, className = '' }: { children: ReactNode; className?: string }) => <div className={`grid gap-3 mb-3 grid-cols-1 lg:grid-cols-[2fr_1fr] ${className}`}>{children}</div>
export const GridHalf = ({ children }: { children: ReactNode }) => <div className="grid gap-3 mb-3 grid-cols-1 lg:grid-cols-2">{children}</div>
export const Table = ({ head, children }: { head: string[]; children: ReactNode }) => (
  <div className="overflow-x-auto border border-ln rounded-sm bg-pn/40" tabIndex={0} role="region" aria-label="Data table (scrollable)">
    <table><thead><tr>{head.map(h => <th key={h}>{h}</th>)}</tr></thead><tbody>{children}</tbody></table>
  </div>
)
export const KV = ({ rows }: { rows: [string, ReactNode][] }) => (
  <div className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 my-2 text-[12.5px]">{rows.map(([k, v]) => <Fragment key={k}><span className="text-mu font-mono text-[11px] uppercase tracking-wide">{k}</span><b className="font-semibold text-tx">{v}</b></Fragment>)}</div>
)
export const Note = ({ children }: { children: ReactNode }) => <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-mu mt-2.5 leading-relaxed">{children}</div>
export const Why = ({ children }: { children: ReactNode }) => <div className="border-t border-dashed border-ln/80 pt-2 text-soft leading-relaxed">{children}</div>

export const Btn = ({ children, onClick, primary = false, active = false, disabled = false, type = 'button', className = '' }: { children: ReactNode; onClick?: () => void; primary?: boolean; active?: boolean; disabled?: boolean; type?: 'button' | 'submit'; className?: string }) => (
  <button type={type} disabled={disabled} onClick={onClick}
    className={`border px-3 py-1.5 text-[11.5px] font-mono tracking-wider uppercase rounded-sm cursor-pointer transition-all duration-100 disabled:opacity-40 disabled:cursor-not-allowed select-none ${primary || active ? 'bg-ac text-onac border-ac hover:brightness-110 active:scale-[0.98] font-bold shadow-sm' : 'bg-pn2 hover:bg-hov text-tx border-ln hover:border-mu active:scale-[0.98]'} ${className}`}>{children}</button>
)

/** Animated skeleton placeholder for individual loading regions. Use instead of a spinner when layout is known. */
export function SkeletonBlock({ rows = 3, className = '' }: { rows?: number; className?: string }) {
  return (
    <div className={className} aria-hidden="true">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className={`skeleton h-4 mb-2 ${i === rows - 1 ? 'w-2/3' : 'w-full'}`} />
      ))}
    </div>
  )
}

export function Loading({ what = 'data' }: { what?: string }) {
  return (
    <div role="status" aria-label={`Loading ${what}`} className="bento-card p-4">
      <div className="flex items-center gap-2.5 text-mu font-mono text-[12px] mb-3">
        <span className="inline-block w-3 h-3 border-2 border-ac border-t-transparent rounded-full animate-spin" aria-hidden="true" />
        <span className="tracking-wide">LOADING {what.toUpperCase()}…</span>
      </div>
      <SkeletonBlock rows={3} />
    </div>
  )
}

export function ErrorBox({ error, onRetry }: { error: ApiError; onRetry?: () => void }) {
  const title = error.code === 'BACKEND_UNREACHABLE' ? 'Backend unavailable'
    : error.code === 'DB_UNAVAILABLE' ? 'Database unavailable' : error.code === 'NOT_READY' ? 'Service not ready' : error.code === 'FORBIDDEN' ? 'Not permitted' : error.code === 'RATE_LIMITED' ? 'Too many requests' : 'Request failed'
  const hint = error.code === 'BACKEND_UNREACHABLE' ? 'Check your connection, then retry. If it persists, contact the administrator.'
    : error.code === 'DB_UNAVAILABLE' || error.code === 'NOT_READY' ? 'Retry in a moment. If it persists, the administrator can check the system status and server logs.'
    : error.code === 'FORBIDDEN' ? 'Your role does not allow this action.' : ''
  return (
    <div role="alert" className="border border-cr/80 bg-errbg text-errtx p-4 rounded shadow-bento">
      <div className="flex items-center gap-2 mb-1">
        <span className="inline-block w-2 h-2 rounded-full bg-cr" />
        <b className="text-cr font-mono tracking-wide uppercase text-[12px]">{title}</b>
      </div>
      <div className="text-[12.5px]">{error.message}</div>
      {hint && <div className="text-mu text-[11.5px] mt-1.5">{hint}</div>}
      {onRetry && <div className="mt-3"><Btn onClick={onRetry}>RETRY ACTION</Btn></div>}
    </div>
  )
}

/** Render children once data is available; show loading / error states otherwise. */
export function Async<T>({ state, what, children }: { state: ApiState<T>; what?: string; children: (d: T) => ReactNode }) {
  if (state.error && !state.data) return <ErrorBox error={state.error} onRetry={state.reload} />
  if (!state.data) return <Loading what={what} />
  return <>{state.error && <div className="mb-2"><ErrorBox error={state.error} onRetry={state.reload} /></div>}{children(state.data)}</>
}

export const CONFIDENCE_NOTE = 'Heuristic confidence index derived from historical backtest error; not a probability of forecast correctness.'

/** Small "i" marker with a hover / keyboard-focus explanation. Not a button (it performs no action). */
export function InfoTip({ text, label = 'More information' }: { text: string; label?: string }) {
  return (
    <span className="relative inline-block group align-middle ml-1.5 normal-case tracking-normal font-sans font-normal">
      <span tabIndex={0} role="img" aria-label={`${label}: ${text}`} data-testid="info-tip"
        className="inline-flex items-center justify-center w-[15px] h-[15px] border border-mu/70 text-mu rounded-full text-[10px] font-mono leading-none cursor-help hover:border-ac hover:text-ac focus:outline focus:outline-1 focus:outline-ac transition-colors">i</span>
      <span role="tooltip" className="hidden group-hover:block group-focus-within:block absolute z-[1100] left-0 top-full mt-1.5 w-64 max-w-[calc(100vw-3rem)] border border-ac bg-pn text-tx text-[11px] leading-snug p-2.5 shadow-xl rounded-sm">{text}</span>
    </span>
  )
}

const CONF_TONE = { ok: 'text-ok', wr: 'text-wr', cr: 'text-cr' }
/** "Confidence Index: 99/100 — HIGH" (+ explanation tooltip). Presentation only: the value and label come unchanged from the backend. */
export function ConfidenceIndex({ value, label, level, className = '' }: { value: number; label: string; level: 'ok' | 'wr' | 'cr'; className?: string }) {
  return (
    <span className={className}>
      <span className={CONF_TONE[level]} data-testid="confidence-index">Confidence Index: {value}/100 — {label}</span>
      <InfoTip text={CONFIDENCE_NOTE} label="About the confidence index" />
    </span>
  )
}

/** Props that make a clickable table row / card reachable and operable by keyboard (Enter or Space). */
export const act = (fn: () => void) => ({
  onClick: fn, tabIndex: 0,
  onKeyDown: (e: { key: string; preventDefault: () => void }) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fn() } },
})

export const PageHeader = ({ title, subtitle, meta }: { title: ReactNode; subtitle?: ReactNode; meta?: ReactNode }) => (
  <header className="mb-4 pb-2 border-b border-ln/60">
    <div className="flex items-center gap-2">
      <span className="inline-block w-2 h-2 rounded-sm bg-ac shadow-[0_0_6px_rgba(206,168,78,0.7)]" />
      <h2 className="m-0 font-mono font-semibold text-[13px] tracking-[.14em] text-act uppercase">{title}</h2>
    </div>
    {subtitle && <p className="m-0 mt-1 text-[12.5px] text-soft max-w-[80ch] leading-relaxed">{subtitle}</p>}
    {meta && <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 font-mono text-[11px] text-mu">{meta}</div>}
  </header>
)
