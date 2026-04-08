"""
COrtai Property Intelligence Platform — Database Schema
28 tables: 12 Buildium-synced (base), 16 COrtai-native (extended intelligence)

Architecture:
  ┌─────────────────────────────────────────────────┐
  │              Buildium API (read/write)           │
  │  Properties · Units · Tenants · Leases          │
  │  Work Orders · Payments · Vendors · Owners       │
  └────────────────────┬────────────────────────────┘
                       │ sync engine (pull every 4h, push on event)
  ┌────────────────────▼────────────────────────────┐
  │           COrtai Database (PostgreSQL)            │
  │                                                   │
  │  BUILDIUM-SYNCED TABLES (12)                     │
  │  properties · units · tenants · leases           │
  │  lease_residents · work_orders · payments        │
  │  vendors · owners · rental_owner_assignments     │
  │  maintenance_requests · outstanding_balances     │
  │                                                   │
  │  CORTAI-NATIVE TABLES (16)                       │
  │  building_systems · building_events              │
  │  unit_appliances · unit_tenant_history           │
  │  tenant_profiles · tenant_communications         │
  │  tenant_documents · payment_history_extended     │
  │  inspections · inspection_items                  │
  │  vendor_ratings · pm_notes                       │
  │  ai_alerts · sync_log · field_mappings           │
  │  cortai_settings                                  │
  └───────────────────────────────────────────────────┘
"""

