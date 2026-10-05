import { fx } from '../format'
import type { ActionView } from '../recommend'
import type { Allocation, Dashboard, Priority } from '../types'
import { Card } from './ui'

interface Step { name: string; does: string; live: string }

/** Compact end-to-end story: DATA → FORECAST → RISK → PRIORITY → ALLOCATION → ROUTE → DECISION.
 *  Every live value is an existing backend figure (dashboard KPIs, priority queue, allocation, route comparison); nothing is computed here. */
export default function DecisionFlow({ dash, prio, alloc, actions }: { dash: Dashboard | null; prio: Priority[] | null; alloc: Allocation | null; actions: ActionView[] }) {
  const k = dash?.kpis
  const top = prio?.[0]
  const route = actions[0]?.route
  const steps: Step[] = [
    { name: 'DATA', does: 'Synthetic consumption, stock, weather, fleet', live: dash ? `${fx(dash.data_coverage.historical_records)} records` : '…' },
    { name: 'FORECAST', does: 'Demand per location and supply', live: k ? `${fx(Number(k.supplies_at_risk_units))} units short · 14 d` : '…' },
    { name: 'RISK', does: 'Days of supply → GREEN / YELLOW / RED', live: k ? `${k.risk_index}/100 · ${k.risk_band}` : '…' },
    { name: 'PRIORITY', does: 'Rank shortages by weighted score', live: top ? `#1 ${top.location} · ${top.supply}` : prio ? 'none at risk' : '…' },
    { name: 'ALLOCATION', does: 'Assign depot stock and vehicles', live: alloc ? `${fx(alloc.allocated)} of ${fx(alloc.total_need)} units` : '…' },
    { name: 'ROUTE', does: 'Lowest combined risk / ETA score', live: route ? `${route.id} · ETA ${route.eta_h.toFixed(1)} h` : alloc ? 'see GIS screen' : '…' },
    { name: 'DECISION', does: 'Top actions for human approval', live: actions.length ? `${actions.length} recommended actions` : '…' },
  ]
  return (
    <Card title="SYSTEM DECISION FLOW · DATA → FORECAST → RISK → PRIORITY → ALLOCATION → ROUTE → DECISION" className="mb-3">
      <ol data-testid="decision-flow" aria-label="System decision flow" className="list-none p-0 m-0 grid grid-cols-2 sm:grid-cols-4 lg:flex lg:items-stretch gap-1.5 lg:gap-0">
        {steps.map((s, i) => {
          const last = i === steps.length - 1
          return (
            <li key={s.name} className="contents lg:flex lg:flex-1 lg:min-w-0 lg:items-stretch">
              <div data-testid={`flow-step-${i + 1}`} className={`bg-ins border px-2.5 py-1.5 min-w-0 lg:flex-1 ${last ? 'border-ac' : 'border-ln'}`}>
                <span className={`block font-mono text-[10px] tracking-[.12em] ${last ? 'text-act' : 'text-mu'}`}>{i + 1} · {s.name}</span>
                <span className="block text-[11px] text-mu leading-snug">{s.does}</span>
                <span className="block font-mono text-[11px] text-tx mt-0.5 break-words">{s.live}</span>
              </div>
              {!last && <span aria-hidden className="hidden lg:flex items-center px-1 text-act">→</span>}
            </li>
          )
        })}
      </ol>
      <div className="text-[11px] text-mu mt-2">Rule-based, deterministic pipeline on synthetic data. The final step is decision support: authorized personnel review and decide; nothing is dispatched automatically.</div>
    </Card>
  )
}
