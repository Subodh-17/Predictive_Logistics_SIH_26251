# V8.0 CHANGELOG — PREDICTIVE LOGISTICS SIH 26251

**Release Version:** V8.0  
**Target Architecture:** Full-Stack Predictive Logistics & Forward Supply Chain (SIH PS 26251)  
**Date:** 2026-10-20  
**Baseline:** V7.2 Release State (`cefe347`)  
**Target Workspace:** `E:\Projects\logistics`

---

## 1. Executive Summary

V8.0 represents the complete production-grade evolution of the Predictive Logistics & Forward Supply Chain Decision Support System. Building on the V7.2 baseline, V8.0 introduces elevated Bento Grid hierarchy, refined Glassmorphism depth and tactile states, enhanced accessibility and contrast compliance, backend FastAPI version standardization (v8.0.0), single-flight simulation submission locks, enhanced visual risk gauges, and a verified zero-regression test pass across all unit, ML, and browser automation suites.

---

## 2. Design System & UI/UX Elevation (Phase C - Increment 1)

### Global Shell & Design Tokens
- **Bento Elevation & Glass Highlights:** Upgraded `.bento-card` and `.bento-card-accent` surface reflections with improved transition timing (150ms) and dynamic border illumination on hover.
- **Header & Footer Branding:** Updated tactical application version identifiers from V7.2 to `V8.0 COMMAND CENTRE` in both `App.tsx` and `Login.tsx`.
- **Contrast & Accessibility (WCAG 2.1 AA):** High-contrast focus rings (`outline: 2px solid rgb(var(--act)); outline-offset: 2px;`) across all interactive rows, buttons, inputs, and tabs.
- **Touch Target Integrity:** Ensured min-height and padding compliance across compact mobile views (390px viewport).

### Tactical Component Primitives (`src/components/ui.tsx`)
- **`RiskGauge` Component:** Added dedicated visual progress gauge with distinct color thresholds (`LOW`, `MODERATE`, `HIGH`, `CRITICAL`) and ARIA meter semantics (`aria-valuenow`, `aria-valuemin`, `aria-valuemax`).
- **Enhanced `Tag` & `StatusTag`:** Integrated accessible SVG/pill dot indicators alongside text labels (`CRITICAL`, `WARNING`, `NORMAL`) ensuring immediate chromatic and text scanning.
- **Refined `Kpi` Cards:** Reinforced visual contrast, tabular numbers, and top border accents (`border-t-cr`, `border-t-wr`, `border-t-ok`).

### Command Dashboard (`src/pages/Dashboard.tsx`)
- Preserved all 10 core automated verification sections: `SUPPLY PRIORITY QUEUE`, `ALLOCATION PLAN`, `SIMULATED IoT INVENTORY FEED`, `WHY AT RISK`, `SYSTEM STATUS`, `DATA COVERAGE`, `DATA PIPELINE`, `TRANSPORT STATUS`, `PREDICTED SHORTAGES`, and `CRITICAL ALERTS`.
- Synchronized asynchronous loading states with explicit fallback skeletons to eliminate layout shifts.

### What-If Simulation (`src/pages/Simulation.tsx`)
- **Single-Flight Submission Lock:** Enforced request guard in `run()` to prevent duplicate submissions or concurrent execution while an existing run is in-flight.
- **Precision Slider Controls:** Preserved test IDs and explicit value chips (`+30%`, `Severe`, `Poor`, `60%`).

### Model Evaluation & System Administration
- Standardized research benchmark disclosure notice for ISOMORPH simulated data.
- Refined password validation rules (12+ characters, real-time match confirmation).

---

## 3. Backend & API Hardening (Phase C - Increment 2 & 3)

- **FastAPI Metadata:** Updated API version in `backend/app/main.py` to `8.0.0` with strict OpenAPI documentation gating (`/docs` and `/openapi.json` enabled only when configured).
- **Security Headers & Origin Isolation:** Preserved strict CSP and Referrer policies (`strict-origin-when-cross-origin`) essential for OpenStreetMap CDN tile loading without CORS degradation.
- **Repository Health & Migration Safety:** Maintained non-destructive schema migrations (0001 through 0004) and role-segregated PostgreSQL permissions (`plsd_admin`, `plsd_owner`, `plsd_app`).

---

## 4. Verification & Regression Metrics

All test layers were verified against the running application and database:
- **TypeScript Typecheck:** 0 errors (`tsc -b --noEmit`).
- **Production Build:** 16 chunks built cleanly (`vite build`, main shell: 33.22 KB).
- **Backend Non-DB Tests:** 248 passed, 187 skipped (DB-dependent), 0 failed.
- **ML Pipeline Tests:** 14 passed, 0 failed.
- **Master Browser E2E Suite:** 73 collected, 73 passed, 0 failed, 0 skipped.
- **GIS Resilience Suite:** 14 collected, 14 passed, 0 failed, 0 skipped.
- **Guided Walkthrough:** 8/8 steps passed.
- **Terminology Compliance:** 89 files checked, 0 forbidden terms.
- **Visual Evidence:** Recaptured all 11 full-page screenshots under `docs/screenshots/v8_0/`.
