-- Predictive Logistics & Forward Supply Chain (SIH PS 26251) - PostgreSQL + PostGIS schema
-- Prototype uses fictional synthetic logistics data and is intended for decision-support demonstration only.
CREATE EXTENSION IF NOT EXISTS postgis;

DROP TABLE IF EXISTS simulation_runs, iot_events, allocations, priority_scores, alerts, forecasts, consumption,
    inventory, weather, terrain, routes, vehicles, depots, locations, supplies CASCADE;

CREATE TABLE supplies (
    id                   text PRIMARY KEY,
    base_daily_demand    numeric(10,2) NOT NULL CHECK (base_daily_demand > 0),
    weather_sensitivity  numeric(4,2)  NOT NULL CHECK (weather_sensitivity BETWEEN 0 AND 1),
    criticality_weight   numeric(4,2)  NOT NULL CHECK (criticality_weight BETWEEN 0 AND 1),
    unit                 text NOT NULL DEFAULT 'units',
    sort_order           smallint NOT NULL DEFAULT 0
);

-- every node of the fictional network: depots and forward locations
CREATE TABLE locations (
    id             text PRIMARY KEY,
    name           text NOT NULL,
    kind           text NOT NULL CHECK (kind IN ('DEPOT', 'FORWARD')),
    geom           geometry(Point, 4326) NOT NULL,
    demand_factor  numeric(5,2) NOT NULL DEFAULT 1,
    sort_order     smallint NOT NULL DEFAULT 0
);
CREATE INDEX locations_geom_gix ON locations USING GIST (geom);

CREATE TABLE depots (
    location_id             text PRIMARY KEY REFERENCES locations(id) ON DELETE CASCADE,
    depot_class             text NOT NULL,
    storage_capacity_units  integer NOT NULL CHECK (storage_capacity_units > 0)
);

CREATE TABLE vehicles (
    id              text PRIMARY KEY,
    depot_id        text NOT NULL REFERENCES depots(location_id),
    vehicle_type    text NOT NULL,
    capacity_units  integer NOT NULL CHECK (capacity_units > 0),
    available       boolean NOT NULL DEFAULT true
);

CREATE TABLE routes (
    id                text PRIMARY KEY,
    depot_id          text NOT NULL REFERENCES depots(location_id),
    destination_id    text NOT NULL REFERENCES locations(id),
    distance_km       numeric(7,1) NOT NULL CHECK (distance_km > 0),
    road_condition    numeric(4,2) NOT NULL CHECK (road_condition BETWEEN 0 AND 1),  -- 0 good .. 1 poor
    nominal_speed_kmh numeric(5,1) NOT NULL CHECK (nominal_speed_kmh > 0),
    geom              geometry(LineString, 4326) NOT NULL
);
CREATE INDEX routes_geom_gix ON routes USING GIST (geom);

CREATE TABLE terrain (
    route_id         text PRIMARY KEY REFERENCES routes(id) ON DELETE CASCADE,
    terrain_type     text NOT NULL,
    difficulty       numeric(4,2) NOT NULL CHECK (difficulty BETWEEN 0 AND 1),
    elevation_band   smallint NOT NULL CHECK (elevation_band BETWEEN 0 AND 3),   -- fictional bands
    elevation_label  text NOT NULL,
    terrain_risk     numeric(5,4) GENERATED ALWAYS AS (0.7 * difficulty + 0.3 * elevation_band / 3.0) STORED
);

-- daily synthetic weather severity index (0..1); day_index >= 110 is the outlook
CREATE TABLE weather (
    day_index       integer PRIMARY KEY,
    obs_date        date NOT NULL,
    severity_index  double precision NOT NULL CHECK (severity_index BETWEEN 0 AND 1),
    kind            text NOT NULL CHECK (kind IN ('OBSERVED', 'OUTLOOK'))
);

CREATE TABLE consumption (
    id                bigserial PRIMARY KEY,
    location_id       text NOT NULL REFERENCES locations(id),
    supply_id         text NOT NULL REFERENCES supplies(id),
    day_index         integer NOT NULL REFERENCES weather(day_index),
    consumption_date  date NOT NULL,
    quantity          integer NOT NULL CHECK (quantity >= 0),
    UNIQUE (location_id, supply_id, day_index)
);
CREATE INDEX consumption_series_ix ON consumption (location_id, supply_id, day_index);

