-- 0003 additional integrity constraints and indexes (all idempotent; verified against the seeded scenario by the test suite).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'routes_depot_not_destination') THEN
        ALTER TABLE routes ADD CONSTRAINT routes_depot_not_destination CHECK (depot_id <> destination_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'forecasts_value_nonneg') THEN
        ALTER TABLE forecasts ADD CONSTRAINT forecasts_value_nonneg CHECK (value >= 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'forecasts_interval_order') THEN
        ALTER TABLE forecasts ADD CONSTRAINT forecasts_interval_order CHECK (lo IS NULL OR hi IS NULL OR lo <= hi);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'allocations_amounts_nonneg') THEN
        ALTER TABLE allocations ADD CONSTRAINT allocations_amounts_nonneg CHECK (need >= 0 AND quantity >= 0 AND unmet >= 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'iot_events_stock_nonneg') THEN
        ALTER TABLE iot_events ADD CONSTRAINT iot_events_stock_nonneg CHECK (stock_before >= 0 AND stock_after >= 0);
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS forecasts_series_ix ON forecasts (kind, location_id, supply_id, day_index);
CREATE INDEX IF NOT EXISTS iot_events_item_ix ON iot_events (location_id, supply_id, event_time DESC);
CREATE INDEX IF NOT EXISTS alerts_scenario_ix ON alerts (scenario_key, days_cover);
