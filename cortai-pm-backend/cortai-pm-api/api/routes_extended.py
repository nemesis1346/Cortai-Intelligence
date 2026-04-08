"""
routes_extended.py — New API routes for extended COrtai features.
Mount in main.py:
    from routes_extended import router as ext_router
    app.include_router(ext_router, prefix="/api")
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
from datetime import date, time, datetime
import asyncpg

router = APIRouter()

# Pool injected at startup — set by main.py
_pool: asyncpg.Pool = None
def set_pool(pool): global _pool; _pool = pool
def pool() -> asyncpg.Pool: return _pool


# ══════════════════════════════════════════════════════════════════
# UNIT ACCESS INSTRUCTIONS
# ══════════════════════════════════════════════════════════════════

@router.get("/units/{unit_id}/access")
async def get_unit_access(unit_id: int):
    async with pool().acquire() as c:
        row = await c.fetchrow("SELECT * FROM unit_access_instructions WHERE unit_id=$1", unit_id)
    if not row:
        raise HTTPException(404, "No access instructions recorded for this unit")
    return dict(row)

class UnitAccessRequest(BaseModel):
    access_method:   str = "Authorized Entry"
    notice_required: Optional[str] = "24 hours written notice (Ontario RTA)"
    key_location:    Optional[str] = None
    lockbox_code:    Optional[str] = None   # Encrypted at rest in production
    alarm_code:      Optional[str] = None   # Encrypted at rest in production
    has_alarm:       bool = False
    restrictions:    Optional[str] = None
    access_hours:    Optional[str] = None
    contact_name:    Optional[str] = None
    contact_phone:   Optional[str] = None
    notes:           Optional[str] = None
    last_updated_by: Optional[str] = None

@router.put("/units/{unit_id}/access")
async def upsert_unit_access(unit_id: int, body: UnitAccessRequest):
    """Create or fully replace access instructions for a unit."""
    async with pool().acquire() as c:
        exists = await c.fetchval(
            "SELECT id FROM unit_access_instructions WHERE unit_id=$1", unit_id)
        if exists:
            await c.execute("""
                UPDATE unit_access_instructions
                SET access_method=$1, notice_required=$2, key_location=$3, lockbox_code=$4,
                    alarm_code=$5, has_alarm=$6, restrictions=$7, access_hours=$8,
                    contact_name=$9, contact_phone=$10, notes=$11, last_updated_by=$12,
                    updated_at=NOW()
                WHERE unit_id=$13""",
                body.access_method, body.notice_required, body.key_location, body.lockbox_code,
                body.alarm_code, body.has_alarm, body.restrictions, body.access_hours,
                body.contact_name, body.contact_phone, body.notes, body.last_updated_by, unit_id)
        else:
            await c.execute("""
                INSERT INTO unit_access_instructions
                    (unit_id, access_method, notice_required, key_location, lockbox_code,
                     alarm_code, has_alarm, restrictions, access_hours,
                     contact_name, contact_phone, notes, last_updated_by)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)""",
                unit_id, body.access_method, body.notice_required, body.key_location,
                body.lockbox_code, body.alarm_code, body.has_alarm, body.restrictions,
                body.access_hours, body.contact_name, body.contact_phone, body.notes, body.last_updated_by)
    return {"message": "Access instructions saved"}

@router.get("/properties/{property_id}/access-summary")
async def property_access_summary(property_id: int):
    """Return access instructions for all units in a property — useful for dispatcher."""
    async with pool().acquire() as c:
        rows = await c.fetch("""
            SELECT u.unit_number, uai.*
            FROM units u
            LEFT JOIN unit_access_instructions uai ON uai.unit_id=u.id
            WHERE u.property_id=$1 AND u.is_active=TRUE
            ORDER BY u.unit_number
        """, property_id)
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════════════
# WO ASSIGNMENTS (scheduling)
# ══════════════════════════════════════════════════════════════════

@router.get("/work-orders/{wo_id}/assignment")
async def get_wo_assignment(wo_id: int):
    async with pool().acquire() as c:
        row = await c.fetchrow("""
            SELECT wa.*, ft.first_name||' '||ft.last_name as tech_name,
                   ft.phone as tech_phone, ft.role as tech_role
            FROM wo_assignments wa
            JOIN field_techs ft ON ft.id=wa.tech_id
            WHERE wa.work_order_id=$1
        """, wo_id)
    if not row:
        raise HTTPException(404, "No assignment for this work order")
    return dict(row)

class WOAssignmentRequest(BaseModel):
    tech_id:            int
    scheduled_date:     date
    time_slot_label:    Optional[str] = None    # '10:00'
    estimated_duration: Optional[int] = None    # minutes
    dispatch_notes:     Optional[str] = None
    assigned_by:        Optional[str] = None

@router.post("/work-orders/{wo_id}/assign", status_code=201)
async def assign_work_order(wo_id: int, body: WOAssignmentRequest,
                            background_tasks: BackgroundTasks):
    async with pool().acquire() as c:
        # Check for time conflict
        if body.time_slot_label:
            conflict = await c.fetchval("""
                SELECT wa.id FROM wo_assignments wa
                WHERE wa.tech_id=$1 AND wa.scheduled_date=$2
                  AND wa.time_slot_label=$3
                  AND wa.assignment_status NOT IN ('Cancelled','Rescheduled')
                  AND wa.work_order_id != $4
            """, body.tech_id, body.scheduled_date, body.time_slot_label, wo_id)
            if conflict:
                raise HTTPException(409, f"Tech already has a booking at {body.time_slot_label} on {body.scheduled_date}")

        # Remove existing assignment if any
        await c.execute(
            "DELETE FROM wo_assignments WHERE work_order_id=$1", wo_id)

        # Create new assignment
        asgn_id = await c.fetchval("""
            INSERT INTO wo_assignments
                (work_order_id, tech_id, scheduled_date, time_slot_label,
                 estimated_duration, dispatch_notes, assigned_by, assignment_status)
            VALUES ($1,$2,$3,$4,$5,$6,$7,'Scheduled') RETURNING id
        """, wo_id, body.tech_id, body.scheduled_date, body.time_slot_label,
            body.estimated_duration, body.dispatch_notes, body.assigned_by)

        # Update WO status to Dispatched
        await c.execute(
            "UPDATE work_orders SET status='Dispatched', updated_at=NOW() WHERE id=$1", wo_id)

    # Push note to Buildium in background
    from buildium.sync_engine_v2 import SyncEngine
    from buildium.client_v2 import BuildiumClient
    import os
    async def push():
        try:
            async with BuildiumClient(
                os.getenv("BUILDIUM_CLIENT_ID",""),
                os.getenv("BUILDIUM_CLIENT_SECRET","")
            ) as client:
                engine = SyncEngine(pool(), client)
                await engine._push_pending_wo_notes()
        except Exception as e:
            pass  # Non-critical
    if os.getenv("BUILDIUM_CLIENT_ID"):
        background_tasks.add_task(push)

    return {"id": asgn_id, "message": "Work order assigned and scheduled"}

@router.delete("/work-orders/{wo_id}/assign")
async def unassign_work_order(wo_id: int):
    async with pool().acquire() as c:
        await c.execute("""
            UPDATE wo_assignments SET assignment_status='Cancelled', updated_at=NOW()
            WHERE work_order_id=$1
        """, wo_id)
        await c.execute(
            "UPDATE work_orders SET status='Submitted', updated_at=NOW() WHERE id=$1", wo_id)
    return {"message": "Assignment cancelled"}

@router.get("/field-techs/{tech_id}/schedule")
async def tech_schedule(tech_id: int, date_from: date = None, date_to: date = None):
    """Return a tech's scheduled work orders for a date range."""
    if not date_from: date_from = date.today()
    if not date_to:   date_to   = date_from
    async with pool().acquire() as c:
        rows = await c.fetch("""
            SELECT wa.*, w.title, w.priority, w.category, w.wo_number,
                   p.name as property_name, u.unit_number
            FROM wo_assignments wa
            JOIN work_orders w ON w.id=wa.work_order_id
            LEFT JOIN properties p ON p.id=w.property_id
            LEFT JOIN units u ON u.id=w.unit_id
            WHERE wa.tech_id=$1
              AND wa.scheduled_date BETWEEN $2 AND $3
              AND wa.assignment_status NOT IN ('Cancelled')
            ORDER BY wa.scheduled_date, wa.time_slot_label
        """, tech_id, date_from, date_to)
    return [dict(r) for r in rows]