-- stock at depots and forward locations; safety_stock is only meaningful at forward locations
CREATE TABLE inventory (
    location_id    text NOT NULL REFERENCES locations(id),
    supply_id      text NOT NULL REFERENCES supplies(id),
    stock          numeric(12,1) NOT NULL CHECK (stock >= 0),
    safety_stock   numeric(12,1) NOT NULL DEFAULT 0 CHECK (safety_stock >= 0),
    initial_stock  numeric(12,1) NOT NULL,
    updated_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (location_id, supply_id)
);

-- model output: kind FIT = one-step-ahead fit on history, FORECAST = 30-day outlook (computed by the backend)
CREATE TABLE forecasts (
    id             bigserial PRIMARY KEY,
    location_id    text NOT NULL REFERENCES locations(id),
    supply_id      text NOT NULL REFERENCES supplies(id),
    day_index      integer NOT NULL,
    forecast_date  date NOT NULL,
    kind           text NOT NULL CHECK (kind IN ('FIT', 'FORECAST')),
    value          double precision NOT NULL,
    model          text NOT NULL DEFAULT 'ewma-weather-seasonal-v1',
    UNIQUE (location_id, supply_id, day_index, kind)
);

CREATE TABLE alerts (
    id           bigserial PRIMARY KEY,
    created_at   timestamptz NOT NULL DEFAULT now(),
    scenario_key text NOT NULL DEFAULT 'baseline',
    location_id  text NOT NULL REFERENCES locations(id),
    supply_id    text NOT NULL REFERENCES supplies(id),
    severity     text NOT NULL CHECK (severity IN ('CRITICAL', 'WARNING')),
    days_cover   double precision NOT NULL,
    stockout_date date,
    lead_days    double precision NOT NULL,
    message      text NOT NULL
);

CREATE TABLE priority_scores (
    id           bigserial PRIMARY KEY,
    created_at   timestamptz NOT NULL DEFAULT now(),
    scenario_key text NOT NULL DEFAULT 'baseline',
    rank         integer NOT NULL,
    location_id  text NOT NULL REFERENCES locations(id),
    supply_id    text NOT NULL REFERENCES supplies(id),
    score        integer NOT NULL CHECK (score BETWEEN 0 AND 100),
    components   jsonb NOT NULL
);

CREATE TABLE allocations (
    id           bigserial PRIMARY KEY,
    created_at   timestamptz NOT NULL DEFAULT now(),
    scenario_key text NOT NULL DEFAULT 'baseline',
    location_id  text NOT NULL REFERENCES locations(id),
    supply_id    text NOT NULL REFERENCES supplies(id),
    route_id     text REFERENCES routes(id),
    vehicle_id   text REFERENCES vehicles(id),
    need         integer NOT NULL,
    quantity     integer NOT NULL,
    unmet        integer NOT NULL,
    status       text NOT NULL,
    unmet_reason text
);

-- simulated ESP32 / RFID events (always simulated; no hardware connected)
CREATE TABLE iot_events (
    id            bigserial PRIMARY KEY,
    event_time    timestamptz NOT NULL DEFAULT now(),
    device_id     text NOT NULL,
    tag_id        text NOT NULL,
    event_type    text NOT NULL CHECK (event_type IN ('RECEIVE', 'ISSUE', 'COUNT')),
    location_id   text NOT NULL REFERENCES locations(id),
    supply_id     text NOT NULL REFERENCES supplies(id),
    quantity      numeric(12,1) NOT NULL CHECK (quantity >= 0),
    stock_before  numeric(12,1) NOT NULL,
    stock_after   numeric(12,1) NOT NULL,
    simulated     boolean NOT NULL DEFAULT true CHECK (simulated),
    payload       jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX iot_events_time_ix ON iot_events (event_time DESC);

CREATE TABLE simulation_runs (
    id           bigserial PRIMARY KEY,
    created_at   timestamptz NOT NULL DEFAULT now(),
    params       jsonb NOT NULL,
    before       jsonb NOT NULL,
    after        jsonb NOT NULL,
    explanation  jsonb NOT NULL
);

CREATE VIEW v_consumption_enriched AS
SELECT c.consumption_date, c.day_index, c.location_id, c.supply_id, c.quantity,
       w.severity_index AS weather_index, s.weather_sensitivity, l.demand_factor
FROM consumption c
JOIN weather w   ON w.day_index = c.day_index
JOIN supplies s  ON s.id = c.supply_id
JOIN locations l ON l.id = c.location_id;
