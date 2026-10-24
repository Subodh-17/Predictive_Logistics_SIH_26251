# V7.2 CHANGELOG — PREDICTIVE LOGISTICS SIH 26251

**Release Version:** V7.2  
**Target Architecture:** Full-Stack Predictive Logistics & Forward Supply Chain (SIH PS 26251)  
**Date:** 2026-10-20  
**Baseline:** V7.1 Final

---

## 1. Summary of Changes

V7.2 delivers a comprehensive visual redesign based on a **Bento Grid + restrained Glassmorphism** command-center aesthetic, performance chunking, test environment repair, and release verification.

---

## 2. Visual & UI/UX Redesign (All 8 Modules + Shell + Login)

### Global Application Shell
- **Bento Framework:** Dark navy/slate palette (`--bg: 10 16 15`, `--pn: 17 26 24`, `--ln: 36 51 47`) with elevated translucent surfaces (`.bento-card`, `.bento-card-accent`) and glass highlight edge reflections (`inset 0 1px 0 0 rgba(255, 255, 255, 0.06)`).
- **Navigation:** Added tactical SVG vector icons for all 8 modules (`Dashboard`, `Demand Forecast`, `GIS Logistics`, `Inventory`, `What-If Simulation`, `Model Evaluation`, `System & Account`, `User Administration`).
- **Tactical Status Bar:** Fixed top beacon bar with pulsing operational state, live database status, advancing simulation clock (60x time acceleration, date-only display to avoid live-time confusion), active forecasting model indicator, and critical alert badge.
- **Responsive Layout:** Optimized breakpoints across 1440px (wide desktop), 1280px (standard desktop), 1024px (tablet landscape), 768px (tablet portrait / mobile nav collapse), and 390px (mobile compact).
- **Theme System:** Preserved full WCAG AA contrast (≥ 4.5:1) in both Dark (command-centre default) and Light modes.

### Authentication & Login (`Login.tsx`)
- Elevated from a dense flat box to a centered tactical Bento card (`bento-card-accent`) with glowing gold beacon, security clearance pill (`OFFICIAL · DECISION SUPPORT ONLY`), responsive layout, and distinct accessible error notices.

### Command Dashboard (`Dashboard.tsx`, `CommandBriefing.tsx`, `DecisionFlow.tsx`, `WhyRecommendation.tsx`)
- **KPI Hierarchy:** Top border tone accents (`cr`, `wr`, `ok`) with tabular metrics and trend context.
- **Overall Risk Gauge:** 40px prominent risk score with boundary indicator (Low 0, Moderate 25, High 45, Severe 65+) and glowing white indicator needle.
- **Critical Alerts Widget:** Ranked list displaying top urgent shortages with days of cover, stockout date, and clear counter badge (`TOP 6 OF 8 CRITICAL ITEMS · RANKED BY COVER`) clarifying the relation to total alerts.
- **Decision Flow:** Redesigned 7-step horizontal pipeline ribbon (`01 DATA → 02 FORECAST → 03 RISK → 04 PRIORITY → 05 ALLOCATION → 06 ROUTE → 07 DECISION`).
- **Data Pipeline:** Sequential stage tiles with stage counters (`STAGE 01` through `STAGE 05`).

### Demand Forecast (`Forecast.tsx`)
- **Bento Toolbar:** Clean segmented controls for 7-Day, 14-Day, and 30-Day forecast outlooks.
- **Model Attribution Glass Card:** Explicit badge distinguishing `STATISTICAL BASELINE` from `TRAINED ML MODEL`, with clear fallback reason disclosure.
- **Interval Shading:** 80% confidence band on Recharts line plot with interactive `ConfidenceIndex` tooltip.

### GIS Logistics (`Gis.tsx`, `RouteSelection.tsx`)
- **Split-Panel Layout:** Interactive Leaflet container with glass border and integrated degraded-mode banner (graceful fallback if tile CDN is slow/unreachable).
- **Selected Corridor Banner:** Monospace corridor identifier, origin depot, destination, ETA, road condition, and terrain risk score.
- **Route Selection Explained:** Bento stat cards for distance, speed, vehicle capacity, road condition, weather risk, and terrain difficulty.

