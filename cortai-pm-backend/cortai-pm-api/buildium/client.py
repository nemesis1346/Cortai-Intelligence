"""
buildium_client.py — Buildium REST API Client
API key headers · Rate limiting · Retry logic · Full field mapping

Buildium API docs: https://developer.buildium.com/
Auth: x-buildium-client-id and x-buildium-client-secret headers per request
Base: BUILDIUM_API_BASE_URL or https://api.buildium.com/v1 (use apisandbox.buildium.com for sandbox keys)
Rate limit: 100 requests/min per client
"""

import os
import httpx
import asyncio
import logging
import time
from datetime import datetime, date
from typing import Optional, Any
from functools import wraps

logger = logging.getLogger(__name__)


def parse_buildium_ts(val):
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    s = str(val).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def parse_buildium_date(val):
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    s = str(val).strip()
    if not s:
        return None
    if "T" in s:
        return parse_buildium_ts(s).date()
    return date.fromisoformat(s[:10])


class BuildiumAPIError(Exception):
    def __init__(self, status_code: int, message: str, detail: dict = None):
        self.status_code = status_code
        self.message = message
        self.detail = detail or {}
        super().__init__(f"Buildium API Error {status_code}: {message}")


class BuildiumRateLimitError(BuildiumAPIError):
    pass


