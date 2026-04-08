"""
schema_v4.py — COrtai Property Intelligence Platform
Schema additions — run AFTER schema_v3.py

New tables (4): brings total from 60 → 64 tables

  Utility Management (2):  utility_owner_config, utility_bill_uploads
  Property Documents (2):  property_surveys, property_floorplans

All file storage (PDFs, images) uses S3 — only the URL is stored in the DB.
"""

SCHEMA_V4 = """

-- ══════════════════════════════════════════════════════════════════
-- 1. UTILITY OWNER CONFIG
-- Controls which landlord clients have utility/OPEX bill tracking
-- enabled. Lionston Group is always active (owner-operator).
-- Other owners opt in — this drives what appears in the Bill Entry
-- workflow and what shows in Admin Housekeeping pending alerts.
-- ══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS utility_owner_config (
    id                  SERIAL PRIMARY KEY,
    owner_id            INTEGER UNIQUE REFERENCES owners(id) ON DELETE CASCADE,
    owner_name          TEXT NOT NULL,                  -- Denormalized for display
    -- Activation
    is_active           BOOLEAN DEFAULT FALSE,          -- Must be explicitly enabled per owner
    activated_at        TIMESTAMPTZ,
    activated_by        TEXT,
    -- Config
    track_hydro         BOOLEAN DEFAULT TRUE,
    track_gas           BOOLEAN DEFAULT TRUE,
    track_water         BOOLEAN DEFAULT TRUE,
    track_common_hydro  BOOLEAN DEFAULT TRUE,
    track_other         BOOLEAN DEFAULT FALSE,
    -- Reporting
    include_in_owner_report BOOLEAN DEFAULT TRUE,       -- Include OPEX in monthly owner statement
    report_frequency    TEXT DEFAULT 'Monthly',
    -- Billing to client (if charging for OPEX management)
    billing_enabled     BOOLEAN DEFAULT FALSE,
    billing_monthly_fee NUMERIC(8,2),
    -- Notes
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Seed Lionston Group as active (they're the owner-operator, always tracked)
-- Run after owners table is populated from Buildium sync
-- INSERT INTO utility_owner_config (owner_name, is_active, activated_by)
-- SELECT 'Lionston Group', TRUE, 'System'
-- WHERE NOT EXISTS (SELECT 1 FROM utility_owner_config WHERE owner_name='Lionston Group');


-- ══════════════════════════════════════════════════════════════════
-- 2. UTILITY BILL UPLOADS
-- Stores invoice document uploads per property / billing period /
-- utility category. The actual file lives in S3; this table stores
-- the metadata and URL.
--
-- Each utility bill entry (opex_actuals row) can have one or more
-- supporting invoice documents attached here.
-- ══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS utility_bill_uploads (
    id                  SERIAL PRIMARY KEY,
    -- Links
    opex_actual_id      INTEGER REFERENCES opex_actuals(id) ON DELETE CASCADE,
    property_id         INTEGER REFERENCES properties(id) ON DELETE CASCADE,
    -- Billing period + category (denormalized for querying without joining opex_actuals)
    billing_period      DATE NOT NULL,                  -- First day of month: 2026-04-01
    utility_category    TEXT NOT NULL,                  -- 'hydro','gas','water','common_hydro','other'
    -- File metadata
    filename            TEXT NOT NULL,                  -- Original filename: 'Enbridge-April-2026.pdf'
    file_url            TEXT,                           -- S3 URL: https://s3.../invoices/...
    file_key            TEXT,                           -- S3 object key for deletion
    file_size_bytes     INTEGER,
    file_size_display   TEXT,                           -- '2.4 MB'
    mime_type           TEXT,                           -- 'application/pdf','image/jpeg','image/png'
    -- Invoice data extracted from document (manual or OCR)
    invoice_number      TEXT,
    invoice_date        DATE,
    vendor_name         TEXT,                           -- 'Enbridge Gas Distribution'
    account_number      TEXT,                           -- Utility account number
    amount_billed       NUMERIC(10,2),                  -- Dollar amount on the invoice
    usage_quantity      NUMERIC(12,3),                  -- kWh, m³ etc.
    usage_unit          TEXT,                           -- 'kWh','m3'
    billing_period_start DATE,
    billing_period_end   DATE,
    -- Status
    is_verified         BOOLEAN DEFAULT FALSE,          -- PM confirmed invoice matches entry
    verified_by         TEXT,
    verified_at         TIMESTAMPTZ,
    -- Audit
    uploaded_by         TEXT,
    uploaded_at         TIMESTAMPTZ DEFAULT NOW(),
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);


-- ══════════════════════════════════════════════════════════════════
-- 3. PROPERTY SURVEYS & REPORTS
-- Legal surveys, environmental assessments, building condition
-- reports, mechanical audits, and other professional reports
-- filed against a property.
-- ══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS property_surveys (
    id                  SERIAL PRIMARY KEY,
    property_id         INTEGER REFERENCES properties(id) ON DELETE CASCADE,
    -- Document identity
    title               TEXT NOT NULL,                  -- 'Survey on Title'
    survey_type         TEXT NOT NULL,                  -- 'Legal Survey','Environmental','Condition Report','Mechanical Audit','Structural','Fire Safety','Elevator','Electrical'
    -- Surveyor / firm
    firm_name           TEXT,                           -- 'Krcmar Surveyors Ltd.'
    contact_name        TEXT,
    contact_phone       TEXT,
    contact_email       TEXT,
    -- Dates
    survey_date         DATE,
    report_date         DATE,
    expiry_date         DATE,                           -- If report has an expiry (e.g. Phase 1 env = 5yr)
    -- File
    file_url            TEXT,                           -- S3 URL
    file_key            TEXT,
    filename            TEXT,
    file_size_bytes     INTEGER,
    mime_type           TEXT DEFAULT 'application/pdf',
    page_count          INTEGER,
    -- Summary
    summary             TEXT,                           -- Key findings / exec summary
    recommendations     TEXT,                           -- Recommended actions
    critical_items      TEXT[],                         -- List of critical findings
    -- Status
    status              TEXT DEFAULT 'current',         -- 'current','superseded','expired','archived'
    requires_followup   BOOLEAN DEFAULT FALSE,
    followup_date       DATE,
    followup_notes      TEXT,
    -- Cost
    survey_cost         NUMERIC(10,2),
    -- Audit
    uploaded_by         TEXT,
    is_confidential     BOOLEAN DEFAULT FALSE,          -- Restrict access (e.g. env reports)
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Upcoming / required reports tracker (separate from completed surveys)
CREATE TABLE IF NOT EXISTS property_report_schedule (
    id                  SERIAL PRIMARY KEY,
    property_id         INTEGER REFERENCES properties(id) ON DELETE CASCADE,
    report_type         TEXT NOT NULL,                  -- 'Building Condition Assessment','TSSA Elevator','ESA','Phase 1 Environmental','Fire Safety'
    legal_requirement   TEXT,                           -- 'Ontario Fire Code s.2.8','TSSA Regulation 209'
    frequency_years     INTEGER,                        -- How often required (1 = annual)
    last_completed_date DATE,
    last_survey_id      INTEGER REFERENCES property_surveys(id) ON DELETE SET NULL,
    next_due_date       DATE GENERATED ALWAYS AS (
                            CASE WHEN last_completed_date IS NOT NULL AND frequency_years IS NOT NULL
                            THEN last_completed_date + (frequency_years || ' years')::INTERVAL
                            ELSE NULL END::DATE
                        ) STORED,
    status              TEXT DEFAULT 'upcoming',        -- 'current','upcoming','overdue','not_required'
    responsible_party   TEXT,                           -- Who arranges/pays: 'Landlord','Tenant','TSSA'
    est_cost            NUMERIC(10,2),
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);


-- ══════════════════════════════════════════════════════════════════
-- 4. PROPERTY FLOOR PLANS
-- As-built drawings, architectural plans, and unit layout files.
-- Stored in S3; metadata here enables search and version control.
-- ══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS property_floorplans (
    id                  SERIAL PRIMARY KEY,
    property_id         INTEGER REFERENCES properties(id) ON DELETE CASCADE,
    -- Plan identity
    title               TEXT NOT NULL,                  -- 'Floors 1-5 Typical Floor Plan'
    plan_type           TEXT NOT NULL,                  -- 'As-Built','Proposed','Schematic','Structural','Mechanical','Electrical','Site Plan'
    floor_designation   TEXT,                           -- 'B1','G','1-5','6','Roof','All'
    floor_number_low    INTEGER,                        -- For range: first floor covered
    floor_number_high   INTEGER,                        -- For range: last floor covered
    -- Units covered
    units_covered       TEXT[],                         -- ['101-112','201-212'] or ['Lobby','Gym','Party Room']
    unit_count          INTEGER,
    sqft_shown          INTEGER,
    -- File
    file_url            TEXT,                           -- S3 URL for PDF/DWG/image
    file_key            TEXT,
    filename            TEXT,
    file_size_bytes     INTEGER,
    mime_type           TEXT,                           -- 'application/pdf','image/png','application/acad'
    thumbnail_url       TEXT,                           -- S3 URL for generated thumbnail/preview
    page_count          INTEGER,
    -- Version control
    version             TEXT DEFAULT '1.0',             -- '1.0','2.1 Rev A'
    revision_date       DATE,
    revision_notes      TEXT,
    supersedes_id       INTEGER REFERENCES property_floorplans(id) ON DELETE SET NULL,
    is_current          BOOLEAN DEFAULT TRUE,           -- FALSE = superseded by newer version
    -- Origin
    architect_firm      TEXT,
    drawn_by            TEXT,
    approved_by         TEXT,
    drawing_number      TEXT,                           -- 'A-101','M-201' etc.
    scale               TEXT,                           -- '1:100','1/8"=1\'-0"'
    -- Access
    is_confidential     BOOLEAN DEFAULT FALSE,
    -- Audit
    uploaded_by         TEXT,
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);


-- ══════════════════════════════════════════════════════════════════
-- INDEXES
-- ══════════════════════════════════════════════════════════════════

-- Utility owner config
CREATE INDEX IF NOT EXISTS idx_util_owner_active    ON utility_owner_config(is_active) WHERE is_active=TRUE;

-- Bill uploads
CREATE INDEX IF NOT EXISTS idx_bill_uploads_actual  ON utility_bill_uploads(opex_actual_id);
CREATE INDEX IF NOT EXISTS idx_bill_uploads_prop    ON utility_bill_uploads(property_id);
CREATE INDEX IF NOT EXISTS idx_bill_uploads_period  ON utility_bill_uploads(billing_period DESC);
CREATE INDEX IF NOT EXISTS idx_bill_uploads_cat     ON utility_bill_uploads(utility_category);

-- Surveys
CREATE INDEX IF NOT EXISTS idx_surveys_property     ON property_surveys(property_id);
CREATE INDEX IF NOT EXISTS idx_surveys_type         ON property_surveys(survey_type);
CREATE INDEX IF NOT EXISTS idx_surveys_status       ON property_surveys(status);
CREATE INDEX IF NOT EXISTS idx_surveys_expiry       ON property_surveys(expiry_date) WHERE expiry_date IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_report_sched_prop    ON property_report_schedule(property_id);
CREATE INDEX IF NOT EXISTS idx_report_sched_due     ON property_report_schedule(next_due_date);

-- Floor plans
CREATE INDEX IF NOT EXISTS idx_floorplans_property  ON property_floorplans(property_id);
CREATE INDEX IF NOT EXISTS idx_floorplans_current   ON property_floorplans(property_id, is_current) WHERE is_current=TRUE;
CREATE INDEX IF NOT EXISTS idx_floorplans_type      ON property_floorplans(plan_type);


-- ══════════════════════════════════════════════════════════════════
-- SEED DATA
-- ══════════════════════════════════════════════════════════════════

-- Standard required reports for all residential multi-family properties
-- (Run once after properties are loaded from Buildium)
-- INSERT INTO property_report_schedule (property_id, report_type, legal_requirement, frequency_years, responsible_party)
-- SELECT id, 'Building Condition Assessment', 'Best practice — lender/insurance', 5, 'Landlord' FROM properties WHERE structure_type='ApartmentComplex'
-- ON CONFLICT DO NOTHING;

-- New cortai_settings for file storage
INSERT INTO cortai_settings (key, value, description, is_secret) VALUES
    ('s3_bucket_documents',     '',  'S3 bucket for property documents (surveys, plans)',   FALSE),
    ('s3_bucket_invoices',      '',  'S3 bucket for utility invoice uploads',               FALSE),
    ('s3_region',               'ca-central-1', 'AWS S3 region',                           FALSE),
    ('max_upload_size_mb',      '10', 'Maximum file upload size in MB',                    FALSE),
    ('allowed_upload_types',    'application/pdf,image/jpeg,image/png,image/webp,application/acad,application/dxf',
                                     'Allowed MIME types for document uploads',             FALSE),
    ('thumbnail_generate',      'true', 'Auto-generate PDF thumbnails on upload',           FALSE)
ON CONFLICT (key) DO NOTHING;
"""

