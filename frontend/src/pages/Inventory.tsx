import { useState, type FormEvent } from 'react'
import { ApiError, get, post, useApi } from '../api'
import IotFlow, { type FlowState } from '../components/IotFlow'
import { useApp } from '../state'
import { usePalette } from '../theme'
import { Async, Btn, Card, ErrorBox, GridHalf, PageTitle, StatusTag, Table, Tag } from '../components/ui'
import { LineChartBox } from '../components/Charts'
import { fx } from '../format'
import type { InvItem, IotEvent } from '../types'

const LOCS = ['Base_01', 'Base_02', 'Base_03', 'Base_04', 'Base_05']
const SUPS = ['Food', 'Fuel', 'Water', 'Medical', 'Maintenance', 'Engineering', 'Clothing', 'Comms', 'Spares', 'Shelter']
interface Proj { days: number[]; projected_stock: number[]; safety_stock: number; days_left: number }
interface IotResult { event_id?: number; stock_before: number; stock_after: number; clipped_at_zero: boolean; item: { days_left: number; status: string } | null; location_status: string | null; dashboard: { critical_items: number; warning_items: number; risk_index: number }; notice: string; request?: { event_type: string; location_id: string; supply_id: string; quantity: number } }

export default function Inventory() {
  const pal = usePalette()
  const { sq, refreshKey, refresh } = useApp()
  const [f, setF] = useState({ l: '', t: '', s: '' })
  const [selKey, setSelKey] = useState<string | null>(null)
  const [flow, setFlow] = useState<FlowState | null>(null)
  const inv = useApi<InvItem[]>('/api/inventory' + (sq ? sq + '&' : '?') + new URLSearchParams({ ...(f.l && { location: f.l }), ...(f.t && { supply: f.t }), ...(f.s && { risk: f.s }) }).toString(), refreshKey)
  const rows = inv.data ?? []
  const cur = rows.find(i => i.location + i.supply === selKey) ?? rows[0]
  const proj = useApi<Proj>(cur ? '/api/inventory/projection' + (sq ? sq + '&' : '?') + new URLSearchParams({ location: cur.location, supply: cur.supply }).toString() : null, refreshKey)
  const events = useApi<IotEvent[]>('/api/iot/events?limit=8', refreshKey)
  return (
    <div>
      <PageTitle>INVENTORY · SUPPLY RISK</PageTitle>
      <div className="flex flex-wrap gap-2 mb-3 items-center">
        <label className="text-mu text-[11px]" htmlFor="il">LOCATION</label>
        <select id="il" value={f.l} onChange={e => setF({ ...f, l: e.target.value })}><option value="">All</option>{LOCS.map(x => <option key={x}>{x}</option>)}</select>
        <label className="text-mu text-[11px]" htmlFor="it">SUPPLY</label>
        <select id="it" value={f.t} onChange={e => setF({ ...f, t: e.target.value })}><option value="">All</option>{SUPS.map(x => <option key={x}>{x}</option>)}</select>
        <label className="text-mu text-[11px]" htmlFor="is">RISK</label>
        <select id="is" value={f.s} onChange={e => setF({ ...f, s: e.target.value })}><option value="">All</option>{['CRITICAL', 'WARNING', 'NORMAL'].map(x => <option key={x}>{x}</option>)}</select>
        <span className="font-mono" data-testid="item-count">{rows.length} items</span>
      </div>
      {cur && <Card title={`STOCK PROJECTION · ${cur.location} · ${cur.supply} · 14 D`} className="mb-3">
        <Async state={proj} what="projection">{p => (
          <LineChartBox xFormat={s => s} height={220} data={p.days.map((d, i) => ({ date: 'D+' + d, stock: p.projected_stock[i], safety: p.safety_stock })) as never}
            lines={[{ key: 'stock', name: 'Projected stock', color: pal.accent }, { key: 'safety', name: 'Safety stock', color: pal.danger, dashed: true }]} />)}</Async>
      </Card>}
      <Card title="INVENTORY POSITION" className="mb-3">
        <Async state={inv} what="inventory">{() => (
          <Table head={['LOCATION', 'SUPPLY', 'STOCK', 'SAFETY', 'DAILY USE', 'DAYS LEFT', 'PRED. SHORTAGE 14 D', 'RISK']}>
            {rows.map(i => (
              <tr key={i.location + i.supply} className={`row ${cur && cur.location + cur.supply === i.location + i.supply ? 'sel' : ''}`} onClick={() => setSelKey(i.location + i.supply)}>
                <td>{i.location}</td><td>{i.supply}</td><td>{fx(i.stock)}</td><td>{fx(i.safety_stock)}</td><td>{fx(i.daily_use)}</td><td>{i.days_left.toFixed(1)}</td><td>{fx(i.shortage_14d)}</td><td><StatusTag s={i.status} /></td></tr>))}
            {!rows.length && <tr><td colSpan={8}>No items match filters.</td></tr>}
          </Table>)}</Async>
      </Card>
      <IotFlow state={flow} />
      <GridHalf>
        <IotControls onDone={refresh} onFlow={setFlow} />
        <Card title="RECENT SIMULATED RFID / ESP32 EVENTS · POSTGRESQL iot_events">
          <Async state={events} what="IoT events">{ev => (
            <Table head={['ID', 'DEVICE', 'TYPE', 'LOCATION', 'SUPPLY', 'QTY', 'STOCK']}>
              {ev.map(e => <tr key={e.id}><td>{e.id}</td><td className="font-mono">{e.device_id}</td><td>{e.event_type}</td><td>{e.location_id}</td><td>{e.supply_id}</td><td>{fx(e.quantity)}</td><td>{fx(e.stock_before)} → {fx(e.stock_after)}</td></tr>)}
              {!ev.length && <tr><td colSpan={7}>No events yet. Send one on the left.</td></tr>}
            </Table>)}</Async>
          <div className="text-[11px] text-mu mt-2"><Tag tone="wr">SIMULATED</Tag> Events come from a software simulator, not hardware.</div>
        </Card>
      </GridHalf>
    </div>
  )
}