@router.get("/field-techs/{tech_id}/availability")
async def tech_availability(tech_id: int, check_date: date = None):
    """Return booked time slots for a tech on a given date."""
    check_date = check_date or date.today()
    async with pool().acquire() as c:
        booked = await c.fetch("""
            SELECT wa.time_slot_label, wa.estimated_duration,
                   w.title, w.priority
            FROM wo_assignments wa
            JOIN work_orders w ON w.id=wa.work_order_id
            WHERE wa.tech_id=$1 AND wa.scheduled_date=$2
              AND wa.assignment_status NOT IN ('Cancelled','Rescheduled')
            ORDER BY wa.time_slot_label
        """, tech_id, check_date)
    return {
        "tech_id":    tech_id,
        "date":       str(check_date),
        "booked_slots": [dict(r) for r in booked],
        "booked_count": len(booked),
    }


# ══════════════════════════════════════════════════════════════════
# FIELD TECHS
# ══════════════════════════════════════════════════════════════════

@router.get("/field-techs")
async def list_field_techs(status: Optional[str] = None, active_only: bool = True):
    sql = """
        SELECT ft.*,
               COUNT(wa.id) FILTER (WHERE wa.assignment_status='Scheduled') as scheduled_count,
               COUNT(wa.id) FILTER (WHERE wa.assignment_status='In Progress') as active_count
        FROM field_techs ft
        LEFT JOIN wo_assignments wa ON wa.tech_id=ft.id
          AND wa.scheduled_date=CURRENT_DATE
        WHERE 1=1
    """
    params, i = [], 1
    if active_only: sql += " AND ft.is_active=TRUE"
    if status:      sql += f" AND ft.status=${i}"; params.append(status); i+=1
    sql += " GROUP BY ft.id ORDER BY ft.last_name, ft.first_name"
    async with pool().acquire() as c:
        rows = await c.fetch(sql, *params)
    return [dict(r) for r in rows]

