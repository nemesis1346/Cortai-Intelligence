"""
schema_v3.py — COrtai Property Intelligence Platform
Schema additions — run AFTER schema_v2.py

New tables (16): brings total from 43 → 59 tables

  Landlord Management (1):  landlord_profiles
  PM Scheduler (2):         pm_schedules, pm_completions
  COI Tracker (1):          vendor_coi
  LTB Forms (1):            ltb_forms
  Move Calendar (2):        move_events, elevator_bookings
  Inspection Detail (4):    inspection_scheduled, inspection_room_results,
                             inspection_appliance_results, inspection_safety_checks,
                             inspection_keys_issued
  AI / ML Layer (5):        ml_predictions, tenant_risk_history,
                             equipment_failure_predictions, rent_recommendations,
                             nlq_query_log

Existing table changes (ALTER TABLE):
  vendors     — add: coi_status computed from vendor_coi
  inspections — add: inspection_subtype, season (for drive-by), signed_tenant
  cortai_settings — seed new keys for AI/ML config
"""

SCHEMA_V3 = """

-- ══════════════════════════════════════════════════════════════════
-- 1. LANDLORD MANAGEMENT
-- Extended owner profiles beyond Buildium's basic owner fields.
-- One row per ownership entity managing properties through Lionston.
-- ══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS landlord_profiles (
    id                  SERIAL PRIMARY KEY,
    owner_id            INTEGER UNIQUE REFERENCES owners(id) ON DELETE CASCADE,
    -- Identity
    entity_name         TEXT NOT NULL,                 -- 'Singh Holdings Corp.'
    entity_type         TEXT,                          -- 'Corporate','Family Office','Family Trust','Private Investor','Individual'
    short_name          TEXT,                          -- 'Singh' — used in UI filters
    initials            TEXT,                          -- 'SH' — used in avatar tiles
    brand_color         TEXT,                          -- CSS color for UI differentiation
    -- Primary contact (may differ from Buildium owner record)
    contact_name        TEXT,
    contact_title       TEXT,
    contact_phone       TEXT,
    contact_email       TEXT,
    -- Secondary contact
    alt_contact_name    TEXT,
    alt_contact_phone   TEXT,
    alt_contact_email   TEXT,
    -- Banking & disbursement
    bank_name           TEXT,
    bank_account        TEXT,                          -- Encrypted at rest
    disbursement_day    INTEGER DEFAULT 15,            -- Day of month to disburse
    disbursement_method TEXT DEFAULT 'EFT',            -- 'EFT','Cheque','Wire'
    -- Reporting preferences
    report_frequency    TEXT DEFAULT 'Monthly',        -- 'Monthly','Quarterly','OnDemand'
    report_recipients   TEXT[],                        -- Additional email addresses
    preferred_language  TEXT DEFAULT 'English',
    -- Relationship
    client_since        DATE,
    account_manager     TEXT,                          -- COrtai/Lionston PM assigned
    contract_url        TEXT,                          -- Management agreement document
    management_fee_pct  NUMERIC(5,3),                 -- e.g. 8.500 = 8.5%
    -- Notes
    internal_notes      TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ══════════════════════════════════════════════════════════════════
-- 2. PREVENTIVE MAINTENANCE SCHEDULER
-- ══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS pm_schedules (
    id                  SERIAL PRIMARY KEY,
    property_id         INTEGER REFERENCES properties(id) ON DELETE CASCADE,
    building_system_id  INTEGER REFERENCES building_systems(id) ON DELETE SET NULL,
    -- Task definition
    task_name           TEXT NOT NULL,                 -- 'Geothermal Filter & Coil Cleaning'
    system_type         TEXT NOT NULL,                 -- 'HVAC','Boiler','Elevator','Fire','Roof','Pest','Electrical','Plumbing'
    description         TEXT,
    -- Schedule
    interval_months     INTEGER,                       -- NULL = one-time task
    last_done_date      DATE,
    next_due_date       DATE,
    overdue_days        INTEGER GENERATED ALWAYS AS (
                            CASE WHEN next_due_date < CURRENT_DATE
                            THEN (CURRENT_DATE - next_due_date)::INTEGER
                            ELSE 0 END
                        ) STORED,
    -- Assignment
    preferred_vendor_id INTEGER REFERENCES vendors(id) ON DELETE SET NULL,
    preferred_vendor_name TEXT,                        -- Denormalized for display when no FK
    preferred_tech_id   INTEGER REFERENCES field_techs(id) ON DELETE SET NULL,
    -- Estimates
    est_cost            NUMERIC(10,2),
    est_hours           NUMERIC(6,2),
    priority            TEXT DEFAULT 'Normal',         -- 'Emergency','High','Normal','Low'
    -- Auto WO
    auto_create_wo      BOOLEAN DEFAULT TRUE,
    wo_category         TEXT DEFAULT 'HVAC',
    wo_description      TEXT,                          -- Template for auto-created WO description
    -- Status
    status              TEXT DEFAULT 'upcoming',       -- 'overdue','due_soon','upcoming','completed','paused'
    is_active           BOOLEAN DEFAULT TRUE,
    -- Notes
    notes               TEXT,
    created_by          TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pm_completions (
    id                  SERIAL PRIMARY KEY,
    schedule_id         INTEGER REFERENCES pm_schedules(id) ON DELETE CASCADE,
    property_id         INTEGER REFERENCES properties(id) ON DELETE CASCADE,
    work_order_id       INTEGER REFERENCES work_orders(id) ON DELETE SET NULL,
    completed_date      DATE NOT NULL,
    completed_by        TEXT,                          -- Tech or vendor name
    vendor_id           INTEGER REFERENCES vendors(id) ON DELETE SET NULL,
    actual_cost         NUMERIC(10,2),
    actual_hours        NUMERIC(6,2),
    result              TEXT DEFAULT 'Pass',           -- 'Pass','Conditional','Fail'
    next_due_set        DATE,                          -- Next due date set after this completion
    notes               TEXT,
    invoice_number      TEXT,
    invoice_url         TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Auto-update pm_schedules when a completion is recorded
CREATE OR REPLACE FUNCTION update_pm_schedule_on_completion() RETURNS TRIGGER AS $$
BEGIN
    UPDATE pm_schedules
    SET last_done_date = NEW.completed_date,
        next_due_date  = NEW.next_due_set,
        status         = CASE
                            WHEN NEW.next_due_set IS NULL THEN 'completed'
                            WHEN NEW.next_due_set > CURRENT_DATE THEN 'upcoming'
                            ELSE 'due_soon'
                         END,
        updated_at     = NOW()
    WHERE id = NEW.schedule_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS pm_completion_trigger ON pm_completions;
CREATE TRIGGER pm_completion_trigger
    AFTER INSERT ON pm_completions
    FOR EACH ROW EXECUTE FUNCTION update_pm_schedule_on_completion();


-- ══════════════════════════════════════════════════════════════════
-- 3. VENDOR COI TRACKER
-- Certificate of Insurance — replaces the basic fields on vendors
-- table with a full COI record that can be versioned over time.
-- ══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS vendor_coi (
    id                  SERIAL PRIMARY KEY,
    vendor_id           INTEGER UNIQUE REFERENCES vendors(id) ON DELETE CASCADE,
    -- Insurer & policy
    insurer_name        TEXT,                          -- 'Intact Insurance'
    policy_number       TEXT,                          -- 'INT-2024-88201'
    coverage_type       TEXT DEFAULT 'Commercial General Liability',
    coverage_amount     NUMERIC(14,2),                 -- 5000000.00 = $5M
    coverage_amount_fmt TEXT,                          -- '$5,000,000' — display
    -- Dates
    effective_date      DATE,
    expiry_date         DATE,
    -- Status (auto-computed — update via trigger or nightly job)
    status              TEXT DEFAULT 'missing',        -- 'valid','expiring_soon','expired','missing'
    days_until_expiry   INTEGER GENERATED ALWAYS AS (
                            CASE WHEN expiry_date IS NOT NULL
                            THEN (expiry_date - CURRENT_DATE)::INTEGER
                            ELSE NULL END
                        ) STORED,
    -- Verification
    verified_by         TEXT,
    verified_date       DATE,
    document_url        TEXT,                          -- S3 URL to COI PDF
    document_filename   TEXT,
    -- Blocking
    dispatch_blocked    BOOLEAN GENERATED ALWAYS AS (
                            status IN ('expired','missing')
                        ) STORED,
    -- Notifications
    renewal_reminder_sent BOOLEAN DEFAULT FALSE,
    renewal_reminder_at TIMESTAMPTZ,
    -- Notes
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Nightly: refresh status based on current date
CREATE OR REPLACE FUNCTION refresh_coi_status() RETURNS void AS $$
BEGIN
    UPDATE vendor_coi SET
        status = CASE
            WHEN expiry_date IS NULL            THEN 'missing'
            WHEN expiry_date < CURRENT_DATE     THEN 'expired'
            WHEN expiry_date < CURRENT_DATE + 30 THEN 'expiring_soon'
            ELSE 'valid'
        END,
        updated_at = NOW();
END;
$$ LANGUAGE plpgsql;


-- ══════════════════════════════════════════════════════════════════
-- 4. ONTARIO LTB FORM GENERATOR
-- Tracks every generated notice — N1, N4, N5, N8, N12
-- ══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS ltb_forms (
    id                  SERIAL PRIMARY KEY,
    form_type           TEXT NOT NULL,                 -- 'N1','N4','N5','N8','N12'
    property_id         INTEGER REFERENCES properties(id) ON DELETE SET NULL,
    unit_id             INTEGER REFERENCES units(id) ON DELETE SET NULL,
    lease_id            INTEGER REFERENCES leases(id) ON DELETE SET NULL,
    tenant_id           INTEGER REFERENCES tenants(id) ON DELETE SET NULL,
    -- N1-specific
    current_rent        NUMERIC(10,2),
    new_rent            NUMERIC(10,2),
    rent_increase_pct   NUMERIC(5,3),
    effective_date      DATE,                          -- Date new rent takes effect
    notice_served_date  DATE,
    -- N4-specific
    arrears_amount      NUMERIC(10,2),
    arrears_periods     JSONB,                         -- [{"month":"March 2026","charged":2480,"paid":0,"owing":2480}]
    termination_date    DATE,                          -- 14 days from service
    -- N5-specific
    violation_type      TEXT[],                        -- ['interference','damage','overcrowding']
    incident_date       DATE,
    incident_description TEXT,
    void_period_days    INTEGER DEFAULT 7,             -- Tenant has 7 days to remedy
    is_second_notice    BOOLEAN DEFAULT FALSE,
    -- Common
    generated_date      DATE DEFAULT CURRENT_DATE,
    generated_by        TEXT,
    pdf_url             TEXT,                          -- S3 URL once rendered
    status              TEXT DEFAULT 'draft',          -- 'draft','printed','served','filed_ltb','resolved','voided'
    served_date         DATE,
    served_method       TEXT,                          -- 'InPerson','Mail','Courier','Portal'
    -- Tracking
    ltb_application_id  TEXT,                          -- L1/L2 file number if filed
    ltb_hearing_date    DATE,
    ltb_outcome         TEXT,
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);


-- ══════════════════════════════════════════════════════════════════
-- 5. MOVE-IN / MOVE-OUT CALENDAR
-- ══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS move_events (
    id                  SERIAL PRIMARY KEY,
    property_id         INTEGER REFERENCES properties(id) ON DELETE CASCADE,
    unit_id             INTEGER REFERENCES units(id) ON DELETE SET NULL,
    lease_id            INTEGER REFERENCES leases(id) ON DELETE SET NULL,
    tenant_id           INTEGER REFERENCES tenants(id) ON DELETE SET NULL,
    -- Event type & date
    event_type          TEXT NOT NULL,                 -- 'move_in','move_out','inspection','key_handover'
    event_date          DATE NOT NULL,
    -- Move-out specific
    move_out_reason     TEXT,                          -- 'Not renewing','N4 eviction','Mutual agreement','N12'
    damage_expected     BOOLEAN DEFAULT FALSE,
    deposit_held        NUMERIC(10,2),
    deposit_returned    NUMERIC(10,2),
    deposit_return_date DATE,
    -- Move-in specific
    keys_issued         JSONB,                         -- {"suite":2,"mailbox":1,"fob":2,"parking_fob":1}
    -- Coordination
    inspector           TEXT,
    inspection_date     DATE,
    inspection_id       INTEGER REFERENCES inspections(id) ON DELETE SET NULL,
    assigned_tech_id    INTEGER REFERENCES field_techs(id) ON DELETE SET NULL,
    -- Status
    status              TEXT DEFAULT 'planning',       -- 'planning','scheduled','confirmed','completed','cancelled'
    notes               TEXT,
    created_by          TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS elevator_bookings (
    id                  SERIAL PRIMARY KEY,
    property_id         INTEGER REFERENCES properties(id) ON DELETE CASCADE,
    move_event_id       INTEGER REFERENCES move_events(id) ON DELETE CASCADE,
    booking_date        DATE NOT NULL,
    start_time          TIME NOT NULL,                 -- '09:00'
    end_time            TIME NOT NULL,                 -- '13:00'
    booked_by           TEXT,                          -- Tenant name or PM name
    elevator_number     INTEGER DEFAULT 1,
    deposit_required    NUMERIC(8,2),
    deposit_paid        BOOLEAN DEFAULT FALSE,
    deposit_returned    BOOLEAN DEFAULT FALSE,
    status              TEXT DEFAULT 'confirmed',      -- 'confirmed','cancelled','completed'
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(property_id, booking_date, start_time, elevator_number)
);


-- ══════════════════════════════════════════════════════════════════
-- 6. INSPECTION DETAIL TABLES
-- The existing `inspections` table stores the header record.
-- These tables store line-item results per room, appliance, and
-- safety check — enabling full audit trail and trend analysis.
-- ══════════════════════════════════════════════════════════════════

-- Alter existing inspections table to support new fields
ALTER TABLE inspections
    ADD COLUMN IF NOT EXISTS inspection_subtype TEXT,   -- 'Spring','Fall','Summer','Winter','General' (for drive-by)
    ADD COLUMN IF NOT EXISTS season             TEXT,   -- 'Spring','Fall','Summer','Winter'
    ADD COLUMN IF NOT EXISTS move_event_id      INTEGER REFERENCES move_events(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS signed_tenant      BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS signed_landlord    BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS keys_returned      JSONB,  -- {"suite":2,"mailbox":1,"fob":2} — move-out
    ADD COLUMN IF NOT EXISTS pdf_url            TEXT;   -- S3 URL of completed inspection PDF

CREATE TABLE IF NOT EXISTS inspection_scheduled (
    id                  SERIAL PRIMARY KEY,
    inspection_id       INTEGER REFERENCES inspections(id) ON DELETE CASCADE,
    property_id         INTEGER REFERENCES properties(id) ON DELETE CASCADE,
    unit_id             INTEGER REFERENCES units(id) ON DELETE SET NULL,
    lease_id            INTEGER REFERENCES leases(id) ON DELETE SET NULL,
    inspection_type     TEXT NOT NULL,
    scheduled_date      DATE NOT NULL,
    inspector           TEXT,
    tenant_name         TEXT,
    tenant_phone        TEXT,
    notice_sent         BOOLEAN DEFAULT FALSE,
    notice_sent_at      TIMESTAMPTZ,
    notice_method       TEXT,                          -- 'Email','Portal','InPerson','Mail'
    elevator_required   BOOLEAN DEFAULT FALSE,
    elevator_booking_id INTEGER REFERENCES elevator_bookings(id) ON DELETE SET NULL,
    status              TEXT DEFAULT 'Scheduled',      -- 'Scheduled','Confirmed','Pending Confirm','Completed','Cancelled'
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS inspection_room_results (
    id                  SERIAL PRIMARY KEY,
    inspection_id       INTEGER REFERENCES inspections(id) ON DELETE CASCADE,
    room_key            TEXT NOT NULL,                 -- 'entry','living','kitchen','bedroom1','bath1','balcony'
    room_label          TEXT NOT NULL,                 -- 'Entry / Hallway','Living Room'
    item_name           TEXT NOT NULL,                 -- 'Flooring','Walls & Paint','Windows & Blinds'
    condition_rating    TEXT,                          -- 'Excellent','Good','Fair','Poor','N/A'
    is_issue            BOOLEAN GENERATED ALWAYS AS (
                            condition_rating IN ('Fair','Poor')
                        ) STORED,
    notes               TEXT,
    -- Move-out specific: compare to move-in
    move_in_condition   TEXT,                          -- Condition at move-in (pulled from prior inspection)
    damage_type         TEXT,                          -- 'Normal Wear','Tenant Damage','Pre-existing'
    charge_amount       NUMERIC(10,2),                 -- Deposit deduction if tenant damage
    photo_urls          TEXT[],
    sort_order          INTEGER DEFAULT 0,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS inspection_appliance_results (
    id                  SERIAL PRIMARY KEY,
    inspection_id       INTEGER REFERENCES inspections(id) ON DELETE CASCADE,
    appliance_type      TEXT NOT NULL,                 -- 'Refrigerator','Stove','Dishwasher'
    make_model          TEXT,
    serial_number       TEXT,
    condition_rating    TEXT,                          -- 'Excellent','Good','Fair','Poor','N/A'
    is_issue            BOOLEAN GENERATED ALWAYS AS (
                            condition_rating IN ('Fair','Poor')
                        ) STORED,
    notes               TEXT,
    move_in_condition   TEXT,
    damage_type         TEXT,
    charge_amount       NUMERIC(10,2),
    photo_urls          TEXT[],
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS inspection_safety_checks (
    id                  SERIAL PRIMARY KEY,
    inspection_id       INTEGER REFERENCES inspections(id) ON DELETE CASCADE,
    check_type          TEXT NOT NULL,                 -- 'smoke_detector','co_detector','hvac_filter','fire_extinguisher'
    check_label         TEXT NOT NULL,
    result              TEXT NOT NULL,                 -- 'Pass','Fail','N/A','Replaced'
    tested_date         DATE DEFAULT CURRENT_DATE,
    next_test_date      DATE,
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS inspection_keys_issued (
    id                  SERIAL PRIMARY KEY,
    inspection_id       INTEGER REFERENCES inspections(id) ON DELETE CASCADE,
    move_event_id       INTEGER REFERENCES move_events(id) ON DELETE SET NULL,
    key_type            TEXT NOT NULL,                 -- 'suite','mailbox','fob','parking_fob','locker','visitor_pass'
    quantity            INTEGER NOT NULL DEFAULT 0,
    returned_quantity   INTEGER DEFAULT 0,             -- Populated on move-out
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);


-- ══════════════════════════════════════════════════════════════════
-- 7. AI / ML LAYER
-- Stores model outputs, predictions, and query logs.
-- Models are trained externally (Python scikit-learn / XGBoost /
-- LightGBM) and predictions written here via API.
-- ══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS ml_predictions (
    id                  SERIAL PRIMARY KEY,
    model_name          TEXT NOT NULL,                 -- 'tenant_delinquency_v1','maint_failure_v2','rent_opt_v1'
    model_version       TEXT DEFAULT 'v1',
    entity_type         TEXT NOT NULL,                 -- 'tenant','equipment','unit','property'
    entity_id           INTEGER NOT NULL,              -- FK to relevant entity (tenant.id, building_system.id, unit.id)
    -- Prediction output
    prediction_label    TEXT,                          -- 'high_risk','failure_likely','below_market'
    prediction_score    NUMERIC(6,4),                  -- 0.0000 – 1.0000 probability
    confidence          NUMERIC(6,4),                  -- Model confidence in this prediction
    -- Feature importance (top 5 contributing factors)
    feature_importance  JSONB,                         -- {"days_since_last_payment":0.42,"nsf_count":0.28,...}
    raw_features        JSONB,                         -- Full feature vector at prediction time
    -- Recommendation
    recommended_action  TEXT,
    urgency             TEXT,                          -- 'immediate','this_week','this_month','monitor'
    -- Lifecycle
    predicted_at        TIMESTAMPTZ DEFAULT NOW(),
    expires_at          TIMESTAMPTZ,                   -- Prediction is stale after this
    actioned_by         TEXT,
    actioned_at         TIMESTAMPTZ,
    actioned_result     TEXT,
    is_active           BOOLEAN DEFAULT TRUE,
    -- Feedback for retraining
    was_correct         BOOLEAN,                       -- Filled in after outcome is known
    actual_outcome      TEXT,
    outcome_recorded_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS tenant_risk_history (
    id                  SERIAL PRIMARY KEY,
    tenant_id           INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
    lease_id            INTEGER REFERENCES leases(id) ON DELETE SET NULL,
    -- Score at this point in time
    risk_score          INTEGER NOT NULL,              -- 0 (no risk) – 100 (critical)
    risk_label          TEXT NOT NULL,                 -- 'Low','Medium','High','Critical'
    -- Feature values at scoring time
    days_in_arrears     INTEGER DEFAULT 0,
    nsf_count           INTEGER DEFAULT 0,
    late_payment_count  INTEGER DEFAULT 0,
    active_n_forms      INTEGER DEFAULT 0,
    open_wos_caused     INTEGER DEFAULT 0,
    months_tenanted     INTEGER DEFAULT 0,
    communication_flag  BOOLEAN DEFAULT FALSE,
    -- Derived
    score_delta         INTEGER,                       -- Change from previous score (+ = worsening)
    scored_at           TIMESTAMPTZ DEFAULT NOW(),
    scored_by           TEXT DEFAULT 'COrtai ML Engine'
);

CREATE TABLE IF NOT EXISTS equipment_failure_predictions (
    id                  SERIAL PRIMARY KEY,
    building_system_id  INTEGER REFERENCES building_systems(id) ON DELETE CASCADE,
    property_id         INTEGER REFERENCES properties(id) ON DELETE CASCADE,
    -- Prediction
    failure_probability NUMERIC(5,4) NOT NULL,         -- 0.0000 – 1.0000
    failure_horizon_days INTEGER,                      -- Predicted days until failure
    failure_horizon_label TEXT,                        -- '30 days','90 days','6 months','12 months'
    severity            TEXT,                          -- 'Minor','Major','Critical','Catastrophic'
    estimated_repair_cost NUMERIC(12,2),
    estimated_replacement_cost NUMERIC(12,2),
    -- Contributing factors
    equipment_age_years INTEGER,
    last_service_days_ago INTEGER,
    iot_anomaly_score   NUMERIC(5,4),                  -- From IoT sensor data
    similar_failures_nearby INTEGER,                   -- Same equipment type in portfolio
    feature_importance  JSONB,
    -- Recommendation
    recommendation      TEXT,                          -- 'Schedule immediate inspection','Budget replacement Q3 2026'
    recommended_action  TEXT,                          -- 'inspect','service','replace','monitor'
    recommended_by      DATE,                          -- Do this by when
    -- Tracking
    predicted_at        TIMESTAMPTZ DEFAULT NOW(),
    pm_schedule_id      INTEGER REFERENCES pm_schedules(id) ON DELETE SET NULL,
    work_order_id       INTEGER REFERENCES work_orders(id) ON DELETE SET NULL,
    resolved            BOOLEAN DEFAULT FALSE,
    resolved_at         TIMESTAMPTZ,
    is_active           BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS rent_recommendations (
    id                  SERIAL PRIMARY KEY,
    unit_id             INTEGER REFERENCES units(id) ON DELETE CASCADE,
    lease_id            INTEGER REFERENCES leases(id) ON DELETE SET NULL,
    tenant_id           INTEGER REFERENCES tenants(id) ON DELETE SET NULL,
    -- Current state
    current_rent        NUMERIC(10,2),
    lease_end_date      DATE,
    days_until_renewal  INTEGER GENERATED ALWAYS AS (
                            CASE WHEN lease_end_date IS NOT NULL
                            THEN (lease_end_date - CURRENT_DATE)::INTEGER
                            ELSE NULL END
                        ) STORED,
    -- Market data
    market_rent_p25     NUMERIC(10,2),                 -- 25th percentile comparable
    market_rent_p50     NUMERIC(10,2),                 -- Median comparable
    market_rent_p75     NUMERIC(10,2),                 -- 75th percentile comparable
    market_source       TEXT,                          -- 'Rentals.ca','Zumper','CMHC','Internal'
    market_data_date    DATE,
    -- Recommendation
    recommended_rent    NUMERIC(10,2),
    min_rent            NUMERIC(10,2),                 -- Floor — don't go below this
    max_rent            NUMERIC(10,2),                 -- Ceiling — market max
    ontario_guideline_max NUMERIC(10,2),               -- Current year guideline limit
    above_guideline     BOOLEAN DEFAULT FALSE,         -- Requires AGI application
    -- Revenue impact
    annual_revenue_delta NUMERIC(12,2),                -- (recommended - current) * 12
    vacancy_risk_score  NUMERIC(5,4),                  -- P(tenant leaves if raised)
    net_revenue_impact  NUMERIC(12,2),                 -- Revenue delta adjusted for vacancy risk
    -- Factors
    tenant_quality_score INTEGER,                      -- From risk scoring
    unit_amenity_score   INTEGER,                      -- Floor, facing, parking, etc.
    feature_importance  JSONB,
    -- Status
    status              TEXT DEFAULT 'pending',        -- 'pending','accepted','modified','declined','expired'
    n1_generated        BOOLEAN DEFAULT FALSE,
    n1_form_id          INTEGER REFERENCES ltb_forms(id) ON DELETE SET NULL,
    generated_at        TIMESTAMPTZ DEFAULT NOW(),
    expires_at          TIMESTAMPTZ GENERATED ALWAYS AS (generated_at + INTERVAL '30 days') STORED,
    actioned_by         TEXT,
    actioned_at         TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS nlq_query_log (
    id                  SERIAL PRIMARY KEY,
    -- Query
    query_text          TEXT NOT NULL,                 -- Original natural language question
    query_by            TEXT,                          -- PM name
    -- Context sent to model
    context_properties  INTEGER[],                     -- Property IDs included in context
    context_summary     TEXT,                          -- Brief description of data context sent
    -- Response
    response_text       TEXT,                          -- Model's answer
    model_used          TEXT DEFAULT 'claude-sonnet-4-6',
    tokens_used         INTEGER,
    latency_ms          INTEGER,
    -- Quality
    was_helpful         BOOLEAN,                       -- User feedback (thumbs up/down)
    follow_up_query_id  INTEGER,                       -- If this was a follow-up question
    -- Audit
    created_at          TIMESTAMPTZ DEFAULT NOW()
);


-- ══════════════════════════════════════════════════════════════════
-- INDEXES
-- ══════════════════════════════════════════════════════════════════

-- Landlord profiles
CREATE INDEX IF NOT EXISTS idx_landlord_profiles_owner ON landlord_profiles(owner_id);

-- PM scheduler
CREATE INDEX IF NOT EXISTS idx_pm_schedules_property  ON pm_schedules(property_id);
CREATE INDEX IF NOT EXISTS idx_pm_schedules_status     ON pm_schedules(status);
CREATE INDEX IF NOT EXISTS idx_pm_schedules_next_due   ON pm_schedules(next_due_date);
CREATE INDEX IF NOT EXISTS idx_pm_schedules_overdue    ON pm_schedules(next_due_date) WHERE next_due_date < CURRENT_DATE AND is_active=TRUE;
CREATE INDEX IF NOT EXISTS idx_pm_completions_schedule ON pm_completions(schedule_id);
CREATE INDEX IF NOT EXISTS idx_pm_completions_date     ON pm_completions(completed_date DESC);

-- COI
CREATE INDEX IF NOT EXISTS idx_vendor_coi_vendor       ON vendor_coi(vendor_id);
CREATE INDEX IF NOT EXISTS idx_vendor_coi_status       ON vendor_coi(status);
CREATE INDEX IF NOT EXISTS idx_vendor_coi_expiry       ON vendor_coi(expiry_date);
CREATE INDEX IF NOT EXISTS idx_vendor_coi_blocked      ON vendor_coi(dispatch_blocked) WHERE dispatch_blocked=TRUE;

-- LTB forms
CREATE INDEX IF NOT EXISTS idx_ltb_forms_tenant        ON ltb_forms(tenant_id);
CREATE INDEX IF NOT EXISTS idx_ltb_forms_lease         ON ltb_forms(lease_id);
CREATE INDEX IF NOT EXISTS idx_ltb_forms_type          ON ltb_forms(form_type);
CREATE INDEX IF NOT EXISTS idx_ltb_forms_status        ON ltb_forms(status);

-- Move events
CREATE INDEX IF NOT EXISTS idx_move_events_property    ON move_events(property_id);
CREATE INDEX IF NOT EXISTS idx_move_events_unit        ON move_events(unit_id);
CREATE INDEX IF NOT EXISTS idx_move_events_date        ON move_events(event_date);
CREATE INDEX IF NOT EXISTS idx_move_events_type        ON move_events(event_type);
CREATE INDEX IF NOT EXISTS idx_elevator_property_date  ON elevator_bookings(property_id, booking_date);

-- Inspection detail
CREATE INDEX IF NOT EXISTS idx_insp_scheduled_date     ON inspection_scheduled(scheduled_date);
CREATE INDEX IF NOT EXISTS idx_insp_scheduled_prop     ON inspection_scheduled(property_id);
CREATE INDEX IF NOT EXISTS idx_insp_scheduled_status   ON inspection_scheduled(status);
CREATE INDEX IF NOT EXISTS idx_insp_room_insp          ON inspection_room_results(inspection_id);
CREATE INDEX IF NOT EXISTS idx_insp_room_issues        ON inspection_room_results(inspection_id) WHERE is_issue=TRUE;
CREATE INDEX IF NOT EXISTS idx_insp_appliance_insp     ON inspection_appliance_results(inspection_id);
CREATE INDEX IF NOT EXISTS idx_insp_safety_insp        ON inspection_safety_checks(inspection_id);
CREATE INDEX IF NOT EXISTS idx_insp_keys_insp          ON inspection_keys_issued(inspection_id);

-- ML / AI
CREATE INDEX IF NOT EXISTS idx_ml_pred_entity          ON ml_predictions(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_ml_pred_model           ON ml_predictions(model_name, predicted_at DESC);
CREATE INDEX IF NOT EXISTS idx_ml_pred_active          ON ml_predictions(is_active, urgency) WHERE is_active=TRUE;
CREATE INDEX IF NOT EXISTS idx_risk_history_tenant     ON tenant_risk_history(tenant_id, scored_at DESC);
CREATE INDEX IF NOT EXISTS idx_risk_history_high       ON tenant_risk_history(risk_score DESC) WHERE risk_score >= 70;
CREATE INDEX IF NOT EXISTS idx_equip_pred_property     ON equipment_failure_predictions(property_id);
CREATE INDEX IF NOT EXISTS idx_equip_pred_active       ON equipment_failure_predictions(failure_probability DESC) WHERE is_active=TRUE;
CREATE INDEX IF NOT EXISTS idx_rent_recs_unit          ON rent_recommendations(unit_id);
CREATE INDEX IF NOT EXISTS idx_rent_recs_pending       ON rent_recommendations(status) WHERE status='pending';
CREATE INDEX IF NOT EXISTS idx_nlq_log_date            ON nlq_query_log(created_at DESC);


-- ══════════════════════════════════════════════════════════════════
-- SEED DATA ADDITIONS
-- ══════════════════════════════════════════════════════════════════

-- New cortai_settings for AI/ML and new modules
INSERT INTO cortai_settings (key, value, description, is_secret) VALUES
    ('ai_enabled',              'true',                  'Master AI/ML feature switch',                   FALSE),
    ('ml_risk_score_schedule',  '0 2 * * *',             'Cron for nightly risk score recalculation',     FALSE),
    ('ml_failure_pred_schedule','0 3 * * 0',             'Cron for weekly equipment failure predictions', FALSE),
    ('ml_rent_opt_schedule',    '0 4 1 * *',             'Cron for monthly rent recommendations',         FALSE),
    ('coi_reminder_days',       '30',                    'Days before COI expiry to send renewal reminder',FALSE),
    ('coi_reminder_email',      '',                      'Email to notify on expiring COI',               FALSE),
    ('coi_refresh_schedule',    '0 1 * * *',             'Cron for nightly COI status refresh',           FALSE),
    ('nlq_enabled',             'true',                  'Enable natural language query interface',        FALSE),
    ('nlq_model',               'claude-sonnet-4-6',     'Model for NLQ responses',                       FALSE),
    ('nlq_max_tokens',          '1000',                  'Max tokens per NLQ response',                   FALSE),
    ('pm_reminder_days',        '14',                    'Days before PM due date to flag as due_soon',   FALSE),
    ('inspection_notice_hours', '24',                    'Default notice period for inspections (hours)', FALSE),
    ('elevator_deposit',        '500',                   'Standard elevator booking deposit (CAD)',        FALSE),
    ('ontario_rent_guideline',  '2.5',                   '2026 Ontario rent increase guideline (%)',      FALSE)
ON CONFLICT (key) DO NOTHING;
"""

