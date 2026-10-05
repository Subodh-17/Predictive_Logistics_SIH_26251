import { fx } from '../format'
import { CONFIDENCE_NOTE, Card, ConfidenceIndex, Tag } from './ui'

export interface FcLite {
  totals: { d7: number; d14: number; d30: number }
  backtest: { mape: number; rmse: number; coefficient_of_variation: number; interval_coverage: number; window_days: number }
  confidence: { value: number; label: string; level: 'ok' | 'wr' | 'cr' }
  horizon: number; methodology: Record<string, any>
}
export interface ChLite { trees: number; depth: number; train_samples: number; holdout_samples: number; holdout_series: number; rf_mape: number; statistical_mape: number; features: string[]; train_days: string; holdout_days: string; library: string }

/** Makes the role of each model explicit: statistical baseline (drives decisions) vs Random Forest (cross-check) vs the rule-based recommendation engine. */
export default function ModelRoles({ f, c }: { f: FcLite; c: ChLite | null }) {
  const rfBetter = c ? c.rf_mape < c.statistical_mape : false
  return (
    <div className="mb-3" data-testid="model-roles">
      <div role="note" className="border border-act bg-ins p-3 mb-3 text-[13px]">
        <b className="text-act font-mono tracking-wide text-[11px]">WHAT IS AND IS NOT “AI” IN THIS SYSTEM</b>
        <div className="mt-1">Only one trained machine-learning model exists: the <b>Random Forest challenger</b>, and it is a <b>cross-check that does not feed any decision</b>.
          Dashboard numbers come from the <b>statistical baseline forecast</b>. Shortage dates, priorities, routes and dispatch advice come from a <b>deterministic rule-based engine</b> —
          it is <b>not machine learning, not an LLM and not generative AI</b>.</div>
      </div>
      <div className="grid gap-3 lg:grid-cols-3">
        <Card title="1 · STATISTICAL BASELINE FORECAST">
          <div className="mb-2"><Tag tone="ok">DRIVES THE DASHBOARD</Tag> <Tag>NOT ML-TRAINED</Tag></div>
          <p className="m-0 mb-2">Weather-adjusted EWMA level + damped trend + weekly seasonality. Deterministic, explainable, recomputed from the database.</p>
          <p className="m-0 text-mu text-[12px] mb-2">Used for: days of supply, shortage dates, GREEN/YELLOW/RED status, priority queue, allocation and the What-If simulation.</p>
          <div className="font-mono text-[12px]">7 d {fx(f.totals.d7)} · 14 d {fx(f.totals.d14)} · 30 d {fx(f.totals.d30)} units</div>
        </Card>
        <Card title="2 · RANDOM FOREST CHALLENGER">
          <div className="mb-2"><Tag tone="wr">CROSS-CHECK ONLY</Tag> <Tag>NOT USED IN DECISIONS</Tag></div>
          {c ? (<>
            <p className="m-0 mb-2">{c.library}: {c.trees} trees, depth {c.depth}, seeded. Trained on days {c.train_days} ({fx(c.train_samples)} samples), validated on days {c.holdout_days} ({fx(c.holdout_samples)} unseen series-days, {c.holdout_series} series).</p>
            <p className="m-0 text-mu text-[12px]">Features ({c.features.length}): {c.features.join(', ')}.</p>
          </>) : <p className="m-0 text-mu">Challenger metrics unavailable.</p>}
        </Card>
        <Card title="3 · VALIDATION METRICS">
          {c ? (<>
            <div data-testid="model-metrics">
              <div className="font-mono text-[10px] tracking-[.08em] text-mu mb-1">HOLD-OUT MAPE · days {c.holdout_days}, same samples</div>
              <div className="flex justify-between gap-3 border-b border-rowln py-1"><span>Statistical baseline</span><b className={`tabular-nums ${rfBetter ? '' : 'text-ok'}`}>{c.statistical_mape.toFixed(1)}%</b></div>
              <div className="flex justify-between gap-3 border-b border-rowln py-1"><span>Random Forest challenger</span><b className={`tabular-nums ${rfBetter ? 'text-ok' : ''}`}>{c.rf_mape.toFixed(1)}%</b></div>
            </div>
            <p className="m-0 mt-2 text-[12px]">{rfBetter ? 'The Random Forest has lower hold-out error on this synthetic data; it stays a cross-check until validated on real data.'
              : `The statistical model has lower hold-out error (${(c.rf_mape - c.statistical_mape).toFixed(1)} pts), which is why it drives decisions.`}</p>
          </>) : <p className="m-0 text-mu">Hold-out comparison unavailable.</p>}
          <p className="m-0 mt-2 text-[12px] text-mu">Selection backtest (statistical, rolling one-step, last {f.backtest.window_days} d): MAPE {f.backtest.mape.toFixed(1)}% · RMSE {fx(f.backtest.rmse, 1)} · interval coverage {f.backtest.interval_coverage.toFixed(0)}% · variability (CV) {f.backtest.coefficient_of_variation.toFixed(1)}%.</p>
        </Card>
      </div>
      <Card title="FORECAST CONFIDENCE" className="mt-3">
        <div className="text-[18px] font-semibold" data-testid="confidence-value">
          <ConfidenceIndex value={f.confidence.value} label={f.confidence.label} level={f.confidence.level} />
        </div>
        <div className="text-mu text-[12px] mt-1">{f.horizon}-day horizon · {f.methodology.confidence_formula}</div>
        <p className="m-0 mt-1 text-[12px] text-mu" data-testid="confidence-note">{CONFIDENCE_NOTE}</p>
        <p className="m-0 mt-1 text-[12px] text-mu">{f.methodology.accuracy_caveat}</p>
      </Card>
    </div>
  )
}