@router.get("/field-techs/{tech_id}")
async def get_field_tech(tech_id: int):
    async with pool().acquire() as c:
        tech = await c.fetchrow("SELECT * FROM field_techs WHERE id=$1", tech_id)
        if not tech: raise HTTPException(404, "Tech not found")
        tasks = await c.fetch("""
            SELECT tt.*, w.wo_number, p.name as property_name
            FROM tech_tasks tt
            LEFT JOIN work_orders w ON w.id=tt.work_order_id
            LEFT JOIN properties p ON p.id=tt.property_id
            WHERE tt.tech_id=$1 ORDER BY tt.scheduled_start DESC LIMIT 30
        """, tech_id)
        today_assignments = await c.fetch("""
            SELECT wa.*, w.title, w.priority, p.name as property_name, u.unit_number
            FROM wo_assignments wa
            JOIN work_orders w ON w.id=wa.work_order_id
            LEFT JOIN properties p ON p.id=w.property_id
            LEFT JOIN units u ON u.id=w.unit_id
            WHERE wa.tech_id=$1 AND wa.scheduled_date=CURRENT_DATE
              AND wa.assignment_status NOT IN ('Cancelled')
            ORDER BY wa.time_slot_label
        """, tech_id)
    return {**dict(tech), "recent_tasks": [dict(t) for t in tasks],
            "today": [dict(a) for a in today_assignments]}

@router.patch("/field-techs/{tech_id}/status")
async def update_tech_status(tech_id: int, body: dict):
    valid = ["Available","On Site","In Transit","Off Duty","On Leave"]
    if body.get("status") not in valid:
        raise HTTPException(400, f"Status must be one of {valid}")
    async with pool().acquire() as c:
        await c.execute(
            "UPDATE field_techs SET status=$1, updated_at=NOW() WHERE id=$2",
            body["status"], tech_id)
    return {"message": "Status updated"}


# ══════════════════════════════════════════════════════════════════
# OPEX ROUTES
# ══════════════════════════════════════════════════════════════════

