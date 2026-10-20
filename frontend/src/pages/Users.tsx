import { useState, type FormEvent } from 'react'
import { ApiError, patch, post, useApi } from '../api'
import { useAuth, type Role, type User } from '../auth'
import { Async, Btn, Card, ErrorBox, PageHeader, Table, Tag } from '../components/ui'

interface Audit { id: number; ts: string; actor: string | null; action: string; target: string | null; outcome: string; client_ip: string | null }
const ROLES: Role[] = ['viewer', 'operator', 'admin']
const ROLE_HELP = 'viewer: read-only · operator: also records inventory events and runs simulations · admin: also resets inventory, recomputes forecasts and manages users'

export default function Users() {
  const { user: me } = useAuth()
  const [tick, setTick] = useState(0)
  const users = useApi<User[]>('/api/users', tick)
  const audit = useApi<Audit[]>('/api/audit-log?limit=30', tick)
  const [nu, setNu] = useState({ username: '', password: '', role: 'viewer' as Role })
  const [err, setErr] = useState<ApiError | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const reload = () => setTick(t => t + 1)
  async function run(fn: () => Promise<unknown>, done: string) {
    setBusy(true); setErr(null); setMsg(null)
    try { await fn(); setMsg(done); reload() } catch (x) { setErr(x instanceof ApiError ? x : new ApiError(0, 'UNKNOWN', String(x))) } finally { setBusy(false) }
  }
  const create = (e: FormEvent) => { e.preventDefault(); void run(async () => { await post('/api/users', nu); setNu({ username: '', password: '', role: 'viewer' }) }, `User ${nu.username} created.`) }
  const [resetFor, setResetFor] = useState<User | null>(null)
  const [newPw, setNewPw] = useState('')
  const doReset = (e: FormEvent) => {
    e.preventDefault()
    if (!resetFor) return
    const u = resetFor
    void run(async () => { await patch(`/api/users/${u.id}`, { password: newPw }); setResetFor(null); setNewPw('') }, `Password for ${u.username} reset; their sessions were signed out.`)
  }
  return (
    <div>
      <PageHeader title="USER ADMINISTRATION" subtitle="Accounts, roles and the security audit trail. Administrators only." />
      {err && <div className="mb-3"><ErrorBox error={err} /></div>}
      {msg && <div role="status" className="text-ok text-[12.5px] bg-ok/10 border border-ok/30 px-3 py-2 rounded-sm mb-3 flex items-center gap-2" data-testid="users-msg"><span className="inline-block w-1.5 h-1.5 rounded-full bg-ok" />{msg}</div>}
      <Card title="USERS" className="mb-3">
        <Async state={users} what="users">{list => (
          <Table head={['USER', 'ROLE', 'STATUS', 'LAST SIGN-IN', 'ACTIONS']}>
            {list.map(u => (
              <tr key={u.id}>
                <td>{u.username}{u.id === me?.id && <> <Tag>YOU</Tag></>}</td>
                <td><label className="sr-only" htmlFor={`role-${u.id}`}>Role of {u.username}</label>
                  <select id={`role-${u.id}`} value={u.role} disabled={busy} onChange={e => void run(() => patch(`/api/users/${u.id}`, { role: e.target.value }), `Role of ${u.username} changed.`)}>{ROLES.map(r => <option key={r}>{r}</option>)}</select></td>
                <td><Tag tone={u.is_active ? 'ok' : 'cr'}>{u.is_active ? 'ACTIVE' : 'DEACTIVATED'}</Tag></td>
                <td>{u.last_login_at ? new Date(u.last_login_at).toLocaleString() : 'never'}</td>
                <td className="whitespace-nowrap"><Btn disabled={busy} onClick={() => void run(() => patch(`/api/users/${u.id}`, { is_active: !u.is_active }), `${u.username} ${u.is_active ? 'deactivated' : 'reactivated'}.`)}>{u.is_active ? 'DEACTIVATE' : 'REACTIVATE'}</Btn>{' '}
                  <Btn disabled={busy} onClick={() => { setResetFor(u); setNewPw('') }}>RESET PASSWORD</Btn></td>
              </tr>))}
          </Table>)}</Async>
        <p className="text-[11px] text-mu mt-2">{ROLE_HELP}. Accounts are deactivated rather than deleted so the audit trail stays complete.</p>
      </Card>
      {resetFor && <Card title={`RESET PASSWORD · ${resetFor.username}`} className="mb-3" accent>
        <form onSubmit={doReset} className="flex flex-wrap gap-2 items-end" data-testid="reset-form">
          <label className="text-[11px] text-mu">NEW PASSWORD (12+)<br /><input type="password" required minLength={12} autoComplete="new-password" autoFocus value={newPw} onChange={e => setNewPw(e.target.value)} /></label>
          <Btn type="submit" primary disabled={busy}>SET PASSWORD</Btn><Btn onClick={() => setResetFor(null)}>CANCEL</Btn>
        </form></Card>}
      <Card title="ADD USER" className="mb-3">
        <form onSubmit={create} className="flex flex-wrap gap-2 items-end" data-testid="user-form">
          <label className="text-[11px] text-mu">USER NAME<br /><input type="text" required minLength={3} maxLength={40} pattern="[a-z0-9][a-z0-9._-]{2,39}" title="3-40 characters: lower-case letters, digits, . _ -" autoComplete="off" value={nu.username} onChange={e => setNu({ ...nu, username: e.target.value.toLowerCase() })} /></label>
          <label className="text-[11px] text-mu">INITIAL PASSWORD (12+)<br /><input type="password" required minLength={12} autoComplete="new-password" value={nu.password} onChange={e => setNu({ ...nu, password: e.target.value })} /></label>
          <label className="text-[11px] text-mu">ROLE<br /><select value={nu.role} onChange={e => setNu({ ...nu, role: e.target.value as Role })}>{ROLES.map(r => <option key={r}>{r}</option>)}</select></label>
          <Btn type="submit" primary disabled={busy}>ADD USER</Btn>
        </form>
      </Card>
      <Card title="AUDIT TRAIL · LAST 30 EVENTS">
        <Async state={audit} what="audit trail">{rows => (
          <Table head={['TIME', 'USER', 'ACTION', 'TARGET', 'OUTCOME', 'ADDRESS']}>
            {rows.map(r => <tr key={r.id}><td className="whitespace-nowrap">{new Date(r.ts).toLocaleString()}</td><td>{r.actor ?? '—'}</td><td>{r.action.replace(/_/g, ' ')}</td><td>{r.target ?? ''}</td>
              <td><Tag tone={r.outcome === 'success' ? 'ok' : r.outcome === 'denied' ? 'wr' : 'cr'}>{r.outcome.toUpperCase()}</Tag></td><td className="font-mono">{r.client_ip ?? ''}</td></tr>)}
          </Table>)}</Async>
      </Card>
    </div>
  )
}
