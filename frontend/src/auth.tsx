import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { ApiError, get, post, setCsrf, setUnauthorizedHandler } from './api'

export type Role = 'viewer' | 'operator' | 'admin'
export interface User { id: number; username: string; role: Role; is_active: boolean; last_login_at: string | null }
interface Session { user: User; csrf_token: string }
const RANK: Record<Role, number> = { viewer: 0, operator: 1, admin: 2 }

interface AuthCtx {
  user: User | null
  checking: boolean            // true until the first /api/auth/session answer
  notice: string | null        // e.g. "Your session has ended"
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
  adopt: (s: Session) => void  // after a password change the server issues a fresh session
  can: (role: Role) => boolean
}
const C = createContext<AuthCtx>(null as unknown as AuthCtx)
export const useAuth = () => useContext(C)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [checking, setChecking] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const adopt = useCallback((s: Session) => { setCsrf(s.csrf_token); setUser(s.user); setNotice(null) }, [])
  useEffect(() => {
    let alive = true
    get<Session & { authenticated: boolean }>('/api/auth/session')
      .then(s => { if (alive && s.authenticated) adopt(s) })
      .catch(() => { /* not signed in: default to anonymous evaluator */ })
      .finally(() => { if (alive) setChecking(false) })
    setUnauthorizedHandler(() => {
      setCsrf('')
      setUser(u => {
        if (u) setNotice('Your session has ended. Please sign in again.')
        return null
      })
    })
    return () => { alive = false; setUnauthorizedHandler(null) }
  }, [adopt])
  const login = useCallback(async (username: string, password: string) => {
    adopt(await post<Session>('/api/auth/login', { username, password }))
  }, [adopt])
  const logout = useCallback(async () => {
    try { await post('/api/auth/logout') } catch (e) { if (!(e instanceof ApiError) || e.status !== 401) throw e }
    setCsrf('')
    setUser(null)
    setNotice(null)
  }, [])
  const can = useCallback((r: Role) => {
    if (!user) return r === 'viewer'
    return RANK[user.role] >= RANK[r]
  }, [user])
  const value = useMemo(() => ({ user, checking, notice, login, logout, adopt, can }), [user, checking, notice, login, logout, adopt, can])
  return <C.Provider value={value}>{children}</C.Provider>
}