@router.get("/opex/{property_id}/summary")
async def opex_summary(property_id: int, year: int = None):
    year = year or datetime.utcnow().year
    async with pool().acquire() as c:
        actuals = await c.fetch("""
            SELECT oc.name, oc.display_name, oc.buildium_gl_account,
                   SUM(oa.amount) as ytd_actual,
                   ob.monthly_budget * 12 as annual_budget,
                   ob.monthly_budget,
                   COUNT(oa.id) as bill_count,
                   SUM(oa.amount) FILTER (WHERE oa.anomaly_flag=TRUE) as anomaly_spend
            FROM opex_categories oc
            LEFT JOIN opex_actuals oa ON oa.category_id=oc.id AND oa.property_id=$1
                AND EXTRACT(YEAR FROM oa.billing_period)=$2
            LEFT JOIN opex_budgets ob ON ob.category_id=oc.id AND ob.property_id=$1
                AND ob.budget_year=$2
            WHERE oc.is_active=TRUE
            GROUP BY oc.id, ob.monthly_budget
            ORDER BY oc.name
        """, property_id, year)
        anomalies = await c.fetch("""
            SELECT oa.*, oc.display_name
            FROM opex_anomalies oa
            JOIN opex_categories oc ON oc.id=oa.category_id
            WHERE oa.property_id=$1 AND oa.is_resolved=FALSE
            ORDER BY oa.severity DESC, oa.billing_period DESC
        """, property_id)
    return {
        "property_id": property_id,
        "year": year,
        "categories": [dict(r) for r in actuals],
        "active_anomalies": [dict(a) for a in anomalies],
    }

@router.get("/opex/{property_id}/monthly")
async def opex_monthly(property_id: int, months: int = 12):
    async with pool().acquire() as c:
        rows = await c.fetch("""
            SELECT oa.billing_period, oc.name as category, oc.display_name,
                   oa.amount, oa.anomaly_flag, oa.anomaly_severity, oa.anomaly_pct_over,
                   ob.monthly_budget
            FROM opex_actuals oa
            JOIN opex_categories oc ON oc.id=oa.category_id
            LEFT JOIN opex_budgets ob ON ob.category_id=oa.category_id
                AND ob.property_id=oa.property_id
                AND ob.budget_year=EXTRACT(YEAR FROM oa.billing_period)
            WHERE oa.property_id=$1
              AND oa.billing_period >= CURRENT_DATE - ($2::TEXT||' months')::INTERVAL
            ORDER BY oa.billing_period DESC, oc.name
        """, property_id, str(months))
    return [dict(r) for r in rows]

class OPEXActualRequest(BaseModel):
    category_name:   str
    billing_period:  date
    amount:          float
    usage_quantity:  Optional[float] = None
    usage_unit:      Optional[str]   = None
    vendor:          Optional[str]   = None
    invoice_number:  Optional[str]   = None
    invoice_date:    Optional[date]  = None
    payment_date:    Optional[date]  = None
    payment_method:  Optional[str]   = None
    notes:           Optional[str]   = None
    entered_by:      Optional[str]   = None

@router.post("/opex/{property_id}/actuals", status_code=201)
async def create_opex_actual(property_id: int, body: OPEXActualRequest,
                             background_tasks: BackgroundTasks):
    async with pool().acquire() as c:
        cat_id = await c.fetchval(
            "SELECT id FROM opex_categories WHERE name=$1 AND is_active=TRUE",
            body.category_name)
        if not cat_id:
            raise HTTPException(404, f"OPEX category '{body.category_name}' not found")

        # Insert (upsert on property+category+period)
        actual_id = await c.fetchval("""
            INSERT INTO opex_actuals
                (property_id, category_id, billing_period, amount, usage_quantity,
                 usage_unit, vendor, invoice_number, invoice_date, payment_date,
                 payment_method, notes, entered_by)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
            ON CONFLICT (property_id, category_id, billing_period)
            DO UPDATE SET amount=$4, vendor=$7, invoice_number=$8,
                payment_date=$10, notes=$12, entered_by=$13, updated_at=NOW() -- no updated_at on this table
            RETURNING id
        """, property_id, cat_id, body.billing_period, body.amount,
            body.usage_quantity, body.usage_unit, body.vendor, body.invoice_number,
            body.invoice_date, body.payment_date, body.payment_method, body.notes, body.entered_by)

    # Anomaly detection runs via DB trigger — no extra work needed here
    # Optionally push to Buildium
    import os
    if os.getenv("BUILDIUM_CLIENT_ID"):
        background_tasks.add_task(_push_opex_bill_background, actual_id)

    return {"id": actual_id}

