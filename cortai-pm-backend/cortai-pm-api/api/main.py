"""
main.py — COrtai Property Intelligence Platform API
FastAPI · asyncpg · PostgreSQL · Buildium-synced + COrtai-native data

Run: uvicorn main:app --host 0.0.0.0 --port 3001 --reload
Docs: http://localhost:3001/docs
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, date
from typing import Optional, List
from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
import asyncpg
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

from api.schema import SCHEMA
from buildium.sync_engine import SyncEngine, run_sync_scheduler
from buildium.client import BuildiumClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────
DATABASE_URL      = os.getenv("DATABASE_URL", "postgresql://cortai:changethis@localhost:5432/cortai_pm")
BUILDIUM_CLIENT_ID     = os.getenv("BUILDIUM_CLIENT_ID", "97bd3408-e97f-4c66-9e43-fb8d70f11453")
BUILDIUM_CLIENT_SECRET = os.getenv("BUILDIUM_CLIENT_SECRET", "/aSnihykBkjMvHZouL0bXphASW9XwpHcWZ1x384ktlY=")

db_pool: asyncpg.Pool = None


# ── Startup / shutdown ───────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    logger.info("Starting COrtai PM API...")
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=3, max_size=20)
    
    # Apply schema
    async with db_pool.acquire() as conn:
        await conn.execute(SCHEMA)
    logger.info("Database schema applied")

    # Start Buildium sync scheduler in background
    if BUILDIUM_CLIENT_ID:
        asyncio.create_task(run_sync_scheduler(db_pool, BUILDIUM_CLIENT_ID, BUILDIUM_CLIENT_SECRET))
        logger.info("Buildium sync scheduler started")
    else:
        logger.warning("BUILDIUM_CLIENT_ID not set — sync disabled. Set env vars to enable.")

    yield

    await db_pool.close()
    logger.info("Database pool closed")


app = FastAPI(
    title="COrtai Property Intelligence Platform",
    description="Property management API for Lionston Group — Buildium-synced + extended intelligence",
    version="1.0.0",
    lifespan=lifespan
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def pool() -> asyncpg.Pool:
    return db_pool


# ════════════════════════════════════════════════════════════════════
# HEALTH & SYNC
# ════════════════════════════════════════════════════════════════════
@app.get("/api/health")
async def health():
    async with pool().acquire() as conn:
        prop_count = await conn.fetchval("SELECT COUNT(*) FROM properties")
        unit_count = await conn.fetchval("SELECT COUNT(*) FROM units")
        tenant_count = await conn.fetchval("SELECT COUNT(*) FROM tenants")
        last_sync = await conn.fetchval("SELECT MAX(created_at) FROM sync_log WHERE status='success'")
    return {
        "status": "ok",
        "company": "Lionston Group",
        "properties": prop_count,
        "units": unit_count,
        "tenants": tenant_count,
        "buildium_connected": bool(BUILDIUM_CLIENT_ID),
        "last_sync": last_sync.isoformat() if last_sync else None,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.post("/api/sync/trigger")
async def trigger_sync(background_tasks: BackgroundTasks, full: bool = False):
    """Trigger an immediate Buildium sync."""
    if not BUILDIUM_CLIENT_ID:
        raise HTTPException(400, "Buildium credentials not configured")

    async def _sync():
        async with BuildiumClient(BUILDIUM_CLIENT_ID, BUILDIUM_CLIENT_SECRET) as client:
            engine = SyncEngine(pool(), client)
            since = None if full else datetime.utcnow().replace(hour=0, minute=0)
            await engine.run_full_sync(since=since)

    background_tasks.add_task(_sync)
    return {"message": "Sync triggered", "type": "full" if full else "incremental"}


@app.get("/api/sync/log")
async def sync_log(limit: int = 50):
    async with pool().acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM sync_log ORDER BY created_at DESC LIMIT $1
        """, limit)
    return [dict(r) for r in rows]


@app.get("/api/sync/status")
async def sync_status():
    async with pool().acquire() as conn:
        stats = await conn.fetch("""
            SELECT entity_type,
                   MAX(created_at) as last_sync,
                   SUM(records_processed) as total_processed,
                   SUM(records_created) as total_created,
                   SUM(records_updated) as total_updated,
                   COUNT(CASE WHEN status='error' THEN 1 END) as errors
            FROM sync_log
            WHERE created_at > NOW() - INTERVAL '24 hours'
            GROUP BY entity_type
        """)
        pending_push = await conn.fetchval(
            "SELECT COUNT(*) FROM work_orders WHERE sync_status='pending_push'")
    return {
        "entities": [dict(r) for r in stats],
        "pending_push": pending_push,
        "buildium_connected": bool(BUILDIUM_CLIENT_ID),
    }


