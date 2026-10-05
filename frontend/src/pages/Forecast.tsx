import { useState } from 'react'
import { usePalette } from '../theme'
import { useApi, qs } from '../api'
import { Async, Btn, CONFIDENCE_NOTE, Card, ConfidenceIndex, InfoTip, KV, Kpi, KpiGrid, PageTitle } from '../components/ui'
import { LineChartBox } from '../components/Charts'
import { fx } from '../format'
import ModelRoles from '../components/ModelRoles'

interface Fc {
  location: string | null; supply: string | null; horizon: number
  history: { date: string; actual: number; fit: number | null }[]
  forecast: { date: string; value: number; lo: number; hi: number }[]
  totals: { d7: number; d14: number; d30: number }; hist_mean_per_day: number
  backtest: { mape: number; rmse: number; coefficient_of_variation: number; interval_coverage: number; window_days: number }
  confidence: { value: number; label: string; level: 'ok' | 'wr' | 'cr' }
  methodology: Record<string, any>
}
interface Challenger { trees: number; depth: number; train_samples: number; holdout_samples: number; holdout_series: number; rf_mape: number; statistical_mape: number; features: string[]; train_days: string; holdout_days: string; role: string; library: string }

const LOCS = ['Base_01', 'Base_02', 'Base_03', 'Base_04', 'Base_05']
const SUPS = ['Food', 'Fuel', 'Water', 'Medical', 'Maintenance', 'Engineering', 'Clothing', 'Comms', 'Spares', 'Shelter']

export default function Forecast() {
  const pal = usePalette()
  const [loc, setLoc] = useState(''); const [sup, setSup] = useState(''); const [hz, setHz] = useState(14)
  const fc = useApi<Fc>('/api/forecast' + qs({ location: loc, supply: sup, horizon: hz }))
  const ch = useApi<Challenger>('/api/forecast/challenger')
  return (
    <div>
      <PageTitle>DEMAND FORECAST · FORECAST</PageTitle>
      <div className="flex flex-wrap gap-2 mb-3 items-center">
        <label className="text-mu text-[11px]" htmlFor="fl">LOCATION</label>
        <select id="fl" value={loc} onChange={e => setLoc(e.target.value)}><option value="">All locations</option>{LOCS.map(l => <option key={l}>{l}</option>)}</select>
        <label className="text-mu text-[11px]" htmlFor="ft">SUPPLY</label>
        <select id="ft" value={sup} onChange={e => setSup(e.target.value)}><option value="">All supply types</option>{SUPS.map(l => <option key={l}>{l}</option>)}</select>
        {[7, 14, 30].map(k => <Btn key={k} active={hz === k} onClick={() => setHz(k)}>{k}-DAY</Btn>)}
      </div>
      <Async state={fc} what="forecast">{f => { const m = f.methodology; return (<>
        <KpiGrid>
          <Kpi label="7-DAY FORECAST" value={fx(f.totals.d7)} sub="units" /><Kpi label="14-DAY FORECAST" value={fx(f.totals.d14)} sub="units" /><Kpi label="30-DAY FORECAST" value={fx(f.totals.d30)} sub="units" />
          <Kpi label="HIST. MEAN / DAY" value={fx(f.hist_mean_per_day)} sub="last 30 d" /><Kpi label="BACKTEST MAPE" value={f.backtest.mape.toFixed(1) + '%'} sub="last 60 d" tone="ok" />
          <Kpi label="FORECAST CONFIDENCE INDEX" value={`${f.confidence.value}/100`} sub={<>{f.confidence.label} · {f.horizon}-day<InfoTip text={CONFIDENCE_NOTE} label="About the confidence index" /></>} tone={f.confidence.level} />
        </KpiGrid>
        <Card title={`ACTUAL VS PREDICTED CONSUMPTION · ${f.location || 'ALL LOCATIONS'} · ${f.supply || 'ALL SUPPLY'} · ${f.horizon}-DAY OUTLOOK`} className="mb-3">
          <LineChartBox height={300} zoom
            data={[...f.history.map(h => ({ date: h.date, actual: h.actual, pred: h.fit })), ...f.forecast.map(x => ({ date: x.date, pred: x.value, band: [x.lo, x.hi] as number[] }))] as never}
            lines={[{ key: 'actual', name: 'Actual', color: pal.tx }, { key: 'pred', name: 'Statistical baseline (fit / forecast)', color: pal.accent, dashed: true }]} band={{ key: 'band', name: '80% interval' }} />
          <div className="text-[11px] text-mu mt-2">Shaded band = 80% interval. Model: weather-adjusted EWMA level + damped trend + weekly seasonality, driven by the synthetic weather outlook. {fx(m.records)} historical records in PostgreSQL.</div>
        </Card>
        <ModelRoles f={f} c={ch.data} />
        <Card title="FORECAST METHODOLOGY · PREDICTION ENGINE">
          <Async state={ch} what="challenger">{c => (
            <KV rows={[
              ['Method in use', <span className="font-normal">{m.method}</span>],
              ['Historical input signals', <span className="font-normal">Daily consumption per location × supply type over {m.history_days} days ({fx(m.records)} records). Selected: {f.location || 'all 5 locations'} · {f.supply || 'all 10 supply types'}.</span>],
              ['Weather signal', <span className="font-normal">Synthetic weather-severity index (0–1). Demand multiplier = 1 + sensitivity × 0.6 × index; sensitivity {m.weather_sensitivity_range[0]}–{m.weather_sensitivity_range[1]} for this selection. Current index {m.weather_index_now.toFixed(2)}; 30-day outlook peaks at {m.weather_outlook_peak.toFixed(2)} on day +{m.weather_outlook_peak_day}.</span>],
              ['Seasonality', <span className="font-normal">{m.seasonality}</span>],
              ['Forecast horizon', <span className="font-normal">{f.horizon} days shown (7 / 14 / 30 selectable).</span>],
              ['Backtest MAPE', <span className="font-normal">{f.backtest.mape.toFixed(1)}% (rolling one-step-ahead, last {f.backtest.window_days} days).</span>],
              ['Interval calibration', <span className="font-normal">{f.backtest.interval_coverage.toFixed(0)}% of the last 60 actuals fell inside the ±1.28σ band (σ = backtest RMSE).</span>],
              ['Demand variability', <span className="font-normal">Coefficient of variation {f.backtest.coefficient_of_variation.toFixed(1)}% over the last 60 days.</span>],
              ['Challenger ML model', <span className="font-normal">Random Forest regression ({c.trees} trees, depth {c.depth}, bootstrap + feature subsampling; {c.library}), trained on the synthetic history ({c.train_samples} samples, days {c.train_days}, seeded). Role: cross-check only — dashboard forecasts, shortage dates and recommendations use the statistical model.</span>],
              ['ML input features', <span className="font-normal">{c.features.join(', ')}.</span>],
              ['ML validation metric', <span className="font-normal">Hold-out MAPE <b>{c.rf_mape.toFixed(1)}%</b> on days {c.holdout_days} ({c.holdout_samples} unseen series-days across {c.holdout_series} series), vs <b>{c.statistical_mape.toFixed(1)}%</b> for the statistical model on the same samples.</span>],
              ['Accuracy caveat', <span className="font-normal">{m.accuracy_caveat}</span>],
              ['Forecast confidence', <span className="font-normal"><ConfidenceIndex value={f.confidence.value} label={f.confidence.label} level={f.confidence.level} className="font-semibold" /> = {m.confidence_formula}. {CONFIDENCE_NOTE}</span>],
            ]} />)}</Async>
        </Card></>) }}</Async>
    </div>
  )
}
