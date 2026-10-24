import { useState } from 'react'
import { ApiError, post, useApi } from '../api'
import { useAuth } from '../auth'
import { Btn, ErrorBox } from '../components/ui'
import { Async, Card, KV, Note, PageHeader, Table, Tag } from '../components/ui'
import type { ModelsStatus } from '../components/ModelRoles'

type M = { wape: number; mae: number; rmse: number; bias: number }
interface Evaluation {
  available: boolean; disclosure: string
  reports: {
    benchmark_forecast: { data: { shape: number[]; provenance: { dataset: string; licence: string; attribution: string; nature: string } }; selected: { num_leaves: number; objective: string; best_iteration: number }
      test: { n_rows: number; overall: Record<string, M>; by_horizon_bucket: Record<string, Record<string, { wape: number }>>; best_baseline: string
        rel_wape_improvement_vs_baseline_95ci: Record<string, number[]>; interval_coverage: Record<string, number>; items_where_lightgbm_beats_best_baseline: string }
      resources: Record<string, number | string> } | null
    scenario_forecast: { protocol: { rows: number; series: number; note: string }; overall: Record<string, M>; promotion: { status: string; reason: string | null }; interval_coverage: Record<string, Record<string, number>> } | null
    shortage_benchmark: { label_definition: string; test_onset_population: Record<string, { base_rate: number; roc_auc: number; pr_auc: number; brier: number; ece: number; precision?: number; recall?: number }>
      test_all_days_context: { share_of_positive_days_that_are_onset: number } } | null
    supply_csv_profile: { rows: number; conclusion: string } | null
  }
}
const NAME: Record<string, string> = { lightgbm: 'Trained LightGBM', random_forest: 'Random Forest (same features)', 'statistical_ewma (existing)': 'Statistical baseline (existing)', naive_last: 'Last value',
  seasonal_naive_7: 'Seasonal naive (7 d)', trailing_mean_28: 'Trailing 28-day mean', ml_plain: 'Trained model (plain)', ml_weather_adapter: 'Trained model + weather adapter',
  lightgbm_calibrated: 'LightGBM, calibrated', lightgbm_uncalibrated: 'LightGBM, uncalibrated', lightgbm_stock_only: 'LightGBM, stock-only inputs', logistic_regression: 'Logistic regression', cover_days_rule_logistic: 'Days-of-cover rule (calibrated)', constant_base_rate: 'Constant base rate' }
const pc = (v: number, d = 2) => (v * 100).toFixed(d) + '%'

const SERIES = [['demand', 'Daily demand'], ['on_hand', 'Daily on-hand stock'], ['in_transit', 'Daily in-transit quantity'], ['backlog', 'Daily backlog'], ['new_backlog', 'Daily new backlog']] as const
interface Score { applicable: boolean; reason?: string; probability?: number; horizon_days?: number; threshold?: number; flag?: boolean; model: string }
const parseSeries = (t: string) => t.split(/[\s,;]+/).filter(Boolean).map(Number)

/** Scores ONE record supplied by the user in the benchmark's format. It does not read the application's inventory and does not change any status. */
function ShortageCheck() {
  const { user } = useAuth()
  const [txt, setTxt] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<ApiError | null>(null)
  const [res, setRes] = useState<Score | null>(null)
  async function run() {
    setBusy(true); setErr(null); setRes(null)
    try {
      const body = Object.fromEntries(SERIES.map(([k]) => [k, parseSeries(txt[k] ?? '')]))
      if (SERIES.some(([k]) => (body[k] as number[]).some(Number.isNaN))) throw new ApiError(0, 'LOCAL_VALIDATION', 'Every value must be a number (separate values with commas, spaces or new lines).')
      setRes(await post<Score>('/api/ml/shortage-risk', body))
    } catch (e) { setErr(e instanceof ApiError ? e : new ApiError(0, 'UNKNOWN', String(e))) } finally { setBusy(false) }
  }
  return (
    <Card title="4 · SHORTAGE-ONSET CHECK FOR A BENCHMARK-FORMAT RECORD" className="mb-3">
      <p className="text-[12px] mb-2">Enter five equally long daily histories (at least 28 days, oldest first, last value = today) for one item at one node. The trained model returns the probability that a backlog <b>begins within 7 days</b>. This check is independent of the application's inventory: it does not read stored stock and does not change any status.</p>
      <div className="grid gap-2 md:grid-cols-2" data-testid="shortage-form">
        {SERIES.map(([k, label]) => <label key={k} className="text-[11px] text-mu">{label.toUpperCase()}<textarea rows={2} className="w-full mt-1 font-mono text-[12px]" value={txt[k] ?? ''} onChange={e => setTxt({ ...txt, [k]: e.target.value })} spellCheck={false} /></label>)}
      </div>
      <div className="mt-2 flex items-center gap-3 flex-wrap">
        <Btn primary disabled={busy || !user || SERIES.some(([k]) => !(txt[k] ?? '').trim())} onClick={() => void run()}>
          {busy ? 'SCORING…' : 'SCORE RECORD'}
        </Btn>
        {!user && <span className="text-mu text-[11px] font-mono">Sign-in required to score custom records. Evaluator model reports are available below.</span>}
      </div>
      {err && <div className="mt-2"><ErrorBox error={err} /></div>}
      {res && (res.applicable
        ? <div role="status" className="mt-2.5 border-l-[3px] border-ac pl-3 bg-ins/90 py-2 text-[12.5px] rounded-r-sm" data-testid="shortage-result">Shortage-onset probability within {res.horizon_days} days: <b className="text-act">{((res.probability ?? 0) * 100).toFixed(1)}%</b> · decision threshold {((res.threshold ?? 0) * 100).toFixed(1)}% → <Tag tone={res.flag ? 'cr' : 'ok'}>{res.flag ? 'ABOVE THRESHOLD' : 'BELOW THRESHOLD'}</Tag> <span className="text-mu block sm:inline mt-1 sm:mt-0">({res.model}; probabilities are calibrated on the benchmark, not on real operations)</span></div>
        : <div role="status" className="mt-2.5 text-wr text-[12.5px] bg-ins/80 border border-wr/30 p-2 rounded-sm" data-testid="shortage-result">Not applicable: {res.reason}.</div>)}
    </Card>
  )
}

