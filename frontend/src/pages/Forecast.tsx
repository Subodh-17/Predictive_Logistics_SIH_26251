import { useState } from 'react'
import { usePalette } from '../theme'
import { useApi, qs } from '../api'
import { Async, Btn, CONFIDENCE_NOTE, Card, ConfidenceIndex, InfoTip, KV, Kpi, KpiGrid, PageHeader, Tag } from '../components/ui'
import { LineChartBox } from '../components/Charts'
import { fx } from '../format'
import ModelRoles, { type ModelsStatus, type ScenarioEval } from '../components/ModelRoles'

interface Fc {
  location: string | null; supply: string | null; horizon: number
  model: { id: string; family: 'machine_learning' | 'statistical'; label: string; series_by_model: Record<string, number>; series_on_statistical_fallback: number
    fallback_reason: string | null; configured_mode: string; generated_at: string | null; history_through: string; interval: { level: number; source: string } }
  trained_model_preview: { model_id: string; dates: string[]; values: number[]; note: string } | null
  history: { date: string; actual: number; fit: number | null }[]
  forecast: { date: string; value: number; lo: number; hi: number }[]
  totals: { d7: number; d14: number; d30: number }; hist_mean_per_day: number
  backtest: { mape: number; rmse: number; coefficient_of_variation: number; interval_coverage: number; window_days: number; kind: string }
  confidence: { value: number; label: string; level: 'ok' | 'wr' | 'cr' }
  methodology: Record<string, any>
}

const LOCS = ['Base_01', 'Base_02', 'Base_03', 'Base_04', 'Base_05']
const SUPS = ['Food', 'Fuel', 'Water', 'Medical', 'Maintenance', 'Engineering', 'Clothing', 'Comms', 'Spares', 'Shelter']
const when = (iso: string | null) => iso ? new Date(iso).toISOString().replace('T', ' ').slice(0, 16) + ' UTC' : 'unknown'

