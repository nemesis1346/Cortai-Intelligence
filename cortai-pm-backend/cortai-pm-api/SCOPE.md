# COrtai Property Intelligence Platform
## Backend Scope of Work — Developer Handoff

**Prepared by:** Ravi · Lionston Group / COrtai Inc.
**Date:** April 2026
**Recipient:** Backend Developer

---

## What Was Built (Already Done — In This Package)

The framework is complete. A senior developer does NOT need to design
anything from scratch. Every architectural decision has been made:

| Artifact | Status | Location |
|---|---|---|
| Database schema (28 tables, all indexes) | ✅ Complete | `api/schema.py` |
| Buildium API client (OAuth, all endpoints, rate limiting, retry) | ✅ Complete | `buildium/client.py` |
| Sync engine (pull + push + conflict resolution) | ✅ Complete | `buildium/sync_engine.py` |
| FastAPI application (45+ endpoints) | ✅ Complete | `api/main.py` |
| Docker + PostgreSQL compose | ✅ Complete | `docker-compose.yml` |
| Environment template | ✅ Complete | `.env.example` |

**The developer's job is to:** wire it up, test it, fix edge cases, and add
the items listed under Sprint 1–3 below.

**Estimated profile:** Mid-to-senior Python developer comfortable with
FastAPI, PostgreSQL, and REST API integration.

---

## The Architecture in 30 Seconds

```
Buildium API (source of truth for base data)
      │
      │ pull every 4 hours · push on event
      ▼
PostgreSQL Database (28 tables)
  ├── 12 Buildium-synced tables  (properties, units, tenants, leases, payments...)
  └── 16 COrtai-native tables    (building systems, history, appliances,
                                   tenant profiles, inspections, AI alerts...)
      │
      ▼
FastAPI REST API (45+ endpoints)
      │
      ▼
COrtai Frontend (cortai-pm.html)
```

**Key rule:** Buildium owns base data. COrtai owns extended intelligence.
The sync engine merges them without overwriting either side.

---

## Stack

| Component | Choice | Why |
|---|---|---|
| Language | Python 3.12 | Team familiarity |
| API Framework | FastAPI | Auto-docs, async, Pydantic validation |
| Database | PostgreSQL 16 | Production-grade, JSONB for flexible fields |
| DB Driver | asyncpg | Native async, highest throughput for FastAPI |
| HTTP Client | httpx | Async, Buildium API calls |
| Container | Docker + Compose | Simple deployment |
| Auth (to add) | python-jose + passlib | JWT tokens |

---

## Task Breakdown & Time Estimates

### Sprint 0 — Environment Setup (1–2 days · ~10 hours)

| # | Task | Hours | Notes |
|---|---|---|---|
| 0.1 | Clone repo, read codebase, understand sync flow | 2h | Required before touching anything |
| 0.2 | Spin up PostgreSQL via Docker | 1h | `docker compose up db` |
| 0.3 | Apply schema, verify all 28 tables created | 1h | Run `uvicorn api.main:app` — schema auto-applies |
| 0.4 | Get Buildium developer account + client credentials | 2h | Ravi to provide or request from Buildium portal |
| 0.5 | Set `.env` variables, run first sync | 2h | Should pull all properties/units/tenants |
| 0.6 | Verify Swagger UI at `/docs` — test 5 endpoints manually | 2h | Confirms DB, sync, API all working |

**Sprint 0 done-criteria:** `/api/health` returns real property/unit/tenant counts from Buildium.

---

### Sprint 1 — Core Stability (1 week · ~35 hours)

| # | Task | Hours | Notes |
|---|---|---|---|
| 1.1 | Fix any asyncpg query issues (parameter count mismatches, type errors) | 4h | The schema is correct; the queries may need tuning for your exact Buildium data |
| 1.2 | Test all 45 endpoints with real data — fix any 500s | 6h | Use Swagger UI + write a quick test script |
| 1.3 | Implement JWT authentication middleware | 6h | `python-jose` · Staff login → token → protected routes |
| 1.4 | Add `/api/auth/login` and `/api/auth/me` endpoints | 3h | Simple username/password against a `staff` table |
| 1.5 | Add `staff` table + seed initial users | 2h | Ravi, Emma R., Marcus L. as initial PMs |
| 1.6 | Wire Buildium incremental sync (delta by last-modified) | 4h | Already coded in `sync_engine.py` — test and tune |
| 1.7 | Handle Buildium pagination edge cases (last page, empty results) | 2h | Already in `_get_all()` — test with real data |
| 1.8 | Add error handling for Buildium auth token expiry during long sync | 2h | `_ensure_token()` already coded — verify it works |
| 1.9 | Add `/api/units` list endpoint (currently only detail) | 2h | Copy pattern from `list_properties` |
| 1.10 | HTTPS setup — Certbot + nginx | 4h | Ubuntu server: `sudo certbot --nginx -d api.yourdomain.com` |