async def _push_opex_bill_background(actual_id: int):
    import os
    from buildium.sync_engine_v2 import SyncEngine
    from buildium.client_v2 import BuildiumClient
    try:
        async with BuildiumClient(
            os.getenv("BUILDIUM_CLIENT_ID",""),
            os.getenv("BUILDIUM_CLIENT_SECRET","")
        ) as client:
            engine = SyncEngine(pool(), client)
            await engine._push_pending_opex_bills()
    except Exception as e:
        pass  # Non-critical

@router.get("/opex/anomalies")
async def list_opex_anomalies(resolved: bool = False, limit: int = 50):
    async with pool().acquire() as c:
        rows = await c.fetch("""
            SELECT oa.*, p.name as property_name, oc.display_name as category_name
            FROM opex_anomalies oa
            JOIN properties p ON p.id=oa.property_id
            JOIN opex_categories oc ON oc.id=oa.category_id
            WHERE oa.is_resolved=$1
            ORDER BY oa.severity DESC, oa.billing_period DESC
            LIMIT $2
        """, resolved, limit)
    return [dict(r) for r in rows]

@router.patch("/opex/anomalies/{anomaly_id}/resolve")
async def resolve_anomaly(anomaly_id: int, body: dict):
    async with pool().acquire() as c:
        await c.execute("""
            UPDATE opex_anomalies SET is_resolved=TRUE, resolved_at=NOW(),
                resolved_by=$1, resolution_notes=$2
            WHERE id=$3
        """, body.get("resolved_by"), body.get("resolution_notes"), anomaly_id)
        # Also clear flag on actual
        await c.execute("""
            UPDATE opex_actuals SET anomaly_resolved=TRUE
            WHERE id=(SELECT actual_id FROM opex_anomalies WHERE id=$1)
        """, anomaly_id)
    return {"message": "Anomaly resolved"}


# ══════════════════════════════════════════════════════════════════
# IoT ROUTES
# ══════════════════════════════════════════════════════════════════

@router.get("/iot/devices")
async def list_iot_devices(property_id: Optional[int] = None, status: Optional[str] = None):
    sql = "SELECT d.*, p.name as property_name FROM iot_devices d JOIN properties p ON p.id=d.property_id WHERE d.is_active=TRUE"
    params, i = [], 1
    if property_id: sql += f" AND d.property_id=${i}"; params.append(property_id); i+=1
    if status:      sql += f" AND d.status=${i}";      params.append(status); i+=1
    sql += " ORDER BY d.property_id, d.location"
    async with pool().acquire() as c:
        rows = await c.fetch(sql, *params)
    return [dict(r) for r in rows]

@router.get("/iot/devices/{device_id}/readings")
async def device_readings(device_id: int, hours: int = 24, limit: int = 1000):
    async with pool().acquire() as c:
        rows = await c.fetch("""
            SELECT reading_value, recorded_at FROM iot_readings
            WHERE device_id=$1 AND recorded_at >= NOW() - ($2::TEXT||' hours')::INTERVAL
            ORDER BY recorded_at DESC LIMIT $3
        """, device_id, str(hours), limit)
    return [dict(r) for r in rows]

