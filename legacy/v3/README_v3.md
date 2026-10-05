# Predictive Logistics & Forward Supply Chain: Decision-Support Prototype (v3)

**SIH Problem Statement ID:** 26251
**Title:** Indian Army - Predictive Logistics & Forward Supply Chain

## What the system demonstrates
A predictive logistics decision-support dashboard that turns synthetic consumption history, inventory, weather, road and vehicle data into demand forecasts, shortage predictions, supply prioritisation and route-risk-aware replenishment recommendations. A what-if simulator shows how demand, weather, road condition and fleet availability change the risk picture.

## Features
- **Command Dashboard:** 7 KPIs (locations, critical shortages, warning locations, vehicles, transport capacity, supplies at risk, overall risk), GIS overview, critical alerts, predicted shortages, demand forecast, transport status and the AI Logistics Insight panel.
- **Demand Forecast:** filter by location and supply type; 7/14/30-day horizons; actual vs predicted consumption with an 80% interval band and backtest MAPE.
- **GIS Logistics:** 3 fictional depots, 5 fictional forward locations, 8 routes; green/yellow/red markers; click a location for inventory status, days remaining, predicted shortage, demand and risk; click a route for distance, ETA, road condition, weather risk, vehicle capacity and route risk.
- **Inventory:** stock, safety stock, daily use, days remaining, predicted shortage and risk status; filters for location, supply type and risk level; 14-day stock projection.
- **What-If Simulation:** demand +0-50%, weather Normal to Severe, road Good to Poor, vehicle availability 100% to 50%; RUN SIMULATION gives before vs after and an explanation of why risk changed; "Apply to all screens" propagates the scenario.
- **Recommendation engine:** deterministic, rule-based (predicted demand, stock, safety stock, lead time, vehicle availability, weather and route risk). No external AI model is used.
- **Data:** 3 depots, 5 forward locations, 10 supply types, 8 routes, 8 vehicles, 5,500 historical consumption records, generated deterministically (fixed seed) at page load.

## Credibility and explainability features (v2)
- **Forecast methodology panel** (Demand Forecast): method in use (statistical, **not** a trained ML model), input signals, weather signal, seasonality, horizon, backtest MAPE, interval calibration and demand variability.
- **Forecast confidence:** deterministic, derived from measured backtest error: 100 − MAPE × (1 + horizon/30). The horizon factor is a stated heuristic. Because the synthetic history shares the model's structure, low error validates the pipeline and does not indicate real-world accuracy.
- **Explainable risk ("Why at risk"):** for every warning/critical location: forecast demand change vs last 7 days, stock, days of cover, safety stock, lead time, weather index and route risk.
- **Supply priority queue:** Decision-Support Priority Score (0-100) = 100 x (0.45 urgency + 0.20 shortfall share + 0.20 supply-criticality weight + 0.15 best-route risk). Deterministic; criticality weights are fixed prototype assumptions.
- **Route optimization comparison:** feasible routes to the selected destination with distance, ETA, vehicle capacity, road, weather risk, route risk and combined score (risk + ETA/24 h), with the reason the selected route won.
- **Data pipeline, system status, data coverage panels** on the dashboard (status is computed from real validation checks).
- **Decision-support disclaimer** pinned at the bottom of every screen.