**Sprint 1 done-criteria:** All endpoints return real data. JWT auth works. HTTPS live.

---

### Sprint 2 — Data Entry & Extended Fields (1 week · ~35 hours)

This sprint is about populating the COrtai-native tables — the 16 tables
Buildium knows nothing about. This is where Lionston Group's institutional
knowledge gets recorded.

| # | Task | Hours | Notes |
|---|---|---|---|
| 2.1 | Build data entry scripts for building systems | 4h | Script to bulk-insert `building_systems` from a spreadsheet (CSV → DB) |
| 2.2 | Build data entry for building history events | 3h | Same pattern — CSV import for `building_events` |
| 2.3 | Build unit detail import (floor, facing, parking, locker, appliances) | 4h | Import from Excel spreadsheet Ravi provides |
| 2.4 | Build tenant profile import (extended fields not in Buildium) | 4h | Income, credit score, employer, pets, vehicles, etc. |
| 2.5 | Build `POST /api/tenants/{id}/unit-history` endpoint | 2h | Record past tenants per unit — historical import |
| 2.6 | Implement risk scoring calculation | 4h | Score 0–100 based on: payment history, arrears, NSFs, communication flags |
| 2.7 | Build AI alert generation (rule-based, not ML) | 6h | Rules: HVAC age > 15yr → alert, arrears > 30d → alert, lease expiry < 30d → alert |
| 2.8 | Test `POST /api/work-orders` → Buildium push flow end-to-end | 4h | Create WO in COrtai → verify it appears in Buildium |
| 2.9 | Test Buildium → COrtai WO pull (Buildium-created requests) | 2h | Verify tenant portal WOs from Buildium sync into COrtai |
| 2.10 | Add vendor rating after WO close | 2h | `POST /api/work-orders/{id}/rate-vendor` endpoint |

**Sprint 2 done-criteria:** All 28 tables have real data. Risk scores calculated. AI alerts generating.

---

### Sprint 3 — Frontend Integration (1 week · ~30 hours)

Wire the `cortai-pm.html` frontend to hit this real API instead of static data.

| # | Task | Hours | Notes |
|---|---|---|---|
| 3.1 | Update `CORTAI_API_BASE` in frontend HTML to point at production URL | 0.5h | One variable change |
| 3.2 | Wire Portfolio Overview → `GET /api/dashboard` | 3h | Replace hardcoded PROPERTIES/TENANTS arrays |
| 3.3 | Wire Property Directory → `GET /api/properties` | 3h | Already matches API response shape |
| 3.4 | Wire Building Detail → `GET /api/properties/{id}` | 4h | Systems, history, units — all in one call |
| 3.5 | Wire Work Order Board → `GET /api/work-orders` | 3h | Filter bar maps to query params |
| 3.6 | Wire WO Create → `POST /api/work-orders` | 2h | Replaces toast stub |
| 3.7 | Wire Tenant Profile → `GET /api/tenants/{id}` | 3h | Payments, comms, docs — all nested |
| 3.8 | Wire Inspections → `GET /api/inspections` + detail | 2h | |
| 3.9 | Wire Financials → `GET /api/financials/rent-roll` + delinquency | 3h | |
| 3.10 | Wire Buildium status panel → `GET /api/sync/log` + `GET /api/sync/status` | 2h | |
| 3.11 | Wire AI alerts → `GET /api/ai-alerts` | 2h | |
| 3.12 | Add login screen to frontend (JWT flow) | 2h | Simple PM login before accessing dashboard |

**Sprint 3 done-criteria:** Frontend fully live. No static data remaining.

---

### Sprint 4 — Polish & Production Hardening (3–5 days · ~20 hours)

| # | Task | Hours | Notes |
|---|---|---|---|
| 4.1 | Add file upload for tenant documents (S3 or local) | 4h | `POST /api/tenants/{id}/documents` with actual file |
| 4.2 | Add inspection photo upload | 3h | Same pattern — link to `inspection_items.photo_urls` |
| 4.3 | Add N4/N5 PDF generation | 4h | Ontario standard forms — fill from tenant/lease data |
| 4.4 | Add email notifications (SendGrid or SMTP) | 4h | Trigger on: WO created, rent overdue, N4 issued |
| 4.5 | Add rate limiting to API (slowapi) | 2h | Prevent abuse |
| 4.6 | Database backups (pg_dump cron or managed backup) | 2h | Critical — daily backup minimum |
| 4.7 | Monitoring (Sentry or similar) | 1h | Error tracking |

