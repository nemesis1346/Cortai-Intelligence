# COrtai PM Platform — "What Else?" Smart Add-Ons
## Prioritized by ROI and Implementation Effort

---

## Already Built This Session

| Module | Status |
|---|---|
| Field Service Tech tracking (roster, tasks, productivity) | ✅ Built |
| OPEX per building with anomaly detection | ✅ Built |
| IoT power room sensors (vibration, acoustic, sump, temp, water leak) | ✅ Built |

---

## Tier 1 — Add These While the Developer is At It (High ROI, Low Effort)

### 1. Preventive Maintenance Scheduler
**What:** Auto-generate recurring WOs from a schedule. Never manually remember "Furnace filter every 3 months at 1441 Clark."
**How:** `pm_schedules` table (property, task, interval, next_due, auto_dispatch). Cron job creates WOs and assigns to field tech.
**Effort:** 1–2 days. Schema + cron job + one new UI screen.
**ROI:** Eliminates forgotten PMs that turn into emergency repairs. A skipped furnace filter costs $200/yr in efficiency; a missed boiler PM costs $40K when it fails.

### 2. Contractor COI Tracker (Certificate of Insurance)
**What:** Track every vendor's insurance certificate — type, coverage amount, expiry date. Auto-alert 30 days before expiry. Block WO dispatch to vendors with expired COIs.
**How:** Add `coi_expiry`, `coi_amount`, `coi_document_url` to vendors table. Cron sends expiry alerts.
**Effort:** Half a day. Already have vendor table — pure extension.
**ROI:** One uncovered vendor incident = $50,000+ liability exposure. This is a legal requirement most PMs track manually in a spreadsheet.

### 3. Common Area Booking System
**What:** Let tenants book the party room, rooftop terrace, gym guest passes, EV charger timeslots. PM sees all bookings. Prevent double-booking conflicts.
**How:** `amenity_bookings` table + simple tenant-facing booking page (no login required — use unit+last name auth).
**Effort:** 2–3 days for PM view. 1 more day for tenant-facing page.
**ROI:** Eliminates double-booking complaints. Generates revenue if you charge for party room ($150/day). Reduces PM admin calls.

### 4. Move-In / Move-Out Scheduling Calendar
**What:** Visual calendar showing all pending move-ins, move-outs, unit turnovers. Assign field techs to prep work. Track elevator booking (critical for mid/high-rise).
**How:** Calendar view of `leases.move_in_date` + `move_out_date` + `tech_tasks`. Add elevator booking slots per property.
**Effort:** 1–2 days.
**ROI:** Eliminates scheduling conflicts. Ensures cleaning, inspection, and repair are all lined up before move-in. Tenant satisfaction impact is significant on first impression.