### Inventory (`Inventory.tsx`)
- **Filter Toolbar:** Bento card with location, supply type, and risk filters, plus live item count badge.
- **Stock Projection Chart:** 14-day projected stock vs dashed safety stock line with shortage onset date.
- **Risk Basis Disclosure:** Clean collapsible explanation of days of supply, 14-day shortage horizon, and status classification rules.
- **Telemetry Scanner:** Interactive ESP32/RFID scanner form with delta chips showing stock before/after.

### What-If Simulation (`Simulation.tsx`, `RecommendedResponse.tsx`)
- **Scenario Controls:** Sliders with live percentage readout chips for demand increase, weather severity, road condition, and fleet availability.
- **Before vs After Table:** Color-coded delta badges (`+` / `-`) highlighting impact on critical items, unmet demand, route risk, and ETA.
- **Recommended Response:** Structured advisory response categorized into `ACT NOW`, `PLAN`, and `OK`.

### Model Evaluation (`Models.tsx`)
- **Benchmark Notice:** Prominent disclosure callout explaining the ISOMORPH simulator-generated research benchmark.
- **Model Registry:** Clean KV card displaying active model, configured mode, and promotion status.
- **Shortage Onset Check:** Interactive single-record scoring form with calibrated probability output.

### System & Account (`System.tsx`)
- Service health status, database connection, schema version, startup state, and uptime.
- Data freshness timestamps.
- Operational counters card.
- Structured password change form with client-side length and match validation.

### User Administration (`Users.tsx`)
- User accounts table with role badges and active/deactivated indicators.
- Password reset form with cancellation.
- Add user form with strict input patterns.
- Security audit trail logging actor, action, target, outcome, and client IP.

---

## 3. Performance & Route-Level Code Splitting

- Implemented dynamic `React.lazy()` imports and `Suspense` inside `App.tsx`.
- Configured Rollup vendor chunking (`react`, `charts`, `map`).
- **Main application shell chunk reduced from 842 KB un-split down to 33.04 KB (11.50 KB gzip).**
- Heavy vendor libraries (`recharts` 558 KB, `leaflet` 155 KB) and module pages (5–23 KB) load strictly on demand.

---

## 4. Defect Repairs

1. **C-01 (Windows Path Separator Bug):** Fixed in `backend/tests/test_terminology.py` using `.as_posix()`.
2. **H-01 (Monolithic Bundle):** Resolved via `manualChunks` and `React.lazy` code splitting.
3. **Deployment Configuration Tests:** Updated `test_deployment_config.py` to isolate `.env` staging and implement platform-aware permission checks (POSIX bits vs NTFS file attributes).
4. **LightGBM CRLF Line Ending Crash:** Fixed in `backend/tests/test_ml_v6.py` using binary `.write_bytes()` to prevent Windows `\r\n` corruption of LightGBM model files.
5. **Windows Symlink Privilege Handling:** Handled `WinError 1314` in `test_ml_v6.py` to cleanly skip when `SeCreateSymbolicLinkPrivilege` is absent.
6. **Auth Test Database Teardown:** Added missing `prepared_db` fixture parameter to `test_auth_api.py:test_bootstrap_admin_is_created_only_when_no_users_exist`.
7. **Button ClassName Support:** Added `className` prop support to `Btn` component in `frontend/src/components/ui.tsx`.

---

## 5. Verification Summary

- **Frontend Typecheck:** `tsc -b --noEmit` -> 0 errors.
- **Frontend Production Build:** Vite v7.3.7 -> clean build.
- **Backend Unit Tests:** `pytest tests/` -> 248 passed, 187 skipped, 0 failed.
- **End-to-End Walkthrough:** `scripts/guided_walkthrough.py` -> 100% passed against live stack.
- **Live Stack:** `http://localhost:8080/api/health` -> HTTP 200, status `ok`.