# Summary for developer handoff
SCHEMA_V3_SUMMARY = """
SCHEMA V3 SUMMARY — 16 new tables, 59 total
============================================================

NEW TABLES:
  landlord_profiles          Extended owner profiles beyond Buildium
  pm_schedules               Recurring PM task definitions (interval, next due, vendor, tech)
  pm_completions             Log of each PM completion — triggers next_due update
  vendor_coi                 COI certificate per vendor — dispatch_blocked auto-computed
  ltb_forms                  Ontario N1/N4/N5/N8/N12 generation + filing tracking
  move_events                Move-in/out/inspection calendar events
  elevator_bookings          Elevator time slots per property + date (unique constraint)
  inspection_scheduled       Upcoming inspection scheduling with notice tracking
  inspection_room_results    Room × item condition ratings per inspection
  inspection_appliance_results Appliance condition + damage assessment per inspection
  inspection_safety_checks   Smoke/CO/HVAC/extinguisher results per inspection
  inspection_keys_issued     Keys given at move-in, returned at move-out
  ml_predictions             Model predictions for any entity type
  tenant_risk_history        Time-series risk score per tenant (daily)
  equipment_failure_predictions  P(failure) per building system
  rent_recommendations       Market-adjusted rent suggestions per unit at renewal

ALTERED TABLES:
  inspections                + inspection_subtype, season, move_event_id,
                               signed_tenant, signed_landlord, keys_returned, pdf_url

AUTO-COMPUTED COLUMNS:
  pm_schedules.overdue_days           — days since next_due_date passed
  vendor_coi.days_until_expiry        — days until COI expires (can be negative)
  vendor_coi.dispatch_blocked         — TRUE when status is 'expired' or 'missing'
  rent_recommendations.days_until_renewal
  rent_recommendations.expires_at     — 30 days after generated_at

KEY TRIGGERS:
  pm_completion_trigger       — updates pm_schedule.last_done + next_due + status on each completion
  (existing) opex_anomaly_trigger, iot_wo_trigger, tech_status_trigger — unchanged

NIGHTLY JOBS TO SCHEDULE (cron):
  SELECT refresh_coi_status();                     -- Update all COI statuses (1am)
  [ML service] calculate_all_risk_scores()         -- Tenant risk recalc (2am)
  [ML service] run_failure_predictions()           -- Equipment failure scoring (3am Sun)
  [ML service] run_rent_recommendations()          -- Rent optimization (4am 1st of month)
  [Partition mgmt] create_iot_partition()          -- New IoT readings partition (25th of month)
"""