### 5. Ontario Standard Lease Generator (N-Form Auto-Fill)
**What:** Auto-populate Ontario Standard Lease from your database. Also generate N1 (rent increase), N4 (non-payment), N5 (tenant's duty), N9 (termination), L1 (application to LTB) with all property/tenant data pre-filled.
**How:** Python + ReportLab or Fillpdf to fill Ontario government PDF forms from DB data.
**Effort:** 2–3 days per form type. Start with N1 + N4 (most common).
**ROI:** Each N4 currently takes 20–30 min to prepare manually. At 5 N4s/month across portfolio = 2.5 hours saved. More importantly, eliminates errors that get hearings thrown out at LTB.

---

## Tier 2 — Plan for Quarter 2 (Medium Effort, Strong ROI)

### 6. Tenant Portal (Basic)
**What:** Simple web page (no app) where tenants can: submit maintenance requests, see request status, pay rent (Stripe), upload documents (proof of insurance), book amenities.
**How:** Separate lightweight app (Next.js or plain HTML) hitting the same API. Auth: unit number + last 4 of phone.
**Effort:** 2–3 weeks for a solid V1.
**ROI:** Reduces PM phone/email volume by 40–60%. Maintenance requests get to the right person immediately. Tenants check status themselves instead of calling.

### 7. Vacancy Syndication — Push to Rentals.ca, Kijiji, Facebook
**What:** When a unit is listed vacant in COrtai, auto-push listing to all platforms with photos, description, and contact info. Track leads per platform.
**How:** Rentals.ca API + Kijiji XML feed + Facebook Marketplace API. Lead tracking table.
**Effort:** 1–2 weeks (APIs vary in quality).
**ROI:** Current manual process: create listing on each platform separately = 45 min per vacancy. With 14 vacancies at any time, this is 10+ hours/month just on listing creation.

### 8. Energy Benchmarking — vs ENERGY STAR / CMHC
**What:** Take your OPEX utility data (you're already tracking it) and benchmark each building against ENERGY STAR Canada standards for multi-family buildings. Flag underperformers. Calculate potential savings from upgrades.
**How:** Integrate ENERGY STAR Portfolio Manager API. Calculate EUI (Energy Use Intensity) per building. Generate upgrade ROI estimates.
**Effort:** 1 week.
**ROI:** Identifies which buildings are inefficient before utility bills tell you. 1441 Clark's geothermal should score ~40 EUI; a poorly performing building might score 180+. The delta is real money.

### 9. Insurance Claim Tracking
**What:** When an incident occurs (burst pipe, slip/fall, fire), track the full claim lifecycle: incident date, claim number, adjuster contact, submitted amount, settlement amount, status. Link to the work order.
**How:** `insurance_claims` table + status lifecycle UI. Link to `building_events` and `incidents`.
**Effort:** 1–2 days.
**ROI:** You're managing this in email/spreadsheets now. With 54 properties, active claims at any time = 3–8. Losing track of a claim means losing money.

### 10. Key / Fob / Access Tracking
**What:** Track who holds which keys, fobs, and access cards for every property. Log issuance, return, lost/stolen. Auto-flag when tenant's key isn't returned at move-out.
**How:** `key_inventory` table linked to properties, units, tenants, and staff. Check-out/check-in workflow.
**Effort:** 1 day.
**ROI:** Currently tracked (if at all) in a binder per building. A lost master key at a multi-family building = recore all locks = $3,000–$8,000. Knowing exactly who has what stops this.

---

## Tier 3 — Plan for Later (Bigger Scope)

### 11. Mobile App for Field Techs
**What:** Native iOS/Android app for field techs — see their task list, clock in/out, upload photos, mark completion, run checklist inspections, all offline-capable.
**How:** React Native app hitting the same API endpoints already built.
**Effort:** 4–6 weeks for a solid V1.
**ROI:** Techs currently call or text status updates. App eliminates manual tracking entirely and gives real-time status to PM dashboard.

### 12. Owner Portal
**What:** Read-only web portal for property owners: monthly statements, occupancy, open work orders, upcoming expenses, inspection reports. Replaces manual PDF email.
**How:** Simple React or Next.js app with owner-level auth. Reports auto-generated from DB.
**Effort:** 2–3 weeks.
**ROI:** Owners get self-serve transparency. Reduces "where's my statement?" calls. Premium owners (Singh Holdings, Patel Ventures) will appreciate it.

### 13. Parking Management
**What:** Track parking spot assignments, waitlists, violations, visitor permits. Integrate with the unit and tenant records already in the system.
**How:** `parking_spots` + `parking_assignments` + `parking_violations` tables. UI to manage.
**Effort:** 3–5 days.
**ROI:** Especially valuable at 2250 Islington (20 spots, 24 units) and 1441 Clark (34 spots, 32 units). Untracked parking = constant tenant disputes.

### 14. Predictive Utility Spend (ML Layer)
**What:** Use 24+ months of OPEX data to predict next month's utility bills per building. Flag anomalies before the bill arrives. Suggest budget adjustments.
**How:** scikit-learn time series model (SARIMA or Prophet). Train on historical OPEX actuals. Run monthly prediction job.
**Effort:** 2–3 weeks (including data prep).
**ROI:** Turns reactive budgeting into proactive. If the model predicts January gas at $6,800 vs budget $4,200, you know to investigate the boiler efficiency in November — not February when the bill arrives.

---

## Summary — Recommended Additions by Priority

| Priority | Item | Effort | Who Builds It |
|---|---|---|---|
| **Now — Sprint 2** | Preventive Maintenance Scheduler | 1–2 days | Backend developer |
| **Now — Sprint 2** | Contractor COI Tracker | 0.5 days | Backend developer |
| **Now — Sprint 2** | Ontario N-Form Auto-Fill (N1, N4) | 2–3 days | Backend developer |
| **Now — Sprint 2** | Move-In/Out Calendar | 1–2 days | Backend developer |
| **Now — Sprint 2** | Common Area Booking | 2–3 days | Backend developer |
| **Q3 2026** | Tenant Portal (Basic) | 2–3 weeks | Separate developer/project |
| **Q3 2026** | Vacancy Syndication | 1–2 weeks | Backend developer |
| **Q3 2026** | Insurance Claim Tracking | 1–2 days | Backend developer |
| **Q3 2026** | Key/Fob Tracking | 1 day | Backend developer |
| **Q3 2026** | Energy Benchmarking (ENERGY STAR) | 1 week | Backend developer |
| **Q4 2026** | Owner Portal | 2–3 weeks | Separate frontend project |
| **Q4 2026** | Mobile App for Field Techs | 4–6 weeks | Mobile developer |
| **2027** | Predictive Utility ML | 2–3 weeks | Data/ML developer |
| **2027** | Parking Management | 3–5 days | Backend developer |
