import type { ReactNode } from 'react'
import { ApiError, type ApiState } from '../api'
import type { Status } from '../types'

export const Card = ({ title, children, className = '', accent = false }: { title?: ReactNode; children: ReactNode; className?: string; accent?: boolean }) => (
  <section className={`bg-pn border p-3 min-w-0 ${accent ? 'border-ac bg-gradient-to-b from-ins to-pn' : 'border-ln'} ${className}`}>
    {title && <h3 className={`font-mono text-[11px] tracking-[.12em] font-semibold mb-2.5 ${accent ? 'text-act' : 'text-mu'}`}>{title}</h3>}
    {children}
  </section>
)

export const PageTitle = ({ children }: { children: ReactNode }) => <div className="font-mono font-semibold text-[11px] tracking-[.14em] text-act mb-2.5">{children}</div>

const KT: Record<string, string> = { cr: 'border-t-cr [&_b]:text-cr', wr: 'border-t-wr [&_b]:text-wr', ok: 'border-t-ok [&_b]:text-ok', '': 'border-t-ln' }
export const Kpi = ({ label, value, sub, tone = '' }: { label: string; value: ReactNode; sub?: ReactNode; tone?: 'cr' | 'wr' | 'ok' | '' }) => (
  <div className={`bg-pn border border-ln border-t-2 px-3 py-2.5 ${KT[tone]}`}>
    <b className="block text-[22px] tabular-nums">{value}</b>
    <i className="block font-mono text-[10px] tracking-[.1em] text-mu not-italic">{label}</i>
    <u className="no-underline text-[11px] text-mu">{sub}</u>
  </div>
)
export const KpiGrid = ({ children }: { children: ReactNode }) => <div className="grid gap-3 mb-3 grid-cols-[repeat(auto-fit,minmax(135px,1fr))]">{children}</div>

const TG: Record<string, string> = { ok: 'text-ok', wr: 'text-wr', cr: 'text-cr', '': 'text-tx' }
export const Tag = ({ tone = '', children }: { tone?: 'ok' | 'wr' | 'cr' | ''; children: ReactNode }) => (
  <span className={`font-mono text-[10px] tracking-[.08em] px-1.5 py-px border rounded-sm whitespace-nowrap border-current ${TG[tone]}`}>{children}</span>
)
export const StatusTag = ({ s }: { s: Status | string | null }) =>
  s === 'CRITICAL' ? <Tag tone="cr">CRITICAL</Tag> : s === 'WARNING' ? <Tag tone="wr">WARNING</Tag> : <Tag tone="ok">NORMAL</Tag>
export const LevelTag = ({ level }: { level: string }) => <Tag tone={level === 'LOW' ? 'ok' : level === 'MODERATE' ? 'wr' : 'cr'}>{level}</Tag>

export const Grid2 = ({ children, className = '' }: { children: ReactNode; className?: string }) => <div className={`grid gap-3 mb-3 grid-cols-1 lg:grid-cols-[2fr_1fr] ${className}`}>{children}</div>
export const GridHalf = ({ children }: { children: ReactNode }) => <div className="grid gap-3 mb-3 grid-cols-1 lg:grid-cols-2">{children}</div>
export const Table = ({ head, children }: { head: string[]; children: ReactNode }) => (
  <div className="overflow-x-auto"><table><thead><tr>{head.map(h => <th key={h}>{h}</th>)}</tr></thead><tbody>{children}</tbody></table></div>
)
export const KV = ({ rows }: { rows: [string, ReactNode][] }) => (
  <div className="grid grid-cols-[auto_1fr] gap-x-3.5 gap-y-1 my-2">{rows.map(([k, v]) => <><span key={k} className="text-mu">{k}</span><b key={k + 'v'} className="font-semibold">{v}</b></>)}</div>
)
export const Note = ({ children }: { children: ReactNode }) => <div className="flex flex-wrap gap-x-3.5 text-[11px] text-mu mt-2">{children}</div>
export const Why = ({ children }: { children: ReactNode }) => <div className="border-t border-dashed border-ln pt-2 text-soft">{children}</div>

export const Btn = ({ children, onClick, primary = false, active = false, disabled = false, type = 'button' }: { children: ReactNode; onClick?: () => void; primary?: boolean; active?: boolean; disabled?: boolean; type?: 'button' | 'submit' }) => (
  <button type={type} disabled={disabled} onClick={onClick}
    className={`border px-3 py-1.5 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed ${primary || active ? 'bg-ac text-onac border-ac font-semibold' : 'bg-pn2 text-tx border-ln hover:border-mu'}`}>{children}</button>
)

export function Loading({ what = 'data' }: { what?: string }) {
  return <div role="status" className="border border-ln bg-pn p-6 text-mu font-mono text-[12px] flex items-center gap-3"><span className="inline-block w-3 h-3 border-2 border-ac border-t-transparent rounded-full animate-spin" />Loading {what} from the backend…</div>
}

export function ErrorBox({ error, onRetry }: { error: ApiError; onRetry?: () => void }) {
  const title = error.code === 'BACKEND_UNREACHABLE' ? 'Backend unavailable'
    : error.code === 'DB_UNAVAILABLE' ? 'Database unavailable' : error.code === 'NOT_READY' ? 'Backend not ready' : 'Request failed'
  const hint = error.code === 'BACKEND_UNREACHABLE' ? 'Start it with `docker compose up --build` (or `uvicorn app.main:app` in backend/).'
    : error.code === 'DB_UNAVAILABLE' || error.code === 'NOT_READY' ? 'PostgreSQL/PostGIS must be running and seeded; the backend initialises an empty database on start-up.' : ''
  return (
    <div role="alert" className="border border-cr bg-errbg text-errtx p-4">
      <b className="block text-cr font-mono tracking-wide mb-1">{title}</b>
      <div>{error.message}</div>{hint && <div className="text-mu mt-1">{hint}</div>}
      {onRetry && <div className="mt-3"><Btn onClick={onRetry}>RETRY</Btn></div>}
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
        className="inline-flex items-center justify-center w-[15px] h-[15px] border border-mu text-mu rounded-full text-[10px] font-mono leading-none cursor-help focus:outline focus:outline-1 focus:outline-ac">i</span>
      <span role="tooltip" className="hidden group-hover:block group-focus-within:block absolute z-[1100] left-0 top-full mt-1 w-64 max-w-[calc(100vw-3rem)] border border-ac bg-pn text-tx text-[11px] leading-snug p-2 shadow-lg">{text}</span>
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
