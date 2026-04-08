"""
schema_v2.py — COrtai Property Intelligence Platform
Complete PostgreSQL schema · 42 tables
Replaces schema.py + schema_additions.py — use this file only.

Tables by domain:
  Buildium-Synced (12):  properties, units, owners, rental_owner_assignments,
                          tenants, leases, lease_residents, work_orders,
                          payments, outstanding_balances, vendors, buildium_bills
  Tenant Intelligence (5): tenant_profiles, tenant_communications,
                             tenant_documents, unit_tenant_history, inspections + inspection_items
  Property Intelligence (4): building_systems, building_events,
                               unit_appliances, unit_access_instructions
  Work Order Management (3): wo_assignments, vendor_ratings, pm_notes
  Field Service (3):     field_techs, tech_tasks, tech_productivity_snapshots
  OPEX & Finance (4):    opex_categories, opex_budgets, opex_actuals, opex_anomalies
  IoT Monitoring (4):    iot_devices, iot_readings, iot_alerts, iot_alert_rules
  Platform (4):          ai_alerts, sync_log, field_mappings, cortai_settings
"""

SCHEMA = """

-- ══════════════════════════════════════════════════════════════════
-- 1. BUILDIUM-SYNCED TABLES (12)
-- Pull from Buildium every 4h. Buildium wins on base fields.
-- ══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS properties (
    id                  SERIAL PRIMARY KEY,
    buildium_id         INTEGER UNIQUE NOT NULL,
    name                TEXT NOT NULL,
    address             TEXT NOT NULL,
    address2            TEXT,
    city                TEXT,
    state_province      TEXT DEFAULT 'ON',
    postal_code         TEXT,
    country             TEXT DEFAULT 'CA',
    property_type       TEXT,                           -- 'ResidentialProperty','Association'
    structure_type      TEXT,                           -- 'ApartmentComplex','SingleFamilyHome','Condo','Commercial'
    total_units         INTEGER DEFAULT 1,
    year_built          INTEGER,
    reserve_fund        NUMERIC(12,2),
    is_active           BOOLEAN DEFAULT TRUE,
    -- Sync
    buildium_created_at TIMESTAMPTZ,
    buildium_updated_at TIMESTAMPTZ,
    last_synced_at      TIMESTAMPTZ DEFAULT NOW(),
    sync_status         TEXT DEFAULT 'synced',
    -- COrtai extensions (NOT in Buildium — never overwritten by sync)
    portfolio_class     TEXT DEFAULT 'Standard',        -- 'Premium','Standard','Value'
    portfolio_region    TEXT,                           -- 'GTA North','GTA West','Muskoka','Barrie'
    portfolio_type      TEXT,                           -- 'Multi-Family','Single Family','Commercial','Muskoka'
    pm_assigned         TEXT,
    pm_phone            TEXT,
    owner_entity        TEXT,
    building_health     INTEGER,                        -- 0-100 COrtai score
    stories             INTEGER,
    pin                 TEXT,                           -- Ontario PIN
    legal_description   TEXT,
    assessed_value      NUMERIC(14,2),
    purchase_price      NUMERIC(14,2),
    purchase_date       DATE,
    mortgage_details    TEXT,
    insurance_details   TEXT,
    insurance_policy    TEXT,
    annual_tax          NUMERIC(10,2),
    tax_due_dates       TEXT,
    amenities           TEXT[],
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS units (
    id                  SERIAL PRIMARY KEY,
    buildium_id         INTEGER UNIQUE NOT NULL,
    property_id         INTEGER REFERENCES properties(id) ON DELETE CASCADE,
    unit_number         TEXT NOT NULL,
    address             TEXT,
    unit_type           TEXT,
    beds                NUMERIC(3,1),
    baths               NUMERIC(3,1),
    sqft                INTEGER,
    market_rent         NUMERIC(10,2),
    is_active           BOOLEAN DEFAULT TRUE,
    -- Sync
    buildium_updated_at TIMESTAMPTZ,
    last_synced_at      TIMESTAMPTZ DEFAULT NOW(),
    -- COrtai extensions
    floor_number        INTEGER,
    facing              TEXT,
    parking_spot        TEXT,
    locker_number       TEXT,
    unit_condition      TEXT DEFAULT 'Good',
    last_inspection_date DATE,
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS owners (
    id                  SERIAL PRIMARY KEY,
    buildium_id         INTEGER UNIQUE NOT NULL,
    first_name          TEXT,
    last_name           TEXT,
    company_name        TEXT,
    email               TEXT,
    phone               TEXT,
    address             TEXT,
    is_company          BOOLEAN DEFAULT FALSE,
    is_active           BOOLEAN DEFAULT TRUE,
    last_synced_at      TIMESTAMPTZ DEFAULT NOW(),
    -- COrtai extensions
    owner_tier          TEXT DEFAULT 'Standard',
    disbursement_day    INTEGER DEFAULT 15,
    disbursement_method TEXT DEFAULT 'EFT',
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rental_owner_assignments (
    id                  SERIAL PRIMARY KEY,
    property_id         INTEGER REFERENCES properties(id) ON DELETE CASCADE,
    owner_id            INTEGER REFERENCES owners(id) ON DELETE CASCADE,
    ownership_pct       NUMERIC(5,2) DEFAULT 100.00,
    last_synced_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(property_id, owner_id)
);

CREATE TABLE IF NOT EXISTS tenants (
    id                  SERIAL PRIMARY KEY,
    buildium_id         INTEGER UNIQUE NOT NULL,
    first_name          TEXT NOT NULL,
    last_name           TEXT NOT NULL,
    email               TEXT,
    phone               TEXT,
    alt_phone           TEXT,
    date_of_birth       DATE,
    company             TEXT,
    is_active           BOOLEAN DEFAULT TRUE,
    buildium_created_at TIMESTAMPTZ,
    last_synced_at      TIMESTAMPTZ DEFAULT NOW(),
    -- COrtai extensions (NOT in Buildium)
    risk_score          INTEGER DEFAULT 0,
    risk_label          TEXT DEFAULT 'Unknown',
    tenant_tier         TEXT DEFAULT 'Standard',
    flags               TEXT[],
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS leases (
    id                  SERIAL PRIMARY KEY,
    buildium_id         INTEGER UNIQUE NOT NULL,
    unit_id             INTEGER REFERENCES units(id) ON DELETE SET NULL,
    lease_type          TEXT,                           -- 'Fixed','AtWill'(MTM)
    lease_status        TEXT,                           -- 'Active','Eviction','PastTenant','Cancelled'
    rent_amount         NUMERIC(10,2),
    security_deposit    NUMERIC(10,2),
    start_date          DATE,
    end_date            DATE,
    move_in_date        DATE,
    move_out_date       DATE,
    is_active           BOOLEAN DEFAULT TRUE,
    buildium_updated_at TIMESTAMPTZ,
    last_synced_at      TIMESTAMPTZ DEFAULT NOW(),
    -- COrtai extensions
    deposit_location    TEXT,
    deposit_returned    NUMERIC(10,2),
    deposit_return_date DATE,
    renewal_offered     BOOLEAN DEFAULT FALSE,
    renewal_offer_amount NUMERIC(10,2),
    renewal_offer_date  DATE,
    renewal_response    TEXT,
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS lease_residents (
    id                  SERIAL PRIMARY KEY,
    buildium_id         INTEGER UNIQUE,
    lease_id            INTEGER REFERENCES leases(id) ON DELETE CASCADE,
    tenant_id           INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
    is_primary          BOOLEAN DEFAULT FALSE,
    move_in_date        DATE,
    move_out_date       DATE,
    last_synced_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS vendors (
    id                  SERIAL PRIMARY KEY,
    buildium_id         INTEGER UNIQUE,
    company_name        TEXT NOT NULL,
    first_name          TEXT,
    last_name           TEXT,
    email               TEXT,
    phone               TEXT,
    alt_phone           TEXT,
    address             TEXT,
    is_active           BOOLEAN DEFAULT TRUE,
    is_1099             BOOLEAN DEFAULT FALSE,
    tax_id              TEXT,
    last_synced_at      TIMESTAMPTZ DEFAULT NOW(),
    -- COrtai extensions
    specialty           TEXT,
    license_type        TEXT,
    license_number      TEXT,
    license_expiry      DATE,
    insurance_amount    TEXT,
    insurance_expiry    DATE,
    coi_document_url    TEXT,
    coi_last_verified   DATE,
    is_preferred        BOOLEAN DEFAULT FALSE,
    rating              NUMERIC(2,1),
    ytd_spend           NUMERIC(10,2) DEFAULT 0,
    active_wo_count     INTEGER DEFAULT 0,
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS work_orders (
    id                  SERIAL PRIMARY KEY,
    buildium_id         INTEGER UNIQUE,                 -- NULL = COrtai-created, not yet pushed
    unit_id             INTEGER REFERENCES units(id) ON DELETE SET NULL,
    property_id         INTEGER REFERENCES properties(id) ON DELETE SET NULL,
    vendor_id           INTEGER REFERENCES vendors(id) ON DELETE SET NULL,
    wo_number           TEXT,                           -- WO-2501
    title               TEXT NOT NULL,
    description         TEXT,
    category            TEXT,
    priority            TEXT DEFAULT 'Normal',
    status              TEXT DEFAULT 'Submitted',
    submitted_by        TEXT,
    submitted_source    TEXT DEFAULT 'COrtai',          -- 'COrtai','TenantPortal','Buildium'
    tenant_notified     BOOLEAN DEFAULT FALSE,
    est_cost            NUMERIC(10,2),
    actual_cost         NUMERIC(10,2),
    invoice_number      TEXT,
    invoice_approved    BOOLEAN DEFAULT FALSE,
    photo_count         INTEGER DEFAULT 0,
    scheduled_date      DATE,                           -- legacy date field
    completed_date      DATE,
    is_tenant_caused    BOOLEAN DEFAULT FALSE,
    is_recurring        BOOLEAN DEFAULT FALSE,
    recurring_interval  TEXT,
    -- Buildium sync fields
    buildium_task_id    INTEGER,
    buildium_synced_at  TIMESTAMPTZ,
    sync_direction      TEXT DEFAULT 'push',
    sync_status         TEXT DEFAULT 'pending_push',   -- 'synced','pending_push','error','cortai_only'
    -- COrtai fields
    notes               TEXT,
    internal_notes      TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS payments (
    id                  SERIAL PRIMARY KEY,
    buildium_id         INTEGER UNIQUE NOT NULL,
    lease_id            INTEGER REFERENCES leases(id) ON DELETE SET NULL,
    tenant_id           INTEGER REFERENCES tenants(id) ON DELETE SET NULL,
    payment_type        TEXT,                           -- 'Charge','Payment','Credit','ReversePayment'
    amount              NUMERIC(10,2) NOT NULL,
    payment_date        DATE NOT NULL,
    memo                TEXT,
    reference           TEXT,
    payment_method      TEXT,                           -- 'eTransfer','PAD','Cheque','Cash'
    is_voided           BOOLEAN DEFAULT FALSE,
    last_synced_at      TIMESTAMPTZ DEFAULT NOW(),
    -- COrtai extensions
    days_late           INTEGER,
    payment_status      TEXT,                           -- 'OnTime','Late','Early','NSF','Partial'
    nsf_fee_charged     BOOLEAN DEFAULT FALSE,
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS outstanding_balances (
    id                  SERIAL PRIMARY KEY,
    buildium_id         INTEGER UNIQUE,
    lease_id            INTEGER REFERENCES leases(id) ON DELETE CASCADE,
    tenant_id           INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
    total_balance       NUMERIC(10,2) DEFAULT 0,
    charge_type         TEXT,
    as_of_date          DATE,
    last_synced_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Bills pulled from Buildium accounting (expenses entered in Buildium)
-- Also used as push target for OPEX actuals entered in COrtai
CREATE TABLE IF NOT EXISTS buildium_bills (
    id                  SERIAL PRIMARY KEY,
    buildium_id         INTEGER UNIQUE,                 -- NULL = COrtai-originated, to be pushed
    property_id         INTEGER REFERENCES properties(id) ON DELETE SET NULL,
    vendor_id           INTEGER REFERENCES vendors(id) ON DELETE SET NULL,
    bill_date           DATE NOT NULL,
    due_date            DATE,
    memo                TEXT,
    reference           TEXT,
    total_amount        NUMERIC(12,2) NOT NULL,
    gl_account          TEXT,                           -- Buildium GL account name
    paid_date           DATE,
    is_paid             BOOLEAN DEFAULT FALSE,
    -- Sync
    buildium_synced_at  TIMESTAMPTZ,
    sync_status         TEXT DEFAULT 'pending_push',
    -- Link to OPEX actual if COrtai-originated
    opex_actual_id      INTEGER,                        -- FK added after opex_actuals created
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ══════════════════════════════════════════════════════════════════
-- 2. TENANT INTELLIGENCE (6 tables)
-- COrtai-native. Enhanced data beyond what Buildium stores.
-- ══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS tenant_profiles (
    id                  SERIAL PRIMARY KEY,
    tenant_id           INTEGER UNIQUE REFERENCES tenants(id) ON DELETE CASCADE,
    date_of_birth       DATE,
    sin_last4           TEXT,                           -- Encrypted — last 4 only
    employer            TEXT,
    employer_phone      TEXT,
    position            TEXT,
    employment_start    DATE,
    annual_income       NUMERIC(12,2),
    income_verified_by  TEXT,
    income_verified_at  DATE,
    income_doc_type     TEXT,                           -- 'T4','NOA','PayStub','BankStatement','EmploymentLetter'
    credit_score        INTEGER,
    credit_bureau       TEXT DEFAULT 'Equifax',
    credit_checked_at   DATE,
    emergency_name      TEXT,
    emergency_relation  TEXT,
    emergency_phone     TEXT,
    pets                BOOLEAN DEFAULT FALSE,
    pet_description     TEXT,
    smoker              BOOLEAN DEFAULT FALSE,
    vehicles            INTEGER DEFAULT 0,
    vehicle_plates      TEXT,
    occupant_names      TEXT,
    -- Risk scoring
    risk_score          INTEGER DEFAULT 0,
    risk_label          TEXT DEFAULT 'Unknown',
    risk_last_calc      TIMESTAMPTZ,
    risk_factors        JSONB,
    -- Screening
    application_date    DATE,
    application_source  TEXT,
    references_verified BOOLEAN DEFAULT FALSE,
    private_notes       TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tenant_communications (
    id                  SERIAL PRIMARY KEY,
    tenant_id           INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
    lease_id            INTEGER REFERENCES leases(id) ON DELETE SET NULL,
    comm_date           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    comm_type           TEXT NOT NULL,                  -- 'Email','Call','SMS','Letter','Notice','InPerson','Portal'
    direction           TEXT NOT NULL,                  -- 'Inbound','Outbound'
    subject             TEXT,
    summary             TEXT NOT NULL,
    outcome             TEXT,
    follow_up_required  BOOLEAN DEFAULT FALSE,
    follow_up_date      DATE,
    logged_by           TEXT,
    attachment_url      TEXT,
    -- Buildium push: comm summaries can be added as Buildium lease notes
    buildium_note_id    INTEGER,
    pushed_to_buildium  BOOLEAN DEFAULT FALSE,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tenant_documents (
    id                  SERIAL PRIMARY KEY,
    tenant_id           INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
    lease_id            INTEGER REFERENCES leases(id) ON DELETE SET NULL,
    doc_type            TEXT NOT NULL,                  -- 'LeaseAgreement','PhotoID','CreditReport','IncomeVerification','PetAgreement','MoveInInspection','KeyReceipt','TenantInsurance','N1','N4','N5','N9','L1','PaymentPlan'
    doc_name            TEXT,
    file_url            TEXT,
    file_size_kb        INTEGER,
    is_signed           BOOLEAN DEFAULT FALSE,
    signed_date         DATE,
    expiry_date         DATE,
    uploaded_by         TEXT,
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS unit_tenant_history (
    id                  SERIAL PRIMARY KEY,
    unit_id             INTEGER REFERENCES units(id) ON DELETE CASCADE,
    lease_id            INTEGER REFERENCES leases(id) ON DELETE SET NULL,
    tenant_name         TEXT NOT NULL,                  -- Denormalized for historical record
    period_start        DATE NOT NULL,
    period_end          DATE,
    monthly_rent        NUMERIC(10,2),
    deposit_paid        NUMERIC(10,2),
    deposit_returned    NUMERIC(10,2),
    tenant_rating       TEXT,                           -- 'Excellent','Good','Fair','Poor'
    issues              TEXT,
    move_out_reason     TEXT,
    final_inspection_result TEXT,
    charges_at_moveout  NUMERIC(10,2) DEFAULT 0,
    eviction            BOOLEAN DEFAULT FALSE,
    nsf_incidents       INTEGER DEFAULT 0,
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS inspections (
    id                  SERIAL PRIMARY KEY,
    unit_id             INTEGER REFERENCES units(id) ON DELETE SET NULL,
    property_id         INTEGER REFERENCES properties(id) ON DELETE SET NULL,
    lease_id            INTEGER REFERENCES leases(id) ON DELETE SET NULL,
    inspection_type     TEXT NOT NULL,                  -- 'MoveIn','MoveOut','Routine','DriveBy','Annual','Insurance','PreListing'
    status              TEXT DEFAULT 'Scheduled',       -- 'Scheduled','InProgress','Completed','Cancelled'
    scheduled_date      DATE,
    completed_date      DATE,
    inspector_name      TEXT,
    tenant_present      BOOLEAN,
    overall_result      TEXT,                           -- 'Pass','Conditional','Fail'
    overall_condition   TEXT,
    duration_minutes    INTEGER,
    total_charges       NUMERIC(10,2) DEFAULT 0,
    deposit_deducted    NUMERIC(10,2) DEFAULT 0,
    notes               TEXT,
    tenant_signature    BOOLEAN DEFAULT FALSE,
    pm_signature        BOOLEAN DEFAULT FALSE,
    report_url          TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS inspection_items (
    id                  SERIAL PRIMARY KEY,
    inspection_id       INTEGER REFERENCES inspections(id) ON DELETE CASCADE,
    room_name           TEXT NOT NULL,
    item_name           TEXT NOT NULL,
    condition_in        TEXT,
    condition_out       TEXT,                           -- 'Excellent','Good','Fair','Poor'
    is_tenant_caused    BOOLEAN DEFAULT FALSE,
    charge_amount       NUMERIC(10,2),
    charge_description  TEXT,
    notes               TEXT,
    photo_urls          TEXT[],
    sort_order          INTEGER DEFAULT 0
);

-- ══════════════════════════════════════════════════════════════════
-- 3. PROPERTY INTELLIGENCE (4 tables)
-- COrtai-native. Not in Buildium's data model.
-- ══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS building_systems (
    id                  SERIAL PRIMARY KEY,
    property_id         INTEGER REFERENCES properties(id) ON DELETE CASCADE,
    system_type         TEXT NOT NULL,                  -- 'HVAC','Plumbing','Electrical','Elevator','Roof','Fire','Intercom','Parking'
    system_name         TEXT,
    brand               TEXT,
    model               TEXT,
    serial_number       TEXT,
    installed_year      INTEGER,
    replaced_year       INTEGER,
    condition           TEXT DEFAULT 'Good',            -- 'Excellent','Good','Fair','Poor','Critical'
    warranty_expiry     DATE,
    contractor          TEXT,
    contractor_phone    TEXT,
    annual_service_cost NUMERIC(10,2),
    last_service_date   DATE,
    next_service_date   DATE,
    last_inspection_date DATE,
    next_inspection_date DATE,
    units_count         INTEGER,
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS building_events (
    id                  SERIAL PRIMARY KEY,
    property_id         INTEGER REFERENCES properties(id) ON DELETE CASCADE,
    event_date          DATE NOT NULL,
    event_type          TEXT NOT NULL,                  -- 'milestone','renovation','maintenance','upgrade','inspection','incident'
    title               TEXT NOT NULL,
    detail              TEXT,
    cost                NUMERIC(12,2),
    vendor              TEXT,
    invoice_number      TEXT,
    insurance_claim     BOOLEAN DEFAULT FALSE,
    warranty_claim      BOOLEAN DEFAULT FALSE,
    document_url        TEXT,
    entered_by          TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS unit_appliances (
    id                  SERIAL PRIMARY KEY,
    unit_id             INTEGER REFERENCES units(id) ON DELETE CASCADE,
    appliance_type      TEXT NOT NULL,                  -- 'Refrigerator','Stove','Dishwasher','Washer','Dryer','AC','Microwave','Hood Fan'
    brand               TEXT,
    model               TEXT,
    serial_number       TEXT,
    installed_year      INTEGER,
    condition           TEXT DEFAULT 'Good',
    is_tenant_owned     BOOLEAN DEFAULT FALSE,
    warranty_expiry     DATE,
    last_service_date   DATE,
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- NEW: Unit Access Instructions
-- Critical for field tech dispatch — how to enter each unit
CREATE TABLE IF NOT EXISTS unit_access_instructions (
    id                  SERIAL PRIMARY KEY,
    unit_id             INTEGER UNIQUE REFERENCES units(id) ON DELETE CASCADE,
    -- Access method
    access_method       TEXT NOT NULL DEFAULT 'Authorized Entry',
                        -- 'Authorized Entry'    = 24hr notice, PM has key, can enter
                        -- 'Tenant Must Be Home' = must coordinate with tenant
                        -- 'Vacant - Free Access'= vacant unit, no restrictions
                        -- 'Lockbox'             = code on door
                        -- 'Building Super'      = go through building superintendent
    -- Entry details
    notice_required     TEXT DEFAULT '24 hours written notice (Ontario RTA)',
    key_location        TEXT,                           -- 'PM holds master key - Key #P3-M', 'Lockbox code: 4821', 'Tenant holds only key'
    lockbox_code        TEXT,                           -- Encrypted in prod, only shown to dispatched tech
    alarm_code          TEXT,                           -- Encrypted — only shown when needed
    has_alarm           BOOLEAN DEFAULT FALSE,
    -- Restrictions
    restrictions        TEXT,                           -- 'Dog in unit — crate required', 'Cats — advise tech', 'Tenant WFH Mon/Wed'
    access_hours        TEXT,                           -- '9am-5pm Mon-Fri', 'Any time', 'After 6pm only'
    -- Contact
    contact_name        TEXT,
    contact_phone       TEXT,
    -- Notes
    notes               TEXT,                           -- Internal PM notes about this unit's access
    -- Audit
    last_updated_by     TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ══════════════════════════════════════════════════════════════════
-- 4. WORK ORDER MANAGEMENT (3 tables)
-- COrtai-native intelligence on top of Buildium WO sync
-- ══════════════════════════════════════════════════════════════════

-- NEW: WO Scheduling & Assignment
-- Stores the tech, date, time, and dispatch notes per work order
CREATE TABLE IF NOT EXISTS wo_assignments (
    id                  SERIAL PRIMARY KEY,
    work_order_id       INTEGER UNIQUE REFERENCES work_orders(id) ON DELETE CASCADE,
    tech_id             INTEGER REFERENCES field_techs(id) ON DELETE SET NULL,
    scheduled_date      DATE NOT NULL,
    scheduled_time      TIME,                           -- e.g. 10:00:00
    time_slot_label     TEXT,                           -- '10:00', '14:00' (display)
    estimated_duration  INTEGER,                        -- minutes
    dispatch_notes      TEXT,                           -- Notes shown to tech: 'Dog in unit — crate first'
    actual_start        TIMESTAMPTZ,
    actual_end          TIMESTAMPTZ,
    actual_duration     INTEGER,                        -- minutes
    assignment_status   TEXT DEFAULT 'Scheduled',       -- 'Scheduled','In Progress','Completed','Cancelled','Rescheduled'
    assigned_by         TEXT,
    assigned_at         TIMESTAMPTZ DEFAULT NOW(),
    confirmed_by_tech   BOOLEAN DEFAULT FALSE,
    confirmed_at        TIMESTAMPTZ,
    -- Push to Buildium as WO note
    buildium_note_pushed BOOLEAN DEFAULT FALSE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS vendor_ratings (
    id                  SERIAL PRIMARY KEY,
    vendor_id           INTEGER REFERENCES vendors(id) ON DELETE CASCADE,
    work_order_id       INTEGER REFERENCES work_orders(id) ON DELETE SET NULL,
    rating              NUMERIC(2,1) NOT NULL,
    quality_score       NUMERIC(2,1),
    timeliness_score    NUMERIC(2,1),
    communication_score NUMERIC(2,1),
    value_score         NUMERIC(2,1),
    review_text         TEXT,
    reviewed_by         TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pm_notes (
    id                  SERIAL PRIMARY KEY,
    property_id         INTEGER REFERENCES properties(id) ON DELETE CASCADE,
    unit_id             INTEGER REFERENCES units(id) ON DELETE SET NULL,
    tenant_id           INTEGER REFERENCES tenants(id) ON DELETE SET NULL,
    work_order_id       INTEGER REFERENCES work_orders(id) ON DELETE SET NULL,
    note_type           TEXT DEFAULT 'General',         -- 'General','Action','Follow-up','Legal','Financial'
    priority            TEXT DEFAULT 'Normal',
    content             TEXT NOT NULL,
    is_resolved         BOOLEAN DEFAULT FALSE,
    resolved_at         TIMESTAMPTZ,
    due_date            DATE,
    created_by          TEXT,
    -- Push important notes to Buildium as lease/task notes
    push_to_buildium    BOOLEAN DEFAULT FALSE,
    buildium_note_id    INTEGER,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ══════════════════════════════════════════════════════════════════
-- 5. FIELD SERVICE MANAGEMENT (3 tables)
-- COrtai-native. Buildium has no field tech concept.
-- ══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS field_techs (
    id                  SERIAL PRIMARY KEY,
    first_name          TEXT NOT NULL,
    last_name           TEXT NOT NULL,
    role                TEXT,                           -- 'Senior Technician','HVAC Specialist','Electrician','General Maintenance'
    email               TEXT,
    phone               TEXT,
    hire_date           DATE,
    status              TEXT DEFAULT 'Available',       -- 'Available','On Site','In Transit','Off Duty','On Leave'
    skills              TEXT[],                         -- ['HVAC','Plumbing','Electrical']
    certifications      TEXT[],                         -- ['TSSA','ESA','313D Refrigeration']
    certification_expiry JSONB,                         -- {'TSSA': '2027-06-30', 'ESA': '2026-12-31'}
    hourly_rate         NUMERIC(8,2),
    is_active           BOOLEAN DEFAULT TRUE,
    current_property_id INTEGER REFERENCES properties(id) ON DELETE SET NULL,
    current_wo_id       INTEGER REFERENCES work_orders(id) ON DELETE SET NULL,
    avg_satisfaction    NUMERIC(3,2),
    avg_completion_min  INTEGER,
    avg_response_min    INTEGER,
    callback_rate_pct   NUMERIC(5,2),
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tech_tasks (
    id                  SERIAL PRIMARY KEY,
    tech_id             INTEGER REFERENCES field_techs(id) ON DELETE CASCADE,
    work_order_id       INTEGER REFERENCES work_orders(id) ON DELETE SET NULL,
    wo_assignment_id    INTEGER REFERENCES wo_assignments(id) ON DELETE SET NULL,
    property_id         INTEGER REFERENCES properties(id) ON DELETE SET NULL,
    unit_id             INTEGER REFERENCES units(id) ON DELETE SET NULL,
    task_name           TEXT NOT NULL,
    task_type           TEXT,                           -- 'Repair','Inspection','PM','Emergency','Dispatch'
    status              TEXT DEFAULT 'Scheduled',       -- 'Scheduled','In Transit','In Progress','Completed','Cancelled'
    scheduled_start     TIMESTAMPTZ,
    actual_start        TIMESTAMPTZ,
    actual_end          TIMESTAMPTZ,
    duration_minutes    INTEGER,
    travel_minutes      INTEGER,
    priority            TEXT DEFAULT 'Normal',
    notes               TEXT,
    tenant_present      BOOLEAN,
    parts_used          TEXT,
    parts_cost          NUMERIC(10,2) DEFAULT 0,
    labour_cost         NUMERIC(10,2) DEFAULT 0,
    satisfaction_rating NUMERIC(2,1),
    callback_required   BOOLEAN DEFAULT FALSE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tech_productivity_snapshots (
    id                  SERIAL PRIMARY KEY,
    tech_id             INTEGER REFERENCES field_techs(id) ON DELETE CASCADE,
    period_start        DATE NOT NULL,
    period_end          DATE NOT NULL,
    period_type         TEXT DEFAULT 'monthly',
    tasks_completed     INTEGER DEFAULT 0,
    tasks_total         INTEGER DEFAULT 0,
    avg_completion_min  INTEGER,
    avg_response_min    INTEGER,
    callback_count      INTEGER DEFAULT 0,
    callback_rate_pct   NUMERIC(5,2),
    total_labour_hours  NUMERIC(8,2),
    total_cost          NUMERIC(12,2),
    cost_per_task       NUMERIC(10,2),
    avg_satisfaction    NUMERIC(3,2),
    properties_visited  INTEGER DEFAULT 0,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tech_id, period_start, period_end)
);

-- ══════════════════════════════════════════════════════════════════
-- 6. OPEX & FINANCIAL INTELLIGENCE (4 tables)
-- COrtai-native analysis layer. OPEX actuals can push to Buildium bills.
-- ══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS opex_categories (
    id                  SERIAL PRIMARY KEY,
    name                TEXT UNIQUE NOT NULL,           -- 'hydro','gas','water','maintenance'
    display_name        TEXT,
    unit                TEXT,                           -- 'kWh','m3','CAD'
    utility_type        BOOLEAN DEFAULT FALSE,
    buildium_gl_account TEXT,                           -- Buildium GL account to map when pushing bills
    is_active           BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS opex_budgets (
    id                  SERIAL PRIMARY KEY,
    property_id         INTEGER REFERENCES properties(id) ON DELETE CASCADE,
    category_id         INTEGER REFERENCES opex_categories(id) ON DELETE CASCADE,
    budget_year         INTEGER NOT NULL,
    monthly_budget      NUMERIC(12,2) NOT NULL,
    annual_budget       NUMERIC(12,2) GENERATED ALWAYS AS (monthly_budget * 12) STORED,
    created_by          TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(property_id, category_id, budget_year)
);

CREATE TABLE IF NOT EXISTS opex_actuals (
    id                  SERIAL PRIMARY KEY,
    property_id         INTEGER REFERENCES properties(id) ON DELETE CASCADE,
    category_id         INTEGER REFERENCES opex_categories(id) ON DELETE CASCADE,
    billing_period      DATE NOT NULL,                  -- First day of month: 2026-04-01
    amount              NUMERIC(12,2) NOT NULL,
    usage_quantity      NUMERIC(12,3),
    usage_unit          TEXT,
    vendor              TEXT,
    invoice_number      TEXT,
    invoice_date        DATE,
    payment_date        DATE,
    payment_method      TEXT,
    is_estimated        BOOLEAN DEFAULT FALSE,
    notes               TEXT,
    -- Anomaly detection (populated by trigger)
    anomaly_flag        BOOLEAN DEFAULT FALSE,
    anomaly_severity    TEXT,                           -- 'warning','alert','critical'
    anomaly_pct_over    NUMERIC(7,2),
    anomaly_reason      TEXT,
    anomaly_resolved    BOOLEAN DEFAULT FALSE,
    -- Buildium sync
    buildium_bill_id    INTEGER REFERENCES buildium_bills(id) ON DELETE SET NULL,
    pushed_to_buildium  BOOLEAN DEFAULT FALSE,
    entered_by          TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(property_id, category_id, billing_period)
);

CREATE TABLE IF NOT EXISTS opex_anomalies (
    id                  SERIAL PRIMARY KEY,
    property_id         INTEGER REFERENCES properties(id) ON DELETE CASCADE,
    actual_id           INTEGER REFERENCES opex_actuals(id) ON DELETE CASCADE,
    category_id         INTEGER REFERENCES opex_categories(id),
    billing_period      DATE NOT NULL,
    budget_amount       NUMERIC(12,2),
    actual_amount       NUMERIC(12,2),
    variance_amount     NUMERIC(12,2),
    variance_pct        NUMERIC(7,2),
    severity            TEXT NOT NULL,
    baseline_3mo_avg    NUMERIC(12,2),
    anomaly_reason      TEXT,
    investigation_notes TEXT,
    work_order_id       INTEGER REFERENCES work_orders(id) ON DELETE SET NULL,
    is_resolved         BOOLEAN DEFAULT FALSE,
    resolved_at         TIMESTAMPTZ,
    resolved_by         TEXT,
    resolution_notes    TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ══════════════════════════════════════════════════════════════════
-- 7. IoT MONITORING (4 tables)
-- COrtai-native. Not in Buildium's data model.
-- IoT critical alerts can trigger WOs which then sync to Buildium.
-- ══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS iot_devices (
    id                  SERIAL PRIMARY KEY,
    device_code         TEXT UNIQUE NOT NULL,           -- 'IOT-P3-001'
    property_id         INTEGER REFERENCES properties(id) ON DELETE CASCADE,
    unit_id             INTEGER REFERENCES units(id) ON DELETE SET NULL,
    device_type         TEXT NOT NULL,                  -- 'VibrationSensor','AcousticSensor','SumpLevel','TempSensor','WaterLeak','CO','Pressure','Humidity','CurrentSensor'
    target_equipment    TEXT NOT NULL,                  -- 'Geothermal Compressor A'
    location            TEXT NOT NULL,                  -- 'Mechanical Room B1'
    manufacturer        TEXT,
    model               TEXT,
    firmware_version    TEXT,
    protocol            TEXT DEFAULT 'MQTT',            -- 'MQTT','Zigbee','Modbus','LoRa'
    ip_address          INET,
    mac_address         TEXT,
    installed_date      DATE,
    installed_by        TEXT,
    status              TEXT DEFAULT 'Online',          -- 'Online','Warning','Alert','Offline','Maintenance'
    is_active           BOOLEAN DEFAULT TRUE,
    threshold_warn      NUMERIC(12,4),
    threshold_critical  NUMERIC(12,4),
    reading_unit        TEXT,                           -- 'mm/s','dB','cm','°C','wet/dry'
    baseline_avg        NUMERIC(12,4),
    baseline_calc_date  DATE,
    last_reading        NUMERIC(12,4),
    last_reading_at     TIMESTAMPTZ,
    trend               TEXT DEFAULT 'stable',          -- 'stable','rising','rising_fast','falling','erratic'
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- High-volume table — partition by month in production
CREATE TABLE IF NOT EXISTS iot_readings (
    id                  BIGSERIAL,
    device_id           INTEGER REFERENCES iot_devices(id) ON DELETE CASCADE,
    reading_value       NUMERIC(12,4) NOT NULL,
    recorded_at         TIMESTAMPTZ DEFAULT NOW(),
    is_triggered        BOOLEAN,                        -- For binary sensors (leak detect)
    PRIMARY KEY (id, recorded_at)
) PARTITION BY RANGE (recorded_at);

-- Create current + next month partitions (add monthly via cron)
CREATE TABLE IF NOT EXISTS iot_readings_2026_04 PARTITION OF iot_readings
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
CREATE TABLE IF NOT EXISTS iot_readings_2026_05 PARTITION OF iot_readings
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
CREATE TABLE IF NOT EXISTS iot_readings_2026_06 PARTITION OF iot_readings
    FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');

CREATE TABLE IF NOT EXISTS iot_alerts (
    id                  SERIAL PRIMARY KEY,
    device_id           INTEGER REFERENCES iot_devices(id) ON DELETE CASCADE,
    property_id         INTEGER REFERENCES properties(id) ON DELETE CASCADE,
    alert_level         TEXT NOT NULL,                  -- 'info','warning','critical'
    alert_type          TEXT NOT NULL,                  -- 'threshold_exceeded','trend_anomaly','device_offline','sensor_fault'
    message             TEXT NOT NULL,
    reading_value       NUMERIC(12,4),
    threshold_triggered NUMERIC(12,4),
    status              TEXT DEFAULT 'Active',          -- 'Active','Acknowledged','Resolved','Suppressed'
    acknowledged_by     TEXT,
    acknowledged_at     TIMESTAMPTZ,
    resolved_at         TIMESTAMPTZ,
    work_order_id       INTEGER REFERENCES work_orders(id) ON DELETE SET NULL,
    auto_dispatched     BOOLEAN DEFAULT FALSE,
    triggered_at        TIMESTAMPTZ DEFAULT NOW(),
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS iot_alert_rules (
    id                  SERIAL PRIMARY KEY,
    device_type         TEXT,
    device_id           INTEGER REFERENCES iot_devices(id) ON DELETE CASCADE,
    rule_name           TEXT NOT NULL,
    condition_type      TEXT NOT NULL,                  -- 'above','below','change_rate','trend','pattern'
    condition_value     NUMERIC(12,4),
    condition_duration  INTEGER,                        -- seconds the condition must persist
    alert_level         TEXT NOT NULL,
    message_template    TEXT,
    auto_create_wo      BOOLEAN DEFAULT FALSE,
    wo_priority         TEXT DEFAULT 'High',
    wo_category         TEXT DEFAULT 'HVAC',
    notify_channels     TEXT[],                         -- ['email','sms','push','pager']
    notify_addresses    TEXT[],
    is_active           BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ══════════════════════════════════════════════════════════════════
-- 8. PLATFORM INFRASTRUCTURE (4 tables)
-- ══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS ai_alerts (
    id                  SERIAL PRIMARY KEY,
    property_id         INTEGER REFERENCES properties(id) ON DELETE CASCADE,
    unit_id             INTEGER REFERENCES units(id) ON DELETE SET NULL,
    tenant_id           INTEGER REFERENCES tenants(id) ON DELETE SET NULL,
    alert_type          TEXT NOT NULL,                  -- 'MaintenanceRisk','DelinquencyRisk','MarketOpportunity','ComplianceRequired','VacancyRisk'
    title               TEXT NOT NULL,
    analysis            TEXT NOT NULL,
    recommended_action  TEXT,
    confidence_pct      NUMERIC(5,2),
    priority            TEXT DEFAULT 'Normal',
    status              TEXT DEFAULT 'Active',          -- 'Active','Actioned','Dismissed','Expired'
    expires_at          TIMESTAMPTZ,
    generated_by        TEXT DEFAULT 'COrtai AI',
    actioned_by         TEXT,
    actioned_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sync_log (
    id                  SERIAL PRIMARY KEY,
    sync_type           TEXT NOT NULL,                  -- 'full','incremental','push','webhook'
    entity_type         TEXT NOT NULL,                  -- 'properties','units','tenants','work_orders','payments'
    entity_buildium_id  INTEGER,
    direction           TEXT NOT NULL,                  -- 'pull','push'
    status              TEXT NOT NULL,                  -- 'success','error','skipped','conflict'
    records_processed   INTEGER DEFAULT 0,
    records_created     INTEGER DEFAULT 0,
    records_updated     INTEGER DEFAULT 0,
    records_skipped     INTEGER DEFAULT 0,
    error_message       TEXT,
    conflict_detail     JSONB,
    duration_ms         INTEGER,
    triggered_by        TEXT DEFAULT 'scheduler',       -- 'scheduler','event','manual','webhook'
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS field_mappings (
    id                  SERIAL PRIMARY KEY,
    entity_type         TEXT NOT NULL,
    buildium_field      TEXT NOT NULL,
    cortai_table        TEXT NOT NULL,
    cortai_field        TEXT NOT NULL,
    transform_fn        TEXT,
    is_bidirectional    BOOLEAN DEFAULT FALSE,
    push_on_update      BOOLEAN DEFAULT FALSE,          -- Push to Buildium when this COrtai field changes
    is_active           BOOLEAN DEFAULT TRUE,
    notes               TEXT,
    UNIQUE(entity_type, buildium_field)
);

CREATE TABLE IF NOT EXISTS cortai_settings (
    key                 TEXT PRIMARY KEY,
    value               TEXT NOT NULL,
    description         TEXT,
    is_secret           BOOLEAN DEFAULT FALSE,          -- True = encrypt value at rest
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ══════════════════════════════════════════════════════════════════
-- INDEXES
-- ══════════════════════════════════════════════════════════════════

-- Properties & Units
CREATE INDEX IF NOT EXISTS idx_properties_buildium ON properties(buildium_id);
CREATE INDEX IF NOT EXISTS idx_properties_type ON properties(portfolio_type);
CREATE INDEX IF NOT EXISTS idx_properties_active ON properties(is_active) WHERE is_active=TRUE;
CREATE INDEX IF NOT EXISTS idx_units_property ON units(property_id);
CREATE INDEX IF NOT EXISTS idx_units_buildium ON units(buildium_id);

-- Tenants & Leases
CREATE INDEX IF NOT EXISTS idx_tenants_buildium ON tenants(buildium_id);
CREATE INDEX IF NOT EXISTS idx_tenants_name ON tenants(last_name, first_name);
CREATE INDEX IF NOT EXISTS idx_tenants_risk ON tenants(risk_score DESC) WHERE risk_score > 0;
CREATE INDEX IF NOT EXISTS idx_leases_buildium ON leases(buildium_id);
CREATE INDEX IF NOT EXISTS idx_leases_unit ON leases(unit_id);
CREATE INDEX IF NOT EXISTS idx_leases_status ON leases(lease_status);
CREATE INDEX IF NOT EXISTS idx_leases_expiring ON leases(end_date) WHERE is_active=TRUE;
CREATE INDEX IF NOT EXISTS idx_lease_residents_lease ON lease_residents(lease_id);
CREATE INDEX IF NOT EXISTS idx_lease_residents_tenant ON lease_residents(tenant_id);

-- Work Orders
CREATE INDEX IF NOT EXISTS idx_wo_property ON work_orders(property_id);
CREATE INDEX IF NOT EXISTS idx_wo_unit ON work_orders(unit_id);
CREATE INDEX IF NOT EXISTS idx_wo_status ON work_orders(status);
CREATE INDEX IF NOT EXISTS idx_wo_priority ON work_orders(priority);
CREATE INDEX IF NOT EXISTS idx_wo_sync ON work_orders(sync_status);
CREATE INDEX IF NOT EXISTS idx_wo_created ON work_orders(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_wo_assignments_wo ON wo_assignments(work_order_id);
CREATE INDEX IF NOT EXISTS idx_wo_assignments_tech ON wo_assignments(tech_id);
CREATE INDEX IF NOT EXISTS idx_wo_assignments_date ON wo_assignments(scheduled_date);

-- Payments
CREATE INDEX IF NOT EXISTS idx_payments_lease ON payments(lease_id);
CREATE INDEX IF NOT EXISTS idx_payments_tenant ON payments(tenant_id);
CREATE INDEX IF NOT EXISTS idx_payments_date ON payments(payment_date DESC);

-- Property intelligence
CREATE INDEX IF NOT EXISTS idx_systems_property ON building_systems(property_id);
CREATE INDEX IF NOT EXISTS idx_systems_type ON building_systems(system_type);
CREATE INDEX IF NOT EXISTS idx_events_property ON building_events(property_id);
CREATE INDEX IF NOT EXISTS idx_events_date ON building_events(event_date DESC);
CREATE INDEX IF NOT EXISTS idx_appliances_unit ON unit_appliances(unit_id);
CREATE INDEX IF NOT EXISTS idx_access_unit ON unit_access_instructions(unit_id);

-- Inspections
CREATE INDEX IF NOT EXISTS idx_inspections_unit ON inspections(unit_id);
CREATE INDEX IF NOT EXISTS idx_inspections_property ON inspections(property_id);
CREATE INDEX IF NOT EXISTS idx_inspection_items_insp ON inspection_items(inspection_id);

-- Tenant intelligence
CREATE INDEX IF NOT EXISTS idx_comms_tenant ON tenant_communications(tenant_id);
CREATE INDEX IF NOT EXISTS idx_comms_date ON tenant_communications(comm_date DESC);
CREATE INDEX IF NOT EXISTS idx_docs_tenant ON tenant_documents(tenant_id);
CREATE INDEX IF NOT EXISTS idx_unit_history_unit ON unit_tenant_history(unit_id);

-- Field techs
CREATE INDEX IF NOT EXISTS idx_tech_tasks_tech ON tech_tasks(tech_id);
CREATE INDEX IF NOT EXISTS idx_tech_tasks_wo ON tech_tasks(work_order_id);
CREATE INDEX IF NOT EXISTS idx_tech_tasks_scheduled ON tech_tasks(scheduled_start);

-- OPEX
CREATE INDEX IF NOT EXISTS idx_opex_actuals_prop ON opex_actuals(property_id);
CREATE INDEX IF NOT EXISTS idx_opex_actuals_period ON opex_actuals(billing_period DESC);
CREATE INDEX IF NOT EXISTS idx_opex_anomaly_flag ON opex_actuals(property_id, anomaly_flag) WHERE anomaly_flag=TRUE;
CREATE INDEX IF NOT EXISTS idx_opex_anomalies_prop ON opex_anomalies(property_id);
CREATE INDEX IF NOT EXISTS idx_opex_anomalies_unresolved ON opex_anomalies(is_resolved) WHERE is_resolved=FALSE;

-- IoT
CREATE INDEX IF NOT EXISTS idx_iot_devices_property ON iot_devices(property_id);
CREATE INDEX IF NOT EXISTS idx_iot_devices_status ON iot_devices(status);
CREATE INDEX IF NOT EXISTS idx_iot_readings_device ON iot_readings(device_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_iot_alerts_device ON iot_alerts(device_id);
CREATE INDEX IF NOT EXISTS idx_iot_alerts_active ON iot_alerts(status, property_id) WHERE status='Active';

-- AI & sync
CREATE INDEX IF NOT EXISTS idx_ai_property ON ai_alerts(property_id);
CREATE INDEX IF NOT EXISTS idx_ai_status ON ai_alerts(status) WHERE status='Active';
CREATE INDEX IF NOT EXISTS idx_sync_log_entity ON sync_log(entity_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sync_log_status ON sync_log(status);

-- ══════════════════════════════════════════════════════════════════
-- SEED DATA
-- ══════════════════════════════════════════════════════════════════

INSERT INTO opex_categories (name, display_name, unit, utility_type, buildium_gl_account) VALUES
    ('hydro',       'Hydro / Electricity',  'kWh', TRUE,  '6100 - Utilities - Electricity'),
    ('gas',         'Natural Gas',           'm3',  TRUE,  '6110 - Utilities - Gas'),
    ('water',       'Water / Sewer',         'm3',  TRUE,  '6120 - Utilities - Water'),
    ('maintenance', 'Maintenance / Repairs', 'CAD', FALSE, '6200 - Maintenance & Repairs'),
    ('insurance',   'Insurance',             'CAD', FALSE, '6300 - Insurance'),
    ('landscaping', 'Landscaping',           'CAD', FALSE, '6400 - Landscaping & Snow Removal'),
    ('management',  'Management Fee',        'CAD', FALSE, '6500 - Management Fees'),
    ('tax',         'Property Tax',          'CAD', FALSE, '6600 - Property Taxes'),
    ('other',       'Other Expenses',        'CAD', FALSE, '6900 - Other Expenses')
ON CONFLICT (name) DO NOTHING;

INSERT INTO cortai_settings (key, value, description, is_secret) VALUES
    ('buildium_api_base',       'https://api.buildium.com/v1',  'Buildium API base URL',                FALSE),
    ('buildium_client_id',      '',                              'Buildium OAuth client ID',             TRUE),
    ('buildium_client_secret',  '',                              'Buildium OAuth client secret',         TRUE),
    ('sync_interval_hours',     '4',                             'Buildium pull interval (hours)',        FALSE),
    ('sync_enabled',            'true',                          'Master Buildium sync switch',           FALSE),
    ('push_wo_to_buildium',     'true',                          'Push new WOs to Buildium as tasks',    FALSE),
    ('push_opex_bills',         'true',                          'Push utility bills to Buildium',       FALSE),
    ('push_vendor_updates',     'true',                          'Push new vendors to Buildium',         FALSE),
    ('push_wo_notes',           'true',                          'Push assignment notes to Buildium WO', FALSE),
    ('company_name',            'Lionston Group',                'Property management company',          FALSE),
    ('default_pm',              'Emma R.',                       'Default property manager',             FALSE),
    ('timezone',                'America/Toronto',               'Timezone for all dates',               FALSE),
    ('currency',                'CAD',                           'Currency code',                        FALSE),
    ('notice_period_hours',     '24',                            'Default notice period for unit entry', FALSE),
    ('iot_alert_email',         '',                              'Email for IoT critical alerts',        FALSE)
ON CONFLICT (key) DO NOTHING;

INSERT INTO field_mappings (entity_type, buildium_field, cortai_table, cortai_field, is_bidirectional, push_on_update) VALUES
    -- Properties (pull only)
    ('property','Id',               'properties','buildium_id',      FALSE,FALSE),
    ('property','Name',             'properties','name',             FALSE,FALSE),
    ('property','Address.Line1',    'properties','address',          FALSE,FALSE),
    ('property','Address.City',     'properties','city',             FALSE,FALSE),
    ('property','Address.PostalCode','properties','postal_code',     FALSE,FALSE),
    ('property','Structure',        'properties','structure_type',   FALSE,FALSE),
    ('property','YearBuilt',        'properties','year_built',       FALSE,FALSE),
    -- Units (pull only)
    ('unit','Id',                   'units','buildium_id',           FALSE,FALSE),
    ('unit','UnitNumber',           'units','unit_number',           FALSE,FALSE),
    ('unit','Bedrooms',             'units','beds',                  FALSE,FALSE),
    ('unit','Bathrooms',            'units','baths',                 FALSE,FALSE),
    ('unit','Area',                 'units','sqft',                  FALSE,FALSE),
    ('unit','MarketRent',           'units','market_rent',           FALSE,FALSE),
    -- Tenants (pull only)
    ('tenant','Id',                 'tenants','buildium_id',         FALSE,FALSE),
    ('tenant','FirstName',          'tenants','first_name',          FALSE,FALSE),
    ('tenant','LastName',           'tenants','last_name',           FALSE,FALSE),
    ('tenant','Email',              'tenants','email',               FALSE,FALSE),
    ('tenant','PhoneNumbers',       'tenants','phone',               FALSE,FALSE),
    -- Leases (pull only)
    ('lease','Id',                  'leases','buildium_id',          FALSE,FALSE),
    ('lease','LeaseType',           'leases','lease_type',           FALSE,FALSE),
    ('lease','LeaseStatus',         'leases','lease_status',         FALSE,FALSE),
    ('lease','Rent',                'leases','rent_amount',          FALSE,FALSE),
    ('lease','SecurityDeposit',     'leases','security_deposit',     FALSE,FALSE),
    ('lease','StartDate',           'leases','start_date',           FALSE,FALSE),
    ('lease','EndDate',             'leases','end_date',             FALSE,FALSE),
    -- Work Orders (bidirectional)
    ('workorder','Id',              'work_orders','buildium_task_id',FALSE,FALSE),
    ('workorder','Title',           'work_orders','title',           TRUE, FALSE),
    ('workorder','Description',     'work_orders','description',     TRUE, FALSE),
    ('workorder','TaskStatus',      'work_orders','status',          TRUE, TRUE),
    ('workorder','DueDate',         'work_orders','scheduled_date',  TRUE, FALSE),
    -- Vendors (bidirectional)
    ('vendor','Id',                 'vendors','buildium_id',         FALSE,FALSE),
    ('vendor','CompanyName',        'vendors','company_name',        TRUE, FALSE),
    ('vendor','Email',              'vendors','email',               TRUE, FALSE),
    ('vendor','PhoneNumbers',       'vendors','phone',               TRUE, FALSE)
ON CONFLICT (entity_type, buildium_field) DO NOTHING;


-- ══════════════════════════════════════════════════════════════════
-- DATABASE FUNCTIONS & TRIGGERS
-- ══════════════════════════════════════════════════════════════════

-- Auto-detect OPEX anomalies on bill entry
CREATE OR REPLACE FUNCTION check_opex_anomaly(p_actual_id INTEGER) RETURNS TEXT AS $$
DECLARE
    v_actual    opex_actuals%ROWTYPE;
    v_budget    NUMERIC;
    v_baseline  NUMERIC;
    v_variance  NUMERIC;
    v_severity  TEXT := NULL;
BEGIN
    SELECT * INTO v_actual FROM opex_actuals WHERE id = p_actual_id;
    SELECT ob.monthly_budget INTO v_budget FROM opex_budgets ob
    WHERE ob.property_id = v_actual.property_id AND ob.category_id = v_actual.category_id
      AND ob.budget_year = EXTRACT(YEAR FROM v_actual.billing_period);
    SELECT AVG(amount) INTO v_baseline FROM opex_actuals
    WHERE property_id = v_actual.property_id AND category_id = v_actual.category_id
      AND billing_period >= v_actual.billing_period - INTERVAL '3 months'
      AND billing_period < v_actual.billing_period;
    IF v_budget IS NOT NULL AND v_budget > 0 THEN
        v_variance := ((v_actual.amount - v_budget) / v_budget * 100);
        IF v_variance > 100 THEN v_severity := 'critical';
        ELSIF v_variance > 30  THEN v_severity := 'alert';
        ELSIF v_variance > 15  THEN v_severity := 'warning';
        END IF;
    END IF;
    IF v_severity IS NOT NULL THEN
        UPDATE opex_actuals SET anomaly_flag=TRUE, anomaly_severity=v_severity, anomaly_pct_over=v_variance WHERE id=p_actual_id;
        INSERT INTO opex_anomalies (property_id,actual_id,category_id,billing_period,budget_amount,actual_amount,variance_amount,variance_pct,severity,baseline_3mo_avg)
        VALUES (v_actual.property_id,p_actual_id,v_actual.category_id,v_actual.billing_period,v_budget,v_actual.amount,v_actual.amount-v_budget,v_variance,v_severity,v_baseline)
        ON CONFLICT DO NOTHING;
    END IF;
    RETURN v_severity;
END;
$$ LANGUAGE plpgsql;

-- Auto-trigger anomaly check
CREATE OR REPLACE FUNCTION trigger_opex_anomaly() RETURNS TRIGGER AS $$
BEGIN PERFORM check_opex_anomaly(NEW.id); RETURN NEW; END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS opex_anomaly_trigger ON opex_actuals;
CREATE TRIGGER opex_anomaly_trigger
    AFTER INSERT OR UPDATE OF amount ON opex_actuals
    FOR EACH ROW EXECUTE FUNCTION trigger_opex_anomaly();

-- Auto-create WO on critical IoT alert
CREATE OR REPLACE FUNCTION trigger_iot_wo() RETURNS TRIGGER AS $$
DECLARE v_rule iot_alert_rules%ROWTYPE; v_wo_id INTEGER;
BEGIN
    IF NEW.alert_level='critical' AND NEW.status='Active' THEN
        SELECT r.* INTO v_rule FROM iot_alert_rules r JOIN iot_devices d ON d.id=NEW.device_id
        WHERE (r.device_id=NEW.device_id OR r.device_type=d.device_type) AND r.auto_create_wo=TRUE AND r.is_active=TRUE LIMIT 1;
        IF FOUND THEN
            INSERT INTO work_orders (property_id,title,description,category,priority,status,submitted_source,sync_status)
            SELECT NEW.property_id,'IoT ALERT: '||d.target_equipment||' — '||d.device_type,NEW.message,
                   COALESCE(v_rule.wo_category,'HVAC'),v_rule.wo_priority,'Submitted','IoT Sensor','pending_push'
            FROM iot_devices d WHERE d.id=NEW.device_id
            RETURNING id INTO v_wo_id;
            UPDATE iot_alerts SET auto_dispatched=TRUE, work_order_id=v_wo_id WHERE id=NEW.id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS iot_wo_trigger ON iot_alerts;
CREATE TRIGGER iot_wo_trigger
    AFTER INSERT ON iot_alerts
    FOR EACH ROW EXECUTE FUNCTION trigger_iot_wo();

-- Auto-update tech status when WO assignment changes
CREATE OR REPLACE FUNCTION update_tech_status() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.assignment_status='In Progress' THEN
        UPDATE field_techs SET status='On Site', current_wo_id=NEW.work_order_id WHERE id=NEW.tech_id;
    ELSIF NEW.assignment_status IN ('Completed','Cancelled') THEN
        UPDATE field_techs SET status='Available', current_wo_id=NULL WHERE id=NEW.tech_id
          AND current_wo_id=NEW.work_order_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS tech_status_trigger ON wo_assignments;
CREATE TRIGGER tech_status_trigger
    AFTER UPDATE OF assignment_status ON wo_assignments
    FOR EACH ROW EXECUTE FUNCTION update_tech_status();
"""