# ════════════════════════════════════════════════════════════════════
# PORTFOLIO / DASHBOARD
# ════════════════════════════════════════════════════════════════════
@app.get("/api/dashboard")
async def dashboard():
    async with pool().acquire() as conn:
        props = await conn.fetchrow("""
            SELECT COUNT(*) as total_properties,
                   SUM(total_units) as total_units
            FROM properties WHERE is_active=TRUE
        """)
        occupancy = await conn.fetchrow("""
            SELECT
                COUNT(DISTINCT u.id) FILTER (WHERE l.lease_status='Active') as occupied,
                COUNT(DISTINCT u.id) as total
            FROM units u
            LEFT JOIN leases l ON l.unit_id=u.id AND l.is_active=TRUE
            WHERE u.is_active=TRUE
        """)
        wo_stats = await conn.fetchrow("""
            SELECT
                COUNT(*) FILTER (WHERE status NOT IN ('Completed','Closed')) as active_wos,
                COUNT(*) FILTER (WHERE priority IN ('Emergency','Urgent') AND status NOT IN ('Completed','Closed')) as urgent_wos,
                COUNT(*) FILTER (WHERE sync_status='pending_push') as pending_push
            FROM work_orders
        """)
        arrears = await conn.fetchrow("""
            SELECT COUNT(*) as delinquent_count,
                   COALESCE(SUM(total_balance),0) as total_arrears
            FROM outstanding_balances WHERE total_balance > 0
        """)
        expiring = await conn.fetchval("""
            SELECT COUNT(*) FROM leases
            WHERE end_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '90 days'
            AND is_active=TRUE AND lease_type='Fixed'
        """)
        last_sync = await conn.fetchval("SELECT MAX(created_at) FROM sync_log WHERE status='success'")

    occ_pct = round(occupancy["occupied"] / occupancy["total"] * 100, 1) if occupancy["total"] else 0
    return {
        "total_properties": props["total_properties"],
        "total_units": props["total_units"],
        "occupied_units": occupancy["occupied"],
        "vacant_units": occupancy["total"] - occupancy["occupied"],
        "occupancy_pct": occ_pct,
        "active_work_orders": wo_stats["active_wos"],
        "urgent_work_orders": wo_stats["urgent_wos"],
        "delinquent_accounts": arrears["delinquent_count"],
        "total_arrears": float(arrears["total_arrears"]),
        "expiring_leases_90d": expiring,
        "last_buildium_sync": last_sync.isoformat() if last_sync else None,
    }


# ════════════════════════════════════════════════════════════════════
# PROPERTIES
# ════════════════════════════════════════════════════════════════════
@app.get("/api/properties")
async def list_properties(
    type: Optional[str] = None,
    region: Optional[str] = None,
    search: Optional[str] = None,
    active_only: bool = True
):
    sql = """
        SELECT p.*,
               COUNT(DISTINCT u.id) as unit_count,
               COUNT(DISTINCT u.id) FILTER (WHERE l.lease_status='Active') as occupied_count,
               COUNT(DISTINCT w.id) FILTER (WHERE w.status NOT IN ('Completed','Closed')) as active_wos,
               COALESCE(SUM(ob.total_balance),0) as total_arrears
        FROM properties p
        LEFT JOIN units u ON u.property_id=p.id AND u.is_active=TRUE
        LEFT JOIN leases l ON l.unit_id=u.id AND l.is_active=TRUE
        LEFT JOIN work_orders w ON w.property_id=p.id
        LEFT JOIN outstanding_balances ob ON ob.lease_id=l.id
        WHERE 1=1
    """
    params, i = [], 1
    if active_only:
        sql += f" AND p.is_active=TRUE"
    if type:
        sql += f" AND p.structure_type=${i}"; params.append(type); i+=1
    if region:
        sql += f" AND p.portfolio_region=${i}"; params.append(region); i+=1
    if search:
        sql += f" AND (p.name ILIKE ${i} OR p.address ILIKE ${i} OR p.city ILIKE ${i})"
        params.append(f"%{search}%"); i+=1
    sql += " GROUP BY p.id ORDER BY p.name"

    async with pool().acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return [dict(r) for r in rows]


@app.get("/api/properties/{property_id}")
async def get_property(property_id: int):
    async with pool().acquire() as conn:
        prop = await conn.fetchrow("SELECT * FROM properties WHERE id=$1", property_id)
        if not prop:
            raise HTTPException(404, "Property not found")

        systems = await conn.fetch(
            "SELECT * FROM building_systems WHERE property_id=$1 ORDER BY system_type", property_id)
        events = await conn.fetch(
            "SELECT * FROM building_events WHERE property_id=$1 ORDER BY event_date DESC LIMIT 20", property_id)
        units = await conn.fetch("""
            SELECT u.*,
                   t.first_name||' '||t.last_name as tenant_name,
                   l.rent_amount, l.lease_status, l.end_date,
                   ob.total_balance as arrears,
                   COUNT(w.id) FILTER (WHERE w.status NOT IN ('Completed','Closed')) as open_wos
            FROM units u
            LEFT JOIN leases l ON l.unit_id=u.id AND l.is_active=TRUE
            LEFT JOIN lease_residents lr ON lr.lease_id=l.id AND lr.is_primary=TRUE
            LEFT JOIN tenants t ON t.id=lr.tenant_id
            LEFT JOIN outstanding_balances ob ON ob.lease_id=l.id
            LEFT JOIN work_orders w ON w.unit_id=u.id
            WHERE u.property_id=$1 AND u.is_active=TRUE
            GROUP BY u.id, t.first_name, t.last_name, l.rent_amount, l.lease_status, l.end_date, ob.total_balance
            ORDER BY u.unit_number
        """, property_id)
        active_wos = await conn.fetch("""
            SELECT w.*, u.unit_number,
                   v.company_name as vendor_name
            FROM work_orders w
            LEFT JOIN units u ON u.id=w.unit_id
            LEFT JOIN vendors v ON v.id=w.vendor_id
            WHERE w.property_id=$1 AND w.status NOT IN ('Completed','Closed')
            ORDER BY CASE w.priority WHEN 'Emergency' THEN 0 WHEN 'Urgent' THEN 1 WHEN 'High' THEN 2 ELSE 3 END
        """, property_id)
        alerts = await conn.fetch(
            "SELECT * FROM ai_alerts WHERE property_id=$1 AND status='Active' ORDER BY priority DESC", property_id)

    return {
        **dict(prop),
        "systems": [dict(s) for s in systems],
        "recent_events": [dict(e) for e in events],
        "units": [dict(u) for u in units],
        "active_work_orders": [dict(w) for w in active_wos],
        "ai_alerts": [dict(a) for a in alerts],
    }


