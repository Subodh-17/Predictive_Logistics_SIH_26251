import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { BASELINE, type Scenario } from './types'
import { qs, scenarioQs } from './api'

export type Tab = 'dash' | 'fc' | 'gis' | 'inv' | 'sim' | 'mdl' | 'sys' | 'usr'
export interface Sel { kind: 'loc' | 'rt'; id: string }

interface Ctx {
  tab: Tab; go: (t: Tab) => void
  sel: Sel; pick: (k: Sel['kind'], id: string) => void
  scenario: Scenario; applyScenario: (s: Scenario) => void; resetScenario: () => void; scenarioActive: boolean
  sq: string                       // scenario query string for GET requests, e.g. "?demand=0.3&..." ('' at baseline)
  refreshKey: number; refresh: () => void
}
const C = createContext<Ctx>(null as unknown as Ctx)
export const useApp = () => useContext(C)

export function AppProvider({ children }: { children: ReactNode }) {
  const [tab, setTab] = useState<Tab>('dash')
  const [sel, setSel] = useState<Sel>({ kind: 'loc', id: 'Base_04' })
  const [scenario, setScenario] = useState<Scenario>(BASELINE)
  const [refreshKey, setRefreshKey] = useState(0)
  const go = useCallback((t: Tab) => { setTab(t); window.scrollTo(0, 0) }, [])
  const pick = useCallback((kind: Sel['kind'], id: string) => { setSel({ kind, id }); setTab('gis'); window.scrollTo(0, 0) }, [])
  const scenarioActive = JSON.stringify(scenario) !== JSON.stringify(BASELINE)
  const value = useMemo<Ctx>(() => ({
    tab, go, sel, pick, scenario, scenarioActive,
    applyScenario: s => { setScenario(s); setTab('dash'); window.scrollTo(0, 0) },
    resetScenario: () => setScenario(BASELINE),
    sq: scenarioActive ? qs(scenarioQs(scenario)) : '',
    refreshKey, refresh: () => setRefreshKey(k => k + 1),
  }), [tab, go, sel, pick, scenario, scenarioActive, refreshKey])
  return <C.Provider value={value}>{children}</C.Provider>
}