## Terrain, allocation, IoT and ML additions (v3)
- **Terrain / altitude model (fictional):** every route has a terrain type, terrain difficulty (0-1), elevation category (fictional bands) and terrain risk score (0.7 x difficulty + 0.3 x elevation index / 3). Terrain lowers effective speed (and so raises ETA), raises route risk, and therefore affects route comparison and route selection. Shown in GIS route details, the routes table, route comparison and the recommendation reason.
- **Route risk formula:** 0.25 x road condition + 0.25 x weather (amplified by terrain) + 0.30 x terrain + 0.20 x distance factor. Effective speed = nominal speed x (1 - 0.45 x road) x (1 - 0.35 x terrain) x (1 - 0.3 x weather).
- **Allocation plan ("Decision-Support Allocation - Synthetic Scenario"):** ranks at-risk items by the Decision-Support Priority Score, sizes need from safety-stock deficit + demand over lead time + 5-day buffer, keeps to feasible routes (depot has an available vehicle), and loads vehicles strictly within effective capacity. Depot stock is assumed sufficient, so transport capacity is the binding constraint. Unmet quantity is reported, never hidden. The simulation screen also shows unmet-after-allocation before vs after.
- **Simulated IoT inventory feed:** container ID, source, destination, quantity, status and simulated last update, generated from the allocation plan and the simulation clock. No hardware or live telemetry.
- **Simulated GIS Logistics View:** map section renamed and labelled; all locations, routes and terrain are fictional.
- **ML credibility:** the production forecast is a statistical predictive-analytics model (not trained ML). A lightweight Random Forest regression (20 trees, depth 6, seeded, trained in the browser on the synthetic history; trained on days 1-90, validated on the last 20 days) is shown as a challenger cross-check on the Demand Forecast screen with its input features and hold-out MAPE next to the statistical model's MAPE on the same samples. It does not drive dashboard numbers. In the current build the statistical model scores better on the hold-out (about 3.7% vs 4.8% MAPE); results come from synthetic data and say nothing about real-world accuracy. It trains on first opening Demand Forecast (about 1 second).

## How to run the website
No installation, backend or internet-hosted services are required.
1. Unzip the archive.
2. Open `Predictive_Logistics_SIH_26251/index.html` in a modern browser (Chrome, Edge or Firefox) by double-clicking it.

Optional local server (any one):
```
cd Predictive_Logistics_SIH_26251
python -m http.server 8000
```
then open http://localhost:8000

## Suggested demo flow
1. **Command Dashboard:** show the KPIs, red/yellow/green map and the AI Logistics Insight (Base_04 Medical, about 2.8 days to stock-out, with recommended quantity, source depot, vehicle and route).
2. **Demand Forecast:** pick a location and supply type, switch 7/14/30-day horizons, point out the weather-driven rise.
3. **GIS Logistics:** click Base_04, then route R03; show distance, ETA, road, weather and route risk.
4. **Inventory:** filter by CRITICAL; select a row to see the stock projection against safety stock.
5. **Dashboard (again):** scroll to the priority queue, "Why at risk", system status, data coverage and pipeline panels; use "View route comparison" on the insight.
6. **Demand Forecast:** open the methodology panel and explain the confidence formula and the accuracy caveat.
7. **Dashboard allocation and IoT panels:** show the allocation plan (capacity-respecting) and the simulated IoT feed. **GIS:** select R03 and R08 and compare terrain, ETA and risk.
8. **What-If Simulation:** set demand +30%, weather Severe, road Poor, vehicles 60%; press RUN SIMULATION; read before vs after and the "why" list; press APPLY TO ALL SCREENS and revisit the dashboard; press RESET.

## Synthetic-data disclaimer
All data is fictional and generated by code. Locations (Depot_A to C, Base_01 to 05), coordinates, routes, vehicles, quantities and consumption figures do not represent any real military location, formation, deployment, route or logistics information.

## Known limitations
- Terrain values, elevation bands, criticality weights and allocation rules are fictional prototype assumptions; the IoT feed is simulated.
- Single-file HTML app (vanilla JavaScript and inline SVG); not a React/Vite/TypeScript + FastAPI project, and there is no REST API or database.
- The map is an SVG schematic on a fictional grid, not Leaflet/OpenStreetMap tiles.
- Forecast confidence uses a documented heuristic (one-step-ahead backtest; multi-day error is not separately measured), and priority weights are assumptions, not calibrated values.
- Forecasting is a simple statistical model (weather-adjusted EWMA with damped trend and weekly seasonality), not a trained ML model.
- Dark theme only; layout is responsive but was not tested across real devices.
- State is in memory only and resets on page reload.