function IotControls({ onDone, onFlow }: { onDone: () => void; onFlow: (s: FlowState | null) => void }) {
  const [v, setV] = useState({ event_type: 'RECEIVE', location_id: 'Base_04', supply_id: 'Medical', quantity: 2000 })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<ApiError | null>(null)
  const [out, setOut] = useState<IotResult[] | null>(null)
  async function run(fn: () => Promise<IotResult[]>, opts?: { item?: { l: string; s: string }; reset?: boolean; req?: NonNullable<IotResult['request']> & { device_id?: string; tag_id?: string } }) {
    setBusy(true); setErr(null)
    try {
      let before: FlowState['before']
      if (!opts?.reset) {                    // context for the Telemetry -> Database -> Impact view; failure here must never block the scan
        try {
          const d = await get<{ kpis: { critical_shortages: number; risk_index: number } }>('/api/dashboard')
          before = { critical: Number(d.kpis.critical_shortages), risk: Number(d.kpis.risk_index) }
          if (opts?.item) { const it = await get<InvItem[]>(`/api/inventory?location=${opts.item.l}&supply=${opts.item.s}`); if (it[0]) { before.itemStatus = it[0].status; before.itemDays = it[0].days_left } }
        } catch { before = undefined }
      }
      const res = await fn(); setOut(res)
      onFlow(opts?.reset ? null : { events: res.map(o => ({ ...o, request: o.request ?? opts?.req })), before }); onDone() } catch (e) { setErr(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', String(e))) } finally { setBusy(false) }
  }
  const send = (e: FormEvent) => {
    e.preventDefault()
    const body = { device_id: 'ESP32-SIM-01', tag_id: 'RFID-SIM-' + Math.floor(1000 + Math.random() * 9000), ...v, quantity: Number(v.quantity), note: 'manual simulated scan' }
    run(async () => [await post<IotResult>('/api/iot/update', body)], { item: { l: v.location_id, s: v.supply_id }, req: { event_type: body.event_type, location_id: body.location_id, supply_id: body.supply_id, quantity: body.quantity, device_id: body.device_id, tag_id: body.tag_id } })
  }
  return (
    <Card title="SIMULATED ESP32 / RFID SCANNER">
      <form onSubmit={send} className="flex flex-wrap gap-2 items-end mb-3">
        <label className="text-[11px] text-mu">EVENT<br /><select value={v.event_type} onChange={e => setV({ ...v, event_type: e.target.value })}>{['RECEIVE', 'ISSUE', 'COUNT'].map(x => <option key={x}>{x}</option>)}</select></label>
        <label className="text-[11px] text-mu">LOCATION<br /><select value={v.location_id} onChange={e => setV({ ...v, location_id: e.target.value })}>{LOCS.map(x => <option key={x}>{x}</option>)}</select></label>
        <label className="text-[11px] text-mu">SUPPLY<br /><select value={v.supply_id} onChange={e => setV({ ...v, supply_id: e.target.value })}>{SUPS.map(x => <option key={x}>{x}</option>)}</select></label>
        <label className="text-[11px] text-mu">QUANTITY<br /><input type="number" min={0} step={10} className="w-24" value={v.quantity} onChange={e => setV({ ...v, quantity: Number(e.target.value) })} /></label>
        <Btn type="submit" primary disabled={busy}>SEND SCAN</Btn>
        <Btn disabled={busy} onClick={() => run(async () => (await post<{ events: IotResult[] }>('/api/iot/simulate', { count: 5 })).events)}>RUN SIMULATOR ×5</Btn>
        <Btn disabled={busy} onClick={() => run(async () => { await post('/api/iot/reset'); return [] }, { reset: true })}>RESET INVENTORY</Btn>
      </form>
      {err && <ErrorBox error={err} />}
      {out && out.length > 0 && (
        <div role="status" data-testid="iot-result" className="text-[12px]">
          {out.map((o, i) => (
            <div key={i} className="mb-1.5 border-l-[3px] border-ac pl-2 bg-ins py-1">
              {o.request && <b>{o.request.event_type} {o.request.location_id}/{o.request.supply_id} ×{fx(o.request.quantity)} · </b>}
              stock {fx(o.stock_before)} → <b>{fx(o.stock_after)}</b>{o.clipped_at_zero ? ' (clipped at 0)' : ''}
              {o.item && <> · cover {o.item.days_left.toFixed(1)} d · {o.item.status}</>} · dashboard: {o.dashboard.critical_items} critical, risk {o.dashboard.risk_index}/100
            </div>))}
          <div className="text-mu text-[11px]">{out[0].notice}</div>
        </div>)}
      {out && out.length === 0 && !err && <div className="text-ok text-[12px]">Inventory restored to the seeded state.</div>}
      <div className="text-[11px] text-mu mt-2">Each scan goes browser → FastAPI → PostgreSQL (iot_events + inventory), then alerts, priority and allocation tables are refreshed. All telemetry is simulated.</div>
    </Card>
  )
}