export default function Models() {
  const ev = useApi<Evaluation>('/api/ml/evaluation')
  const md = useApi<ModelsStatus>('/api/ml/models')
  return (
    <div>
      <PageHeader title="MODEL EVALUATION" subtitle="Measured results of the training pipeline, the data it used, and what those results do and do not show."
        meta={<span>MEASURED BY ml/ SCRIPTS · REPORTS READ FROM ml/reports</span>} />
      <div role="note" className="border border-ac bg-ins/90 p-3.5 mb-3 text-[12.5px] rounded-sm shadow-xs" data-testid="benchmark-disclosure">
        <div className="flex items-center gap-1.5 mb-1">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-ac" />
          <b className="text-act font-mono tracking-[.14em] text-[11px] uppercase">READ THIS FIRST · RESEARCH BENCHMARK NOTICE</b>
        </div>
        <div className="leading-relaxed text-soft">ISOMORPH is a <b>simulator-generated research benchmark</b>, not observed logistics operations. Scores below measure performance on that benchmark and on this application's illustrative scenario. They are not evidence of accuracy on any real supply system.</div>
      </div>
      <Async state={md} what="model registry">{m => (
        <Card title="MODEL REGISTRY" className="mb-3">
          <KV rows={[
            ['Active forecast model', <span data-testid="registry-active">{m.active_forecast_model.model_id} <Tag tone={m.active_forecast_model.family === 'machine_learning' ? 'ok' : ''}>{m.active_forecast_model.family === 'machine_learning' ? 'TRAINED ML' : 'STATISTICAL'}</Tag></span>],
            ['Configured mode', m.mode],
            ['Trained demand model', m.demand_forecast.loaded ? `${m.demand_forecast.artefact?.model_id} · ${m.demand_forecast.promotion?.status ?? 'no decision'}` : `unavailable (${m.demand_forecast.error})`],
            ['Shortage-risk model', m.shortage_risk.loaded ? m.shortage_risk.artefact?.model_id : `unavailable (${m.shortage_risk.error})`],
          ]} />
          {m.active_forecast_model.fallback_reason && <Note>{m.active_forecast_model.fallback_reason}</Note>}
          <Note>{m.shortage_risk.note}</Note>
        </Card>)}</Async>
      <Async state={ev} what="evaluation reports">{e => { const b = e.reports.benchmark_forecast, s = e.reports.scenario_forecast, h = e.reports.shortage_benchmark, c = e.reports.supply_csv_profile
        return (<>
        {!e.available && <div role="status" className="border border-ln bg-pn p-4 mb-3">Evaluation reports are not present. Run the training pipeline (see ml/README.md).</div>}
        {b && <Card title="1 · DEMAND FORECAST · BENCHMARK TEST SPLIT (CHRONOLOGICAL, EVALUATED ONCE)" className="mb-3">
          <Table head={['MODEL', 'WAPE', 'MAE', 'RMSE', 'BIAS', 'WAPE d1–7', 'WAPE d8–14', 'WAPE d15–30']}>
            {Object.entries(b.test.overall).map(([k, v]) => <tr key={k}><td>{NAME[k] ?? k}{k === b.test.best_baseline && <> <Tag>BEST BASELINE</Tag></>}</td><td>{pc(v.wape)}</td><td>{v.mae.toFixed(1)}</td><td>{v.rmse.toFixed(1)}</td><td>{pc(v.bias)}</td>
              {['h01_07', 'h08_14', 'h15_30'].map(x => <td key={x}>{pc(b.test.by_horizon_bucket[x][k].wape)}</td>)}</tr>)}
          </Table>
          <Note>
            <span>Rows: {b.test.n_rows.toLocaleString()} (items × origins × horizons 1–30)</span>
            <span>Improvement vs best baseline, 95% CI: {pc(b.test.rel_wape_improvement_vs_baseline_95ci[b.test.best_baseline][0], 1)} to {pc(b.test.rel_wape_improvement_vs_baseline_95ci[b.test.best_baseline][1], 1)}</span>
            <span>Items improved: {b.test.items_where_lightgbm_beats_best_baseline}</span>
            <span>80% interval coverage on test: {pc(b.test.interval_coverage.test_overall, 1)}</span>
          </Note>
          <Note><span>Latency {String(b.resources.lightgbm_latency_ms_30_horizons_median)} ms per series (30 horizons)</span><span>Model file {String(b.resources.model_file_kb)} KB</span><span>Training {String(b.resources.train_seconds_best_config)} s (1 CPU thread)</span></Note>
          <Note>WAPE = Σ|actual − forecast| / Σ actual. The existing statistical model was run on the benchmark with its weather term disabled (no weather series exists there).</Note>
        </Card>}
        {s && <Card title="2 · SAME MODELS ON THIS APPLICATION'S ILLUSTRATIVE SCENARIO (ROLLING-ORIGIN HOLDOUT)" className="mb-3">
          <Table head={['MODEL', 'WAPE (d1–30)', 'MAE', 'RMSE']}>
            {Object.entries(s.overall).map(([k, v]) => <tr key={k}><td>{NAME[k] ?? k}</td><td>{pc(v.wape)}</td><td>{v.mae.toFixed(1)}</td><td>{v.rmse.toFixed(1)}</td></tr>)}
          </Table>
          <Note><span data-testid="promotion-status">Promotion decision: <b>{s.promotion.status.replace('_', ' ').toUpperCase()}</b></span></Note>
          {s.promotion.reason && <Note>{s.promotion.reason}</Note>}
          <Note>{s.protocol.note}. {s.protocol.series} series, {s.protocol.rows.toLocaleString()} forecast rows.</Note>
        </Card>}
        {h && <Card title="3 · SHORTAGE-ONSET RISK · BENCHMARK TEST (7-DAY, ITEM-DAYS WITH NO BACKLOG)" className="mb-3">
          <Table head={['MODEL', 'ROC-AUC', 'PR-AUC', 'BRIER', 'CALIBRATION ERROR (ECE)']}>
            {Object.entries(h.test_onset_population).map(([k, v]) => <tr key={k}><td>{NAME[k] ?? k}</td><td>{v.roc_auc.toFixed(3)}</td><td>{v.pr_auc.toFixed(3)}</td><td>{v.brier.toFixed(4)}</td><td>{v.ece.toFixed(4)}</td></tr>)}
          </Table>
          <Note>Target: {h.label_definition}. Only {pc(h.test_all_days_context.share_of_positive_days_that_are_onset, 0)} of shortage-risk days are onsets; the rest are continuing backlogs that persistence already predicts.</Note>
          <Note>This model needs backlog and in-transit histories that the illustrative scenario does not have, so it does not drive the application's inventory status. Its probabilities are calibrated to the ISOMORPH replenishment policy only.</Note>
        </Card>}
        <ShortageCheck />
        <Card title="5 · DATA SOURCES, LICENCES AND LIMITATIONS">
          <KV rows={[
            ['ISOMORPH Sample', <span className="font-normal">{b?.data.provenance.nature ?? 'simulator-generated research benchmark'}. Licence {b?.data.provenance.licence ?? 'CC-BY-4.0'}. {b?.data.provenance.attribution}</span>],
            ['Training target', <span className="font-normal">Observed daily demand counts (daily_records.demand). The file demand_signals.npy holds the simulator's latent, non-integer intensity and is not used as a target.</span>],
            ['Supply optimisation CSV', <span className="font-normal">{c ? c.conclusion : 'Profile report unavailable.'}</span>],
            ['Illustrative scenario', <span className="font-normal">Fictional locations, simulated consumption, weather and IoT telemetry. Not operational records.</span>],
            ['Not validated', <span className="font-normal">Route-disruption prediction (no outcome labels exist in any supplied dataset) and accuracy on real operations.</span>],
          ]} />
        </Card></>) }}</Async>
    </div>
  )
}