---

## Summary Timeline

| Sprint | Duration | Hours | What Gets Delivered |
|---|---|---|---|
| Sprint 0 — Setup | Days 1–2 | 10h | DB live, Buildium connected, real data flowing |
| Sprint 1 — Stability | Week 1 | 35h | All endpoints working, auth, HTTPS |
| Sprint 2 — Data Entry | Week 2 | 35h | All 28 tables populated, risk scoring, AI alerts |
| Sprint 3 — Frontend | Week 3 | 30h | Frontend fully wired to real API |
| Sprint 4 — Polish | Days 1–3 of Week 4 | 20h | Documents, emails, N4 generation, monitoring |
| **TOTAL** | **~4 weeks** | **~130 hours** | **Fully operational platform** |

**At ~$100–130 CAD/hr for a mid-senior Python dev = $13,000–$17,000 total.**
**At Krzysztof's rate (Poland) = $7,000–$10,000 CAD equivalent.**

The biggest variable is Sprint 2 (data entry). If Lionston Group can provide
all building/unit/tenant extended data in spreadsheet form, the developer
can write import scripts instead of entering everything manually. That saves
5–10 hours.

---

## What the Developer Does NOT Need to Build

These are already done:

- ✅ All 28 database tables, columns, indexes, and foreign keys
- ✅ Buildium OAuth2 token flow with auto-refresh
- ✅ Rate limiting (90 req/min) + retry with exponential backoff
- ✅ Pagination for all Buildium list endpoints
- ✅ Full sync engine (pull all entities in dependency order)
- ✅ Push engine (work orders from COrtai → Buildium)
- ✅ Conflict resolution (Buildium wins on base fields, COrtai on extended)
- ✅ All 45+ REST API endpoints
- ✅ Docker + PostgreSQL compose
- ✅ Environment template
- ✅ Frontend HTML (243KB, 3,300+ lines, all screens)

---

## Files in This Package

```
cortai-pm-api/
│
├── api/
│   ├── main.py          ← FastAPI app + all 45 endpoints
│   └── schema.py        ← 28-table PostgreSQL schema + indexes + seed
│
├── buildium/
│   ├── client.py        ← Buildium API client (OAuth, all endpoints)
│   └── sync_engine.py   ← Sync orchestrator (pull + push + scheduler)
│
├── .env.example         ← Environment variables template
├── requirements.txt     ← 7 Python packages
├── Dockerfile           ← API container
├── docker-compose.yml   ← API + PostgreSQL
└── SCOPE.md             ← This file
```

Plus the frontend:
```
cortai-pm.html           ← Complete 243KB frontend (separate file)
```

---

## Getting Started (For the Developer)

```bash
# 1. Clone / copy this folder
cd cortai-pm-api

# 2. Set up environment
cp .env.example .env
# Edit .env — add your Buildium credentials

# 3. Start PostgreSQL
docker compose up db -d

# 4. Install Python deps (local dev)
pip install -r requirements.txt

# 5. Start API
uvicorn api.main:app --host 0.0.0.0 --port 3001 --reload

# 6. Verify
curl http://localhost:3001/api/health

# 7. Trigger first Buildium sync
curl -X POST http://localhost:3001/api/sync/trigger?full=true

# 8. Open Swagger UI
open http://localhost:3001/docs
```

**First sign that things are working:**
`/api/health` returns `properties: 54, units: 325, tenants: {your count}`.

---

## Buildium Developer Setup

1. Log into Buildium as an admin
2. Go to **Settings → API & Integrations → Developer Portal**
3. Create a new application — select **Client Credentials** grant type
4. Copy `Client ID` and `Client Secret` into `.env`
5. Required scope: `urn:buildium:apis:all`
6. Buildium sandbox available for testing: https://developer.buildium.com

---

## Key Contacts

**Ravi** — Lionston Group · COrtai Inc.
Product decisions, data questions, Buildium account access

**Krzysztof** — COrtai Backend Lead (Poland)
XDP/eBPF architect on StayGate — available for code review

**Emma R. / Marcus L.** — Property Managers
Subject matter experts for data entry priorities
