import { fx } from '../format'
import { Card, Tag } from './ui'

export interface ModelsStatus {
  mode: string
  active_forecast_model: { model_id: string; family: string; fallback_reason: string | null; adapter: string }
  demand_forecast: { loaded: boolean; error: string | null; promotion: { status: string; reason: string | null; best_variant?: string } | null; artefact: { model_id: string; created_utc: string; training_dataset: string; licence: string } | null }
  shortage_risk: { loaded: boolean; error: string | null; artefact: { model_id: string } | null; note: string }
}
export interface ScenarioEval {
  overall: Record<string, { wape: number; mae: number; rmse: number }>
  by_horizon_bucket: Record<string, Record<string, { wape: number }>>
  promotion: { status: string; reason: string | null; best_variant: string }
}

const LABEL: Record<string, string> = { 'statistical_ewma (existing)': 'Statistical baseline (EWMA)', ml_weather_adapter: 'Trained model + weather adapter', ml_plain: 'Trained model (plain)',
  naive_last: 'Last value', seasonal_naive_7: 'Seasonal naive (7 d)', trailing_mean_28: 'Trailing 28-day mean' }

/** Which model drives the application, which model is only evaluated, and how the rule-based engine fits in. */
export default function ModelRoles({ m, sc }: { m: ModelsStatus | null; sc: ScenarioEval | null }) {
  const a = m?.active_forecast_model
  const ml = a?.family === 'machine_learning'
  const h14 = sc?.by_horizon_bucket?.h01_14
  return (
    <div className="mb-3" data-testid="model-roles">
      <div role="note" className="border border-act bg-ins p-3 mb-3 text-[13px]">
        <b className="text-act font-mono tracking-wide text-[11px]">WHAT IS AND IS NOT MACHINE LEARNING HERE</b>
        <div className="mt-1">Demand forecasts come from the <b>{ml ? 'trained gradient-boosted model' : 'statistical baseline'}</b>. Shortage dates, priorities, routes and dispatch advice are produced by a
          <b> deterministic rule-based engine</b> that consumes those forecasts — it is not machine learning, not an LLM and not generative AI.
          Every forecast row records which model produced it.</div>
      </div>
      <div className="grid gap-3 lg:grid-cols-3">
        <Card title="1 · ACTIVE FORECAST MODEL">
          <div className="mb-2"><Tag tone="ok">DRIVES THE APPLICATION</Tag> <Tag>{ml ? 'TRAINED ML' : 'NOT ML-TRAINED'}</Tag></div>
          <p className="m-0 mb-2 font-mono text-[12px]" data-testid="active-model-id">{a?.model_id ?? 'unavailable'}</p>
          <p className="m-0 text-[12px] text-mu">Configured mode: {m?.mode ?? '—'}. {a?.fallback_reason ?? 'Selected by the configured mode and the recorded promotion decision.'}</p>
        </Card>
        <Card title="2 · TRAINED MODEL (LIGHTGBM, DIRECT MULTI-HORIZON)">
          {m?.demand_forecast.loaded ? (<>
            <div className="mb-2"><Tag tone={m.demand_forecast.promotion?.status === 'promoted' ? 'ok' : 'wr'}>{m.demand_forecast.promotion?.status === 'promoted' ? 'PROMOTED' : 'NOT PROMOTED'}</Tag> <Tag>OPT-IN</Tag></div>
            <p className="m-0 mb-1 text-[12px]">Artefact {m.demand_forecast.artefact?.model_id}, trained on {m.demand_forecast.artefact?.training_dataset} ({m.demand_forecast.artefact?.licence}).</p>
            <p className="m-0 text-[12px] text-mu">{m.demand_forecast.promotion?.reason ?? 'Passed the pre-registered promotion rule.'}</p>
          </>) : <p className="m-0 text-mu" role="status">Trained model unavailable{m?.demand_forecast.error ? `: ${m.demand_forecast.error}` : '.'} The statistical baseline is in use and is labelled as such.</p>}
        </Card>
        <Card title="3 · HOLDOUT ON THIS SCENARIO (WAPE, DAYS 1–14)">
          {h14 ? (<div data-testid="model-metrics">
            {Object.entries(h14).filter(([k]) => ['statistical_ewma (existing)', 'ml_weather_adapter', 'ml_plain', 'seasonal_naive_7'].includes(k)).map(([k, v]) =>
              <div key={k} className="flex justify-between gap-3 border-b border-rowln py-1"><span>{LABEL[k] ?? k}</span><b className="tabular-nums">{(v.wape * 100).toFixed(2)}%</b></div>)}
            <p className="m-0 mt-2 text-[12px] text-mu">WAPE = Σ|actual − forecast| / Σ actual, rolling origins over this scenario's own history. The scenario is generated from the statistical model's structure, which favours it; see Model Evaluation.</p>
          </div>) : <p className="m-0 text-mu">Holdout report unavailable. Run <code>ml/evaluate_app_series.py</code>.</p>}
          {sc && <p className="m-0 mt-1 text-[11px] text-mu">Series evaluated: {fx(50)} · origins every 3 days · horizons 1–30.</p>}
        </Card>
      </div>
    </div>
  )
}