SCHEMA_V4_SUMMARY = """
SCHEMA V4 SUMMARY — 4 new tables + 1 sub-table, 64 total
===========================================================

NEW TABLES:
  utility_owner_config        Per-landlord switch for utility tracking opt-in.
                              Lionston Group seeded as active. Others require
                              explicit enable — controls Bill Entry UI and
                              Admin Housekeeping pending alerts.

  utility_bill_uploads        One row per uploaded invoice document.
                              Links to opex_actuals (the dollar entry).
                              Stores S3 URL, filename, size, mime type.
                              Also captures invoice_number, account_number,
                              vendor_name, and amount_billed if extracted.
                              verified_by/at for PM sign-off workflow.

  property_surveys            Legal surveys, env assessments, condition reports,
                              mechanical audits, fire safety inspections.
                              Includes expiry_date (Phase 1 = 5yr, elevator = 1yr).
                              requires_followup flag + followup_date.
                              is_confidential for restricted reports.

  property_report_schedule    Tracks required recurring reports per property.
                              next_due_date is auto-computed from
                              last_completed_date + frequency_years.
                              Query WHERE status='overdue' for Admin Housekeeping.

  property_floorplans         Floor plan files with version control.
                              supersedes_id FK for revision history.
                              is_current flag — only latest version is current.
                              thumbnail_url for PDF preview generation.
                              floor_number_low/high for range floors (1-5 typical).

NEW CORTAI_SETTINGS KEYS:
  s3_bucket_documents         S3 bucket for surveys + floor plans
  s3_bucket_invoices          S3 bucket for utility invoice uploads
  s3_region                   AWS region (default: ca-central-1)
  max_upload_size_mb          10MB default
  allowed_upload_types        PDF, JPEG, PNG, WebP, DWG, DXF
  thumbnail_generate          Auto-generate PDF preview thumbnails

KEY DESIGN DECISIONS:
  - Utility bills (amounts) stay in opex_actuals — uploads are an attachment
  - One invoice can span multiple utility categories (some landlords get combined bills)
    → handled at API layer, not schema level
  - Floor plans use supersedes_id for version control rather than soft-delete
  - property_report_schedule.next_due_date is generated column — never set manually
  - All files stored in S3; DB stores only metadata + URL

RUN ORDER:
  schema_v2.py → schema_v3.py → schema_v4.py
"""
