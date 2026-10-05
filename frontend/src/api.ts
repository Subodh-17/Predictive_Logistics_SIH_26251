import { useCallback, useEffect, useState } from 'react'
import type { Scenario } from './types'

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) { super(message) }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(BASE + path, { ...init, headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) } })
  } catch {
    throw new ApiError(0, 'BACKEND_UNREACHABLE', 'Backend unavailable. Check that the FastAPI service is running.')
  }
  if (!res.ok) {
    let code = 'HTTP_' + res.status, msg = res.statusText
    try {
      const j = await res.json()
      code = j.code ?? (j.status === 'degraded' ? 'DB_UNAVAILABLE' : code)
      msg = typeof j.detail === 'string' ? j.detail : j.status === 'degraded' ? 'Database unavailable. Check that PostgreSQL/PostGIS is running.' : JSON.stringify(j.detail ?? j)
    } catch { /* non-JSON error body (e.g. proxy 502) */ }
    if (res.status === 502 || res.status === 504) { code = 'BACKEND_UNREACHABLE'; msg = 'Backend unavailable. Check that the FastAPI service is running.' }
    throw new ApiError(res.status, code, msg)
  }
  return res.json() as Promise<T>
}

export const get = <T,>(path: string) => request<T>(path)
export const post = <T,>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

export const qs = (o: Record<string, string | number | undefined | null>) => {
  const p = new URLSearchParams()
  Object.entries(o).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '') p.set(k, String(v)) })
  const s = p.toString()
  return s ? '?' + s : ''
}
export const scenarioQs = (s: Scenario) => ({ demand: s.demand, weather: s.weather, road: s.road, vehicles: s.vehicles })

export interface ApiState<T> { data: T | null; error: ApiError | null; loading: boolean; reload: () => void }

/** Fetch `path` (re-fetched whenever path or `refreshKey` changes). `path === null` skips the request. */
export function useApi<T>(path: string | null, refreshKey = 0): ApiState<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [loading, setLoading] = useState(path !== null)
  const [tick, setTick] = useState(0)
  useEffect(() => {
    if (path === null) return
    let alive = true
    setLoading(true)
    get<T>(path).then(d => { if (alive) { setData(d); setError(null) } })
      .catch(e => { if (alive) setError(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', String(e))) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [path, refreshKey, tick])
  const reload = useCallback(() => setTick(t => t + 1), [])
  return { data, error, loading, reload }
}
