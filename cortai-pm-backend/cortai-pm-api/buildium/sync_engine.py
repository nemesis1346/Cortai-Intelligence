"""
sync_engine.py — Buildium ↔ COrtai Sync Orchestrator

Pull strategy:  Full sync on first run. Incremental (by last_modified) every 4 hours.
Push strategy:  Work orders push to Buildium immediately on creation/status change.
Conflict rule:  Buildium wins for base fields. COrtai wins for extended fields.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Optional
import asyncpg
from buildium.client import BuildiumClient, BuildiumAPIError, parse_buildium_date

logger = logging.getLogger(__name__)


class SyncEngine:

    def __init__(self, db_pool: asyncpg.Pool, buildium: BuildiumClient):
        self.db = db_pool
        self.b = buildium

    # ══════════════════════════════════════════════════════════════════
    # MASTER SYNC — call this on startup and every 4 hours
    # ══════════════════════════════════════════════════════════════════
    async def run_full_sync(self, since: Optional[datetime] = None):
        """
        Pull everything from Buildium in dependency order:
        owners → properties → units → tenants → leases → work_orders → payments
        """
        start = time.time()
        logger.info(f"=== Buildium Full Sync Started {'(incremental: '+since.isoformat()+')' if since else '(full)'} ===")

        try:
            await self._sync_owners()
            await self._sync_properties(since)
            await self._sync_units(since)
            await self._sync_tenants(since)
            await self._sync_leases(since)
            await self._sync_outstanding_balances()
            await self._sync_vendors()
            # Work orders: pull Buildium-originated, then push COrtai-created ones back
            await self._sync_work_orders(since)
            await self._push_pending_work_orders()

            duration = int((time.time() - start) * 1000)
            await self._log_sync("full", "all", None, "pull", "success",
                                 duration_ms=duration, triggered_by="scheduler")
            logger.info(f"=== Sync Complete in {duration/1000:.1f}s ===")

        except Exception as e:
            logger.error(f"Sync failed: {e}", exc_info=True)
            await self._log_sync("full", "all", None, "pull", "error", error_message=str(e))
            raise

    # ── Owners ─────────────────────────────────────────────────────
    async def _sync_owners(self):
        t = time.time()
        owners = await self.b.get_owners()
        created, updated = 0, 0
        async with self.db.acquire() as conn:
            for o in owners:
                exists = await conn.fetchval("SELECT id FROM owners WHERE buildium_id=$1", o["buildium_id"])
                if exists:
                    await conn.execute("""
                        UPDATE owners SET first_name=$1, last_name=$2, company_name=$3,
                            email=$4, phone=$5, is_company=$6, is_active=$7, last_synced_at=NOW()
                        WHERE buildium_id=$8
                    """, o["first_name"], o["last_name"], o["company_name"],
                        o["email"], o["phone"], o["is_company"], o["is_active"], o["buildium_id"])
                    updated += 1
                else:
                    await conn.execute("""
                        INSERT INTO owners (buildium_id,first_name,last_name,company_name,email,phone,is_company,is_active)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                    """, o["buildium_id"], o["first_name"], o["last_name"], o["company_name"],
                        o["email"], o["phone"], o["is_company"], o["is_active"])
                    created += 1
        await self._log_sync("full","owners",None,"pull","success",len(owners),created,updated,0,int((time.time()-t)*1000))
        logger.info(f"  Owners: {len(owners)} total · {created} new · {updated} updated")

    # ── Properties ─────────────────────────────────────────────────
    async def _sync_properties(self, since: Optional[datetime] = None):
        t = time.time()
        props = await self.b.get_properties(since)
        created, updated = 0, 0
        async with self.db.acquire() as conn:
            for p in props:
                exists = await conn.fetchval("SELECT id FROM properties WHERE buildium_id=$1", p["buildium_id"])
                if exists:
                    await conn.execute("""
                        UPDATE properties SET name=$1, address=$2, city=$3, state_province=$4,
                            postal_code=$5, structure_type=$6, total_units=$7, year_built=$8,
                            is_active=$9, buildium_updated_at=$10, last_synced_at=NOW()
                        WHERE buildium_id=$11
                    """, p["name"], p["address"], p["city"], p["state_province"],
                        p["postal_code"], p["structure_type"], None, p.get("year_built"),
                        p["is_active"], p.get("buildium_updated_at"), p["buildium_id"])
                    updated += 1
                else:
                    await conn.execute("""
                        INSERT INTO properties (buildium_id,name,address,city,state_province,
                            postal_code,structure_type,year_built,is_active,buildium_created_at,buildium_updated_at)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                    """, p["buildium_id"], p["name"], p["address"], p["city"],
                        p["state_province"], p["postal_code"], p["structure_type"],
                        p.get("year_built"), p["is_active"],
                        p.get("buildium_created_at"), p.get("buildium_updated_at"))
                    created += 1
        await self._log_sync("full","properties",None,"pull","success",len(props),created,updated,0,int((time.time()-t)*1000))
        logger.info(f"  Properties: {len(props)} total · {created} new · {updated} updated")

    # ── Units ───────────────────────────────────────────────────────
    async def _sync_units(self, since: Optional[datetime] = None):
        t = time.time()
        units = await self.b.get_units()
        created, updated, skipped = 0, 0, 0
        async with self.db.acquire() as conn:
            for u in units:
                # Resolve property FK
                prop_bid = u.pop("_property_buildium_id", None)
                if not prop_bid:
                    skipped += 1
                    continue
                prop_id = await conn.fetchval("SELECT id FROM properties WHERE buildium_id=$1", prop_bid)
                if not prop_id:
                    logger.warning(f"Unit {u['buildium_id']}: property {prop_bid} not found in DB")
                    skipped += 1
                    continue

                exists = await conn.fetchval("SELECT id FROM units WHERE buildium_id=$1", u["buildium_id"])
                if exists:
                    await conn.execute("""
                        UPDATE units SET unit_number=$1, unit_type=$2, beds=$3, baths=$4,
                            sqft=$5, market_rent=$6, is_active=$7, last_synced_at=NOW()
                        WHERE buildium_id=$8
                    """, u["unit_number"], u.get("unit_type"), u.get("beds"),
                        u.get("baths"), u.get("sqft"), u.get("market_rent"),
                        u.get("is_active", True), u["buildium_id"])
                    updated += 1
                else:
                    await conn.execute("""
                        INSERT INTO units (buildium_id,property_id,unit_number,unit_type,beds,baths,sqft,market_rent,is_active)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                    """, u["buildium_id"], prop_id, u["unit_number"], u.get("unit_type"),
                        u.get("beds"), u.get("baths"), u.get("sqft"), u.get("market_rent"), u.get("is_active",True))
                    created += 1

        await self._log_sync("full","units",None,"pull","success",len(units),created,updated,skipped,int((time.time()-t)*1000))
        logger.info(f"  Units: {len(units)} total · {created} new · {updated} updated · {skipped} skipped")

    # ── Tenants ─────────────────────────────────────────────────────
    async def _sync_tenants(self, since: Optional[datetime] = None):
        t = time.time()
        tenants = await self.b.get_tenants()
        created, updated = 0, 0
        async with self.db.acquire() as conn:
            for tn in tenants:
                exists = await conn.fetchval("SELECT id FROM tenants WHERE buildium_id=$1", tn["buildium_id"])
                if exists:
                    await conn.execute("""
                        UPDATE tenants SET first_name=$1, last_name=$2, email=$3,
                            phone=$4, is_active=$5, last_synced_at=NOW()
                        WHERE buildium_id=$6
                    """, tn["first_name"], tn["last_name"], tn["email"],
                        tn["phone"], tn["is_active"], tn["buildium_id"])
                    updated += 1
                else:
                    await conn.execute("""
                        INSERT INTO tenants (buildium_id,first_name,last_name,email,phone,is_active,buildium_created_at)
                        VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """, tn["buildium_id"], tn["first_name"], tn["last_name"],
                        tn["email"], tn["phone"], tn["is_active"], tn.get("buildium_created_at"))
                    created += 1

        await self._log_sync("full","tenants",None,"pull","success",len(tenants),created,updated,0,int((time.time()-t)*1000))
        logger.info(f"  Tenants: {len(tenants)} total · {created} new · {updated} updated")

    # ── Leases ──────────────────────────────────────────────────────
    async def _sync_leases(self, since: Optional[datetime] = None):
        t = time.time()
        leases = await self.b.get_leases()
        created, updated, skipped = 0, 0, 0
        async with self.db.acquire() as conn:
            for ls in leases:
                residents = ls.pop("_residents", [])
                unit_bid  = ls.pop("_unit_buildium_id", None)
                unit_id   = await conn.fetchval("SELECT id FROM units WHERE buildium_id=$1", unit_bid) if unit_bid else None

                exists = await conn.fetchval("SELECT id FROM leases WHERE buildium_id=$1", ls["buildium_id"])
                if exists:
                    await conn.execute("""
                        UPDATE leases SET lease_type=$1, lease_status=$2, rent_amount=$3,
                            security_deposit=$4, start_date=$5, end_date=$6, move_in_date=$7,
                            move_out_date=$8, is_active=$9, buildium_updated_at=$10, last_synced_at=NOW()
                        WHERE buildium_id=$11
                    """, ls["lease_type"], ls["lease_status"], ls["rent_amount"],
                        ls["security_deposit"], ls.get("start_date"), ls.get("end_date"),
                        ls.get("move_in_date"), ls.get("move_out_date"), ls["is_active"],
                        ls.get("buildium_updated_at"), ls["buildium_id"])
                    lease_id = await conn.fetchval("SELECT id FROM leases WHERE buildium_id=$1", ls["buildium_id"])
                    updated += 1
                else:
                    lease_id = await conn.fetchval("""
                        INSERT INTO leases (buildium_id,unit_id,lease_type,lease_status,rent_amount,
                            security_deposit,start_date,end_date,move_in_date,move_out_date,is_active)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) RETURNING id
                    """, ls["buildium_id"], unit_id, ls["lease_type"], ls["lease_status"],
                        ls["rent_amount"], ls["security_deposit"], ls.get("start_date"),
                        ls.get("end_date"), ls.get("move_in_date"), ls.get("move_out_date"), ls["is_active"])
                    created += 1

                # Sync lease residents
                for res in residents:
                    tenant_bid = res.get("Id") or res.get("ResidentId")
                    if not tenant_bid:
                        continue
                    tenant_id = await conn.fetchval("SELECT id FROM tenants WHERE buildium_id=$1", tenant_bid)
                    if tenant_id and lease_id:
                        await conn.execute("""
                            INSERT INTO lease_residents (buildium_id,lease_id,tenant_id,is_primary,move_in_date,move_out_date)
                            VALUES ($1,$2,$3,$4,$5,$6)
                            ON CONFLICT (buildium_id) DO UPDATE SET last_synced_at=NOW()
                        """, res.get("Id"), lease_id, tenant_id,
                            res.get("IsPrimary", True), parse_buildium_date(res.get("MoveInDate")),
                            parse_buildium_date(res.get("MoveOutDate")))

        await self._log_sync("full","leases",None,"pull","success",len(leases),created,updated,skipped,int((time.time()-t)*1000))
        logger.info(f"  Leases: {len(leases)} total · {created} new · {updated} updated")

    # ── Outstanding Balances ────────────────────────────────────────
    async def _sync_outstanding_balances(self):
        balances = await self.b.get_outstanding_balances()
        async with self.db.acquire() as conn:
            for bal in balances:
                lease_bid = bal.get("LeaseId")
                tenant_bid = bal.get("TenantId")
                lease_id = await conn.fetchval("SELECT id FROM leases WHERE buildium_id=$1", lease_bid) if lease_bid else None
                tenant_id = await conn.fetchval("SELECT id FROM tenants WHERE buildium_id=$1", tenant_bid) if tenant_bid else None
                if not lease_id:
                    continue
                await conn.execute("""
                    INSERT INTO outstanding_balances (buildium_id,lease_id,tenant_id,total_balance,as_of_date)
                    VALUES ($1,$2,$3,$4,$5)
                    ON CONFLICT (buildium_id) DO UPDATE
                        SET lease_id=EXCLUDED.lease_id, tenant_id=EXCLUDED.tenant_id,
                            total_balance=EXCLUDED.total_balance, as_of_date=EXCLUDED.as_of_date,
                            last_synced_at=NOW()
                """, bal.get("Id"), lease_id, tenant_id,
                    bal.get("TotalBalance",0), datetime.utcnow().date())
        logger.info(f"  Outstanding Balances: {len(balances)} synced")

    # ── Vendors ─────────────────────────────────────────────────────
    async def _sync_vendors(self):
        t = time.time()
        vendors = await self.b.get_vendors()
        created, updated = 0, 0
        async with self.db.acquire() as conn:
            for v in vendors:
                exists = await conn.fetchval("SELECT id FROM vendors WHERE buildium_id=$1", v["buildium_id"])
                if exists:
                    await conn.execute("""
                        UPDATE vendors SET company_name=$1, email=$2, phone=$3,
                            is_active=$4, last_synced_at=NOW()
                        WHERE buildium_id=$5
                    """, v["company_name"], v.get("email"), v.get("phone"), v.get("is_active",True), v["buildium_id"])
                    updated += 1
                else:
                    await conn.execute("""
                        INSERT INTO vendors (buildium_id,company_name,first_name,last_name,email,phone,is_active,is_1099)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                    """, v["buildium_id"], v["company_name"], v.get("first_name"), v.get("last_name"),
                        v.get("email"), v.get("phone"), v.get("is_active",True), v.get("is_1099",False))
                    created += 1
        logger.info(f"  Vendors: {len(vendors)} total · {created} new · {updated} updated")

    # ── Work Orders Pull ────────────────────────────────────────────
    async def _sync_work_orders(self, since: Optional[datetime] = None):
        t = time.time()
        wos = await self.b.get_work_orders(since=since)
        synced = 0
        async with self.db.acquire() as conn:
            for wo in wos:
                unit_bid = wo.pop("_unit_buildium_id", None)
                unit_id = await conn.fetchval("SELECT id FROM units WHERE buildium_id=$1", unit_bid) if unit_bid else None

                exists = await conn.fetchval("SELECT id FROM work_orders WHERE buildium_task_id=$1", wo["buildium_task_id"])
                if not exists:
                    await conn.execute("""
                        INSERT INTO work_orders (unit_id,title,status,submitted_source,buildium_task_id,buildium_synced_at,sync_status)
                        VALUES ($1,$2,$3,$4,$5,$6,'synced')
                    """, unit_id, wo["title"], wo["status"], "Buildium",
                        wo["buildium_task_id"], wo.get("buildium_synced_at"))
                    synced += 1
        logger.info(f"  Work Orders (pull): {len(wos)} from Buildium · {synced} new")

    # ── Work Orders Push ────────────────────────────────────────────
    async def _push_pending_work_orders(self):
        """Push COrtai-created work orders back to Buildium."""
        async with self.db.acquire() as conn:
            pending = await conn.fetch("""
                SELECT w.*, u.buildium_id as unit_buildium_id
                FROM work_orders w
                LEFT JOIN units u ON u.id = w.unit_id
                WHERE w.sync_status = 'pending_push' AND w.buildium_task_id IS NULL
                LIMIT 50
            """)

        pushed, failed = 0, 0
        for wo in pending:
            try:
                wo_dict = dict(wo)
                wo_dict["_unit_buildium_id"] = wo["unit_buildium_id"]
                result = await self.b.push_work_order(wo_dict)
                async with self.db.acquire() as conn:
                    await conn.execute("""
                        UPDATE work_orders SET buildium_task_id=$1, buildium_synced_at=NOW(), sync_status='synced'
                        WHERE id=$2
                    """, result.get("Id"), wo["id"])
                pushed += 1
                await self._log_sync("push","work_orders",result.get("Id"),"push","success",
                                     records_updated=1, triggered_by="event")
            except BuildiumAPIError as e:
                async with self.db.acquire() as conn:
                    await conn.execute(
                        "UPDATE work_orders SET sync_status='error' WHERE id=$1", wo["id"])
                await self._log_sync("push","work_orders",None,"push","error",error_message=str(e))
                failed += 1

        if pushed or failed:
            logger.info(f"  Work Orders (push): {pushed} pushed · {failed} failed")

    async def push_wo_status_update(self, wo_id: int, status: str, notes: str = None):
        """Push a single status change to Buildium immediately."""
        async with self.db.acquire() as conn:
            row = await conn.fetchrow("SELECT buildium_task_id FROM work_orders WHERE id=$1", wo_id)
        if row and row["buildium_task_id"]:
            try:
                await self.b.update_work_order_status(row["buildium_task_id"], status, notes)
                async with self.db.acquire() as conn:
                    await conn.execute(
                        "UPDATE work_orders SET buildium_synced_at=NOW(), sync_status='synced' WHERE id=$1", wo_id)
            except BuildiumAPIError as e:
                logger.warning(f"Failed to push WO {wo_id} status to Buildium: {e}")

    # ── Sync log ────────────────────────────────────────────────────
    async def _log_sync(self, sync_type, entity_type, entity_buildium_id, direction,
                        status, records_processed=0, records_created=0, records_updated=0,
                        records_skipped=0, duration_ms=0, error_message=None, triggered_by="scheduler"):
        async with self.db.acquire() as conn:
            await conn.execute("""
                INSERT INTO sync_log (sync_type,entity_type,entity_buildium_id,direction,status,
                    records_processed,records_created,records_updated,records_skipped,
                    duration_ms,error_message,triggered_by)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
            """, sync_type, entity_type, entity_buildium_id, direction, status,
                records_processed, records_created, records_updated, records_skipped,
                duration_ms, error_message, triggered_by)


# ── Scheduler — runs every 4 hours ──────────────────────────────────
async def run_sync_scheduler(db_pool: asyncpg.Pool, client_id: str, client_secret: str):
    """Background task. Call this from FastAPI lifespan."""
    while True:
        try:
            async with BuildiumClient(client_id, client_secret) as buildium:
                engine = SyncEngine(db_pool, buildium)
                # Incremental: only pull changes from last 5 hours
                since = datetime.utcnow() - timedelta(hours=5)
                await engine.run_full_sync(since=since)
        except Exception as e:
            logger.error(f"Scheduler sync failed: {e}")
        await asyncio.sleep(4 * 60 * 60)  # 4 hours