class PropertyUpdateRequest(BaseModel):
    portfolio_class: Optional[str] = None
    portfolio_region: Optional[str] = None
    pm_assigned: Optional[str] = None
    pin: Optional[str] = None
    assessed_value: Optional[float] = None
    purchase_price: Optional[float] = None
    purchase_date: Optional[date] = None
    mortgage_details: Optional[str] = None
    insurance_details: Optional[str] = None
    annual_tax: Optional[float] = None
    building_health: Optional[int] = None
    notes: Optional[str] = None

@app.patch("/api/properties/{property_id}")
async def update_property(property_id: int, body: PropertyUpdateRequest):
    """Update COrtai-only fields (not Buildium fields)."""
    updates = {k: v for k, v in body.dict().items() if v is not None}
    if not updates:
        raise HTTPException(400, "No fields to update")
    sets = ", ".join(f"{k}=${i+2}" for i, k in enumerate(updates))
    async with pool().acquire() as conn:
        await conn.execute(
            f"UPDATE properties SET {sets}, updated_at=NOW() WHERE id=$1",
            property_id, *updates.values()
        )
    return {"message": "Property updated"}


# ════════════════════════════════════════════════════════════════════
# BUILDING SYSTEMS
# ════════════════════════════════════════════════════════════════════
@app.get("/api/properties/{property_id}/systems")
async def get_building_systems(property_id: int):
    async with pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM building_systems WHERE property_id=$1 ORDER BY system_type", property_id)
    return [dict(r) for r in rows]

class BuildingSystemRequest(BaseModel):
    system_type: str
    system_name: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    installed_year: Optional[int] = None
    replaced_year: Optional[int] = None
    condition: str = "Good"
    warranty_expiry: Optional[date] = None
    contractor: Optional[str] = None
    contractor_phone: Optional[str] = None
    annual_service_cost: Optional[float] = None
    next_service_date: Optional[date] = None
    notes: Optional[str] = None

@app.post("/api/properties/{property_id}/systems", status_code=201)
async def add_building_system(property_id: int, body: BuildingSystemRequest):
    async with pool().acquire() as conn:
        row_id = await conn.fetchval("""
            INSERT INTO building_systems (property_id,system_type,system_name,brand,model,
                installed_year,replaced_year,condition,warranty_expiry,contractor,contractor_phone,
                annual_service_cost,next_service_date,notes)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14) RETURNING id
        """, property_id, body.system_type, body.system_name, body.brand, body.model,
            body.installed_year, body.replaced_year, body.condition, body.warranty_expiry,
            body.contractor, body.contractor_phone, body.annual_service_cost,
            body.next_service_date, body.notes)
    return {"id": row_id}