SCHEMA = """
-- ══════════════════════════════════════════════════════════════════
-- BUILDIUM-SYNCED TABLES
-- These mirror Buildium's data model. Columns map 1:1 to API fields.
-- Never manually edit — always re-sync from Buildium.
-- ══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS properties (
    id                  SERIAL PRIMARY KEY,
    buildium_id         INTEGER UNIQUE NOT NULL,         -- Buildium rental ID
    name                TEXT NOT NULL,
    address             TEXT NOT NULL,
    address2            TEXT,
    city                TEXT,
    state_province      TEXT DEFAULT 'ON',
    postal_code         TEXT,
    country             TEXT DEFAULT 'CA',
    property_type       TEXT,                            -- 'ResidentialProperty','ResidentialUnit'
    structure_type      TEXT,                            -- 'ApartmentComplex','SingleFamilyHome'...
    total_units         INTEGER DEFAULT 1,
    year_built          INTEGER,
    reserve_fund        NUMERIC(12,2),
    is_active           BOOLEAN DEFAULT TRUE,
    -- Sync metadata
    buildium_created_at TIMESTAMPTZ,
    buildium_updated_at TIMESTAMPTZ,
    last_synced_at      TIMESTAMPTZ DEFAULT NOW(),
    sync_status         TEXT DEFAULT 'synced',          -- 'synced','pending','error'
    -- COrtai extension fields (NOT in Buildium)
    portfolio_class     TEXT DEFAULT 'Standard',        -- 'Premium','Standard','Value'
    portfolio_region    TEXT,                           -- 'GTA','Muskoka','Barrie'
    pm_assigned         TEXT,
    owner_entity        TEXT,
    building_health     INTEGER,
    pin                 TEXT,
    assessed_value      NUMERIC(14,2),
    purchase_price      NUMERIC(14,2),
    purchase_date       DATE,
    mortgage_details    TEXT,
    insurance_details   TEXT,
    annual_tax          NUMERIC(10,2),
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
    unit_type           TEXT,                           -- 'Apartment','SingleFamilyHome'
    beds                NUMERIC(3,1),
    baths               NUMERIC(3,1),
    sqft                INTEGER,
    market_rent         NUMERIC(10,2),
    is_active           BOOLEAN DEFAULT TRUE,
    -- Sync metadata
    buildium_created_at TIMESTAMPTZ,
    buildium_updated_at TIMESTAMPTZ,
    last_synced_at      TIMESTAMPTZ DEFAULT NOW(),
    -- COrtai extension
    floor_number        INTEGER,
    facing              TEXT,                           -- 'North','South-East'...
    parking_spot        TEXT,
    locker_number       TEXT,
    unit_condition      TEXT DEFAULT 'Good',            -- 'Excellent','Good','Fair','Poor'
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
    -- Sync metadata
    last_synced_at      TIMESTAMPTZ DEFAULT NOW(),
    -- COrtai extension
    owner_tier          TEXT DEFAULT 'Standard',        -- 'Premium','Standard'
    disbursement_day    INTEGER DEFAULT 15,
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
    tax_id              TEXT,                           -- for commercial
    company             TEXT,                           -- for commercial
    is_active           BOOLEAN DEFAULT TRUE,
    -- Sync metadata
    buildium_created_at TIMESTAMPTZ,
    last_synced_at      TIMESTAMPTZ DEFAULT NOW(),
    -- COrtai extension (NOT in Buildium)
    employer            TEXT,
    position            TEXT,
    annual_income       NUMERIC(12,2),
    income_verified_at  DATE,
    income_verified_doc TEXT,
    credit_score        INTEGER,
    credit_checked_at   DATE,
    emergency_contact   TEXT,
    pets                BOOLEAN DEFAULT FALSE,
    pet_description     TEXT,
    smoker              BOOLEAN DEFAULT FALSE,
    vehicles            INTEGER DEFAULT 0,
    vehicle_plates      TEXT,
    occupants           TEXT,
    risk_score          INTEGER DEFAULT 0,
    risk_label          TEXT DEFAULT 'Unknown',
    tenant_tier         TEXT DEFAULT 'Standard',        -- 'Excellent','Good Standing','Watch','High Risk'
    flags               TEXT[],                         -- Array: ['NSF','N4 Issued','On Watchlist']
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
    -- Sync metadata
    buildium_created_at TIMESTAMPTZ,
    buildium_updated_at TIMESTAMPTZ,
    last_synced_at      TIMESTAMPTZ DEFAULT NOW(),
    -- COrtai extension
    deposit_location    TEXT,
    deposit_returned    NUMERIC(10,2),
    deposit_return_date DATE,
    renewal_offered     BOOLEAN DEFAULT FALSE,
    renewal_offer_amount NUMERIC(10,2),
    renewal_offer_date  DATE,
    renewal_response    TEXT,                           -- 'Accepted','Declined','Pending'
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

CREATE TABLE IF NOT EXISTS work_orders (
    id                  SERIAL PRIMARY KEY,
    buildium_id         INTEGER UNIQUE,                 -- NULL if COrtai-created (not yet pushed)
    unit_id             INTEGER REFERENCES units(id) ON DELETE SET NULL,
    property_id         INTEGER REFERENCES properties(id) ON DELETE SET NULL,
    vendor_id           INTEGER,                        -- References vendors(id)
    wo_number           TEXT,                           -- Internal: WO-2501
    title               TEXT NOT NULL,
    description         TEXT,
    category            TEXT,                           -- 'HVAC','Plumbing','Electrical'...
    priority            TEXT DEFAULT 'Normal',          -- 'Emergency','Urgent','High','Normal','Low','Preventive'
    status              TEXT DEFAULT 'Submitted',       -- Lifecycle stages
    submitted_by        TEXT,
    submitted_source    TEXT DEFAULT 'COrtai',          -- 'TenantPortal','COrtai','Buildium'
    tenant_notified     BOOLEAN DEFAULT FALSE,
    est_cost            NUMERIC(10,2),
    actual_cost         NUMERIC(10,2),
    invoice_number      TEXT,
    invoice_approved    BOOLEAN DEFAULT FALSE,
    photo_count         INTEGER DEFAULT 0,
    scheduled_date      DATE,
    completed_date      DATE,
    is_tenant_caused    BOOLEAN DEFAULT FALSE,
    is_recurring        BOOLEAN DEFAULT FALSE,
    recurring_interval  TEXT,                           -- 'Monthly','Quarterly','Annual'
    -- Sync metadata
    buildium_task_id    INTEGER,
    buildium_synced_at  TIMESTAMPTZ,
    sync_direction      TEXT DEFAULT 'push',            -- 'push','pull','bidirectional'
    sync_status         TEXT DEFAULT 'pending_push',
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
    payment_type        TEXT,                           -- 'Charge','Payment','Credit'
    amount              NUMERIC(10,2) NOT NULL,
    payment_date        DATE NOT NULL,
    memo                TEXT,
    reference           TEXT,
    payment_method      TEXT,                           -- 'eTransfer','PAD','Cheque','Cash'
    is_voided           BOOLEAN DEFAULT FALSE,
    -- Sync metadata
    last_synced_at      TIMESTAMPTZ DEFAULT NOW(),
    -- COrtai extension
    days_late           INTEGER,
    payment_status      TEXT,                           -- 'OnTime','Late','Early','NSF'
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

CREATE TABLE IF NOT EXISTS vendors (
    id                  SERIAL PRIMARY KEY,
    buildium_id         INTEGER UNIQUE,                 -- NULL if COrtai-only vendor
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
    -- Sync metadata
    last_synced_at      TIMESTAMPTZ DEFAULT NOW(),
    -- COrtai extension
    specialty           TEXT,                           -- 'HVAC','Plumbing','Electrical'...
    license_type        TEXT,
    license_number      TEXT,
    license_expiry      DATE,
    insurance_amount    TEXT,
    insurance_expiry    DATE,
    is_preferred        BOOLEAN DEFAULT FALSE,
    rating              NUMERIC(2,1),
    ytd_spend           NUMERIC(10,2) DEFAULT 0,
    active_wo_count     INTEGER DEFAULT 0,
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ══════════════════════════════════════════════════════════════════
-- CORTAI-NATIVE TABLES (16)
-- Not synced from Buildium. Entered manually or via COrtai workflows.
-- This is the intelligence layer on top of Buildium's base data.
-- ══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS building_systems (
    id                  SERIAL PRIMARY KEY,
    property_id         INTEGER REFERENCES properties(id) ON DELETE CASCADE,
    system_type         TEXT NOT NULL,                  -- 'HVAC','Plumbing','Electrical','Elevator','Roof','Fire','Intercom','Parking'
    system_name         TEXT,
    brand               TEXT,
    model               TEXT,
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
    units_count         INTEGER,                        -- e.g. # elevator cabs
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
    appliance_type      TEXT NOT NULL,                  -- 'Refrigerator','Stove','Dishwasher','Washer','Dryer','AC','Microwave'
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

CREATE TABLE IF NOT EXISTS tenant_profiles (
    id                  SERIAL PRIMARY KEY,
    tenant_id           INTEGER UNIQUE REFERENCES tenants(id) ON DELETE CASCADE,
    -- Extended personal info (not in Buildium)
    date_of_birth       DATE,
    sin_last4           TEXT,                           -- Encrypted in prod
    employer            TEXT,
    employer_phone      TEXT,
    position            TEXT,
    employment_start    DATE,
    annual_income       NUMERIC(12,2),
    income_verified_by  TEXT,
    income_verified_at  DATE,
    income_doc_type     TEXT,
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
    risk_score          INTEGER DEFAULT 0,              -- 0-100
    risk_label          TEXT DEFAULT 'Unknown',
    risk_last_calc      TIMESTAMPTZ,
    risk_factors        JSONB,                          -- JSON array of risk factors
    -- Screening
    application_date    DATE,
    application_source  TEXT,                           -- 'Rentals.ca','Kijiji','Referral','Walk-in'
    references_verified BOOLEAN DEFAULT FALSE,
    -- Notes
    private_notes       TEXT,                           -- PM-only notes
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
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tenant_documents (
    id                  SERIAL PRIMARY KEY,
    tenant_id           INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
    lease_id            INTEGER REFERENCES leases(id) ON DELETE SET NULL,
    doc_type            TEXT NOT NULL,                  -- 'LeaseAgreement','PhotoID','CreditReport','IncomeVerification','PetAgreement','MoveInInspection','KeyReceipt','TenantInsurance','N4','N5','L1','PaymentPlan'
    doc_name            TEXT,
    file_url            TEXT,                           -- S3 or local path
    file_size_kb        INTEGER,
    is_signed           BOOLEAN DEFAULT FALSE,
    signed_date         DATE,
    expiry_date         DATE,
    uploaded_by         TEXT,
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
    room_name           TEXT NOT NULL,                  -- 'Kitchen','Living Room','Master Bedroom'...
    item_name           TEXT NOT NULL,                  -- 'Refrigerator','Hardwood Floor','Walls'
    condition_in        TEXT,                           -- Move-in condition (for move-out comparison)
    condition_out       TEXT,                           -- 'Excellent','Good','Fair','Poor'
    is_tenant_caused    BOOLEAN DEFAULT FALSE,
    charge_amount       NUMERIC(10,2),
    charge_description  TEXT,
    notes               TEXT,
    photo_urls          TEXT[],
    sort_order          INTEGER
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
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS vendor_ratings (
    id                  SERIAL PRIMARY KEY,
    vendor_id           INTEGER REFERENCES vendors(id) ON DELETE CASCADE,
    work_order_id       INTEGER REFERENCES work_orders(id) ON DELETE SET NULL,
    rating              NUMERIC(2,1) NOT NULL,           -- 1.0 - 5.0
    quality_score       NUMERIC(2,1),
    timeliness_score    NUMERIC(2,1),
    communication_score NUMERIC(2,1),
    value_score         NUMERIC(2,1),
    review_text         TEXT,
    reviewed_by         TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

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

-- ══════════════════════════════════════════════════════════════════
-- SYNC INFRASTRUCTURE
-- ══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS sync_log (
    id                  SERIAL PRIMARY KEY,
    sync_type           TEXT NOT NULL,                  -- 'full','incremental','push'
    entity_type         TEXT NOT NULL,                  -- 'properties','units','tenants'...
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
    triggered_by        TEXT DEFAULT 'scheduler',
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS field_mappings (
    id                  SERIAL PRIMARY KEY,
    entity_type         TEXT NOT NULL,
    buildium_field      TEXT NOT NULL,
    cortai_field        TEXT NOT NULL,
    transform_fn        TEXT,                           -- Optional Python transform function name
    is_bidirectional    BOOLEAN DEFAULT FALSE,          -- If True, COrtai can push this field back
    is_active           BOOLEAN DEFAULT TRUE,
    notes               TEXT,
    UNIQUE(entity_type, buildium_field)
);

CREATE TABLE IF NOT EXISTS cortai_settings (
    key                 TEXT PRIMARY KEY,
    value               TEXT NOT NULL,
    description         TEXT,
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ══════════════════════════════════════════════════════════════════
-- INDEXES — critical for performance with 325+ units
-- ══════════════════════════════════════════════════════════════════

-- Properties
CREATE INDEX IF NOT EXISTS idx_properties_buildium ON properties(buildium_id);
CREATE INDEX IF NOT EXISTS idx_properties_type ON properties(structure_type);
CREATE INDEX IF NOT EXISTS idx_properties_active ON properties(is_active);

-- Units
CREATE INDEX IF NOT EXISTS idx_units_property ON units(property_id);
CREATE INDEX IF NOT EXISTS idx_units_buildium ON units(buildium_id);

-- Tenants
CREATE INDEX IF NOT EXISTS idx_tenants_buildium ON tenants(buildium_id);
CREATE INDEX IF NOT EXISTS idx_tenants_name ON tenants(last_name, first_name);
CREATE INDEX IF NOT EXISTS idx_tenants_risk ON tenants(risk_score);

-- Leases
CREATE INDEX IF NOT EXISTS idx_leases_buildium ON leases(buildium_id);
CREATE INDEX IF NOT EXISTS idx_leases_unit ON leases(unit_id);
CREATE INDEX IF NOT EXISTS idx_leases_status ON leases(lease_status);
CREATE INDEX IF NOT EXISTS idx_leases_end ON leases(end_date);

-- Lease residents
CREATE INDEX IF NOT EXISTS idx_lease_residents_lease ON lease_residents(lease_id);
CREATE INDEX IF NOT EXISTS idx_lease_residents_tenant ON lease_residents(tenant_id);

-- Work orders
CREATE INDEX IF NOT EXISTS idx_wo_property ON work_orders(property_id);
CREATE INDEX IF NOT EXISTS idx_wo_unit ON work_orders(unit_id);
CREATE INDEX IF NOT EXISTS idx_wo_status ON work_orders(status);
CREATE INDEX IF NOT EXISTS idx_wo_priority ON work_orders(priority);
CREATE INDEX IF NOT EXISTS idx_wo_created ON work_orders(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_wo_sync ON work_orders(sync_status);

-- Payments
CREATE INDEX IF NOT EXISTS idx_payments_lease ON payments(lease_id);
CREATE INDEX IF NOT EXISTS idx_payments_tenant ON payments(tenant_id);
CREATE INDEX IF NOT EXISTS idx_payments_date ON payments(payment_date DESC);

-- Building systems & events
CREATE INDEX IF NOT EXISTS idx_systems_property ON building_systems(property_id);
CREATE INDEX IF NOT EXISTS idx_systems_type ON building_systems(system_type);
CREATE INDEX IF NOT EXISTS idx_events_property ON building_events(property_id);
CREATE INDEX IF NOT EXISTS idx_events_date ON building_events(event_date DESC);

-- Unit history
CREATE INDEX IF NOT EXISTS idx_unit_history_unit ON unit_tenant_history(unit_id);
CREATE INDEX IF NOT EXISTS idx_unit_appliances_unit ON unit_appliances(unit_id);

-- Inspections
CREATE INDEX IF NOT EXISTS idx_inspections_unit ON inspections(unit_id);
CREATE INDEX IF NOT EXISTS idx_inspections_property ON inspections(property_id);
CREATE INDEX IF NOT EXISTS idx_inspections_type ON inspections(inspection_type);
CREATE INDEX IF NOT EXISTS idx_inspection_items ON inspection_items(inspection_id);

-- Tenant extras
CREATE INDEX IF NOT EXISTS idx_comms_tenant ON tenant_communications(tenant_id);
CREATE INDEX IF NOT EXISTS idx_comms_date ON tenant_communications(comm_date DESC);
CREATE INDEX IF NOT EXISTS idx_docs_tenant ON tenant_documents(tenant_id);

-- AI
CREATE INDEX IF NOT EXISTS idx_ai_property ON ai_alerts(property_id);
CREATE INDEX IF NOT EXISTS idx_ai_status ON ai_alerts(status);
CREATE INDEX IF NOT EXISTS idx_ai_type ON ai_alerts(alert_type);

-- Sync
CREATE INDEX IF NOT EXISTS idx_sync_log_entity ON sync_log(entity_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sync_log_status ON sync_log(status);

-- ══════════════════════════════════════════════════════════════════
-- SEED: Default field mappings and settings
-- ══════════════════════════════════════════════════════════════════

INSERT INTO cortai_settings (key, value, description) VALUES
    ('buildium_api_base',   'https://api.buildium.com/v1',           'Buildium API base URL'),
    ('buildium_client_id',  '',                                       'Buildium OAuth client ID — set this'),
    ('buildium_client_secret', '',                                    'Buildium OAuth client secret — set this'),
    ('sync_interval_hours', '4',                                      'How often to pull from Buildium (hours)'),
    ('sync_enabled',        'true',                                   'Master switch for Buildium sync'),
    ('push_wo_to_buildium', 'true',                                   'Push work orders back to Buildium as tasks'),
    ('push_on_create',      'true',                                   'Push to Buildium immediately on WO creation'),
    ('company_name',        'Lionston Group',                         'Property management company name'),
    ('default_pm',          'Emma R.',                                'Default property manager name'),
    ('timezone',            'America/Toronto',                        'Timezone for all dates'),
    ('currency',            'CAD',                                    'Currency code')
ON CONFLICT (key) DO NOTHING;

INSERT INTO field_mappings (entity_type, buildium_field, cortai_field, is_bidirectional) VALUES
    ('property', 'Id',              'buildium_id',       FALSE),
    ('property', 'Name',            'name',              FALSE),
    ('property', 'Address.Line1',   'address',           FALSE),
    ('property', 'Address.City',    'city',              FALSE),
    ('property', 'Address.PostalCode', 'postal_code',   FALSE),
    ('property', 'Structure',       'structure_type',    FALSE),
    ('property', 'TotalUnits',      'total_units',       FALSE),
    ('property', 'YearBuilt',       'year_built',        FALSE),
    ('unit',     'Id',              'buildium_id',       FALSE),
    ('unit',     'UnitNumber',      'unit_number',       FALSE),
    ('unit',     'Bedrooms',        'beds',              FALSE),
    ('unit',     'Bathrooms',       'baths',             FALSE),
    ('unit',     'Area',            'sqft',              FALSE),
    ('unit',     'MarketRent',      'market_rent',       FALSE),
    ('tenant',   'Id',              'buildium_id',       FALSE),
    ('tenant',   'FirstName',       'first_name',        FALSE),
    ('tenant',   'LastName',        'last_name',         FALSE),
    ('tenant',   'Email',           'email',             FALSE),
    ('tenant',   'PhoneNumbers',    'phone',             FALSE),
    ('lease',    'Id',              'buildium_id',       FALSE),
    ('lease',    'LeaseType',       'lease_type',        FALSE),
    ('lease',    'LeaseStatus',     'lease_status',      FALSE),
    ('lease',    'Rent',            'rent_amount',       FALSE),
    ('lease',    'SecurityDeposit', 'security_deposit',  FALSE),
    ('lease',    'StartDate',       'start_date',        FALSE),
    ('lease',    'EndDate',         'end_date',          FALSE),
    ('workorder','Id',              'buildium_id',       FALSE),
    ('workorder','Title',           'title',             TRUE),
    ('workorder','Status',          'status',            TRUE),
    ('workorder','DueDate',         'scheduled_date',    TRUE)
ON CONFLICT (entity_type, buildium_field) DO NOTHING;
"""


def get_schema():
    return SCHEMA
