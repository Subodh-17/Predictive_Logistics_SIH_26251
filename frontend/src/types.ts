export type Status = 'NORMAL' | 'WARNING' | 'CRITICAL'
export interface Scenario { demand: number; weather: number; road: number; vehicles: number }
export const BASELINE: Scenario = { demand: 0, weather: 0, road: 0, vehicles: 1 }

export interface Health {
  status: 'ok' | 'degraded'; api: string; data_notice: string; simulated_iot: boolean
  database: { connected: boolean; postgis?: string; counts?: Record<string, number>; error?: string }
}
export interface Loc {
  id: string; name: string; kind: 'DEPOT' | 'FORWARD'; lat: number; lon: number; status: Status | null
  n_critical: number; n_warning: number; n_normal: number; min_days: number | null; min_supply: string | null
  short_units: number; demand_per_day: number; best_route: string | null; best_route_risk: number | null; available_capacity: number | null
}
export interface Terrain { type: string; difficulty: number; elevation_band: number; elevation_label: string; risk: number }
export interface Route {
  id: string; depot: string; destination: string; distance_km: number; geo_length_km: number | null; road_condition: number; road_label: string
  terrain: Terrain; nominal_speed_kmh: number; effective_speed_kmh: number; eta_h: number; delay_h: number; weather_risk: number; weather_level: string
  risk: number; risk_level: string; vehicle_capacity: number; feasible: boolean; coordinates: [number, number][]
  combined_score?: number; decision?: string
}
export interface InvItem {
  location: string; supply: string; stock: number; safety_stock: number; daily_use: number; days_left: number; shortage_14d: number
  status: Status; lead_days: number; stockout_date: string; replenish_qty: number; below_safety: boolean
}
export interface Insight {
  location: string; supply: string; days_cover: number; status: Status; headline: string; predicted_demand_14d: number; stock: number
  safety_stock: number; stockout_date: string; lead_days: number; replenish_qty: number; source: string | null; vehicle: string | null
  route: string | null; reason: string
}
export interface Why {
  location: string; status: Status; weather_index: number; best_route: string; best_route_risk_level: string; best_route_risk: number; summary: string
  items: { supply: string; demand_change_pct: number; stock: number; days_cover: number; safety: number; below_safety: boolean; lead_days: number }[]
}
export interface Vehicle { id: string; depot_id: string; vehicle_type: string; capacity: number; effective_capacity: number; available: boolean }
export interface Priority {
  rank: number; location: string; supply: string; status: Status; score: number; components: Record<string, number>
  days_cover: number; stockout_date: string; replenish_qty: number; best_route: string | null; route_feasible: boolean
}
export interface AllocRow {
  rank: number; location: string; supply: string; score: number; safety_deficit: number; lead_days: number; need: number; allocated: number
  unmet: number; status: string; unmet_reason: string; legs: { vehicle: string; route: string; depot: string; quantity: number }[]
}
export interface Allocation {
  label: string; total_need: number; fleet_capacity: number; allocated: number; unmet: number; capacity_left: number; pooled_fleet_deficit: number
  unmet_by_reason: Record<string, number>; rows: AllocRow[]; notes: string[]
  depot_stock_used: { depot: string; supply: string; start: number; remaining: number; used: number }[]
}
export interface Dashboard {
  kpis: Record<string, number | string>; scenario_active: boolean; scenario: Record<string, number>
  forecast_chart: { date: string; actual: number | null; forecast: number | null }[]
  system_status: { engine: string; ok: boolean; detail: string }[]
  data_coverage: Record<string, number>; pipeline: { stage: string; detail: string }[]
}
export interface Container { container_id: string; source: string; destination: string; supply: string; quantity: number; status: string; last_update_sim: string; route: string; vehicle: string }
export interface IotEvent {
  id: number; event_time: string; device_id: string; tag_id: string; event_type: string; location_id: string; supply_id: string
  quantity: number; stock_before: number; stock_after: number; simulated: boolean; clipped_at_zero: boolean
}
export interface SimResult {
  params: Record<string, number>; run_id: number; before: Record<string, number>; after: Record<string, number>
  locations: { id: string; before: Status; after: Status; days_before: number; days_after: number }[]
  routes: { id: string; eta_before: number; eta_after: number; risk_before: number; risk_after: number }[]
  explanation: string[]
}
