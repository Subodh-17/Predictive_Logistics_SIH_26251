// Presentation helpers only: they join and phrase data that the backend already computed (priority, allocation, routes).
import { fx } from './format'
import type { Allocation, Priority, Route } from './types'

export interface ActionView {
  p: Priority; need: number; allocated: number; unmet: number; unmetReason: string
  legs: { vehicle: string; route: string; depot: string; quantity: number }[]; route: Route | null; headline: string
}

type Leg = { vehicle: string; route: string; depot: string; quantity: number }
/** Legs grouped by depot + route, so a plan that uses two depots is never described as one route: "Depot_A via R03 (V001 + V002: 9,000 units) and Depot_B via R08 (V005: 4,850 units)". */
export function legsText(legs: Leg[]): string {
  const g = new Map<string, { depot: string; route: string; vehicles: string[]; qty: number }>()
  for (const l of legs) {
    const k = l.depot + '|' + l.route, e = g.get(k) ?? { depot: l.depot, route: l.route, vehicles: [], qty: 0 }
    if (!e.vehicles.includes(l.vehicle)) e.vehicles.push(l.vehicle)
    e.qty += l.quantity; g.set(k, e)
  }
  return Array.from(g.values()).map(e => `${e.depot} via ${e.route} (${e.vehicles.join(' + ')}: ${fx(e.qty)} units)`).join(' and ')
}
/** "Depot_A → Base_04 via R03" per depot + route used by a plan (a two-depot plan yields two corridors). */
export function corridorText(legs: Leg[], destination: string): string {
  const seen = new Set<string>(), out: string[] = []
  for (const l of legs) { const k = l.depot + '|' + l.route; if (!seen.has(k)) { seen.add(k); out.push(`${l.depot} → ${destination} via ${l.route}`) } }
  return out.join(' and ')
}
/** The route carrying the largest share of a plan. */
export const mainRoute = (legs: Leg[]): string | undefined => {
  const q = new Map<string, number>(); legs.forEach(l => q.set(l.route, (q.get(l.route) ?? 0) + l.quantity))
  return Array.from(q.entries()).sort((a, b) => b[1] - a[1])[0]?.[0]
}

export function buildActions(prio: Priority[] | null, alloc: Allocation | null, routes: Route[] | null, n = 3): ActionView[] {
  if (!prio || !alloc) return []
  return prio.slice(0, n).map(p => {
    const row = alloc.rows.find(r => r.location === p.location && r.supply === p.supply)
    const legs = row?.legs ?? []
    const rid = mainRoute(legs) ?? p.best_route
    const allocated = row?.allocated ?? 0
    const headline = legs.length
      ? `Dispatch ${fx(allocated)} units of ${p.supply} to ${p.location}: ${legsText(legs)}`
      : `No dispatch possible for ${p.supply} at ${p.location} (${(row?.unmet_reason || 'no feasible route').toLowerCase()}) — escalate transport allocation`
    return { p, need: row?.need ?? p.replenish_qty, allocated, unmet: row?.unmet ?? p.replenish_qty, unmetReason: row?.unmet_reason ?? '',
      legs, route: routes?.find(r => r.id === rid) ?? null, headline }
  })
}

export const tone = (s: string): 'cr' | 'wr' | 'ok' => s === 'CRITICAL' ? 'cr' : s === 'WARNING' ? 'wr' : 'ok'
export const FACTOR_LABEL: Record<string, string> = {
  urgency: 'Shortage urgency (days of cover)', shortage: 'Shortage volume (unmet share of 14-day demand)', deficit: 'Stock deficit vs safety stock',
  criticality: 'Supply criticality', lead_time: 'Lead-time pressure', route: 'Route feasibility / risk', capacity: 'Transport capacity',
}
export const criticalityLabel = (w: number) => w >= 0.9 ? 'Mission-critical' : w >= 0.7 ? 'High' : w >= 0.5 ? 'Medium' : 'Lower'
