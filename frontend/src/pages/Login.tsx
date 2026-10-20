import { useState, type FormEvent } from 'react'
import { ApiError } from '../api'
import { useAuth } from '../auth'
import { Btn } from '../components/ui'

export default function Login() {
  const { login, notice } = useAuth()
  const [u, setU] = useState('')
  const [p, setP] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true); setErr(null)
    try { await login(u.trim(), p) } catch (x) {
      const a = x instanceof ApiError ? x : null
      setErr(a?.code === 'INVALID_CREDENTIALS' ? 'Invalid user name or password.'
        : a?.code === 'TOO_MANY_ATTEMPTS' ? 'Too many failed attempts. Wait a few minutes before trying again.'
        : a?.code === 'BACKEND_UNREACHABLE' || a?.code === 'NOT_READY' || a?.code === 'DB_UNAVAILABLE' ? a.message : a?.message ?? 'Sign-in failed.')
    } finally { setBusy(false) }
  }
  return (
    <main className="min-h-screen grid place-items-center p-4 bg-bg">
      <div className="w-full max-w-md">
        <form onSubmit={submit} className="bento-card-accent p-6 sm:p-8" aria-labelledby="login-title" data-testid="login-form">
          <div className="flex items-center justify-between mb-4 pb-3 border-b border-ln/60">
            <div className="flex items-center gap-2.5">
              <span className="w-3 h-3 rounded-xs bg-ac shadow-[0_0_8px_rgba(206,168,78,0.8)]" />
              <div>
                <h1 id="login-title" className="text-[13px] tracking-[.14em] text-act font-bold font-mono uppercase leading-tight">
                  PREDICTIVE LOGISTICS
                </h1>
                <span className="font-mono text-[10px] text-mu tracking-wider block">FORWARD SUPPLY CHAIN · DECISION SUPPORT</span>
              </div>
            </div>
            <span className="font-mono text-[9px] uppercase px-2 py-0.5 border border-ln rounded-xs bg-pn2 text-mu">V7.2</span>
          </div>

          <div className="mb-4">
            <p className="text-soft text-[12.5px] leading-relaxed m-0">Sign in to access the logistics command dashboard. Access is restricted to authorised operators and administrators.</p>
          </div>

          {notice && <div role="status" className="border border-wr/60 bg-warnbg text-wr px-3 py-2 mb-3 text-[12px] rounded-sm">{notice}</div>}

          <div className="space-y-3.5 mb-4">
            <label htmlFor="lu" className="block text-[11px] text-mu font-mono uppercase tracking-wide">
              USER NAME
              <input id="lu" name="username" autoComplete="username" autoFocus required maxLength={64} value={u} onChange={e => setU(e.target.value)} className="w-full mt-1.5" placeholder="Enter username" />
            </label>

            <label htmlFor="lp" className="block text-[11px] text-mu font-mono uppercase tracking-wide">
              PASSWORD
              <input id="lp" name="password" type="password" autoComplete="current-password" required maxLength={256} value={p} onChange={e => setP(e.target.value)} className="w-full mt-1.5" placeholder="Enter password" />
            </label>
          </div>

          <div aria-live="polite" className="min-h-[1.5rem]">
            {err && <div role="alert" className="text-cr text-[12px] bg-cr/10 border border-cr/30 px-3 py-1.5 rounded-sm mb-3" data-testid="login-error">{err}</div>}
          </div>

          <div className="pt-1">
            <Btn type="submit" primary disabled={busy || !u || !p} className="w-full py-2.5 text-[12px] font-bold tracking-[.1em]">
              {busy ? 'AUTHENTICATING…' : 'SIGN IN TO COMMAND CENTRE'}
            </Btn>
          </div>

          <div className="mt-5 pt-3 border-t border-ln/60 text-center">
            <p className="text-mu text-[10.5px] leading-relaxed m-0">
              Illustrative scenario: fictional locations and simulated telemetry, not operational records.
            </p>
          </div>
        </form>
      </div>
    </main>
  )
}