class BuildiumClient:
    """
    Async Buildium API client.

    Usage:
        async with BuildiumClient(client_id="...", client_secret="...") as client:
            properties = await client.get_properties()

    All methods return normalized dicts ready to insert into COrtai DB.
    """

    def __init__(self, client_id: str, client_secret: str, page_size: int = 100, base_url: Optional[str] = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.page_size = page_size
        raw = (base_url if base_url is not None else os.getenv("BUILDIUM_API_BASE_URL", "https://api.buildium.com/v1")).strip()
        self.base_url = raw.rstrip("/") if raw else "https://api.buildium.com/v1"
        self._request_count = 0
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

    # ── Rate limiting ───────────────────────────────────────────────
    async def _rate_limit(self):
        """Enforce 90 req/min (Buildium limit: 100/min — leave buffer)."""
        now = time.time()
        if now - self._window_start >= 60:
            self._request_count = 0
            self._window_start = now
        if self._request_count >= 90:
            sleep_time = 60 - (now - self._window_start)
            if sleep_time > 0:
                logger.debug(f"Rate limit: sleeping {sleep_time:.1f}s")
                await asyncio.sleep(sleep_time)
            self._request_count = 0
            self._window_start = time.time()
        self._request_count += 1

    # ── Core request ────────────────────────────────────────────────
    async def _get(self, path: str, params: dict = None) -> dict | list:
        await self._rate_limit()

        headers = self._auth_headers()
        url = f"{self.base_url}{path}"

        for attempt in range(3):
            try:
                resp = await self._http.get(url, headers=headers, params=params or {})
                if resp.status_code == 429:
                    wait = int(resp.headers.get("Retry-After", 60))
                    logger.warning(f"Rate limited. Waiting {wait}s...")
                    await asyncio.sleep(wait)
                    continue
                if resp.status_code == 401:
                    raise BuildiumAPIError(resp.status_code, resp.text, {})
                if resp.status_code >= 400:
                    raise BuildiumAPIError(resp.status_code, resp.text, {})
                return resp.json()
            except httpx.TimeoutException:
                if attempt == 2:
                    raise
                await asyncio.sleep(2 ** attempt)

    async def _post(self, path: str, body: dict) -> dict:
        await self._rate_limit()
        headers = self._auth_headers(json_body=True)
        resp = await self._http.post(f"{self.base_url}{path}", headers=headers, json=body)
        if resp.status_code >= 400:
            raise BuildiumAPIError(resp.status_code, resp.text, {})
        return resp.json()

    async def _patch(self, path: str, body: dict) -> dict:
        await self._rate_limit()
        headers = self._auth_headers(json_body=True)
        resp = await self._http.patch(f"{self.base_url}{path}", headers=headers, json=body)
        if resp.status_code >= 400:
            raise BuildiumAPIError(resp.status_code, resp.text, {})
        return resp.json()

    async def _put(self, path: str, body: dict) -> dict:
        await self._rate_limit()
        headers = self._auth_headers(json_body=True)
        resp = await self._http.put(f"{self.base_url}{path}", headers=headers, json=body)
        if resp.status_code >= 400:
            raise BuildiumAPIError(resp.status_code, resp.text, {})
        return resp.json()

    # ── Pagination helper ───────────────────────────────────────────
    async def _get_all(self, path: str, params: dict = None, key: str = None) -> list:
        """Paginate through all results automatically."""
        all_results = []
        offset = 0
        params = params or {}
        params["pagesize"] = self.page_size

        while True:
            params["offset"] = offset
            data = await self._get(path, params)
            items = data if isinstance(data, list) else data.get(key or "results", data)
            if not items:
                break
            all_results.extend(items)
            if len(items) < self.page_size:
                break
            offset += self.page_size
            logger.debug(f"Paginated {path}: {len(all_results)} fetched so far...")

        return all_results

    # ══════════════════════════════════════════════════════════════════
    # PROPERTIES
    # ══════════════════════════════════════════════════════════════════
    async def get_properties(self, since: datetime = None) -> list[dict]:
        """Pull all rental properties. Returns normalized COrtai format."""
        params = {}
        if since:
            params["lastmodifieddatetimeto"] = since.isoformat()

        raw = await self._get_all("/rentals", params)
        return [self._normalize_property(p) for p in raw]

    async def get_property(self, buildium_id: int) -> dict:
        raw = await self._get(f"/rentals/{buildium_id}")
        return self._normalize_property(raw)

    def _normalize_property(self, raw: dict) -> dict:
        addr = raw.get("Address", {})
        return {
            "buildium_id":          raw.get("Id"),
            "name":                 raw.get("Name", ""),
            "address":              addr.get("AddressLine1", ""),
            "address2":             addr.get("AddressLine2"),
            "city":                 addr.get("City", ""),
            "state_province":       addr.get("StateOrProvince", "ON"),
            "postal_code":          addr.get("PostalCode", ""),
            "country":              addr.get("Country", "CA"),
            "property_type":        raw.get("Type"),
            "structure_type":       raw.get("Structure"),
            "year_built":           raw.get("YearBuilt"),
            "reserve_fund":         raw.get("ReserveFundAmount"),
            "is_active":            raw.get("IsActive", True),
            "buildium_created_at":  parse_buildium_ts(raw.get("CreatedDateTime")),
            "buildium_updated_at":  parse_buildium_ts(raw.get("UpdatedDateTime")),
        }

    # ══════════════════════════════════════════════════════════════════
    # UNITS
    # ══════════════════════════════════════════════════════════════════
    async def get_units(self, property_buildium_id: int = None) -> list[dict]:
        params = {}
        if property_buildium_id:
            params["propertyids"] = property_buildium_id
        raw = await self._get_all("/rentals/units", params)
        return [self._normalize_unit(u) for u in raw]

    def _normalize_unit(self, raw: dict) -> dict:
        addr = raw.get("Address", {})
        return {
            "buildium_id":      raw.get("Id"),
            "unit_number":      raw.get("UnitNumber", ""),
            "address":          addr.get("AddressLine1"),
            "unit_type":        raw.get("UnitType"),
            "beds":             raw.get("Bedrooms"),
            "baths":            raw.get("Bathrooms"),
            "sqft":             raw.get("Area"),
            "market_rent":      raw.get("MarketRent"),
            "is_active":        raw.get("IsActive", True),
            "buildium_updated_at": parse_buildium_ts(raw.get("UpdatedDateTime")),
            # property_id populated by sync engine via FK lookup
            "_property_buildium_id": raw.get("Property", {}).get("Id") if isinstance(raw.get("Property"), dict) else raw.get("PropertyId"),
        }

    # ══════════════════════════════════════════════════════════════════
    # OWNERS
    # ══════════════════════════════════════════════════════════════════
    async def get_owners(self) -> list[dict]:
        raw = await self._get_all("/rentals/owners")
        return [self._normalize_owner(o) for o in raw]

    def _normalize_owner(self, raw: dict) -> dict:
        return {
            "buildium_id":  raw.get("Id"),
            "first_name":   raw.get("FirstName"),
            "last_name":    raw.get("LastName"),
            "company_name": raw.get("CompanyName"),
            "email":        (raw.get("PrimaryEmail") or raw.get("AlternateEmail")),
            "phone":        next((p.get("Number") for p in raw.get("PhoneNumbers", []) if p.get("IsPrimary")), None),
            "is_company":   raw.get("IsCompany", False),
            "is_active":    raw.get("IsActive", True),
        }

    # ══════════════════════════════════════════════════════════════════
    # TENANTS / RESIDENTS
    # ══════════════════════════════════════════════════════════════════
    async def get_tenants(self) -> list[dict]:
        raw = await self._get_all("/leases/tenants")
        return [self._normalize_tenant(t) for t in raw]

    async def get_tenant(self, buildium_id: int) -> dict:
        raw = await self._get(f"/leases/tenants/{buildium_id}")
        return self._normalize_tenant(raw)

    def _normalize_tenant(self, raw: dict) -> dict:
        phones = raw.get("PhoneNumbers", [])
        primary_phone = next((p.get("Number") for p in phones if p.get("IsPrimary")), None)
        return {
            "buildium_id":  raw.get("Id"),
            "first_name":   raw.get("FirstName", ""),
            "last_name":    raw.get("LastName", ""),
            "email":        raw.get("Email"),
            "phone":        primary_phone,
            "date_of_birth": parse_buildium_date(raw.get("DateOfBirth")),
            "company":      raw.get("Company"),
            "is_active":    raw.get("IsActive", True),
            "buildium_created_at": parse_buildium_ts(raw.get("CreatedDateTime")),
        }

    # ══════════════════════════════════════════════════════════════════
    # LEASES
    # ══════════════════════════════════════════════════════════════════
    async def get_leases(self, status: str = None) -> list[dict]:
        params = {}
        if status:
            params["leasestatuses"] = status  # 'Active','Eviction','PastTenant'
        raw = await self._get_all("/leases", params)
        return [self._normalize_lease(l) for l in raw]

    async def get_lease(self, buildium_id: int) -> dict:
        raw = await self._get(f"/leases/{buildium_id}")
        return self._normalize_lease(raw)

    def _normalize_lease(self, raw: dict) -> dict:
        return {
            "buildium_id":      raw.get("Id"),
            "lease_type":       raw.get("LeaseType"),           # 'Fixed','AtWill'
            "lease_status":     raw.get("LeaseStatus"),
            "rent_amount":      raw.get("Rent"),
            "security_deposit": raw.get("SecurityDeposit"),
            "start_date":       parse_buildium_date(raw.get("StartDate")),
            "end_date":         parse_buildium_date(raw.get("EndDate")),
            "move_in_date":     parse_buildium_date(raw.get("MoveInDate")),
            "move_out_date":    parse_buildium_date(raw.get("MoveOutDate")),
            "is_active":        raw.get("LeaseStatus") == "Active",
            "_unit_buildium_id": raw.get("Unit", {}).get("Id") if isinstance(raw.get("Unit"), dict) else None,
            "_residents":       raw.get("LeaseResidents", []),
            "buildium_updated_at": parse_buildium_ts(raw.get("UpdatedDateTime")),
        }

    # ══════════════════════════════════════════════════════════════════
    # WORK ORDERS / MAINTENANCE REQUESTS
    # ══════════════════════════════════════════════════════════════════
    async def get_work_orders(self, statuses: list = None, since: datetime = None) -> list[dict]:
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
        return [self._normalize_wo(w) for w in all_results]

    async def push_work_order(self, wo: dict) -> dict:
        """Create a new work order in Buildium."""
        body = {
            "Title": wo["title"],
            "Description": wo.get("description", ""),
            "Category": wo.get("category", "General"),
            "Priority": self._map_priority_to_buildium(wo.get("priority", "Normal")),
            "UnitId": wo.get("_unit_buildium_id"),
            "DueDate": wo.get("scheduled_date"),
        }
        result = await self._post("/tasks/residentrequests", {k: v for k, v in body.items() if v is not None})
        return result

    async def update_work_order_status(self, buildium_task_id: int, status: str, notes: str = None) -> dict:
        body = {"TaskStatus": self._map_status_to_buildium(status)}
        if notes:
            body["Message"] = notes
        return await self._put(f"/tasks/residentrequests/{buildium_task_id}", body)

    def _normalize_wo(self, raw: dict) -> dict:
        tid = raw.get("Id")
        if tid is None:
            tid = raw.get("id")
        tst = raw.get("TaskStatus") or raw.get("task_status")
        uid = raw.get("UnitId")
        if uid is None:
            uid = raw.get("unit_id")
        return {
            "buildium_task_id": tid,
            "title":            raw.get("Title") or raw.get("title") or "",
            "description":      raw.get("Description") or raw.get("description"),
            "status":           self._map_status_from_buildium(tst),
            "_unit_buildium_id": uid,
            "submitted_source": "Buildium",
            "buildium_synced_at": datetime.utcnow(),
        }

    def _map_priority_to_buildium(self, priority: str) -> str:
        return {"Emergency": "Emergency", "Urgent": "High", "High": "High",
                "Normal": "Normal", "Low": "Low", "Preventive": "Low"}.get(priority, "Normal")

    def _map_status_to_buildium(self, status: str) -> str:
        return {"Submitted": "New", "Dispatched": "Assigned", "Scheduled": "Assigned",
                "In Progress": "InProgress", "Parts Pending": "InProgress",
                "Completed": "Completed", "Closed": "Completed"}.get(status, "New")

    def _map_status_from_buildium(self, status: str) -> str:
        return {"New": "Submitted", "Assigned": "Dispatched", "InProgress": "In Progress",
                "Completed": "Completed", "Closed": "Closed"}.get(status or "", "Submitted")

    # ══════════════════════════════════════════════════════════════════
    # PAYMENTS
    # ══════════════════════════════════════════════════════════════════
    async def get_lease_transactions(self, lease_buildium_id: int, since: datetime = None) -> list[dict]:
        params = {}
        if since:
            params["from"] = since.strftime("%Y-%m-%d")
        raw = await self._get_all(f"/leases/{lease_buildium_id}/transactions", params)
        return [self._normalize_payment(p, lease_buildium_id) for p in raw]

    async def get_outstanding_balances(self) -> list[dict]:
        raw = await self._get_all("/leases/outstandingbalances")
        return raw

    def _normalize_payment(self, raw: dict, lease_buildium_id: int) -> dict:
        return {
            "buildium_id":      raw.get("Id"),
            "payment_type":     raw.get("Type"),
            "amount":           raw.get("TotalAmount"),
            "payment_date":     parse_buildium_date(raw.get("Date")),
            "memo":             raw.get("Memo"),
            "is_voided":        raw.get("IsVoided", False),
            "_lease_buildium_id": lease_buildium_id,
        }

    # ══════════════════════════════════════════════════════════════════
    # VENDORS
    # ══════════════════════════════════════════════════════════════════
    async def get_vendors(self, is_active: bool = True) -> list[dict]:
        params = {"isactive": str(is_active).lower()}
        raw = await self._get_all("/vendors", params)
        return [self._normalize_vendor(v) for v in raw]

    async def push_vendor(self, vendor: dict) -> dict:
        body = {
            "CompanyName": vendor.get("company_name"),
            "FirstName": vendor.get("first_name"),
            "LastName": vendor.get("last_name"),
            "Email": vendor.get("email"),
            "PhoneNumbers": [{"Number": vendor["phone"], "PhoneType": "Main"}] if vendor.get("phone") else [],
            "Is1099": vendor.get("is_1099", False),
        }
        return await self._post("/vendors", body)

    def _normalize_vendor(self, raw: dict) -> dict:
        phones = raw.get("PhoneNumbers", [])
        return {
            "buildium_id":  raw.get("Id"),
            "company_name": raw.get("CompanyName", ""),
            "first_name":   raw.get("FirstName"),
            "last_name":    raw.get("LastName"),
            "email":        raw.get("Email"),
            "phone":        next((p.get("Number") for p in phones if p.get("PhoneType") == "Main"), None),
            "is_active":    raw.get("IsActive", True),
            "is_1099":      raw.get("Is1099", False),
            "tax_id":       raw.get("TaxInformation", {}).get("TaxIdentificationNumber"),
        }