@app.patch("/api/systems/{system_id}")
async def update_building_system(system_id: int, body: dict):
    allowed = {"condition","next_service_date","last_service_date","notes","contractor","annual_service_cost"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        raise HTTPException(400, "No valid fields")
    sets = ", ".join(f"{k}=${i+2}" for i, k in enumerate(updates))
    async with pool().acquire() as conn:
        await conn.execute(f"UPDATE building_systems SET {sets}, updated_at=NOW() WHERE id=$1",
                           system_id, *updates.values())
    return {"message": "Updated"}


# ════════════════════════════════════════════════════════════════════
# BUILDING EVENTS
# ════════════════════════════════════════════════════════════════════
@app.get("/api/properties/{property_id}/events")
async def get_building_events(property_id: int, limit: int = 50):
    async with pool().acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM building_events WHERE property_id=$1 ORDER BY event_date DESC LIMIT $2
        """, property_id, limit)
    return [dict(r) for r in rows]

class BuildingEventRequest(BaseModel):
    event_date: date
    event_type: str                # 'milestone','renovation','maintenance','upgrade','inspection','incident'
    title: str
    detail: Optional[str] = None
    cost: Optional[float] = None
    vendor: Optional[str] = None
    invoice_number: Optional[str] = None
    insurance_claim: bool = False
    entered_by: Optional[str] = None

@app.post("/api/properties/{property_id}/events", status_code=201)
async def add_building_event(property_id: int, body: BuildingEventRequest):
    async with pool().acquire() as conn:
        row_id = await conn.fetchval("""
            INSERT INTO building_events (property_id,event_date,event_type,title,detail,cost,vendor,
                invoice_number,insurance_claim,entered_by)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING id
        """, property_id, body.event_date, body.event_type, body.title, body.detail,
            body.cost, body.vendor, body.invoice_number, body.insurance_claim, body.entered_by)
    return {"id": row_id}


# ════════════════════════════════════════════════════════════════════
# UNITS
# ════════════════════════════════════════════════════════════════════
@app.get("/api/units/{unit_id}")
async def get_unit(unit_id: int):
    async with pool().acquire() as conn:
        unit = await conn.fetchrow("SELECT * FROM units WHERE id=$1", unit_id)
        if not unit:
            raise HTTPException(404, "Unit not found")

        appliances = await conn.fetch(
            "SELECT * FROM unit_appliances WHERE unit_id=$1 ORDER BY appliance_type", unit_id)
        tenant_history = await conn.fetch("""
            SELECT uth.*, l.lease_type
            FROM unit_tenant_history uth
            LEFT JOIN leases l ON l.id=uth.lease_id
            WHERE uth.unit_id=$1 ORDER BY uth.period_start DESC
        """, unit_id)
        service_history = await conn.fetch("""
            SELECT w.*, v.company_name as vendor_name
            FROM work_orders w
            LEFT JOIN vendors v ON v.id=w.vendor_id
            WHERE w.unit_id=$1
            ORDER BY w.created_at DESC LIMIT 50
        """, unit_id)
        active_lease = await conn.fetchrow("""
            SELECT l.*,
                   t.id as tenant_db_id,
                   t.first_name||' '||t.last_name as tenant_name,
                   t.email as tenant_email, t.phone as tenant_phone,
                   ob.total_balance as arrears
            FROM leases l
            JOIN lease_residents lr ON lr.lease_id=l.id AND lr.is_primary=TRUE
            JOIN tenants t ON t.id=lr.tenant_id
            LEFT JOIN outstanding_balances ob ON ob.lease_id=l.id
            WHERE l.unit_id=$1 AND l.is_active=TRUE
            LIMIT 1
        """, unit_id)
        inspections = await conn.fetch("""
            SELECT * FROM inspections WHERE unit_id=$1 ORDER BY completed_date DESC LIMIT 10
        """, unit_id)

    return {
        **dict(unit),
        "appliances": [dict(a) for a in appliances],
        "tenant_history": [dict(h) for h in tenant_history],
        "service_history": [dict(s) for s in service_history],
        "active_lease": dict(active_lease) if active_lease else None,
        "inspections": [dict(i) for i in inspections],
    }

class UnitUpdateRequest(BaseModel):
    floor_number: Optional[int] = None
    facing: Optional[str] = None
    parking_spot: Optional[str] = None
    locker_number: Optional[str] = None
    unit_condition: Optional[str] = None
    notes: Optional[str] = None

@app.patch("/api/units/{unit_id}")
async def update_unit(unit_id: int, body: UnitUpdateRequest):
    updates = {k: v for k, v in body.dict().items() if v is not None}
    if not updates:
        raise HTTPException(400, "No fields to update")
    sets = ", ".join(f"{k}=${i+2}" for i, k in enumerate(updates))
    async with pool().acquire() as conn:
        await conn.execute(f"UPDATE units SET {sets}, updated_at=NOW() WHERE id=$1",
                           unit_id, *updates.values())
    return {"message": "Updated"}

class ApplianceRequest(BaseModel):
    appliance_type: str
    brand: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    installed_year: Optional[int] = None
    condition: str = "Good"
    warranty_expiry: Optional[date] = None
    notes: Optional[str] = None

@app.post("/api/units/{unit_id}/appliances", status_code=201)
async def add_appliance(unit_id: int, body: ApplianceRequest):
    async with pool().acquire() as conn:
        row_id = await conn.fetchval("""
            INSERT INTO unit_appliances (unit_id,appliance_type,brand,model,serial_number,
                installed_year,condition,warranty_expiry,notes)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING id
        """, unit_id, body.appliance_type, body.brand, body.model, body.serial_number,
            body.installed_year, body.condition, body.warranty_expiry, body.notes)
    return {"id": row_id}


# ════════════════════════════════════════════════════════════════════
# TENANTS
# ════════════════════════════════════════════════════════════════════
@app.get("/api/tenants")
async def list_tenants(
    search: Optional[str] = None,
    risk_min: Optional[int] = None,
    active_only: bool = True
):
    sql = """
        SELECT t.*,
               p.name as property_name,
               u.unit_number,
               l.rent_amount, l.end_date, l.lease_status,
               ob.total_balance as arrears
        FROM tenants t
        LEFT JOIN lease_residents lr ON lr.tenant_id=t.id AND lr.is_primary=TRUE
        LEFT JOIN leases l ON l.id=lr.lease_id AND l.is_active=TRUE
        LEFT JOIN units u ON u.id=l.unit_id
        LEFT JOIN properties p ON p.id=u.property_id
        LEFT JOIN outstanding_balances ob ON ob.lease_id=l.id
        WHERE 1=1
    """
    params, i = [], 1
    if active_only:
        sql += " AND t.is_active=TRUE"
    if search:
        sql += f" AND (t.first_name ILIKE ${i} OR t.last_name ILIKE ${i} OR t.email ILIKE ${i})"
        params.append(f"%{search}%"); i+=1
    if risk_min is not None:
        sql += f" AND t.risk_score >= ${i}"; params.append(risk_min); i+=1
    sql += " ORDER BY t.last_name, t.first_name"

    async with pool().acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return [dict(r) for r in rows]


@app.get("/api/tenants/{tenant_id}")
async def get_tenant(tenant_id: int):
    async with pool().acquire() as conn:
        tenant = await conn.fetchrow("SELECT * FROM tenants WHERE id=$1", tenant_id)
        if not tenant:
            raise HTTPException(404, "Tenant not found")

        profile = await conn.fetchrow("SELECT * FROM tenant_profiles WHERE tenant_id=$1", tenant_id)
        documents = await conn.fetch(
            "SELECT * FROM tenant_documents WHERE tenant_id=$1 ORDER BY created_at DESC", tenant_id)
        communications = await conn.fetch("""
            SELECT * FROM tenant_communications WHERE tenant_id=$1 ORDER BY comm_date DESC LIMIT 30
        """, tenant_id)
        payments = await conn.fetch("""
            SELECT p.*, l.buildium_id as lease_buildium_id
            FROM payments p
            JOIN leases l ON l.id=p.lease_id
            WHERE p.tenant_id=$1
            ORDER BY p.payment_date DESC LIMIT 24
        """, tenant_id)
        leases = await conn.fetch("""
            SELECT l.*, u.unit_number, p.name as property_name
            FROM leases l
            JOIN lease_residents lr ON lr.lease_id=l.id AND lr.tenant_id=$1
            JOIN units u ON u.id=l.unit_id
            JOIN properties p ON p.id=u.property_id
            ORDER BY l.start_date DESC
        """, tenant_id)
        work_orders = await conn.fetch("""
            SELECT w.*, u.unit_number, v.company_name as vendor_name
            FROM work_orders w
            LEFT JOIN units u ON u.id=w.unit_id
            LEFT JOIN vendors v ON v.id=w.vendor_id
            WHERE w.unit_id IN (
                SELECT DISTINCT l.unit_id FROM leases l
                JOIN lease_residents lr ON lr.lease_id=l.id WHERE lr.tenant_id=$1
            )
            ORDER BY w.created_at DESC LIMIT 20
        """, tenant_id)
        outstanding = await conn.fetchrow(
            "SELECT * FROM outstanding_balances WHERE tenant_id=$1", tenant_id)

    return {
        **dict(tenant),
        "profile": dict(profile) if profile else None,
        "documents": [dict(d) for d in documents],
        "communications": [dict(c) for c in communications],
        "payments": [dict(p) for p in payments],
        "leases": [dict(l) for l in leases],
        "work_orders": [dict(w) for w in work_orders],
        "outstanding_balance": dict(outstanding) if outstanding else None,
    }


class TenantProfileRequest(BaseModel):
    employer: Optional[str] = None
    employer_phone: Optional[str] = None
    position: Optional[str] = None
    employment_start: Optional[date] = None
    annual_income: Optional[float] = None
    income_verified_by: Optional[str] = None
    income_verified_at: Optional[date] = None
    income_doc_type: Optional[str] = None
    credit_score: Optional[int] = None
    credit_checked_at: Optional[date] = None
    emergency_name: Optional[str] = None
    emergency_relation: Optional[str] = None
    emergency_phone: Optional[str] = None
    pets: Optional[bool] = None
    pet_description: Optional[str] = None
    smoker: Optional[bool] = None
    vehicles: Optional[int] = None
    vehicle_plates: Optional[str] = None
    occupant_names: Optional[str] = None
    risk_score: Optional[int] = None
    risk_label: Optional[str] = None
    private_notes: Optional[str] = None

@app.put("/api/tenants/{tenant_id}/profile")
async def upsert_tenant_profile(tenant_id: int, body: TenantProfileRequest):
    """Create or update extended tenant profile (COrtai-only fields)."""
    updates = {k: v for k, v in body.dict().items() if v is not None}
    async with pool().acquire() as conn:
        exists = await conn.fetchval("SELECT id FROM tenant_profiles WHERE tenant_id=$1", tenant_id)
        if exists:
            sets = ", ".join(f"{k}=${i+2}" for i, k in enumerate(updates))
            if sets:
                await conn.execute(f"UPDATE tenant_profiles SET {sets}, updated_at=NOW() WHERE tenant_id=$1",
                                   tenant_id, *updates.values())
        else:
            cols = "tenant_id, " + ", ".join(updates)
            vals = ", ".join(f"${i+1}" for i in range(len(updates)+1))
            await conn.execute(
                f"INSERT INTO tenant_profiles ({cols}) VALUES ({vals})",
                tenant_id, *updates.values()
            )
    return {"message": "Profile saved"}


class CommunicationRequest(BaseModel):
    comm_date: datetime = Field(default_factory=datetime.utcnow)
    comm_type: str
    direction: str
    subject: Optional[str] = None
    summary: str
    outcome: Optional[str] = None
    follow_up_required: bool = False
    follow_up_date: Optional[date] = None
    logged_by: Optional[str] = None

@app.post("/api/tenants/{tenant_id}/communications", status_code=201)
async def log_communication(tenant_id: int, body: CommunicationRequest):
    async with pool().acquire() as conn:
        row_id = await conn.fetchval("""
            INSERT INTO tenant_communications (tenant_id,comm_date,comm_type,direction,subject,summary,
                outcome,follow_up_required,follow_up_date,logged_by)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING id
        """, tenant_id, body.comm_date, body.comm_type, body.direction, body.subject,
            body.summary, body.outcome, body.follow_up_required, body.follow_up_date, body.logged_by)
    return {"id": row_id}

@app.post("/api/tenants/{tenant_id}/documents", status_code=201)
async def add_tenant_document(tenant_id: int, body: dict):
    async with pool().acquire() as conn:
        row_id = await conn.fetchval("""
            INSERT INTO tenant_documents (tenant_id,doc_type,doc_name,file_url,is_signed,signed_date,notes,uploaded_by)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id
        """, tenant_id, body["doc_type"], body.get("doc_name"), body.get("file_url"),
            body.get("is_signed",False), body.get("signed_date"), body.get("notes"), body.get("uploaded_by"))
    return {"id": row_id}


# ════════════════════════════════════════════════════════════════════
# WORK ORDERS
# ════════════════════════════════════════════════════════════════════
@app.get("/api/work-orders")
async def list_work_orders(
    property_id: Optional[int] = None,
    unit_id: Optional[int] = None,
    priority: Optional[str] = None,
    status: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 100
):
    sql = """
        SELECT w.*,
               u.unit_number, p.name as property_name,
               v.company_name as vendor_name,
               t.first_name||' '||t.last_name as tenant_name
        FROM work_orders w
        LEFT JOIN units u ON u.id=w.unit_id
        LEFT JOIN properties p ON p.id=w.property_id
        LEFT JOIN vendors v ON v.id=w.vendor_id
        LEFT JOIN leases l ON l.unit_id=u.id AND l.is_active=TRUE
        LEFT JOIN lease_residents lr ON lr.lease_id=l.id AND lr.is_primary=TRUE
        LEFT JOIN tenants t ON t.id=lr.tenant_id
        WHERE 1=1
    """
    params, i = [], 1
    if property_id:
        sql += f" AND w.property_id=${i}"; params.append(property_id); i+=1
    if unit_id:
        sql += f" AND w.unit_id=${i}"; params.append(unit_id); i+=1
    if priority:
        sql += f" AND w.priority=${i}"; params.append(priority); i+=1
    if status:
        sql += f" AND w.status=${i}"; params.append(status); i+=1
    if category:
        sql += f" AND w.category=${i}"; params.append(category); i+=1
    sql += f" ORDER BY CASE w.priority WHEN 'Emergency' THEN 0 WHEN 'Urgent' THEN 1 WHEN 'High' THEN 2 WHEN 'Normal' THEN 3 ELSE 4 END, w.created_at DESC LIMIT ${i}"
    params.append(limit)

    async with pool().acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return [dict(r) for r in rows]


class WorkOrderRequest(BaseModel):
    property_id: Optional[int] = None
    unit_id: Optional[int] = None
    vendor_id: Optional[int] = None
    title: str
    description: Optional[str] = None
    category: str = "General"
    priority: str = "Normal"
    est_cost: Optional[float] = None
    scheduled_date: Optional[date] = None
    submitted_by: Optional[str] = None
    submitted_source: str = "COrtai"
    tenant_notified: bool = False
    is_tenant_caused: bool = False
    is_recurring: bool = False
    recurring_interval: Optional[str] = None
    notes: Optional[str] = None

@app.post("/api/work-orders", status_code=201)
async def create_work_order(body: WorkOrderRequest, background_tasks: BackgroundTasks):
    # Auto-generate WO number
    async with pool().acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM work_orders") or 0
        wo_number = f"WO-{2500 + count + 1}"
        row_id = await conn.fetchval("""
            INSERT INTO work_orders (property_id,unit_id,vendor_id,wo_number,title,description,
                category,priority,status,est_cost,scheduled_date,submitted_by,submitted_source,
                tenant_notified,is_tenant_caused,is_recurring,recurring_interval,notes,sync_status)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'Submitted',$9,$10,$11,$12,$13,$14,$15,$16,$17,'pending_push')
            RETURNING id
        """, body.property_id, body.unit_id, body.vendor_id, wo_number, body.title,
            body.description, body.category, body.priority, body.est_cost, body.scheduled_date,
            body.submitted_by, body.submitted_source, body.tenant_notified, body.is_tenant_caused,
            body.is_recurring, body.recurring_interval, body.notes)

    # Push to Buildium in background if configured
    if BUILDIUM_CLIENT_ID:
        async def push():
            async with BuildiumClient(BUILDIUM_CLIENT_ID, BUILDIUM_CLIENT_SECRET) as client:
                engine = SyncEngine(pool(), client)
                await engine._push_pending_work_orders()
        background_tasks.add_task(push)

    return {"id": row_id, "wo_number": wo_number}


class WorkOrderStatusUpdate(BaseModel):
    status: str
    actual_cost: Optional[float] = None
    invoice_number: Optional[str] = None
    notes: Optional[str] = None

@app.patch("/api/work-orders/{wo_id}/status")
async def update_wo_status(wo_id: int, body: WorkOrderStatusUpdate, background_tasks: BackgroundTasks):
    async with pool().acquire() as conn:
        await conn.execute("""
            UPDATE work_orders SET status=$1, actual_cost=COALESCE($2,actual_cost),
                invoice_number=COALESCE($3,invoice_number),
                completed_date=CASE WHEN $1 IN ('Completed','Closed') THEN CURRENT_DATE ELSE completed_date END,
                sync_status='pending_push', updated_at=NOW()
            WHERE id=$4
        """, body.status, body.actual_cost, body.invoice_number, wo_id)
        if body.notes:
            await conn.execute(
                "UPDATE work_orders SET notes=notes||E'\n---\n'||$1 WHERE id=$2", body.notes, wo_id)

    if BUILDIUM_CLIENT_ID:
        async def push_status():
            async with BuildiumClient(BUILDIUM_CLIENT_ID, BUILDIUM_CLIENT_SECRET) as client:
                engine = SyncEngine(pool(), client)
                await engine.push_wo_status_update(wo_id, body.status, body.notes)
        background_tasks.add_task(push_status)

    return {"message": "Work order updated"}


# ════════════════════════════════════════════════════════════════════
# LEASES
# ════════════════════════════════════════════════════════════════════
@app.get("/api/leases/expiring")
async def expiring_leases(days: int = 90):
    async with pool().acquire() as conn:
        rows = await conn.fetch("""
            SELECT l.*,
                   u.unit_number, p.name as property_name,
                   t.first_name||' '||t.last_name as tenant_name,
                   ob.total_balance as arrears
            FROM leases l
            JOIN units u ON u.id=l.unit_id
            JOIN properties p ON p.id=u.property_id
            JOIN lease_residents lr ON lr.lease_id=l.id AND lr.is_primary=TRUE
            JOIN tenants t ON t.id=lr.tenant_id
            LEFT JOIN outstanding_balances ob ON ob.lease_id=l.id
            WHERE l.end_date BETWEEN CURRENT_DATE AND CURRENT_DATE + ($1 || ' days')::INTERVAL
            AND l.is_active=TRUE
            ORDER BY l.end_date
        """, str(days))
    return [dict(r) for r in rows]


class LeaseRenewalOffer(BaseModel):
    renewal_offer_amount: float
    renewal_offer_date: Optional[date] = None

@app.post("/api/leases/{lease_id}/renewal-offer")
async def create_renewal_offer(lease_id: int, body: LeaseRenewalOffer):
    async with pool().acquire() as conn:
        await conn.execute("""
            UPDATE leases SET renewal_offered=TRUE, renewal_offer_amount=$1,
                renewal_offer_date=COALESCE($2,CURRENT_DATE), renewal_response='Pending',
                updated_at=NOW()
            WHERE id=$3
        """, body.renewal_offer_amount, body.renewal_offer_date, lease_id)
    return {"message": "Renewal offer recorded"}


# ════════════════════════════════════════════════════════════════════
# INSPECTIONS
# ════════════════════════════════════════════════════════════════════
@app.get("/api/inspections")
async def list_inspections(
    property_id: Optional[int] = None,
    type: Optional[str] = None,
    status: Optional[str] = None
):
    sql = """
        SELECT i.*,
               u.unit_number, p.name as property_name
        FROM inspections i
        LEFT JOIN units u ON u.id=i.unit_id
        LEFT JOIN properties p ON p.id=i.property_id
        WHERE 1=1
    """
    params, idx = [], 1
    if property_id:
        sql += f" AND (i.property_id=${idx} OR u.property_id=${idx})"; params.append(property_id); idx+=1
    if type:
        sql += f" AND i.inspection_type=${idx}"; params.append(type); idx+=1
    if status:
        sql += f" AND i.status=${idx}"; params.append(status); idx+=1
    sql += " ORDER BY i.scheduled_date DESC LIMIT 100"

    async with pool().acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return [dict(r) for r in rows]


class InspectionRequest(BaseModel):
    unit_id: Optional[int] = None
    property_id: Optional[int] = None
    lease_id: Optional[int] = None
    inspection_type: str
    scheduled_date: Optional[date] = None
    inspector_name: Optional[str] = None

@app.post("/api/inspections", status_code=201)
async def create_inspection(body: InspectionRequest):
    async with pool().acquire() as conn:
        row_id = await conn.fetchval("""
            INSERT INTO inspections (unit_id,property_id,lease_id,inspection_type,scheduled_date,inspector_name)
            VALUES ($1,$2,$3,$4,$5,$6) RETURNING id
        """, body.unit_id, body.property_id, body.lease_id, body.inspection_type,
            body.scheduled_date, body.inspector_name)
    return {"id": row_id}


@app.get("/api/inspections/{inspection_id}")
async def get_inspection(inspection_id: int):
    async with pool().acquire() as conn:
        insp = await conn.fetchrow("SELECT * FROM inspections WHERE id=$1", inspection_id)
        if not insp:
            raise HTTPException(404, "Inspection not found")
        items = await conn.fetch(
            "SELECT * FROM inspection_items WHERE inspection_id=$1 ORDER BY sort_order", inspection_id)
    return {**dict(insp), "items": [dict(i) for i in items]}


@app.post("/api/inspections/{inspection_id}/items", status_code=201)
async def add_inspection_item(inspection_id: int, body: dict):
    async with pool().acquire() as conn:
        row_id = await conn.fetchval("""
            INSERT INTO inspection_items (inspection_id,room_name,item_name,condition_in,condition_out,
                is_tenant_caused,charge_amount,charge_description,notes,sort_order)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING id
        """, inspection_id, body["room_name"], body["item_name"],
            body.get("condition_in"), body.get("condition_out"),
            body.get("is_tenant_caused",False), body.get("charge_amount"),
            body.get("charge_description"), body.get("notes"), body.get("sort_order",0))

        # Update total charges
        await conn.execute("""
            UPDATE inspections SET total_charges=(
                SELECT COALESCE(SUM(charge_amount),0) FROM inspection_items WHERE inspection_id=$1
            ), updated_at=NOW() WHERE id=$1
        """, inspection_id)
    return {"id": row_id}


# ════════════════════════════════════════════════════════════════════
# VENDORS
# ════════════════════════════════════════════════════════════════════
@app.get("/api/vendors")
async def list_vendors(specialty: Optional[str] = None, preferred_only: bool = False):
    sql = """
        SELECT v.*,
               COALESCE(AVG(vr.rating),0) as avg_rating,
               COUNT(DISTINCT w.id) FILTER (WHERE w.status NOT IN ('Completed','Closed')) as active_wos,
               COALESCE(SUM(w.actual_cost) FILTER (WHERE EXTRACT(YEAR FROM w.completed_date)=EXTRACT(YEAR FROM CURRENT_DATE)),0) as ytd_spend
        FROM vendors v
        LEFT JOIN vendor_ratings vr ON vr.vendor_id=v.id
        LEFT JOIN work_orders w ON w.vendor_id=v.id
        WHERE v.is_active=TRUE
    """
    params, i = [], 1
    if specialty:
        sql += f" AND v.specialty=${i}"; params.append(specialty); i+=1
    if preferred_only:
        sql += " AND v.is_preferred=TRUE"
    sql += " GROUP BY v.id ORDER BY is_preferred DESC, avg_rating DESC"

    async with pool().acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return [dict(r) for r in rows]


class VendorRequest(BaseModel):
    company_name: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    specialty: Optional[str] = None
    license_type: Optional[str] = None
    license_number: Optional[str] = None
    insurance_amount: Optional[str] = None
    is_preferred: bool = False
    notes: Optional[str] = None

@app.post("/api/vendors", status_code=201)
async def create_vendor(body: VendorRequest, background_tasks: BackgroundTasks):
    async with pool().acquire() as conn:
        row_id = await conn.fetchval("""
            INSERT INTO vendors (company_name,first_name,last_name,email,phone,
                specialty,license_type,license_number,insurance_amount,is_preferred,notes)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) RETURNING id
        """, body.company_name, body.first_name, body.last_name, body.email, body.phone,
            body.specialty, body.license_type, body.license_number,
            body.insurance_amount, body.is_preferred, body.notes)

    # Optionally push to Buildium as vendor
    return {"id": row_id}


# ════════════════════════════════════════════════════════════════════
# AI ALERTS
# ════════════════════════════════════════════════════════════════════
@app.get("/api/ai-alerts")
async def list_ai_alerts(status: str = "Active", limit: int = 50):
    async with pool().acquire() as conn:
        rows = await conn.fetch("""
            SELECT a.*, p.name as property_name, u.unit_number,
                   t.first_name||' '||t.last_name as tenant_name
            FROM ai_alerts a
            LEFT JOIN properties p ON p.id=a.property_id
            LEFT JOIN units u ON u.id=a.unit_id
            LEFT JOIN tenants t ON t.id=a.tenant_id
            WHERE a.status=$1
            ORDER BY CASE a.priority WHEN 'Emergency' THEN 0 WHEN 'Urgent' THEN 1 WHEN 'High' THEN 2 ELSE 3 END,
                     a.created_at DESC
            LIMIT $2
        """, status, limit)
    return [dict(r) for r in rows]

@app.patch("/api/ai-alerts/{alert_id}/action")
async def action_alert(alert_id: int, body: dict):
    async with pool().acquire() as conn:
        await conn.execute("""
            UPDATE ai_alerts SET status=$1, actioned_by=$2, actioned_at=NOW()
            WHERE id=$3
        """, body.get("status","Actioned"), body.get("actioned_by"), alert_id)
    return {"message": "Alert actioned"}


# ════════════════════════════════════════════════════════════════════
# FINANCIALS
# ════════════════════════════════════════════════════════════════════
@app.get("/api/financials/rent-roll")
async def rent_roll(property_id: Optional[int] = None):
    sql = """
        SELECT p.name as property_name, u.unit_number,
               t.first_name||' '||t.last_name as tenant_name,
               l.rent_amount, l.start_date, l.end_date, l.lease_type, l.lease_status,
               ob.total_balance as arrears,
               pay.last_payment_date, pay.last_payment_amount
        FROM leases l
        JOIN units u ON u.id=l.unit_id
        JOIN properties p ON p.id=u.property_id
        JOIN lease_residents lr ON lr.lease_id=l.id AND lr.is_primary=TRUE
        JOIN tenants t ON t.id=lr.tenant_id
        LEFT JOIN outstanding_balances ob ON ob.lease_id=l.id
        LEFT JOIN LATERAL (
            SELECT MAX(payment_date) as last_payment_date,
                   MAX(amount) FILTER (WHERE payment_date=MAX(payment_date)) as last_payment_amount
            FROM payments WHERE lease_id=l.id AND is_voided=FALSE
        ) pay ON TRUE
        WHERE l.is_active=TRUE
    """
    params = []
    if property_id:
        sql += " AND u.property_id=$1"; params.append(property_id)
    sql += " ORDER BY p.name, u.unit_number"

    async with pool().acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return [dict(r) for r in rows]


@app.get("/api/financials/delinquency")
async def delinquency_report():
    async with pool().acquire() as conn:
        rows = await conn.fetch("""
            SELECT p.name as property_name, u.unit_number,
                   t.first_name||' '||t.last_name as tenant_name,
                   t.email, t.phone, t.flags,
                   ob.total_balance, ob.as_of_date,
                   l.rent_amount, l.lease_status
            FROM outstanding_balances ob
            JOIN leases l ON l.id=ob.lease_id
            JOIN units u ON u.id=l.unit_id
            JOIN properties p ON p.id=u.property_id
            JOIN tenants t ON t.id=ob.tenant_id
            WHERE ob.total_balance > 0
            ORDER BY ob.total_balance DESC
        """)
    return [dict(r) for r in rows]


@app.get("/api/financials/summary")
async def financial_summary():
    async with pool().acquire() as conn:
        rent_roll = await conn.fetchrow("""
            SELECT
                COUNT(DISTINCT l.id) as active_leases,
                COALESCE(SUM(l.rent_amount),0) as monthly_rent_roll
            FROM leases l WHERE l.is_active=TRUE
        """)
        arrears = await conn.fetchrow("""
            SELECT COUNT(*) as delinquent_count, COALESCE(SUM(total_balance),0) as total_arrears
            FROM outstanding_balances WHERE total_balance > 0
        """)
        wo_costs = await conn.fetchrow("""
            SELECT
                COALESCE(SUM(actual_cost) FILTER (WHERE EXTRACT(YEAR FROM completed_date)=EXTRACT(YEAR FROM CURRENT_DATE)),0) as ytd_wo_spend,
                COALESCE(SUM(actual_cost) FILTER (WHERE EXTRACT(MONTH FROM completed_date)=EXTRACT(MONTH FROM CURRENT_DATE)),0) as mtd_wo_spend
            FROM work_orders WHERE status IN ('Completed','Closed')
        """)
    return {
        "monthly_rent_roll": float(rent_roll["monthly_rent_roll"]),
        "active_leases": rent_roll["active_leases"],
        "delinquent_count": arrears["delinquent_count"],
        "total_arrears": float(arrears["total_arrears"]),
        "ytd_wo_spend": float(wo_costs["ytd_wo_spend"]),
        "mtd_wo_spend": float(wo_costs["mtd_wo_spend"]),
    }


# ════════════════════════════════════════════════════════════════════
# PM NOTES
# ════════════════════════════════════════════════════════════════════
@app.get("/api/notes")
async def list_notes(property_id: Optional[int] = None, resolved: bool = False):
    sql = "SELECT * FROM pm_notes WHERE is_resolved=$1"
    params = [resolved]
    if property_id:
        sql += " AND property_id=$2"; params.append(property_id)
    sql += " ORDER BY created_at DESC LIMIT 50"
    async with pool().acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return [dict(r) for r in rows]

@app.post("/api/notes", status_code=201)
async def create_note(body: dict):
    async with pool().acquire() as conn:
        row_id = await conn.fetchval("""
            INSERT INTO pm_notes (property_id,unit_id,tenant_id,work_order_id,note_type,priority,content,due_date,created_by)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING id
        """, body.get("property_id"), body.get("unit_id"), body.get("tenant_id"),
            body.get("work_order_id"), body.get("note_type","General"),
            body.get("priority","Normal"), body["content"],
            body.get("due_date"), body.get("created_by"))
    return {"id": row_id}