@router.post("/iot/readings", status_code=201)
async def ingest_reading(body: dict):
    """Ingest a sensor reading from IoT gateway. High-volume endpoint."""
    async with pool().acquire() as c:
        dev = await c.fetchrow(
            "SELECT * FROM iot_devices WHERE device_code=$1", body.get("device_code"))
        if not dev: raise HTTPException(404, "Device not found")

        val = float(body["reading_value"])
        await c.execute("""
            INSERT INTO iot_readings(device_id, reading_value, recorded_at)
            VALUES ($1, $2, $3)
        """, dev["id"], val, body.get("recorded_at") or datetime.utcnow())

        # Update device last_reading
        trend = "stable"
        if dev["baseline_avg"]:
            pct_change = (val - float(dev["baseline_avg"])) / float(dev["baseline_avg"]) * 100
            if pct_change > 30:   trend = "rising_fast"
            elif pct_change > 10: trend = "rising"
            elif pct_change < -10: trend = "falling"

        await c.execute("""
            UPDATE iot_devices SET last_reading=$1, last_reading_at=NOW(), trend=$2,
                status=CASE
                    WHEN $1 >= threshold_critical THEN 'Alert'
                    WHEN $1 >= threshold_warn     THEN 'Warning'
                    ELSE 'Online' END,
                updated_at=NOW()
            WHERE id=$3
        """, val, trend, dev["id"])

        # Auto-create alert if threshold crossed
        alert_level = None
        if dev["threshold_critical"] and val >= float(dev["threshold_critical"]):
            alert_level = "critical"
        elif dev["threshold_warn"] and val >= float(dev["threshold_warn"]):
            alert_level = "warning"

        if alert_level:
            await c.execute("""
                INSERT INTO iot_alerts(device_id, property_id, alert_level, alert_type, message, reading_value, threshold_triggered)
                VALUES ($1,$2,$3,'threshold_exceeded',$4,$5,$6)
            """, dev["id"], dev["property_id"], alert_level,
                f"{dev['target_equipment']}: {val} {dev['reading_unit']} — threshold {'critical' if alert_level=='critical' else 'warning'} exceeded",
                val, float(dev["threshold_critical"] if alert_level=="critical" else dev["threshold_warn"]))

    return {"status": "ingested", "trend": trend, "alert": alert_level}

@router.get("/iot/alerts")
async def list_iot_alerts(status: str = "Active", property_id: Optional[int] = None):
    sql = """
        SELECT ia.*, d.device_type, d.target_equipment, d.location, d.device_code,
               p.name as property_name
        FROM iot_alerts ia
        JOIN iot_devices d ON d.id=ia.device_id
        JOIN properties p ON p.id=ia.property_id
        WHERE ia.status=$1
    """
    params = [status]
    if property_id:
        sql += " AND ia.property_id=$2"; params.append(property_id)
    sql += " ORDER BY CASE ia.alert_level WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, ia.triggered_at DESC"
    async with pool().acquire() as c:
        rows = await c.fetch(sql, *params)
    return [dict(r) for r in rows]

@router.patch("/iot/alerts/{alert_id}")
async def update_iot_alert(alert_id: int, body: dict):
    async with pool().acquire() as c:
        await c.execute("""
            UPDATE iot_alerts SET status=$1, acknowledged_by=$2, acknowledged_at=CASE
                WHEN $1='Acknowledged' THEN NOW() ELSE acknowledged_at END,
                resolved_at=CASE WHEN $1='Resolved' THEN NOW() ELSE resolved_at END
            WHERE id=$3
        """, body.get("status","Acknowledged"), body.get("acknowledged_by"), alert_id)
    return {"message": "Alert updated"}


# ══════════════════════════════════════════════════════════════════
# BUILDIUM SYNC CONTROL (webhooks + manual trigger)
# ══════════════════════════════════════════════════════════════════

@router.post("/webhooks/buildium")
async def buildium_webhook(body: dict, background_tasks: BackgroundTasks):
    """
    Receive real-time push notifications from Buildium.
    Register this URL in Buildium Developer Portal.
    """
    event = body.get("EventType", "")
    logger.info(f"Buildium webhook received: {event}")

    import os
    from buildium.sync_engine_v2 import SyncEngine
    from buildium.client_v2 import BuildiumClient

    async def handle():
        try:
            async with BuildiumClient(
                os.getenv("BUILDIUM_CLIENT_ID",""),
                os.getenv("BUILDIUM_CLIENT_SECRET","")
            ) as client:
                engine = SyncEngine(pool(), client)
                if "Maintenance" in event:
                    await engine._sync_work_orders(since=None)
                elif "Payment" in event or "Lease" in event:
                    await engine._sync_outstanding_balances()
                    await engine._sync_leases(since=None)
                elif "Vendor" in event:
                    await engine._sync_vendors()
        except Exception as e:
            logger.error(f"Webhook handler error: {e}")

    background_tasks.add_task(handle)
    return {"received": True, "event": event}