export default function Forecast() {
  const pal = usePalette()
  const [loc, setLoc] = useState(''); const [sup, setSup] = useState(''); const [hz, setHz] = useState(14)
  const fc = useApi<Fc>('/api/forecast' + qs({ location: loc, supply: sup, horizon: hz }))
  const models = useApi<ModelsStatus>('/api/ml/models')
  const ev = useApi<{ reports: { scenario_forecast: ScenarioEval | null } }>('/api/ml/evaluation')
  return (
    <div>
      <PageHeader title="DEMAND FORECAST" subtitle="Expected daily consumption for the selected location and supply type, with the model that produced it, its horizon and its uncertainty."
        meta={fc.data ? <><span>MODEL · <b className="text-tx" data-testid="forecast-model-id">{fc.data.model.id}</b></span><span>GENERATED · {when(fc.data.model.generated_at)}</span><span>HISTORY THROUGH · {fc.data.model.history_through}</span><span>HORIZON · {fc.data.horizon} d</span></> : undefined} />
      <div className="bento-card px-3.5 py-2.5 mb-3 flex flex-wrap gap-3 items-center" role="group" aria-label="Forecast filters">
        <div className="flex items-center gap-1.5">
          <label className="text-mu font-mono text-[11px] uppercase tracking-wide" htmlFor="fl">LOCATION</label>
          <select id="fl" value={loc} onChange={e => setLoc(e.target.value)}><option value="">All locations</option>{LOCS.map(l => <option key={l}>{l}</option>)}</select>
        </div>
        <div className="flex items-center gap-1.5">
          <label className="text-mu font-mono text-[11px] uppercase tracking-wide" htmlFor="ft">SUPPLY</label>
          <select id="ft" value={sup} onChange={e => setSup(e.target.value)}><option value="">All supply types</option>{SUPS.map(l => <option key={l}>{l}</option>)}</select>
        </div>
        <div className="flex items-center gap-1 ml-auto">
          <span className="text-mu font-mono text-[10px] uppercase tracking-wider mr-1">HORIZON</span>
          {[7, 14, 30].map(k => <Btn key={k} active={hz === k} onClick={() => setHz(k)}>{k}-DAY</Btn>)}
        </div>
      </div>
      <Async state={fc} what="forecast">{f => { const m = f.methodology; const ml = f.model.family === 'machine_learning'; return (<>
        <div role="note" data-testid="model-attribution" className={`border p-3 mb-3 text-[12.5px] rounded-sm ${ml ? 'border-ok/80 bg-ok/5' : 'border-ln bg-ins/80'}`}>
          <div className="flex flex-wrap items-center gap-2">
            <Tag tone={ml ? 'ok' : ''}>{f.model.label.toUpperCase()}</Tag>
            <b className="font-mono text-tx">{f.model.id}</b>
            {f.model.series_on_statistical_fallback > 0 && <span className="text-wr text-[11.5px] font-mono">({f.model.series_on_statistical_fallback} series on statistical fallback)</span>}
          </div>
          {f.model.fallback_reason && <div className="mt-1.5 text-soft text-[12px]">Why not the trained model: {f.model.fallback_reason}</div>}
          <div className="mt-1 text-mu text-[11.5px]">Interval ({Math.round(f.model.interval.level * 100)}%): {f.model.interval.source}.</div>
        </div>
        <KpiGrid>
          <Kpi label="7-DAY FORECAST" value={fx(f.totals.d7)} sub="units" /><Kpi label="14-DAY FORECAST" value={fx(f.totals.d14)} sub="units" /><Kpi label="30-DAY FORECAST" value={fx(f.totals.d30)} sub="units" />
          <Kpi label="HIST. MEAN / DAY" value={fx(f.hist_mean_per_day)} sub="last 30 d" /><Kpi label="BACKTEST MAPE" value={f.backtest.mape.toFixed(1) + '%'} sub={`last ${f.backtest.window_days} d · one-step`} />
          <Kpi label="FORECAST CONFIDENCE INDEX" value={`${f.confidence.value}/100`} sub={<>{f.confidence.label} · {f.horizon}-day<InfoTip text={CONFIDENCE_NOTE} label="About the confidence index" /></>} tone={f.confidence.level} />
        </KpiGrid>
        <Card title={`ACTUAL VS PREDICTED CONSUMPTION · ${f.location || 'ALL LOCATIONS'} · ${f.supply || 'ALL SUPPLY'} · ${f.horizon}-DAY OUTLOOK`} className="mb-3">
          <LineChartBox height={300} zoom label={`Actual and forecast daily consumption, ${f.horizon}-day outlook, with ${Math.round(f.model.interval.level * 100)}% interval`}
            data={[...f.history.map(h => ({ date: h.date, actual: h.actual, pred: h.fit })), ...f.forecast.map((x, k) => ({ date: x.date, pred: x.value, band: [x.lo, x.hi] as number[], ml: f.trained_model_preview?.values[k] }))] as never}
            lines={[{ key: 'actual', name: 'Actual', color: pal.tx }, { key: 'pred', name: `${f.model.label} (fit / forecast)`, color: pal.accent, dashed: true },
              ...(f.trained_model_preview ? [{ key: 'ml', name: 'Trained ML model (preview, not active)', color: pal.ok, dashed: true }] : [])]}
            band={{ key: 'band', name: `${Math.round(f.model.interval.level * 100)}% interval` }} />
          <div className="text-[11px] text-mu mt-2">Shaded band = {Math.round(f.model.interval.level * 100)}% interval from the active model. History shows out-of-sample one-step fits. {fx(m.records)} historical records in PostgreSQL. Scenario data is simulated.</div>
        </Card>
        <ModelRoles m={models.data} sc={ev.data?.reports.scenario_forecast ?? null} />
        <Card title="FORECAST METHODOLOGY">
          <KV rows={[
            ['Method in use', <span className="font-normal">{m.method}</span>],
            ['Historical input signals', <span className="font-normal">Daily consumption per location × supply type over {m.history_days} days ({fx(m.records)} records). Selected: {f.location || 'all 5 locations'} · {f.supply || 'all 10 supply types'}.</span>],
            ['Weather signal', <span className="font-normal">Simulated weather-severity index (0–1). Demand multiplier = 1 + sensitivity × 0.6 × index; sensitivity {m.weather_sensitivity_range[0]}–{m.weather_sensitivity_range[1]} for this selection. Current index {m.weather_index_now.toFixed(2)}; 30-day outlook peaks at {m.weather_outlook_peak.toFixed(2)} on day +{m.weather_outlook_peak_day}.</span>],
            ['Seasonality', <span className="font-normal">{m.seasonality}</span>],
            ['Backtest', <span className="font-normal">MAPE {f.backtest.mape.toFixed(1)}% ({f.backtest.kind}, last {f.backtest.window_days} days; days with zero actual demand are excluded from MAPE).</span>],
            ['Interval check', <span className="font-normal">{f.backtest.interval_coverage.toFixed(0)}% of the last 60 actuals fell inside ±1.28σ of the one-step backtest error.</span>],
            ['Demand variability', <span className="font-normal">Coefficient of variation {f.backtest.coefficient_of_variation.toFixed(1)}% over the last 60 days.</span>],
            ['Accuracy caveat', <span className="font-normal">{m.accuracy_caveat}</span>],
            ['Forecast confidence', <span className="font-normal"><span data-testid="confidence-value"><ConfidenceIndex value={f.confidence.value} label={f.confidence.label} level={f.confidence.level} className="font-semibold" /></span> = {m.confidence_formula} <span data-testid="confidence-note">{CONFIDENCE_NOTE}</span></span>],
          ]} />
        </Card></>) }}</Async>
    </div>
  )
}
