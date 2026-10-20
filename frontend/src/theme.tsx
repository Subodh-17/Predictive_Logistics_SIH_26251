import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

export type Theme = 'dark' | 'light'
const KEY = 'plsd-theme'

/** Colours that must be plain hex strings (SVG charts). Everything else uses CSS variables from index.css. */
export interface Palette { grid: string; axis: string; tx: string; accent: string; danger: string; ok: string; ttBg: string; ttBorder: string }
export const PALETTES: Record<Theme, Palette> = {
  dark: { grid: '#24332f', axis: '#7f948b', tx: '#d6e2dc', accent: '#c9a44c', danger: '#ea6058', ok: '#3fbf7f', ttBg: '#121c1a', ttBorder: '#24332f' },
  light: { grid: '#b0bec7', axis: '#475950', tx: '#14201b', accent: '#7a5800', danger: '#b3261e', ok: '#127546', ttBg: '#ffffff', ttBorder: '#b0beb7' },
}

const read = (): Theme => { try { return localStorage.getItem(KEY) === 'light' ? 'light' : 'dark' } catch { return 'dark' } }

interface Ctx { theme: Theme; toggle: () => void; palette: Palette }
const C = createContext<Ctx>({ theme: 'dark', toggle: () => {}, palette: PALETTES.dark })
export const useTheme = () => useContext(C)
export const usePalette = () => useContext(C).palette

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(read)
  useEffect(() => { document.documentElement.setAttribute('data-theme', theme) }, [theme])
  const toggle = useCallback(() => setTheme(t => {
    const n: Theme = t === 'dark' ? 'light' : 'dark'
    try { localStorage.setItem(KEY, n) } catch { /* storage unavailable: theme still switches for this session */ }
    return n
  }), [])
  const value = useMemo(() => ({ theme, toggle, palette: PALETTES[theme] }), [theme, toggle])
  return <C.Provider value={value}>{children}</C.Provider>
}
