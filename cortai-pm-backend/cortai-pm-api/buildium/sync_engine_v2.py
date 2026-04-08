"""
sync_engine_v2.py — Complete Buildium ↔ COrtai Sync
Replaces sync_engine.py — use this file.

Pull order: owners → properties → units → tenants → leases →
            outstanding_balances → payments(recent) → vendors → 
            maintenance_requests → bills
Push queue: work_orders → opex_bills → vendor_additions → 
            wo_notes → lease_notes
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Optional

import asyncpg
from buildium.client_v2 import BuildiumClient, BuildiumAPIError

logger = logging.getLogger(__name__)


class SyncEngine:

    def __init__(self, db: asyncpg.Pool, b: BuildiumClient):
        self.db = db
        self.b  = b

    # ══════════════════════════════════════════════════════════════
    # MASTER SYNC
    # ══════════════════════════════════════════════════════════════

    async def run_full_sync(self, since: Optional[datetime] = None):
        start = time.time()
        scope = f"incremental since {since.isoformat()}" if since else "full"
        logger.info(f"=== Buildium Sync Started ({scope}) ===")

        pull_steps = [
            ("owners",           self._sync_owners),
            ("properties",       lambda: self._sync_properties(since)),
            ("units",            lambda: self._sync_units(since)),
            ("tenants",          self._sync_tenants),
            ("leases",           lambda: self._sync_leases(since)),
            ("balances",         self._sync_outstanding_balances),
            ("vendors",          self._sync_vendors),
            ("work_orders",      lambda: self._sync_work_orders(since)),
            ("bills",            lambda: self._sync_bills(since)),
        ]
        push_steps = [
            ("push_work_orders", self._push_pending_work_orders),
            ("push_wo_notes",    self._push_pending_wo_notes),
            ("push_opex_bills",  self._push_pending_opex_bills),
            ("push_vendors",     self._push_pending_vendors),
            ("push_lease_notes", self._push_pending_lease_notes),
        ]

        errors = []
        for name, fn in pull_steps:
            try:
                await fn()
            except Exception as e:
                logger.error(f"  Pull {name} failed: {e}", exc_info=True)
                errors.append(name)
                await self._log(f"pull_{name}", "pull", "error", error_message=str(e))

        for name, fn in push_steps:
            try:
                await fn()
            except Exception as e:
                logger.error(f"  Push {name} failed: {e}", exc_info=True)
                errors.append(name)

        ms = int((time.time() - start) * 1000)
        status = "success" if not errors else "partial"
        await self._log("full_sync", "pull", status, duration_ms=ms,
                        error_message=", ".join(errors) if errors else None)
        logger.info(f"=== Sync {status.upper()} in {ms/1000:.1f}s — {len(errors)} errors ===")

    # ══════════════════════════════════════════════════════════════
    # PULL METHODS
    # ══════════════════════════════════════════════════════════════

    async def _sync_owners(self):
        t = time.time()
        owners = await self.b.get_owners()
        cr, up = 0, 0
        async with self.db.acquire() as c:
            for o in owners:
                exists = await c.fetchval("SELECT id FROM owners WHERE buildium_id=$1", o["buildium_id"])
                if exists:
                    await c.execute(
                        "UPDATE owners SET first_name=$1,last_name=$2,company_name=$3,email=$4,phone=$5,is_company=$6,is_active=$7,last_synced_at=NOW() WHERE buildium_id=$8",
                        o["first_name"],o["last_name"],o["company_name"],o["email"],o["phone"],o["is_company"],o["is_active"],o["buildium_id"])
                    up+=1
                else:
                    await c.execute(
                        "INSERT INTO owners(buildium_id,first_name,last_name,company_name,email,phone,is_company,is_active) VALUES($1,$2,$3,$4,$5,$6,$7,$8)",
                        o["buildium_id"],o["first_name"],o["last_name"],o["company_name"],o["email"],o["phone"],o["is_company"],o["is_active"])
                    cr+=1
        await self._log("owners","pull","success",len(owners),cr,up,0,int((time.time()-t)*1000))
        logger.info(f"  Owners: {len(owners)} · {cr} new · {up} updated")

    async def _sync_properties(self, since):
        t = time.time()
        props = await self.b.get_properties(since)
        cr, up = 0, 0
        async with self.db.acquire() as c:
            for p in props:
                exists = await c.fetchval("SELECT id FROM properties WHERE buildium_id=$1", p["buildium_id"])
                if exists:
                    await c.execute("""
                        UPDATE properties SET name=$1,address=$2,city=$3,state_province=$4,postal_code=$5,
                            structure_type=$6,year_built=$7,is_active=$8,buildium_updated_at=$9,last_synced_at=NOW()
                        WHERE buildium_id=$10""",
                        p["name"],p["address"],p["city"],p["state_province"],p["postal_code"],
                        p["structure_type"],p.get("year_built"),p["is_active"],
                        p.get("buildium_updated_at"),p["buildium_id"])
                    up+=1
                else:
                    await c.execute("""
                        INSERT INTO properties(buildium_id,name,address,city,state_province,postal_code,
                            structure_type,year_built,is_active,buildium_created_at,buildium_updated_at)
                        VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)""",
                        p["buildium_id"],p["name"],p["address"],p["city"],p["state_province"],
                        p["postal_code"],p["structure_type"],p.get("year_built"),p["is_active"],
                        p.get("buildium_created_at"),p.get("buildium_updated_at"))
                    cr+=1
        await self._log("properties","pull","success",len(props),cr,up,0,int((time.time()-t)*1000))
        logger.info(f"  Properties: {len(props)} · {cr} new · {up} updated")

    async def _sync_units(self, since):
        t = time.time()
        units = await self.b.get_units()
        cr, up, sk = 0, 0, 0
        async with self.db.acquire() as c:
            for u in units:
                prop_bid = u.pop("_property_buildium_id", None)
                prop_id  = await c.fetchval("SELECT id FROM properties WHERE buildium_id=$1", prop_bid) if prop_bid else None
                if not prop_id: sk+=1; continue
                exists = await c.fetchval("SELECT id FROM units WHERE buildium_id=$1", u["buildium_id"])
                if exists:
                    await c.execute("""
                        UPDATE units SET unit_number=$1,unit_type=$2,beds=$3,baths=$4,sqft=$5,
                            market_rent=$6,is_active=$7,buildium_updated_at=$8,last_synced_at=NOW()
                        WHERE buildium_id=$9""",
                        u["unit_number"],u.get("unit_type"),u.get("beds"),u.get("baths"),
                        u.get("sqft"),u.get("market_rent"),u.get("is_active",True),
                        u.get("buildium_updated_at"),u["buildium_id"])
                    up+=1
                else:
                    await c.execute("""
                        INSERT INTO units(buildium_id,property_id,unit_number,unit_type,beds,baths,sqft,market_rent,is_active)
                        VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
                        u["buildium_id"],prop_id,u["unit_number"],u.get("unit_type"),
                        u.get("beds"),u.get("baths"),u.get("sqft"),u.get("market_rent"),u.get("is_active",True))
                    cr+=1
        await self._log("units","pull","success",len(units),cr,up,sk,int((time.time()-t)*1000))
        logger.info(f"  Units: {len(units)} · {cr} new · {up} updated · {sk} skipped")

    async def _sync_tenants(self):
        t = time.time()
        tenants = await self.b.get_tenants()
        cr, up = 0, 0
        async with self.db.acquire() as c:
            for tn in tenants:
                exists = await c.fetchval("SELECT id FROM tenants WHERE buildium_id=$1", tn["buildium_id"])
                if exists:
                    await c.execute("""
                        UPDATE tenants SET first_name=$1,last_name=$2,email=$3,phone=$4,
                            is_active=$5,last_synced_at=NOW() WHERE buildium_id=$6""",
                        tn["first_name"],tn["last_name"],tn["email"],tn["phone"],tn["is_active"],tn["buildium_id"])
                    up+=1
                else:
                    await c.execute("""
                        INSERT INTO tenants(buildium_id,first_name,last_name,email,phone,is_active,buildium_created_at)
                        VALUES($1,$2,$3,$4,$5,$6,$7)""",
                        tn["buildium_id"],tn["first_name"],tn["last_name"],tn["email"],
                        tn["phone"],tn["is_active"],tn.get("buildium_created_at"))
                    cr+=1
        await self._log("tenants","pull","success",len(tenants),cr,up,0,int((time.time()-t)*1000))
        logger.info(f"  Tenants: {len(tenants)} · {cr} new · {up} updated")

    async def _sync_leases(self, since):
        t = time.time()
        leases = await self.b.get_leases(since=since)
        cr, up = 0, 0
        async with self.db.acquire() as c:
            for ls in leases:
                residents = ls.pop("_residents", [])
                unit_bid  = ls.pop("_unit_buildium_id", None)
                unit_id   = await c.fetchval("SELECT id FROM units WHERE buildium_id=$1", unit_bid) if unit_bid else None
                exists    = await c.fetchval("SELECT id FROM leases WHERE buildium_id=$1", ls["buildium_id"])
                if exists:
                    lease_id = exists
                    await c.execute("""
                        UPDATE leases SET lease_type=$1,lease_status=$2,rent_amount=$3,security_deposit=$4,
                            start_date=$5,end_date=$6,move_in_date=$7,move_out_date=$8,
                            is_active=$9,buildium_updated_at=$10,last_synced_at=NOW()
                        WHERE buildium_id=$11""",
                        ls["lease_type"],ls["lease_status"],ls["rent_amount"],ls["security_deposit"],
                        ls.get("start_date"),ls.get("end_date"),ls.get("move_in_date"),ls.get("move_out_date"),
                        ls["is_active"],ls.get("buildium_updated_at"),ls["buildium_id"])
                    up+=1
                else:
                    lease_id = await c.fetchval("""
                        INSERT INTO leases(buildium_id,unit_id,lease_type,lease_status,rent_amount,
                            security_deposit,start_date,end_date,move_in_date,move_out_date,is_active)
                        VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) RETURNING id""",
                        ls["buildium_id"],unit_id,ls["lease_type"],ls["lease_status"],ls["rent_amount"],
                        ls["security_deposit"],ls.get("start_date"),ls.get("end_date"),
                        ls.get("move_in_date"),ls.get("move_out_date"),ls["is_active"])
                    cr+=1
                # Sync residents
                for res in residents:
                    t_bid = res.get("Id") or res.get("ResidentId")
                    t_id  = await c.fetchval("SELECT id FROM tenants WHERE buildium_id=$1", t_bid) if t_bid else None
                    if t_id and lease_id:
                        await c.execute("""
                            INSERT INTO lease_residents(buildium_id,lease_id,tenant_id,is_primary,move_in_date,move_out_date)
                            VALUES($1,$2,$3,$4,$5,$6)
                            ON CONFLICT(buildium_id) DO UPDATE SET last_synced_at=NOW()""",
                            res.get("Id"),lease_id,t_id,res.get("IsPrimary",True),
                            res.get("MoveInDate"),res.get("MoveOutDate"))
        await self._log("leases","pull","success",len(leases),cr,up,0,int((time.time()-t)*1000))
        logger.info(f"  Leases: {len(leases)} · {cr} new · {up} updated")

    async def _sync_outstanding_balances(self):
        bals = await self.b.get_outstanding_balances()
        async with self.db.acquire() as c:
            for bal in bals:
                lease_id  = await c.fetchval("SELECT id FROM leases WHERE buildium_id=$1", bal.get("LeaseId"))
                tenant_id = await c.fetchval("SELECT id FROM tenants WHERE buildium_id=$1", bal.get("TenantId"))
                if not lease_id: continue
                await c.execute("""
                    INSERT INTO outstanding_balances(buildium_id,lease_id,tenant_id,total_balance,as_of_date)
                    VALUES($1,$2,$3,$4,$5)
                    ON CONFLICT(buildium_id) DO UPDATE SET total_balance=$3,as_of_date=$4,last_synced_at=NOW()""",
                    bal.get("Id"),lease_id,tenant_id,bal.get("TotalBalance",0),datetime.utcnow().date())
        logger.info(f"  Balances: {len(bals)} synced")

    async def _sync_vendors(self):
        t = time.time()
        vendors = await self.b.get_vendors()
        cr, up = 0, 0
        async with self.db.acquire() as c:
            for v in vendors:
                exists = await c.fetchval("SELECT id FROM vendors WHERE buildium_id=$1", v["buildium_id"])
                if exists:
                    await c.execute("""
                        UPDATE vendors SET company_name=$1,email=$2,phone=$3,is_active=$4,
                            is_1099=$5,last_synced_at=NOW() WHERE buildium_id=$6""",
                        v["company_name"],v.get("email"),v.get("phone"),v.get("is_active",True),
                        v.get("is_1099",False),v["buildium_id"])
                    up+=1
                else:
                    await c.execute("""
                        INSERT INTO vendors(buildium_id,company_name,first_name,last_name,email,phone,is_active,is_1099)
                        VALUES($1,$2,$3,$4,$5,$6,$7,$8)""",
                        v["buildium_id"],v["company_name"],v.get("first_name"),v.get("last_name"),
                        v.get("email"),v.get("phone"),v.get("is_active",True),v.get("is_1099",False))
                    cr+=1
        logger.info(f"  Vendors: {len(vendors)} · {cr} new · {up} updated")

    async def _sync_work_orders(self, since):
        wos = await self.b.get_maintenance_requests(
            statuses=["New","Assigned","InProgress"] if since else None, since=since)
        cr = 0
        async with self.db.acquire() as c:
            for wo in wos:
                unit_bid = wo.pop("_unit_buildium_id", None)
                unit_id  = await c.fetchval("SELECT id FROM units WHERE buildium_id=$1", unit_bid) if unit_bid else None
                if not await c.fetchval("SELECT id FROM work_orders WHERE buildium_task_id=$1", wo["buildium_task_id"]):
                    await c.execute("""
                        INSERT INTO work_orders(unit_id,title,description,status,scheduled_date,
                            submitted_source,buildium_task_id,buildium_synced_at,sync_status)
                        VALUES($1,$2,$3,$4,$5,'Buildium',$6,NOW(),'synced')""",
                        unit_id,wo["title"],wo.get("description"),wo["status"],
                        wo.get("scheduled_date"),wo["buildium_task_id"])
                    cr+=1
        logger.info(f"  Work orders (pull): {len(wos)} · {cr} new")

    async def _sync_bills(self, since):
        since = since or (datetime.utcnow() - timedelta(days=7))
        bills = await self.b.get_bills(since)
        async with self.db.acquire() as c:
            for bill in bills:
                if not await c.fetchval("SELECT id FROM buildium_bills WHERE buildium_id=$1", bill.get("Id")):
                    vendor_id = await c.fetchval("SELECT id FROM vendors WHERE buildium_id=$1", bill.get("VendorId"))
                    await c.execute("""
                        INSERT INTO buildium_bills(buildium_id,vendor_id,bill_date,due_date,memo,total_amount,is_paid,buildium_synced_at)
                        VALUES($1,$2,$3,$4,$5,$6,$7,NOW())""",
                        bill.get("Id"),vendor_id,bill.get("BillDate"),bill.get("DueDate"),
                        bill.get("Memo"),bill.get("TotalAmount",0),bill.get("IsPaid",False))
        logger.info(f"  Bills (pull): {len(bills)} checked")

    # ══════════════════════════════════════════════════════════════
    # PUSH METHODS
    # ══════════════════════════════════════════════════════════════

    async def _push_pending_work_orders(self):
        """Push COrtai-created WOs to Buildium as maintenance requests."""
        async with self.db.acquire() as c:
            pending = await c.fetch("""
                SELECT w.*, u.buildium_id as unit_buildium_id,
                       p.name as property_name
                FROM work_orders w
                LEFT JOIN units u ON u.id=w.unit_id
                LEFT JOIN properties p ON p.id=w.property_id
                WHERE w.sync_status='pending_push' AND w.buildium_task_id IS NULL
                LIMIT 50
            """)
        pushed, failed = 0, 0
        for wo in pending:
            try:
                wo_dict = dict(wo)
                wo_dict["_unit_buildium_id"] = wo["unit_buildium_id"]
                result = await self.b.push_work_order(wo_dict)
                bid = result.get("Id")
                async with self.db.acquire() as c:
                    await c.execute(
                        "UPDATE work_orders SET buildium_task_id=$1,buildium_synced_at=NOW(),sync_status='synced' WHERE id=$2",
                        bid, wo["id"])
                await self._log("work_orders","push","success",records_updated=1,entity_buildium_id=bid,triggered_by="event")
                pushed += 1
            except BuildiumAPIError as e:
                async with self.db.acquire() as c:
                    await c.execute("UPDATE work_orders SET sync_status='error' WHERE id=$1", wo["id"])
                await self._log("work_orders","push","error",error_message=str(e))
                failed += 1
        if pushed or failed:
            logger.info(f"  WO push: {pushed} pushed · {failed} failed")

    async def _push_pending_wo_notes(self):
        """
        Push tech assignment notes to Buildium WO.
        Runs after new wo_assignments are created.
        """
        async with self.db.acquire() as c:
            pending = await c.fetch("""
                SELECT wa.*, w.buildium_task_id,
                       ft.first_name||' '||ft.last_name as tech_name,
                       ft.phone as tech_phone
                FROM wo_assignments wa
                JOIN work_orders w ON w.id=wa.work_order_id
                JOIN field_techs ft ON ft.id=wa.tech_id
                WHERE wa.buildium_note_pushed=FALSE
                  AND w.buildium_task_id IS NOT NULL
                  AND wa.assignment_status NOT IN ('Cancelled')
                LIMIT 50
            """)
        pushed = 0
        for a in pending:
            note = (
                f"Assigned to: {a['tech_name']} ({a['tech_phone']})\n"
                f"Scheduled: {a['scheduled_date']} at {a['time_slot_label'] or 'TBD'}\n"
                f"{('Notes: ' + a['dispatch_notes']) if a['dispatch_notes'] else ''}"
            ).strip()
            try:
                await self.b.add_wo_note(a["buildium_task_id"], note, is_private=True)
                async with self.db.acquire() as c:
                    await c.execute("UPDATE wo_assignments SET buildium_note_pushed=TRUE WHERE id=$1", a["id"])
                pushed += 1
            except BuildiumAPIError as e:
                logger.warning(f"WO note push failed for assignment {a['id']}: {e}")
        if pushed:
            logger.info(f"  WO notes pushed: {pushed}")

    async def _push_pending_opex_bills(self):
        """Push OPEX utility bills entered in COrtai to Buildium Accounting."""
        setting = await self._get_setting("push_opex_bills")
        if setting != "true": return

        async with self.db.acquire() as c:
            pending = await c.fetch("""
                SELECT oa.*, oc.display_name, oc.buildium_gl_account,
                       p.name as property_name
                FROM opex_actuals oa
                JOIN opex_categories oc ON oc.id=oa.category_id
                JOIN properties p ON p.id=oa.property_id
                WHERE oa.pushed_to_buildium=FALSE
                  AND oc.buildium_gl_account IS NOT NULL
                  AND oc.buildium_gl_account != ''
                LIMIT 30
            """)
        pushed, failed = 0, 0
        for bill in pending:
            try:
                # Find or use generic vendor
                async with self.db.acquire() as c:
                    vendor_bid = await c.fetchval(
                        "SELECT buildium_id FROM vendors WHERE company_name ILIKE $1 AND buildium_id IS NOT NULL LIMIT 1",
                        f"%{bill['vendor'] or ''}%")
                if not vendor_bid:
                    logger.warning(f"  No Buildium vendor found for '{bill['vendor']}' — skipping bill push")
                    failed += 1
                    continue

                memo = f"{bill['display_name']} — {bill['billing_period'].strftime('%B %Y')} — {bill['property_name']}"
                result = await self.b.push_opex_bill(dict(bill), vendor_bid, bill["buildium_gl_account"])
                bid = result.get("Id")

                async with self.db.acquire() as c:
                    await c.execute(
                        "UPDATE opex_actuals SET pushed_to_buildium=TRUE WHERE id=$1", bill["id"])
                    if bid:
                        await c.execute("""
                            INSERT INTO buildium_bills(buildium_id,vendor_id,bill_date,total_amount,memo,buildium_synced_at)
                            SELECT $1, v.id, $3, $4, $5, NOW() FROM vendors v WHERE v.buildium_id=$2
                            ON CONFLICT DO NOTHING""",
                            bid, vendor_bid, bill["billing_period"], float(bill["amount"]), memo)
                pushed += 1
            except BuildiumAPIError as e:
                logger.warning(f"  OPEX bill push failed: {e}")
                failed += 1
        if pushed or failed:
            logger.info(f"  OPEX bills: {pushed} pushed · {failed} failed")

    async def _push_pending_vendors(self):
        """Push new vendors created in COrtai to Buildium."""
        setting = await self._get_setting("push_vendor_updates")
        if setting != "true": return

        async with self.db.acquire() as c:
            pending = await c.fetch(
                "SELECT * FROM vendors WHERE buildium_id IS NULL AND is_active=TRUE LIMIT 20")
        pushed = 0
        for v in pending:
            try:
                result = await self.b.push_vendor(dict(v))
                bid = result.get("Id")
                if bid:
                    async with self.db.acquire() as c:
                        await c.execute(
                            "UPDATE vendors SET buildium_id=$1, last_synced_at=NOW() WHERE id=$2", bid, v["id"])
                    pushed += 1
            except BuildiumAPIError as e:
                logger.warning(f"  Vendor push failed for '{v['company_name']}': {e}")
        if pushed:
            logger.info(f"  Vendors pushed: {pushed}")

    async def _push_pending_lease_notes(self):
        """Push flagged tenant communications (N4, N5, formal notices) to Buildium lease notes."""
        setting = await self._get_setting("push_wo_notes")
        if setting != "true": return

        async with self.db.acquire() as c:
            pending = await c.fetch("""
                SELECT tc.*, l.buildium_id as lease_buildium_id
                FROM tenant_communications tc
                JOIN leases l ON l.id=tc.lease_id
                WHERE tc.push_to_buildium=TRUE
                  AND tc.pushed_to_buildium=FALSE
                  AND l.buildium_id IS NOT NULL
                LIMIT 20
            """)
        pushed = 0
        for comm in pending:
            note = f"{comm['comm_date'].strftime('%Y-%m-%d')} — {comm['subject']}\n{comm['summary']}"
            try:
                result = await self.b.add_lease_note(comm["lease_buildium_id"], note, is_private=True)
                async with self.db.acquire() as c:
                    await c.execute(
                        "UPDATE tenant_communications SET pushed_to_buildium=TRUE, buildium_note_id=$1 WHERE id=$2",
                        result.get("Id"), comm["id"])
                pushed += 1
            except BuildiumAPIError as e:
                logger.warning(f"  Lease note push failed: {e}")
        if pushed:
            logger.info(f"  Lease notes pushed: {pushed}")

    # ── Helpers ────────────────────────────────────────────────────
    async def push_wo_status_now(self, wo_id: int, status: str, notes: str = None):
        """Real-time push of a single WO status change. Called by API on status update."""
        async with self.db.acquire() as c:
            row = await c.fetchrow(
                "SELECT buildium_task_id FROM work_orders WHERE id=$1", wo_id)
        if row and row["buildium_task_id"]:
            try:
                await self.b.update_wo_status(row["buildium_task_id"], status)
                if notes:
                    await self.b.add_wo_note(row["buildium_task_id"], notes, is_private=True)
                async with self.db.acquire() as c:
                    await c.execute(
                        "UPDATE work_orders SET buildium_synced_at=NOW(),sync_status='synced' WHERE id=$1", wo_id)
            except BuildiumAPIError as e:
                logger.warning(f"WO {wo_id} status push failed: {e}")
                async with self.db.acquire() as c:
                    await c.execute("UPDATE work_orders SET sync_status='pending_push' WHERE id=$1", wo_id)

    async def _get_setting(self, key: str) -> str:
        async with self.db.acquire() as c:
            val = await c.fetchval("SELECT value FROM cortai_settings WHERE key=$1", key)
        return val or ""

    async def _log(self, entity_type, direction, status, records_processed=0,
                   records_created=0, records_updated=0, records_skipped=0,
                   duration_ms=0, error_message=None, entity_buildium_id=None,
                   triggered_by="scheduler"):
        async with self.db.acquire() as c:
            await c.execute("""
                INSERT INTO sync_log(sync_type,entity_type,entity_buildium_id,direction,status,
                    records_processed,records_created,records_updated,records_skipped,
                    duration_ms,error_message,triggered_by)
                VALUES('incremental',$1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)""",
                entity_type,entity_buildium_id,direction,status,
                records_processed,records_created,records_updated,records_skipped,
                duration_ms,error_message,triggered_by)


# ── Background scheduler ───────────────────────────────────────────
async def run_sync_scheduler(db_pool: asyncpg.Pool, client_id: str, client_secret: str):
    """
    Background task started from FastAPI lifespan.
    - First run: full sync
    - Subsequent runs: incremental (last 5 hours window)
    """
    first_run = True
    while True:
        try:
            async with BuildiumClient(client_id, client_secret) as client:
                engine = SyncEngine(db_pool, client)
                since = None if first_run else datetime.utcnow() - timedelta(hours=5)
                await engine.run_full_sync(since=since)
                first_run = False
        except Exception as e:
            logger.error(f"Sync scheduler error: {e}", exc_info=True)
        await asyncio.sleep(4 * 60 * 60)  # 4 hours
