import { fx } from '../format'
import { Card, StatusTag, Tag } from './ui'

export interface FlowEvent { event_id?: number; stock_before: number; stock_after: number; clipped_at_zero: boolean; item: { days_left: number; status: string } | null; location_status: string | null
  dashboard: { critical_items: number; warning_items: number; risk_index: number }; request?: { event_type: string; location_id: string; supply_id: string; quantity: number; device_id?: string; tag_id?: string } }
export interface FlowState { events: FlowEvent[]; before?: { critical: number; risk: number; itemStatus?: string; itemDays?: number } }

function Stage({ n, title, sub, children }: { n: number; title: string; sub: string; children: React.ReactNode }) {
  return (
    <div className="bg-ins border border-ln p-3 min-w-0 flex-1" data-testid={`iot-stage-${n}`}>
      <div className="font-mono text-[10px] tracking-[.12em] text-act">{n} · {title}</div>
      <div className="text-[11px] text-mu mb-2">{sub}</div>
      <div className="text-[12px] space-y-1">{children}</div>
    </div>
  )
}
const VALUE_FLOW = ['ESP32 / RFID TELEMETRY', 'API', 'PostgreSQL', 'INVENTORY / RISK', 'DECISION SUPPORT']
const Arrow = () => <div aria-hidden className="text-act text-[22px] self-center px-1 rotate-90 md:rotate-0 text-center">→</div>

/** Telemetry → Database → Inventory/Risk impact for the latest simulated scan. */
export default function IotFlow({ state }: { state: FlowState | null }) {
  const last = state?.events[state.events.length - 1]
  const r = last?.request
  return (
    <Card title="IoT DATA FLOW · TELEMETRY → DATABASE → INVENTORY / RISK IMPACT (ALL SIMULATED)" className="mb-3">
      <div data-testid="iot-value-flow" className="mb-3">
        <ol aria-label="IoT value flow" className="list-none p-0 m-0 flex flex-wrap items-center gap-x-1 gap-y-1.5 font-mono text-[11px]">
          {VALUE_FLOW.map((name, i) => (
            <li key={name} className="flex items-center gap-1">
              <span className={`border px-2 py-1 bg-ins ${i === VALUE_FLOW.length - 1 ? 'border-ac text-act' : 'border-ln text-tx'}`}>{name}</span>
              {i < VALUE_FLOW.length - 1 && <span aria-hidden className="text-act">→</span>}
            </li>
          ))}
        </ol>
        <div className="text-[11px] text-mu mt-1.5">Purpose: every scan updates stock, which updates days of supply and GREEN / YELLOW / RED risk, which refreshes priority and allocation so recommendations follow the latest inventory.
          <b className="text-wr"> All telemetry is simulated — no ESP32 or RFID hardware is connected or required.</b></div>
      </div>
      <div className="flex flex-col md:flex-row gap-2 md:gap-1 items-stretch" data-testid="iot-flow">
        <Stage n={1} title="TELEMETRY" sub="simulated ESP32 + RFID scan (no hardware)">
          {r ? (<>
            <div><Tag tone="wr">SIMULATED</Tag> <b>{r.event_type}</b> {r.location_id} / {r.supply_id}</div>
            <div>quantity <b>{fx(r.quantity)}</b>{r.device_id ? <> · device <span className="font-mono">{r.device_id}</span></> : null}{r.tag_id ? <> · tag <span className="font-mono">{r.tag_id}</span></> : null}</div>
            {state && state.events.length > 1 && <div className="text-mu">latest of {state.events.length} scans in this batch</div>}
          </>) : <div className="text-mu">Waiting for a scan. Send one below or run the simulator.</div>}
        </Stage>
        <Arrow />
        <Stage n={2} title="DATABASE" sub="FastAPI → PostgreSQL / PostGIS">
          {last ? (<>
            <div>validated and stored in <span className="font-mono">iot_events</span>{last.event_id ? <> as <b>#{last.event_id}</b></> : null}</div>
            <div><span className="font-mono">inventory.stock</span> <b>{fx(last.stock_before)} → {fx(last.stock_after)}</b>{last.clipped_at_zero ? ' (clipped at 0)' : ''}</div>
            <div className="text-mu">alerts, priority scores and allocation refreshed</div>
          </>) : <div className="text-mu">Each scan is validated, written to <span className="font-mono">iot_events</span>, applied to <span className="font-mono">inventory</span>, then alerts / priority / allocation are refreshed.</div>}
        </Stage>
        <Arrow />
        <Stage n={3} title="INVENTORY / RISK IMPACT" sub="recalculated by the backend">
          {last ? (<>
            {last.item && <div>{r?.location_id} {r?.supply_id}: cover <b>{last.item.days_left.toFixed(1)} d</b>{state?.before?.itemDays !== undefined ? <> (was {state.before.itemDays.toFixed(1)} d)</> : null} · {state?.before?.itemStatus ? <><StatusTag s={state.before.itemStatus} /> → </> : null}<StatusTag s={last.item.status} /></div>}
            {last.location_status && <div>location status: <StatusTag s={last.location_status} /></div>}
            <div>dashboard: critical items {state?.before ? <>{state.before.critical} → </> : null}<b>{last.dashboard.critical_items}</b> · risk index {state?.before ? <>{state.before.risk} → </> : null}<b>{last.dashboard.risk_index}</b> / 100</div>
          </>) : <div className="text-mu">Days of supply, GREEN/YELLOW/RED status, location status and the overall risk index update immediately.</div>}
        </Stage>
      </div>
    </Card>
  )
}
