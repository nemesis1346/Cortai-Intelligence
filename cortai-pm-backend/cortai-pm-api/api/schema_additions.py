"""
schema_additions.py — Append to existing schema.py

New tables for: Field Service Techs · OPEX Tracking · IoT Devices
Add SCHEMA_ADDITIONS string to the end of your init_db() call.
"""

SCHEMA_ADDITIONS = """

-- ══════════════════════════════════════════════════════════════════
-- FIELD SERVICE TECHNICIANS
-- ══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS field_techs (
    id                  SERIAL PRIMARY KEY,
    first_name          TEXT NOT NULL,
    last_name           TEXT NOT NULL,
    role                TEXT,                           -- 'Senior Technician','HVAC Specialist','Electrician'
    email               TEXT,
    phone               TEXT,
    hire_date           DATE,
    status              TEXT DEFAULT 'Available',       -- 'Available','On Site','In Transit','Off Duty','On Leave'
    skills              TEXT[],                         -- ['HVAC','Plumbing','Electrical']
    certifications      TEXT[],                         -- ['TSSA','ESA','313D']
    hourly_rate         NUMERIC(8,2),
    is_active           BOOLEAN DEFAULT TRUE,
    current_property_id INTEGER REFERENCES properties(id) ON DELETE SET NULL,
    current_wo_id       INTEGER REFERENCES work_orders(id) ON DELETE SET NULL,
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tech_tasks (
    id                  SERIAL PRIMARY KEY,
    tech_id             INTEGER REFERENCES field_techs(id) ON DELETE CASCADE,
    work_order_id       INTEGER REFERENCES work_orders(id) ON DELETE SET NULL,
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
    total_cost          NUMERIC(10,2) GENERATED ALWAYS AS (parts_cost + labour_cost) STORED,
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
    period_type         TEXT DEFAULT 'monthly',         -- 'daily','weekly','monthly'
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
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ══════════════════════════════════════════════════════════════════
-- OPEX TRACKING — Operating Expense per Building
-- ══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS opex_categories (
    id                  SERIAL PRIMARY KEY,
    name                TEXT UNIQUE NOT NULL,           -- 'Hydro','Gas','Water','Maintenance','Insurance'
    display_name        TEXT,
    unit                TEXT,                           -- 'kWh','m3','CAD'
    utility_type        BOOLEAN DEFAULT FALSE,          -- True if this is a metered utility
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
    usage_quantity      NUMERIC(12,3),                  -- kWh, m3, etc.
    usage_unit          TEXT,
    vendor              TEXT,
    invoice_number      TEXT,
    invoice_date        DATE,
    payment_date        DATE,
    payment_method      TEXT,
    is_estimated        BOOLEAN DEFAULT FALSE,
    notes               TEXT,
    anomaly_flag        BOOLEAN DEFAULT FALSE,
    anomaly_severity    TEXT,                           -- 'warning','alert','critical'
    anomaly_pct_over    NUMERIC(7,2),
    anomaly_reason      TEXT,
    anomaly_resolved    BOOLEAN DEFAULT FALSE,
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
-- IoT DEVICE MONITORING
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
    -- Thresholds
    threshold_warn      NUMERIC(12,4),
    threshold_critical  NUMERIC(12,4),
    reading_unit        TEXT,                           -- 'mm/s','dB','cm','°C','wet/dry'
    baseline_avg        NUMERIC(12,4),
    baseline_calc_date  DATE,
    -- Current state
    last_reading        NUMERIC(12,4),
    last_reading_at     TIMESTAMPTZ,
    trend               TEXT DEFAULT 'stable',          -- 'stable','rising','rising_fast','falling','erratic'
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS iot_readings (
    id                  BIGSERIAL PRIMARY KEY,          -- Use BIGSERIAL — high volume
    device_id           INTEGER REFERENCES iot_devices(id) ON DELETE CASCADE,
    reading_value       NUMERIC(12,4) NOT NULL,
    recorded_at         TIMESTAMPTZ DEFAULT NOW(),
    -- For binary sensors (leak detect)
    is_triggered        BOOLEAN,
    -- Partitioned by month in production (pg_partman recommended)
    CONSTRAINT iot_readings_value_check CHECK (reading_value IS NOT NULL)
) PARTITION BY RANGE (recorded_at);  -- Requires pg_partman setup

-- Monthly partitions (create via script)
-- CREATE TABLE iot_readings_2026_04 PARTITION OF iot_readings
--   FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');

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
    dispatch_notes      TEXT,
    triggered_at        TIMESTAMPTZ DEFAULT NOW(),
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS iot_alert_rules (
    id                  SERIAL PRIMARY KEY,
    device_type         TEXT,                           -- NULL = applies to all
    device_id           INTEGER REFERENCES iot_devices(id) ON DELETE CASCADE,
    rule_name           TEXT NOT NULL,
    condition_type      TEXT NOT NULL,                  -- 'above','below','change_rate','trend','pattern'
    condition_value     NUMERIC(12,4),
    condition_duration  INTEGER,                        -- seconds condition must persist before alert
    alert_level         TEXT NOT NULL,
    message_template    TEXT,
    auto_create_wo      BOOLEAN DEFAULT FALSE,
    wo_priority         TEXT DEFAULT 'High',
    notify_channels     TEXT[],                         -- ['email','sms','push','pager']
    notify_addresses    TEXT[],
    is_active           BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ══════════════════════════════════════════════════════════════════
-- INDEXES — New tables
-- ══════════════════════════════════════════════════════════════════

-- Field Tech
CREATE INDEX IF NOT EXISTS idx_tech_tasks_tech ON tech_tasks(tech_id);
CREATE INDEX IF NOT EXISTS idx_tech_tasks_wo ON tech_tasks(work_order_id);
CREATE INDEX IF NOT EXISTS idx_tech_tasks_status ON tech_tasks(status);
CREATE INDEX IF NOT EXISTS idx_tech_tasks_scheduled ON tech_tasks(scheduled_start);
CREATE INDEX IF NOT EXISTS idx_productivity_tech ON tech_productivity_snapshots(tech_id);

-- OPEX
CREATE INDEX IF NOT EXISTS idx_opex_actuals_prop ON opex_actuals(property_id);
CREATE INDEX IF NOT EXISTS idx_opex_actuals_period ON opex_actuals(billing_period DESC);
CREATE INDEX IF NOT EXISTS idx_opex_actuals_anomaly ON opex_actuals(anomaly_flag) WHERE anomaly_flag=TRUE;
CREATE INDEX IF NOT EXISTS idx_opex_anomalies_prop ON opex_anomalies(property_id);
CREATE INDEX IF NOT EXISTS idx_opex_anomalies_unresolved ON opex_anomalies(is_resolved) WHERE is_resolved=FALSE;

-- IoT
CREATE INDEX IF NOT EXISTS idx_iot_devices_property ON iot_devices(property_id);
CREATE INDEX IF NOT EXISTS idx_iot_devices_status ON iot_devices(status);
CREATE INDEX IF NOT EXISTS idx_iot_readings_device ON iot_readings(device_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_iot_alerts_device ON iot_alerts(device_id);
CREATE INDEX IF NOT EXISTS idx_iot_alerts_active ON iot_alerts(status) WHERE status='Active';
CREATE INDEX IF NOT EXISTS idx_iot_alerts_property ON iot_alerts(property_id);

-- ══════════════════════════════════════════════════════════════════
-- SEED: OPEX categories
-- ══════════════════════════════════════════════════════════════════

INSERT INTO opex_categories (name, display_name, unit, utility_type) VALUES
    ('hydro',       'Hydro / Electricity', 'kWh', TRUE),
    ('gas',         'Natural Gas',         'm3',  TRUE),
    ('water',       'Water / Sewer',       'm3',  TRUE),
    ('maintenance', 'Maintenance / Repairs','CAD', FALSE),
    ('insurance',   'Insurance',           'CAD', FALSE),
    ('landscaping', 'Landscaping',         'CAD', FALSE),
    ('management',  'Management Fee',      'CAD', FALSE),
    ('tax',         'Property Tax',        'CAD', FALSE),
    ('other',       'Other Expenses',      'CAD', FALSE)
ON CONFLICT (name) DO NOTHING;

-- ══════════════════════════════════════════════════════════════════
-- OPEX ANOMALY DETECTION FUNCTION
-- Run this after inserting each opex_actual record
-- ══════════════════════════════════════════════════════════════════

CREATE OR REPLACE FUNCTION check_opex_anomaly(
    p_actual_id INTEGER
) RETURNS TEXT AS $$
DECLARE
    v_actual    opex_actuals%ROWTYPE;
    v_budget    NUMERIC;
    v_baseline  NUMERIC;
    v_variance  NUMERIC;
    v_severity  TEXT := NULL;
BEGIN
    SELECT * INTO v_actual FROM opex_actuals WHERE id = p_actual_id;

    -- Get monthly budget
    SELECT ob.monthly_budget INTO v_budget
    FROM opex_budgets ob
    WHERE ob.property_id = v_actual.property_id
      AND ob.category_id = v_actual.category_id
      AND ob.budget_year = EXTRACT(YEAR FROM v_actual.billing_period);

    -- Get 3-month rolling baseline
    SELECT AVG(amount) INTO v_baseline
    FROM opex_actuals
    WHERE property_id = v_actual.property_id
      AND category_id = v_actual.category_id
      AND billing_period >= v_actual.billing_period - INTERVAL '3 months'
      AND billing_period < v_actual.billing_period;

    -- Check vs budget
    IF v_budget IS NOT NULL AND v_budget > 0 THEN
        v_variance := ((v_actual.amount - v_budget) / v_budget * 100);
        IF v_variance > 100 THEN
            v_severity := 'critical';
        ELSIF v_variance > 30 THEN
            v_severity := 'alert';
        ELSIF v_variance > 15 THEN
            v_severity := 'warning';
        END IF;
    END IF;

    -- Also check vs 3-month baseline (catches seasonal patterns budget misses)
    IF v_baseline IS NOT NULL AND v_baseline > 0 THEN
        DECLARE v_baseline_var NUMERIC;
        BEGIN
            v_baseline_var := ((v_actual.amount - v_baseline) / v_baseline * 100);
            IF v_baseline_var > 50 AND v_severity IS NULL THEN
                v_severity := 'warning';
            END IF;
        END;
    END IF;

    IF v_severity IS NOT NULL THEN
        UPDATE opex_actuals
        SET anomaly_flag = TRUE,
            anomaly_severity = v_severity,
            anomaly_pct_over = v_variance
        WHERE id = p_actual_id;

        INSERT INTO opex_anomalies
            (property_id, actual_id, category_id, billing_period,
             budget_amount, actual_amount, variance_amount, variance_pct,
             severity, baseline_3mo_avg)
        VALUES
            (v_actual.property_id, p_actual_id, v_actual.category_id, v_actual.billing_period,
             v_budget, v_actual.amount, v_actual.amount - v_budget, v_variance,
             v_severity, v_baseline);
    END IF;

    RETURN v_severity;
END;
$$ LANGUAGE plpgsql;

-- Auto-trigger anomaly check on insert/update
CREATE OR REPLACE FUNCTION trigger_opex_anomaly_check()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM check_opex_anomaly(NEW.id);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER opex_anomaly_trigger
    AFTER INSERT OR UPDATE OF amount ON opex_actuals
    FOR EACH ROW EXECUTE FUNCTION trigger_opex_anomaly_check();

-- IoT: Auto-create WO when critical alert fires (configurable)
CREATE OR REPLACE FUNCTION trigger_iot_alert_wo()
RETURNS TRIGGER AS $$
DECLARE
    v_rule iot_alert_rules%ROWTYPE;
BEGIN
    IF NEW.alert_level = 'critical' AND NEW.status = 'Active' THEN
        SELECT * INTO v_rule
        FROM iot_alert_rules r
        JOIN iot_devices d ON d.id = NEW.device_id
        WHERE (r.device_id = NEW.device_id OR r.device_type = d.device_type)
          AND r.auto_create_wo = TRUE
          AND r.is_active = TRUE
        LIMIT 1;

        IF FOUND THEN
            INSERT INTO work_orders (property_id, title, description, category, priority, status, submitted_source, sync_status)
            SELECT
                NEW.property_id,
                'IoT ALERT: ' || d.target_equipment || ' — ' || d.device_type,
                NEW.message,
                'HVAC',
                v_rule.wo_priority,
                'Submitted',
                'IoT Sensor',
                'pending_push'
            FROM iot_devices d WHERE d.id = NEW.device_id;

            UPDATE iot_alerts SET auto_dispatched = TRUE WHERE id = NEW.id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER iot_alert_wo_trigger
    AFTER INSERT ON iot_alerts
    FOR EACH ROW EXECUTE FUNCTION trigger_iot_alert_wo();
"""
