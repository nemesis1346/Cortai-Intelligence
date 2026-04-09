"""
client_v2.py — Buildium REST API Client (v2)
Adds: bill push · lease notes · WO notes · vendor updates · webhook support
Replaces client.py — use this file.
"""

import os
import httpx
from buildium.client import parse_buildium_ts, parse_buildium_date
import asyncio
import logging
import time
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class BuildiumAPIError(Exception):
    def __init__(self, status_code: int, message: str, detail: dict = None):
        self.status_code = status_code
        self.message     = message
        self.detail      = detail or {}
        super().__init__(f"Buildium {status_code}: {message}")

class BuildiumRateLimitError(BuildiumAPIError):
    pass


class BuildiumClient:
    """
    Async Buildium API client. API key headers, rate limiting, pagination, retry.

    Usage:
        async with BuildiumClient(client_id, client_secret) as client:
            props = await client.get_properties()
            await client.push_work_order(wo_dict)
    """

    def __init__(self, client_id: str, client_secret: str, page_size: int = 100, base_url: Optional[str] = None):
        self.client_id     = client_id
        self.client_secret = client_secret
        self.page_size     = page_size
        raw = (base_url if base_url is not None else os.getenv("BUILDIUM_API_BASE_URL", "https://api.buildium.com/v1")).strip()
        self.base_url = raw.rstrip("/") if raw else "https://api.buildium.com/v1"
        self._req_count    = 0
        self._window_start = time.time()
        self._http: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self._http = httpx.AsyncClient(timeout=30.0)
        logger.info("Buildium API client ready (header auth) base=%s", self.base_url)
        return self

    async def __aexit__(self, *args):
        if self._http:
            await self._http.aclose()

    def _auth_headers(self, json_body: bool = False) -> dict:
        h = {
            "x-buildium-client-id": self.client_id,
            "x-buildium-client-secret": self.client_secret,
            "Accept": "application/json",
        }
        if json_body:
            h["Content-Type"] = "application/json"
        return h

    # ── Rate limiting (90/min — Buildium limit is 100) ─────────────
    async def _rate_limit(self):
        now = time.time()
        if now - self._window_start >= 60:
            self._req_count = 0
            self._window_start = now
        if self._req_count >= 90:
            sleep = 60 - (now - self._window_start)
            if sleep > 0:
                logger.debug(f"Rate limit: sleeping {sleep:.1f}s")
                await asyncio.sleep(sleep)
            self._req_count = 0
            self._window_start = time.time()
        self._req_count += 1

    # ── Core HTTP ──────────────────────────────────────────────────
    async def _request(self, method: str, path: str, **kwargs) -> dict | list:
        await self._rate_limit()
        json_body = method in ("POST", "PATCH", "PUT")
        headers = self._auth_headers(json_body=json_body)
        url = f"{self.base_url}{path}"
        for attempt in range(3):
            try:
                resp = await self._http.request(method, url, headers=headers, **kwargs)
                if resp.status_code == 429:
                    wait = int(resp.headers.get("Retry-After", 60))
                    logger.warning(f"Rate limited. Waiting {wait}s")
                    await asyncio.sleep(wait)
                    continue
                if resp.status_code == 401:
                    raise BuildiumAPIError(resp.status_code, resp.text[:500], {})
                if resp.status_code in (204,):           # No content
                    return {}
                if resp.status_code >= 400:
                    raise BuildiumAPIError(resp.status_code, resp.text[:500], {})
                return resp.json()
            except httpx.TimeoutException:
                if attempt == 2: raise
                await asyncio.sleep(2 ** attempt)
        raise BuildiumAPIError(0, "Max retries exceeded", {})

    async def _get(self, path: str, params: dict = None) -> dict | list:
        return await self._request("GET", path, params=params or {})

    async def _post(self, path: str, body: dict) -> dict:
        return await self._request("POST", path, json=body)

    async def _patch(self, path: str, body: dict) -> dict:
        return await self._request("PATCH", path, json=body)

    async def _put(self, path: str, body: dict) -> dict:
        return await self._request("PUT", path, json=body)

    async def _get_all(self, path: str, params: dict = None) -> list:
        all_results, offset = [], 0
        params = {**(params or {}), "pagesize": self.page_size}
        while True:
            params["offset"] = offset
            data = await self._get(path, params)
            items = data if isinstance(data, list) else data.get("results", [])
            if not items: break
            all_results.extend(items)
            if len(items) < self.page_size: break
            offset += self.page_size
            logger.debug(f"{path}: {len(all_results)} fetched")
        return all_results

    # ══════════════════════════════════════════════════════════════
    # PULL — READ FROM BUILDIUM
    # ══════════════════════════════════════════════════════════════

    async def get_properties(self, since: datetime = None) -> list[dict]:
        params = {}
        if since: params["lastupdatedfrom"] = since.isoformat()
        raw = await self._get_all("/rentals", params)
        return [self._norm_property(p) for p in raw]

    async def get_property(self, bid: int) -> dict:
        return self._norm_property(await self._get(f"/rentals/{bid}"))

    def _norm_property(self, r: dict) -> dict:
        a = r.get("Address", {})
        return {
            "buildium_id":          r.get("Id"),
            "name":                 r.get("Name", ""),
            "address":              a.get("AddressLine1", ""),
            "address2":             a.get("AddressLine2"),
            "city":                 a.get("City", ""),
            "state_province":       a.get("StateOrProvince", "ON"),
            "postal_code":          a.get("PostalCode", ""),
            "property_type":        r.get("Type"),
            "structure_type":       r.get("Structure"),
            "year_built":           r.get("YearBuilt"),
            "reserve_fund":         r.get("ReserveFundAmount"),
            "is_active":            r.get("IsActive", True),
            "buildium_created_at":  parse_buildium_ts(r.get("CreatedDateTime")),
            "buildium_updated_at":  parse_buildium_ts(r.get("UpdatedDateTime")),
        }

    async def get_units(self, property_bid: int = None) -> list[dict]:
        params = {}
        if property_bid: params["propertyids"] = property_bid
        return [self._norm_unit(u) for u in await self._get_all("/rentals/units", params)]

    def _norm_unit(self, r: dict) -> dict:
        prop = r.get("Property") or {}
        return {
            "buildium_id":           r.get("Id"),
            "unit_number":           r.get("UnitNumber", ""),
            "unit_type":             r.get("UnitType"),
            "beds":                  r.get("Bedrooms"),
            "baths":                 r.get("Bathrooms"),
            "sqft":                  r.get("Area"),
            "market_rent":           r.get("MarketRent"),
            "is_active":             r.get("IsActive", True),
            "buildium_updated_at":   parse_buildium_ts(r.get("UpdatedDateTime")),
            "_property_buildium_id": prop.get("Id") if isinstance(prop, dict) else r.get("PropertyId"),
        }

    async def get_owners(self) -> list[dict]:
        return [self._norm_owner(o) for o in await self._get_all("/rentals/owners")]

    def _norm_owner(self, r: dict) -> dict:
        phones = r.get("PhoneNumbers", [])
        return {
            "buildium_id":  r.get("Id"),
            "first_name":   r.get("FirstName"),
            "last_name":    r.get("LastName"),
            "company_name": r.get("CompanyName"),
            "email":        r.get("PrimaryEmail") or r.get("AlternateEmail"),
            "phone":        next((p.get("Number") for p in phones if p.get("IsPrimary")), None),
            "is_company":   r.get("IsCompany", False),
            "is_active":    r.get("IsActive", True),
        }

    async def get_tenants(self) -> list[dict]:
        return [self._norm_tenant(t) for t in await self._get_all("/leases/tenants")]

    def _norm_tenant(self, r: dict) -> dict:
        phones = r.get("PhoneNumbers", [])
        return {
            "buildium_id":         r.get("Id"),
            "first_name":          r.get("FirstName", ""),
            "last_name":           r.get("LastName", ""),
            "email":               r.get("Email"),
            "phone":               next((p.get("Number") for p in phones if p.get("IsPrimary")), None),
            "date_of_birth":       parse_buildium_date(r.get("DateOfBirth")),
            "company":             r.get("Company"),
            "is_active":           r.get("IsActive", True),
            "buildium_created_at": parse_buildium_ts(r.get("CreatedDateTime")),
        }

    async def get_leases(self, statuses: list = None, since: datetime = None) -> list[dict]:
        params = {}
        if statuses: params["leasestatuses"] = ",".join(statuses)
        if since:    params["lastupdatedfrom"] = since.isoformat()
        return [self._norm_lease(l) for l in await self._get_all("/leases", params)]

    def _norm_lease(self, r: dict) -> dict:
        unit = r.get("Unit") or {}
        return {
            "buildium_id":           r.get("Id"),
            "lease_type":            r.get("LeaseType"),
            "lease_status":          r.get("LeaseStatus"),
            "rent_amount":           r.get("Rent"),
            "security_deposit":      r.get("SecurityDeposit"),
            "start_date":            parse_buildium_date(r.get("StartDate")),
            "end_date":              parse_buildium_date(r.get("EndDate")),
            "move_in_date":          parse_buildium_date(r.get("MoveInDate")),
            "move_out_date":         parse_buildium_date(r.get("MoveOutDate")),
            "is_active":             r.get("LeaseStatus") == "Active",
            "buildium_updated_at":   parse_buildium_ts(r.get("UpdatedDateTime")),
            "_unit_buildium_id":     unit.get("Id") if isinstance(unit, dict) else None,
            "_residents":            r.get("LeaseResidents", []),
        }

    async def get_outstanding_balances(self) -> list[dict]:
        return await self._get_all("/leases/outstandingbalances")

    async def get_lease_transactions(self, lease_bid: int, since: datetime = None) -> list[dict]:
        params = {}
        if since: params["from"] = since.strftime("%Y-%m-%d")
        raw = await self._get_all(f"/leases/{lease_bid}/transactions", params)
        return [self._norm_payment(p, lease_bid) for p in raw]

    def _norm_payment(self, r: dict, lease_bid: int) -> dict:
        return {
            "buildium_id":        r.get("Id"),
            "payment_type":       r.get("Type"),
            "amount":             r.get("TotalAmount"),
            "payment_date":       parse_buildium_date(r.get("Date")),
            "memo":               r.get("Memo"),
            "is_voided":          r.get("IsVoided", False),
            "_lease_buildium_id": lease_bid,
        }

    async def get_vendors(self, active_only: bool = True) -> list[dict]:
        params = {"isactive": str(active_only).lower()}
        return [self._norm_vendor(v) for v in await self._get_all("/vendors", params)]

    def _norm_vendor(self, r: dict) -> dict:
        phones = r.get("PhoneNumbers", [])
        return {
            "buildium_id":  r.get("Id"),
            "company_name": r.get("CompanyName", ""),
            "first_name":   r.get("FirstName"),
            "last_name":    r.get("LastName"),
            "email":        r.get("Email"),
            "phone":        next((p.get("Number") for p in phones if p.get("PhoneType") == "Main"), None),
            "is_active":    r.get("IsActive", True),
            "is_1099":      r.get("Is1099", False),
            "tax_id":       (r.get("TaxInformation") or {}).get("TaxIdentificationNumber"),
        }

    async def get_maintenance_requests(self, statuses: list = None, since: datetime = None) -> list[dict]:
        params = {}
        if statuses:
            params["statuses"] = ",".join(statuses)
        if since:
            params["lastupdatedfrom"] = since.strftime("%Y-%m-%d")
        all_results = []
        offset = 0
        while True:
            batch = dict(params)
            batch["offset"] = offset
            batch["limit"] = self.page_size
            data = await self._get("/tasks/residentrequests", batch)
            items = data if isinstance(data, list) else (data.get("results") or [])
            if not items:
                break
            all_results.extend(items)
            if len(items) < self.page_size:
                break
            offset += self.page_size
        return [self._norm_wo(w) for w in all_results]

    def _norm_wo(self, r: dict) -> dict:
        tid = r.get("Id")
        if tid is None:
            tid = r.get("id")
        tst = r.get("TaskStatus") or r.get("task_status")
        uid = r.get("UnitId")
        if uid is None:
            uid = r.get("unit_id")
        return {
            "buildium_task_id": tid,
            "title":            r.get("Title") or r.get("title") or "",
            "description":      r.get("Description") or r.get("description"),
            "status":           self._status_from_buildium(tst),
            "scheduled_date":   r.get("DueDate") or r.get("due_date"),
            "_unit_buildium_id": uid,
        }

    def _status_from_buildium(self, s: str) -> str:
        return {"New":"Submitted","Assigned":"Dispatched","InProgress":"In Progress",
                "Completed":"Completed","Closed":"Closed"}.get(s or "", "Submitted")

    def _status_to_buildium(self, s: str) -> str:
        return {"Submitted":"New","Dispatched":"Assigned","Scheduled":"Assigned",
                "In Progress":"InProgress","Parts Pending":"InProgress",
                "Completed":"Completed","Closed":"Closed"}.get(s, "New")

    def _priority_to_buildium(self, p: str) -> str:
        return {"Emergency":"Emergency","Urgent":"High","High":"High",
                "Normal":"Normal","Low":"Low","Preventive":"Low"}.get(p, "Normal")

    async def get_bills(self, since: datetime = None) -> list[dict]:
        params = {}
        if since: params["from"] = since.strftime("%Y-%m-%d")
        return await self._get_all("/accounting/bills", params)

    # ══════════════════════════════════════════════════════════════
    # PUSH — WRITE TO BUILDIUM
    # ══════════════════════════════════════════════════════════════

    async def push_work_order(self, wo: dict) -> dict:
        """
        Create a new maintenance request in Buildium.
        wo dict must include: title, description, category, priority, _unit_buildium_id
        Returns Buildium response with Id.
        """
        body = {
            "Title":       wo["title"],
            "Description": wo.get("description", ""),
            "Category":    wo.get("category", "General"),
            "Priority":    self._priority_to_buildium(wo.get("priority", "Normal")),
        }
        if wo.get("_unit_buildium_id"):
            body["UnitId"] = wo["_unit_buildium_id"]
        if wo.get("scheduled_date"):
            body["DueDate"] = str(wo["scheduled_date"])
        return await self._post("/tasks/residentrequests", body)

    async def update_wo_status(self, buildium_task_id: int, status: str) -> dict:
        """Push a status change to a Buildium maintenance request."""
        body = {"TaskStatus": self._status_to_buildium(status)}
        return await self._put(f"/tasks/residentrequests/{buildium_task_id}", body)

    async def add_wo_note(self, buildium_task_id: int, note: str, is_private: bool = True) -> dict:
        """
        Add a note to a Buildium maintenance request.
        Use for: tech assignment confirmation, dispatch notes, status updates.
        is_private=True means the note is internal — not visible to tenant via Buildium portal.
        """
        return await self._post(f"/tasks/residentrequests/{buildium_task_id}/notes", {
            "Note":      note,
            "IsPrivate": is_private,
        })

    async def push_vendor(self, vendor: dict) -> dict:
        """Create a new vendor in Buildium. Returns response with Id."""
        phones = []
        if vendor.get("phone"):
            phones.append({"Number": vendor["phone"], "PhoneType": "Main"})
        if vendor.get("alt_phone"):
            phones.append({"Number": vendor["alt_phone"], "PhoneType": "Alternate"})
        body = {
            "CompanyName":  vendor.get("company_name", ""),
            "FirstName":    vendor.get("first_name"),
            "LastName":     vendor.get("last_name"),
            "Email":        vendor.get("email"),
            "PhoneNumbers": phones,
            "Is1099":       vendor.get("is_1099", False),
        }
        return await self._post("/vendors", {k: v for k, v in body.items() if v is not None})

    async def update_vendor(self, buildium_vendor_id: int, vendor: dict) -> dict:
        """Update a vendor in Buildium (company name, email, phone)."""
        phones = []
        if vendor.get("phone"):
            phones.append({"Number": vendor["phone"], "PhoneType": "Main"})
        body = {
            "CompanyName":  vendor.get("company_name"),
            "Email":        vendor.get("email"),
            "PhoneNumbers": phones,
        }
        return await self._patch(f"/vendors/{buildium_vendor_id}", {k: v for k, v in body.items() if v is not None})

    async def push_opex_bill(self, bill: dict, vendor_buildium_id: int, gl_account: str) -> dict:
        """
        Push a utility/OPEX bill to Buildium accounting.

        bill dict: {
            'amount': 1420.00,
            'billing_period': date(2026, 4, 1),
            'vendor': 'Enbridge Gas',
            'invoice_number': 'ENG-20260401',
            'notes': 'Natural Gas — April 2026 — 1441 Clark Ave W'
        }
        """
        bill_date = str(bill.get("billing_period") or bill.get("invoice_date", ""))
        due_date  = str(bill.get("payment_date") or bill.get("billing_period", ""))
        body = {
            "VendorId":  vendor_buildium_id,
            "BillDate":  bill_date,
            "DueDate":   due_date,
            "Memo":      bill.get("notes") or bill.get("memo", ""),
            "Reference": bill.get("invoice_number"),
            "Lines": [{
                "GLAccount":   gl_account,
                "Amount":      float(bill["amount"]),
                "Description": bill.get("notes", ""),
            }],
        }
        return await self._post("/accounting/bills", {k: v for k, v in body.items() if v is not None})

    async def add_lease_note(self, buildium_lease_id: int, note: str, is_private: bool = True) -> dict:
        """
        Add a note to a Buildium lease.
        Use for: N4/N5 notices, payment arrangements, formal communications.
        """
        return await self._post(f"/leases/{buildium_lease_id}/notes", {
            "Note":      note,
            "IsPrivate": is_private,
        })

    async def register_webhook(self, callback_url: str, events: list[str]) -> dict:
        """
        Register a Buildium webhook subscription for real-time push from Buildium.
        Events: ['MaintenanceRequestCreated', 'LeasePaymentReceived', 'LeaseStatusChanged']
        """
        return await self._post("/webhooks/subscriptions", {
            "Url":    callback_url,
            "Events": events,
        })

    async def list_webhooks(self) -> list:
        return await self._get_all("/webhooks/subscriptions")

    async def delete_webhook(self, webhook_id: int) -> dict:
        return await self._request("DELETE", f"/webhooks/subscriptions/{webhook_id}")
