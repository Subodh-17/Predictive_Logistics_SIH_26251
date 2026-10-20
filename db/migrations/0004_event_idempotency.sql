-- 0004 optional client-supplied idempotency key for inventory events: a retried or duplicated request with the same key is rejected
-- instead of being applied twice. NULL (no key) keeps the V6 behaviour. Partial unique index: only keyed events are constrained.
ALTER TABLE iot_events ADD COLUMN IF NOT EXISTS event_id text;
CREATE UNIQUE INDEX IF NOT EXISTS iot_events_event_id_uq ON iot_events (event_id) WHERE event_id IS NOT NULL;
