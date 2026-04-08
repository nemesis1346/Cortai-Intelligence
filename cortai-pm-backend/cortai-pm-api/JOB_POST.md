# Job Post: Python/FastAPI Developer — Property Management Platform Go-Live
## COrtai Inc. / Lionston Group — Toronto, Canada (Remote OK)

---

## What This Is

We are a Canadian real estate company (54 properties, 325+ units across GTA and Muskoka) that has built a custom property intelligence platform called **COrtai PM**. The platform is fully designed and largely built. We need an experienced developer to take it from a working prototype to a live production system.

**This is not a greenfield project.** The architecture is decided, the code is written, and the database schema is done. Your job is to wire it together, deploy it, connect it to our property management software (Buildium), and make it real.

---

## What Exists Today

You will receive on day one:

**Frontend (ready to wire to real API):**
- `cortai-pm.html` — 444KB, 6,366-line single-file PM dashboard. 12 sections: Portfolio, Properties, Residents, Work Orders, Inspections, Leasing, Financials, Field Techs, OPEX Tracking, IoT Monitoring, AI Intelligence, Buildium Sync. Currently runs on static demo data.
- `cortai-tech-portal.html` — 43KB mobile-optimized field technician portal. Login with PIN, view assigned work orders, access instructions, add comments and photos, update job status.

**Backend (written, needs deployment + wiring):**
- `api/schema_v2.py` — 43-table PostgreSQL schema, all indexes, triggers, functions
- `api/main.py` — FastAPI app, 39 REST endpoints
- `api/routes_extended.py` — 22 additional endpoints (IoT, OPEX, field techs, scheduling, access instructions)
- `buildium/client_v2.py` — Complete Buildium API OAuth client (all pull + push endpoints, rate limiting, retry)
- `buildium/sync_engine_v2.py` — Full sync orchestrator (pull every 4h, push on event, conflict resolution)
- `buildium/INTEGRATION_SPEC.md` — 525-line field-by-field Buildium integration spec
- `docker-compose.yml` + `Dockerfile` + `.env.example` — containerized deployment ready

**What the database covers:**
43 tables split across: Buildium-synced base data (12 tables), tenant intelligence (6), property intelligence (4 including unit access instructions), work order management (3 including scheduling), field service techs (3), OPEX tracking (4), IoT monitoring (4), platform infrastructure (4). Three PostgreSQL triggers: OPEX anomaly detection, IoT-to-WO auto-creation, tech status on assignment change.

---

## The Job — Sprint by Sprint

### Sprint 0 — Environment Setup (Days 1–2 · ~10 hours)
**Done-criteria: `/api/health` returns real Buildium property/unit/tenant counts**

