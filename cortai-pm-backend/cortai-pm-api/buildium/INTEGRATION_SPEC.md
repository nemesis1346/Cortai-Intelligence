# COrtai ↔ Buildium Integration Specification
## Lionston Group Property Intelligence Platform

**Version:** 2.0  
**Last Updated:** April 2026  
**Buildium API Version:** v1 (https://api.buildium.com/v1)  
**Auth:** OAuth2 Client Credentials (`urn:buildium:apis:all` scope)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         BUILDIUM                                     │
│  Source of truth for: Financials · Leases · Tenant base data        │
│  Tenant portal · Owner portal · Accounting GL · Reports             │
└───────────────┬───────────────────────────────┬─────────────────────┘
                │ PULL (every 4 hours)           │ PUSH (on event)
                ▼                               ▲
┌─────────────────────────────────────────────────────────────────────┐
│                      CORTAI DATABASE                                 │
│                                                                      │
│  Buildium-mirrored:  properties · units · tenants · leases          │
│                      payments · vendors · owners · bills             │
│                                                                      │
│  COrtai-native:      building systems · IoT sensors · OPEX          │
│                      field techs · scheduling · access instructions  │
│                      inspection checklists · risk scoring · AI alerts│
└─────────────────────────────────────────────────────────────────────┘
```

### Core Rules

1. **Buildium wins** on all base fields during pull. COrtai never overwrites Buildium data.
2. **COrtai wins** on all extended fields (never touched by sync).
3. **Push is event-triggered**, not scheduled — WO created → push immediately.
4. **Conflict resolution**: if Buildium and COrtai both changed a field since last sync → log conflict, keep Buildium version, flag for manual review.
5. **Retry**: failed pushes queue in `sync_log` with status=`error` and retry on next scheduled sync.

---

## 1. PULL — What COrtai Reads from Buildium

### 1.1 Properties

| Buildium Field | Buildium Endpoint | COrtai Column | Notes |
|---|---|---|---|
| `Id` | `GET /v1/rentals` | `properties.buildium_id` | Primary key link |
| `Name` | | `properties.name` | |
| `Address.AddressLine1` | | `properties.address` | |
| `Address.City` | | `properties.city` | |
| `Address.StateOrProvince` | | `properties.state_province` | |
| `Address.PostalCode` | | `properties.postal_code` | |
| `Type` | | `properties.property_type` | 'ResidentialProperty','Association' |
| `Structure` | | `properties.structure_type` | 'ApartmentComplex','SingleFamilyHome'... |
| `YearBuilt` | | `properties.year_built` | |
| `ReserveFundAmount` | | `properties.reserve_fund` | |
| `IsActive` | | `properties.is_active` | |

**Pull schedule:** Full sync on startup. Incremental (by `lastupdatedfrom`) every 4 hours.  
**COrtai-only fields NOT overwritten:** `portfolio_class`, `portfolio_region`, `pm_assigned`, `building_health`, `pin`, `assessed_value`, `purchase_price`, `purchase_date`, `mortgage_details`, `insurance_details`, `annual_tax`, `amenities`, `notes`, `stories`.

---

### 1.2 Units

| Buildium Field | Buildium Endpoint | COrtai Column | Notes |
|---|---|---|---|
| `Id` | `GET /v1/rentals/units` | `units.buildium_id` | |
| `UnitNumber` | | `units.unit_number` | |
| `Address.AddressLine1` | | `units.address` | |
| `UnitType` | | `units.unit_type` | |
| `Bedrooms` | | `units.beds` | |
| `Bathrooms` | | `units.baths` | |
| `Area` | | `units.sqft` | Square footage |
| `MarketRent` | | `units.market_rent` | Buildium's market rent |
| `IsActive` | | `units.is_active` | |
| `Property.Id` | | FK to `properties` | Used to resolve property_id |

**COrtai-only fields NOT overwritten:** `floor_number`, `facing`, `parking_spot`, `locker_number`, `unit_condition`, `last_inspection_date`, `notes`.

---

### 1.3 Owners

| Buildium Field | Endpoint | COrtai Column |
|---|---|---|
| `Id` | `GET /v1/rentals/owners` | `owners.buildium_id` |
| `FirstName` / `LastName` | | `owners.first_name` / `last_name` |
| `CompanyName` | | `owners.company_name` |
| `PrimaryEmail` | | `owners.email` |
| `PhoneNumbers[primary]` | | `owners.phone` |
| `IsCompany` | | `owners.is_company` |
| `IsActive` | | `owners.is_active` |

**Owner-to-property mapping:** Buildium returns ownership percentages. Stored in `rental_owner_assignments`.

---

### 1.4 Tenants

| Buildium Field | Endpoint | COrtai Column |
|---|---|---|
| `Id` | `GET /v1/leases/residents` | `tenants.buildium_id` |
| `FirstName` / `LastName` | | `tenants.first_name` / `last_name` |
| `Email` | | `tenants.email` |
| `PhoneNumbers[primary]` | | `tenants.phone` |
| `DateOfBirth` | | `tenants.date_of_birth` |
| `Company` | | `tenants.company` (commercial) |
| `IsActive` | | `tenants.is_active` |

**COrtai-only (in `tenant_profiles` — never overwritten):**  
Employer, annual income, credit score, income verification, emergency contact, pets, vehicles, risk score, risk factors, private notes.

---

### 1.5 Leases

| Buildium Field | Endpoint | COrtai Column |
|---|---|---|
| `Id` | `GET /v1/leases` | `leases.buildium_id` |
| `LeaseType` | | `leases.lease_type` | 'Fixed' or 'AtWill' (MTM) |
| `LeaseStatus` | | `leases.lease_status` | 'Active','Eviction','PastTenant' |
| `Rent` | | `leases.rent_amount` | |
| `SecurityDeposit` | | `leases.security_deposit` | |
| `StartDate` / `EndDate` | | `leases.start_date` / `end_date` | |
| `MoveInDate` / `MoveOutDate` | | `leases.move_in_date` / `move_out_date` | |
| `LeaseResidents[].Id` | | → `lease_residents` | Resolve to tenant FK |
| `LeaseResidents[].IsPrimary` | | `lease_residents.is_primary` | |
| `Unit.Id` | | FK to `units` | |

**COrtai-only (NOT overwritten):** `deposit_location`, `deposit_returned`, `renewal_offered`, `renewal_offer_amount`, `renewal_response`, `notes`.

---

### 1.6 Payments & Transactions

| Buildium Field | Endpoint | COrtai Column |
|---|---|---|
| `Id` | `GET /v1/leases/{id}/transactions` | `payments.buildium_id` |
| `Type` | | `payments.payment_type` | 'Charge','Payment','Credit' |
| `TotalAmount` | | `payments.amount` | |
| `Date` | | `payments.payment_date` | |
| `Memo` | | `payments.memo` | |
| `IsVoided` | | `payments.is_voided` | |

**Outstanding balances:** `GET /v1/leases/outstandingbalances` → `outstanding_balances` table. Refreshed every 4 hours.

**COrtai-only on payments:** `days_late`, `payment_status` (OnTime/Late/Early/NSF — calculated by COrtai), `nsf_fee_charged`.

---

### 1.7 Work Orders (Maintenance Requests)

**Pull direction:** Buildium tenant-portal-created maintenance requests → COrtai.  
**Push direction:** COrtai-created WOs → Buildium (see Section 2.1).

| Buildium Field | Endpoint | COrtai Column |
|---|---|---|
| `Id` | `GET /v1/tasks/maintenancerequests` | `work_orders.buildium_task_id` |
| `Title` | | `work_orders.title` |
| `Description` | | `work_orders.description` |
| `TaskStatus` | | `work_orders.status` (mapped) |
| `UnitId` | | FK to `units` |
| `DueDate` | | `work_orders.scheduled_date` |

**Status mapping (Buildium → COrtai):**

| Buildium `TaskStatus` | COrtai `status` |
|---|---|
| `New` | `Submitted` |
| `Assigned` | `Dispatched` |
| `InProgress` | `In Progress` |
| `Completed` | `Completed` |
| `Closed` | `Closed` |

**Pull filter:** `?statuses=New,Assigned,InProgress` on incremental. Full status on weekly full sync.

---

### 1.8 Vendors

| Buildium Field | Endpoint | COrtai Column |
|---|---|---|
| `Id` | `GET /v1/vendors` | `vendors.buildium_id` |
| `CompanyName` | | `vendors.company_name` |
| `FirstName` / `LastName` | | `vendors.first_name` / `last_name` |
| `Email` | | `vendors.email` |
| `PhoneNumbers[Main]` | | `vendors.phone` |
| `IsActive` | | `vendors.is_active` |
| `Is1099` | | `vendors.is_1099` |
| `TaxInformation.TaxIdentificationNumber` | | `vendors.tax_id` |

**COrtai-only (NOT overwritten):** `specialty`, `license_type`, `license_number`, `license_expiry`, `insurance_amount`, `insurance_expiry`, `coi_document_url`, `is_preferred`, `rating`.

---

### 1.9 Bills / Expenses

Bills entered directly in Buildium are pulled to track expenses PM didn't enter in COrtai.

| Buildium Field | Endpoint | COrtai Column |
|---|---|---|
| `Id` | `GET /v1/accounting/bills` | `buildium_bills.buildium_id` |
| `VendorId` | | FK to `vendors` |
| `BillDate` | | `buildium_bills.bill_date` |
| `DueDate` | | `buildium_bills.due_date` |
| `Memo` | | `buildium_bills.memo` |
| `TotalAmount` | | `buildium_bills.total_amount` |
| `GLAccount` | | `buildium_bills.gl_account` |
| `IsPaid` | | `buildium_bills.is_paid` |

---

## 2. PUSH — What COrtai Writes to Buildium

### 2.1 Work Orders → Buildium Maintenance Requests

**Trigger:** Immediately when a WO is created in COrtai (`sync_status = 'pending_push'`).  
**Endpoint:** `POST /v1/tasks/maintenancerequests`

**Payload:**
```json
{
  "Title":       "Furnace Not Working — No Heat",
  "Description": "Tenant reported no heat at 11pm. Temperature 14°C inside.",
  "Category":    "General",
  "Priority":    "Emergency",
  "UnitId":      12345,
  "DueDate":     "2026-04-07"
}
```

**On success:** Store returned `Id` in `work_orders.buildium_task_id`, set `sync_status = 'synced'`.  
**On failure:** Set `sync_status = 'error'`, retry on next scheduled run.

**Priority mapping (COrtai → Buildium):**

| COrtai `priority` | Buildium `Priority` |
|---|---|
| `Emergency` | `Emergency` |
| `Urgent` | `High` |
| `High` | `High` |
| `Normal` | `Normal` |
| `Low` | `Low` |
| `Preventive` | `Low` |

---

### 2.2 Work Order Status Updates → Buildium

**Trigger:** When `work_orders.status` changes and `buildium_task_id` is set.  
**Endpoint:** `PATCH /v1/tasks/maintenancerequests/{buildium_task_id}`

```json
{ "TaskStatus": "InProgress" }
```

**What pushes:** Status changes to Dispatched, In Progress, Completed, Closed.  
**What does NOT push:** Submitted (not yet in Buildium), Parts Pending (no Buildium equivalent — stays InProgress in Buildium).

---

### 2.3 Tech Assignment Notes → Buildium WO

**Trigger:** When a WO assignment is confirmed in `wo_assignments`.  
**Endpoint:** `POST /v1/tasks/maintenancerequests/{buildium_task_id}/notes`

```json
{
  "Note": "Assigned to Marcus Torres — scheduled 2026-04-10 at 10:00.\nDispatch notes: Call tenant 30 min before. Dog in unit (Mocha) — ask tenant to crate first.",
  "IsPrivate": true
}
```

**Format:** Always `IsPrivate: true` — internal notes only, not visible to tenant via Buildium portal.

---

### 2.4 Vendor Creation → Buildium

**Trigger:** When a new vendor is added in COrtai and `buildium_id` is null.  
**Endpoint:** `POST /v1/vendors`

```json
{
  "CompanyName": "Heritage Flooring",
  "Email": "quotes@heritageflooring.ca",
  "PhoneNumbers": [{"Number": "905-555-0240", "PhoneType": "Main"}],
  "Is1099": false
}
```

**After push:** Store returned `Id` in `vendors.buildium_id`.  
**Note:** COrtai-only vendor fields (license, insurance, specialty, rating) stay in COrtai — Buildium doesn't have these fields.

---

### 2.5 OPEX Bills → Buildium Accounting

**Trigger:** When an OPEX actual is entered in COrtai and `push_opex_bills = 'true'` in settings.  
**Endpoint:** `POST /v1/accounting/bills`

```json
{
  "VendorId":   98765,
  "BillDate":   "2026-04-01",
  "DueDate":    "2026-04-15",
  "Memo":       "April 2026 - Natural Gas - 1441 Clark Ave W",
  "Lines": [{
    "GLAccountId": "6110",
    "Amount": 1420.00,
    "Description": "Gas bill - Enbridge - April 2026"
  }]
}
```

**GL Account mapping:** Set via `opex_categories.buildium_gl_account`. Confirm GL account IDs match your Buildium chart of accounts.  
**After push:** Update `opex_actuals.pushed_to_buildium = TRUE` and store `buildium_bills.buildium_id`.

---

### 2.6 Lease Notes (Communications) → Buildium

**Trigger:** When `tenant_communications.push_to_buildium = TRUE` (N4 notices, important communications).  
**Endpoint:** `POST /v1/leases/{buildium_lease_id}/notes`

```json
{
  "Note": "Apr 1 2026 — N4 Notice served. Arrears: $5,560. 14 days to pay or vacate. Mediation Apr 15.",
  "IsPrivate": true
}
```

**What pushes:** Legal notices (N4, N5, N9, L1), formal payment arrangements.  
**What does NOT push:** Internal PM notes, risk scores, private tenant profile notes.

---

### 2.7 PM Notes → Buildium Task Notes

**Trigger:** When `pm_notes.push_to_buildium = TRUE` and `pm_notes.work_order_id` is set.  
**Endpoint:** `POST /v1/tasks/maintenancerequests/{task_id}/notes`

---

## 3. WHAT STAYS IN CORTAI ONLY

These data categories are **not in Buildium's data model** and are never synced:

| Category | Tables | Why Not in Buildium |
|---|---|---|
| Building Systems | `building_systems` | Buildium has no building equipment tracking |
| Building History | `building_events` | Buildium has no capex/event timeline |
| Unit Appliances | `unit_appliances` | Buildium has no per-unit appliance registry |
| Unit Access Instructions | `unit_access_instructions` | Buildium has no access protocol field |
| IoT Sensors | `iot_devices`, `iot_readings`, `iot_alerts` | No IoT concept in Buildium |
| OPEX Analysis | `opex_anomalies`, anomaly flags | The analysis layer is COrtai-only (bills sync, analysis doesn't) |
| Field Techs | `field_techs`, `tech_tasks`, `tech_productivity_snapshots` | Buildium has no field tech management |
| WO Scheduling | `wo_assignments` | Buildium has no time-slot booking — we push a note instead |
| Tenant Risk Scores | `tenant_profiles.risk_score`, `risk_factors` | COrtai proprietary scoring |
| Tenant Extended Profile | `tenant_profiles` | Employer, income, credit score, pets — COrtai-only |
| AI Alerts | `ai_alerts` | Predictive intelligence layer — COrtai-only |
| Inspection Checklists | `inspection_items` | Buildium has basic inspection notes only |
| Vendor Ratings | `vendor_ratings` | Buildium has no vendor performance scoring |
| OPEX Budgets | `opex_budgets`, `opex_categories` | Budgeting done in COrtai; actuals push to Buildium |

---

## 4. SYNC SCHEDULE

| Event | Trigger | Endpoint | Notes |
|---|---|---|---|
| Full properties pull | Startup + weekly Sunday 2am | `GET /v1/rentals` | All records, no filter |
| Incremental properties | Every 4 hours | `GET /v1/rentals?lastupdatedfrom=...` | Delta only |
| Full units pull | Startup + weekly | `GET /v1/rentals/units` | |
| Incremental units | Every 4 hours | `GET /v1/rentals/units?lastupdatedfrom=...` | |
| Full tenants pull | Startup + weekly | `GET /v1/leases/residents` | |
| Incremental tenants | Every 4 hours | | |
| Full leases pull | Startup + weekly | `GET /v1/leases` | All statuses |
| Active leases only | Every 4 hours | `GET /v1/leases?leasestatuses=Active` | |
| Outstanding balances | Every 4 hours | `GET /v1/leases/outstandingbalances` | Full refresh |
| Open WO pull | Every 4 hours | `GET /v1/tasks/maintenancerequests?statuses=New,Assigned,InProgress` | |
| Vendor pull | Weekly | `GET /v1/vendors?isactive=true` | |
| Bills pull | Daily at midnight | `GET /v1/accounting/bills?from=...` | Last 7 days |
| **Push: new WO** | On WO creation | `POST /v1/tasks/maintenancerequests` | Immediate |
| **Push: WO status** | On status change | `PATCH /v1/tasks/maintenancerequests/{id}` | Immediate |
| **Push: WO note** | On assignment | `POST /v1/tasks/maintenancerequests/{id}/notes` | Immediate |
| **Push: new vendor** | On vendor creation | `POST /v1/vendors` | Immediate |
| **Push: OPEX bill** | On bill entry | `POST /v1/accounting/bills` | Immediate (if enabled) |
| **Push: lease note** | On marked comms | `POST /v1/leases/{id}/notes` | Immediate |

---

## 5. AUTHENTICATION

```python
# Token request
POST https://auth.buildium.com/oauth/token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials
&client_id={BUILDIUM_CLIENT_ID}        # From Buildium Developer Portal
&client_secret={BUILDIUM_CLIENT_SECRET}
&scope=urn:buildium:apis:all

# Response
{
  "access_token": "eyJ...",
  "token_type": "Bearer",
  "expires_in": 3600
}

# All API calls
Authorization: Bearer {access_token}
```

**Rate limit:** 100 requests/minute per client. COrtai enforces 90/min to leave buffer.  
**Token expiry:** Refresh 60 seconds before expiry. Handled automatically by `BuildiumClient`.

---

## 6. ERROR HANDLING & CONFLICT RESOLUTION

### Pull Errors
| Scenario | Action |
|---|---|
| 401 Unauthorized | Re-authenticate, retry once |
| 429 Rate Limited | Wait `Retry-After` header (default 60s), retry |
| 404 Not Found | Log warning, skip record |
| 5xx Server Error | Retry with exponential backoff (2s, 4s, 8s), log error |
| Network timeout | Retry up to 3 times, log if all fail |

### Push Errors
| Scenario | Action |
|---|---|
| 400 Bad Request | Log error detail to `sync_log`, set `sync_status='error'`, do NOT retry automatically (needs manual fix) |
| 401 Unauthorized | Re-authenticate, retry |
| 409 Conflict | Log conflict detail in `sync_log.conflict_detail` JSONB, keep COrtai version, flag for review |
| 5xx Server Error | Queue for retry on next scheduled sync run |

### Conflict Resolution Rules
1. **Buildium wins on base fields** — if Buildium has a newer `UpdatedDateTime` for a tenant name, phone, or lease amount, COrtai adopts it.
2. **COrtai wins on extended fields** — risk scores, extended profiles, access instructions are never overwritten.
3. **WO status conflicts** — if a WO is marked Complete in Buildium but In Progress in COrtai, log conflict and set COrtai to the Buildium status (Buildium is the source of truth for completion).
4. **Bill conflicts** — if a bill was already entered in Buildium for the same vendor/month as a COrtai OPEX actual, do not push (detect by amount + date + vendor match).

---

## 7. SETUP CHECKLIST — For the Developer

### Step 1: Buildium Developer Portal
1. Log into Buildium as account admin
2. Navigate to **Settings → API & Integrations → Developer Portal**
3. Create a new application, select **Client Credentials** grant type
4. Required scope: `urn:buildium:apis:all`
5. Copy `Client ID` and `Client Secret` into `.env`

### Step 2: Buildium GL Account Setup
1. In Buildium: **Accounting → Chart of Accounts**
2. Note the GL account IDs for utilities and expenses
3. Update `opex_categories.buildium_gl_account` with correct account strings

### Step 3: Buildium Maintenance Request Categories
1. In Buildium: **Settings → Maintenance → Categories**
2. Ensure categories match COrtai WO categories (HVAC, Plumbing, Electrical, etc.)
3. If Buildium uses different category names, add mapping to `field_mappings`

### Step 4: First Sync
```bash
# Trigger full sync after startup
curl -X POST http://localhost:3001/api/sync/trigger?full=true

# Monitor
curl http://localhost:3001/api/sync/log
```

### Step 5: Verify
- `/api/health` returns real `properties`, `units`, `tenants` counts from Buildium
- Create a test WO in COrtai → verify it appears in Buildium within 30 seconds
- Update WO status in COrtai → verify status updates in Buildium
- Enter an OPEX bill → verify it appears in Buildium Accounting (if push enabled)

---

## 8. FUTURE: BUILDIUM WEBHOOKS

Buildium supports webhooks for real-time push from Buildium to COrtai (instead of polling).

When available, replace polling with:
```
POST https://api.buildium.com/v1/webhooks/subscriptions
{
  "url": "https://api.yourdomain.com/api/webhooks/buildium",
  "events": [
    "MaintenanceRequestCreated",
    "MaintenanceRequestStatusChanged",
    "LeasePaymentReceived",
    "LeaseResidentAdded",
    "LeaseStatusChanged"
  ]
}
```

Handler endpoint: `POST /api/webhooks/buildium`  
This reduces sync latency from 4 hours to seconds for critical events like rent payments and new maintenance requests.

---

## 9. DATA VOLUME ESTIMATES

| Entity | Lionston Portfolio | Sync Size |
|---|---|---|
| Properties | 54 | Small — full sync in <1s |
| Units | ~325 | Small — full sync in <2s |
| Tenants | ~280 (active + past) | Small |
| Leases | ~400 (active + historical) | Small |
| Payments | ~30,000/yr (cumulative) | Medium — incremental only after initial |
| WO Maintenance Requests | ~600/yr | Small |
| Bills | ~1,200/yr (utilities + expenses) | Small |
| IoT Readings | ~2M/yr (high-volume, never synced) | N/A — COrtai only |

Full initial sync estimated time: **8–15 minutes** (limited by Buildium rate limit of 100 req/min).  
Incremental 4-hour sync: **~30–60 seconds**.