- [ ] Stand up Ubuntu 22.04 VPS (DigitalOcean, Hetzner, or equivalent — we will pay)
- [ ] Deploy PostgreSQL 16 via Docker Compose
- [ ] Run schema: `uvicorn api.main:app` (schema auto-applies on boot)
- [ ] Verify all 43 tables created with correct indexes
- [ ] Set `.env` with Buildium credentials (we provide)
- [ ] Trigger first Buildium sync — verify 54 properties, 325+ units, ~280 tenants pull correctly
- [ ] Confirm Swagger UI at `https://api.yourdomain.com/docs` shows all endpoints
- [ ] HTTPS via nginx + Certbot (Let's Encrypt)

---

### Sprint 1 — Core Stability (Week 1 · ~35 hours)
**Done-criteria: All 61 endpoints return real data. JWT auth works.**

- [ ] **Buildium sync verification** — run pull, confirm all entity types populate correctly. Fix any asyncpg type mismatches against real Buildium data (the schema is correct; real API responses may have nulls or unexpected types)
- [ ] **WO push test end-to-end** — create WO in COrtai → confirm it appears in Buildium as a maintenance task within 30 seconds. Update status → confirm Buildium updates.
- [ ] **JWT authentication** — add `staff` table, `/api/auth/login`, `/api/auth/me`. PM dashboard requires valid JWT. Use `python-jose` + `passlib`. Initial users: Ravi (admin), Emma R. (PM), Marcus L. (PM).
- [ ] **Tech portal auth** — the tech portal uses PIN login (already built in frontend JS). Backend: `POST /api/auth/tech-login` validates tech ID + PIN, returns JWT with `role: field_tech` and `tech_id`. All other routes return 403 to field_tech role.
- [ ] **Buildium incremental sync** — ensure delta sync (last-modified filter) runs correctly on 4-hour schedule. Full sync on startup only.
- [ ] **Error handling** — Buildium 401 refresh, 429 rate limit backoff, 5xx retry. All already coded in `client_v2.py` — verify against real API.
- [ ] **Test all 61 endpoints** — write a simple pytest script that hits each endpoint with real data. Fix any 500s.

---

### Sprint 2 — Data Entry Layer (Week 2 · ~35 hours)
**Done-criteria: All 43 tables have real Lionston Group data.**

This sprint populates the COrtai-native tables — the 31 tables Buildium knows nothing about. You write import scripts; we provide the source data in spreadsheets.

- [ ] **Building systems import** — script to bulk-insert `building_systems` from CSV. Ravi provides: equipment type, brand, model, installed year, condition, service contractor per building. ~8 buildings × ~8 systems each.
- [ ] **Building events/history import** — `building_events` CSV import. Major capital events per building: boiler replacements, roof work, elevator modernizations, incidents.
- [ ] **Unit detail import** — `units` extended fields + `unit_appliances`. Floor, facing, parking spot, locker, appliance inventory per unit. Ravi provides Excel.
- [ ] **Unit access instructions import** — `unit_access_instructions`. One record per unit: access method, notice requirement, key location, restrictions, contact. CSV import script.
- [ ] **Tenant extended profiles** — `tenant_profiles`. Employer, income verified, credit score range, emergency contact, pets, vehicles. Import from existing screening records.
- [ ] **Risk scoring function** — `calculate_tenant_risk(tenant_id)` → 0–100 score. Factors: days in arrears, NSF history, late payment count, active N-forms, lease violations. Scheduled to recalculate nightly.
- [ ] **AI alert rules** — rule engine that generates `ai_alerts` records. Rules: HVAC system age > 15yr → maintenance risk, lease expiring < 30d with no renewal offer → vacancy risk, tenant risk score > 70 → delinquency risk, water bill +30% over baseline → leak risk. Run on data load and nightly.
- [ ] **OPEX budget seed** — import monthly budgets per building per category from spreadsheet Ravi provides. Required for anomaly detection triggers to work.
- [ ] **Unit tenant history** — import `unit_tenant_history` from PM records. Who lived in each unit, what period, rating, deposit outcome.

---

### Sprint 3 — Frontend Wiring (Week 3 · ~30 hours)
**Done-criteria: Frontend fully live. Zero static data remaining.**

Replace the hardcoded JavaScript data arrays in `cortai-pm.html` with real API calls.

- [ ] **Add API layer** — add `CortaiAPI` class in the HTML that wraps `fetch()` calls, handles JWT header, handles 401 → redirect to login. Add login screen before dashboard loads (simple email/password form → `/api/auth/login`).
- [ ] **Portfolio Overview** — wire to `GET /api/dashboard` and `GET /api/properties`. The landlord filter (already built in frontend) passes `?owner=Singh+Holdings` as query param.
- [ ] **Property Directory + Building Detail** — `GET /api/properties` for list, `GET /api/properties/{id}` for full building detail (units, systems, history, active WOs).
- [ ] **Work Order Triage + Board** — `GET /api/work-orders`, `POST /api/work-orders`, `PATCH /api/work-orders/{id}/status`, `POST /api/work-orders/{id}/assign`.
- [ ] **Resident Directory + Tenant Detail** — `GET /api/tenants`, `GET /api/tenants/{id}` (profile, payments, comms, docs).
- [ ] **Leasing** — `GET /api/leases/expiring`, `POST /api/leases/{id}/renewal-offer`.
- [ ] **Financials** — `GET /api/financials/rent-roll`, `GET /api/financials/delinquency`, `GET /api/financials/summary`.
- [ ] **Field Techs + Workload** — `GET /api/field-techs`, `GET /api/field-techs/{id}`, `GET /api/field-techs/{id}/schedule`.
- [ ] **OPEX** — `GET /api/opex/{property_id}/monthly`, `POST /api/opex/{property_id}/actuals`, `GET /api/opex/anomalies`.
- [ ] **IoT Dashboard** — `GET /api/iot/devices`, `GET /api/iot/alerts`. IoT readings are high-volume — frontend polls alerts every 60s, not raw readings.
- [ ] **Buildium Sync Panel** — `GET /api/sync/status`, `GET /api/sync/log`, `POST /api/sync/trigger`.
- [ ] **Tech Portal wiring** — `POST /api/auth/tech-login` for PIN auth. `GET /api/work-orders?tech_id={id}` for their job list. `PATCH /api/work-orders/{id}/status` for status updates. Photo upload to `POST /api/work-orders/{id}/photos` (store to server filesystem or S3).

---

### Sprint 4 — Polish & Production Hardening (Days 1–3 of Week 4 · ~20 hours)
**Done-criteria: Platform is production-ready. PM is using it daily.**

- [ ] **File storage for tenant documents + inspection photos** — integrate AWS S3 (ca-central-1) or DigitalOcean Spaces. `POST /api/tenants/{id}/documents` uploads file, stores URL. Tech portal photo capture → S3.
- [ ] **Daily database backup** — `pg_dump` cron to S3 or separate volume. Minimum daily. Keep 30 days.
- [ ] **Monitoring** — Sentry.io (or equivalent) for API error tracking. Set up alerts for Buildium sync failures.
- [ ] **Email notifications** — SendGrid or SMTP. Triggers: WO created (email vendor + PM), rent 5 days overdue (email PM), N4 due (email PM), IoT critical alert (email + SMS). Use existing `cortai_settings` table for email config.
- [ ] **Performance** — Add Redis caching for dashboard KPI queries (expire 5 min). The dashboard query hits 6 tables — cache it.
- [ ] **IoT partition maintenance** — cron job to create next month's `iot_readings_YYYY_MM` partition on the 25th of each month (script already in schema comments).
- [ ] **Rate limiting on API** — add `slowapi` middleware: 100 req/min per IP for unauthenticated, 300/min for authenticated.
- [ ] **Final user acceptance testing** — Ravi walks through every screen. You fix whatever doesn't match the design.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| API framework | FastAPI + Uvicorn |
| Database | PostgreSQL 16 |
| DB driver | asyncpg (native async) |
| Auth | python-jose + passlib (JWT) |
| HTTP client | httpx (async, for Buildium calls) |
| Container | Docker + Docker Compose |
| Reverse proxy | nginx |
| TLS | Certbot / Let's Encrypt |
| File storage | AWS S3 or DigitalOcean Spaces |
| Cache (Sprint 4) | Redis |
| Email | SendGrid |
| Monitoring | Sentry |
| CI (optional) | GitHub Actions |

The frontend is a single HTML file — no React, no build step, no npm. You will add API calls using plain `fetch()`. This is intentional — it keeps deployment simple and the client can maintain it without a build pipeline.

---

## What We Need From You

### Required skills
- Python 3.10+ (async/await fluency — this codebase is 100% async)
- FastAPI and Pydantic v2
- PostgreSQL — complex queries, indexes, triggers, partitioned tables
- asyncpg (not SQLAlchemy — we use raw queries for performance)
- REST API integration (OAuth2 client credentials, pagination, error handling)
- Linux server administration (Ubuntu, nginx, Certbot, Docker)
- Git

### Nice to have
- Prior Buildium API experience
- Property management software integrations generally
- Redis
- AWS S3 / DigitalOcean Spaces
- SendGrid

### NOT required
- React, Vue, Next.js — the frontend is vanilla JS
- Django or Flask experience — we use FastAPI
- DevOps / Kubernetes — Docker Compose is sufficient for this scale

---

## Scale

54 properties · 325+ units · ~280 tenants · ~600 work orders/year · 11 IoT sensors (growing) · 5 field technicians · 8 landlord clients

This is not a high-traffic consumer application. Concurrent users: 5–10 (3 PMs, 5 field techs). Database is small. The architecture is intentionally simple.

---

## Deliverables

At project completion you deliver:
1. Live API at `https://api.lionston.cortai.ca` (or agreed subdomain)
2. Live PM dashboard at `https://pm.lionston.cortai.ca`
3. Live tech portal at `https://tech.lionston.cortai.ca`
4. Buildium sync running — confirmed with real property/tenant/payment data
5. WO push confirmed — test WO created in COrtai appears in Buildium within 30s
6. All 43 database tables populated with real Lionston Group data
7. GitHub repo (private) with all code, `.env.example`, deployment README
8. Handoff call — walk us through the deployment so we can manage it

---

## Timeline

4 weeks from start. Weekly check-ins (30 min, Fridays). We are available on Slack for questions same day.

---

## Budget

**CAD $12,000–$18,000 fixed price** depending on your rate and location.

Or hourly: **CAD $90–$140/hr** (equivalent USD $65–$100/hr) · estimated 130–140 hours.

We are open to milestone-based payments:
- 25% on Sprint 0 completion (API live, Buildium syncing)
- 25% on Sprint 1 completion (auth working, all endpoints tested)
- 25% on Sprint 2 completion (all real data in database)
- 25% on Sprint 3+4 completion (frontend live, UAT passed)

**For developers in Eastern Europe (Poland, Ukraine, Romania):** we have existing team members there and are comfortable with that timezone. Equivalent budget applies at your local rate.

---

## How to Apply

Send us:

1. **2–3 sentences on your FastAPI + PostgreSQL experience** — specifically async, asyncpg, and any property management or real estate work.
2. **One example of a REST API integration you built** — describe the third-party API, how you handled auth/rate limiting/pagination, what happened when it failed.
3. **Your rate / availability** — fixed price bid or hourly, start date.
4. **GitHub profile or code sample** — specifically Python async code.

Do NOT send: a generic cover letter, your full CV, references.

**Applications that don't answer the 4 points above will not be read.**

---

## About the Project

COrtai is an AI-powered enterprise intelligence platform built by the team at Lionston Group, a Canadian real estate development and property management company. The PM platform is an internal tool — we are not building a SaaS product for external customers. The developer works directly with Ravi (founder, product owner) with no PM layer in between. Decisions move fast.

The codebase is well-organized and heavily commented. You will not be debugging someone else's spaghetti. You will be deploying a system that was designed to be deployed.

---

## Platforms to Post This

Post on **Upwork** (filter to Python/FastAPI, 90%+ JSS, $60+/hr), **Toptal** (if budget allows), **LinkedIn** (tag Python, FastAPI, PostgreSQL, Property Management), or reach out to **Krzysztof** directly (our Poland-based backend lead on StayGate — he knows the codebase architecture well and may be available or can refer someone).
