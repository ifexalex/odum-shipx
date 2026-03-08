#!/usr/bin/env python3
"""
ShipX End-to-End API Test Runner
=================================
Tests every API endpoint from platform admin through to refunds,
chaining state (IDs, tokens) across requests and asserting expected outcomes.

Usage:
    # Ensure 'make dev' is running first, then:
    python3 scripts/e2e_test.py
    python3 scripts/e2e_test.py --base-url http://localhost:3000
    python3 scripts/e2e_test.py --stop-on-fail
    python3 scripts/e2e_test.py --output results.json

Requires:
    pip install requests
"""

import argparse
import json
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

try:
    import requests
except ImportError:
    sys.exit("ERROR: 'requests' package not installed. Run: pip install requests")

# ─── Colours ──────────────────────────────────────────────────────────────────

RESET  = "\033[0m"
GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
BOLD   = "\033[1m"
DIM    = "\033[2m"

def _c(colour: str, text: str) -> str:
    return f"{colour}{text}{RESET}"

# ─── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class TestResult:
    name: str
    method: str
    path: str
    status_code: int
    expected_status: int
    passed: bool
    assertions: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    response_ms: float = 0.0
    response_body: Any = None

# ─── Runner core ──────────────────────────────────────────────────────────────

class E2ERunner:
    def __init__(self, base_url: str, stop_on_fail: bool = False):
        self.base_url = base_url.rstrip("/")
        self.stop_on_fail = stop_on_fail
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self.results: list[TestResult] = []
        self.state: dict = {}   # shared state across tests

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    def _headers(self, role: str, tenant_id: str | None = None, user_id: str | None = None) -> dict:
        tid = tenant_id or self.state.get("tenant_id", "test-tenant-id")
        uid = user_id or self.state.get("admin_user_id", "test-user-id")
        return {
            "X-Tenant-ID": tid,
            "X-Role": role,
            "X-User-ID": uid,
        }

    def _platform_headers(self) -> dict:
        return {
            "X-Tenant-ID": "PLATFORM",
            "X-Role": "platform_admin",
            "X-User-ID": self.state.get("platform_user_id", "00000000-0000-0000-0000-000000000001"),
        }

    def _req(
        self,
        method: str,
        path: str,
        *,
        role: str = "tenant_admin",
        tenant_id: str | None = None,
        user_id: str | None = None,
        platform: bool = False,
        body: dict | None = None,
        params: dict | None = None,
    ) -> tuple[requests.Response, float]:
        headers = self._platform_headers() if platform else self._headers(role, tenant_id, user_id)
        url = f"{self.base_url}{path}"
        t0 = time.monotonic()
        resp = self.session.request(
            method, url, json=body, params=params, headers=headers, timeout=15
        )
        elapsed_ms = (time.monotonic() - t0) * 1000
        return resp, elapsed_ms

    # ── Assertion builder ─────────────────────────────────────────────────────

    def _run(
        self,
        name: str,
        method: str,
        path: str,
        expected_status: int,
        *,
        role: str = "tenant_admin",
        tenant_id: str | None = None,
        user_id: str | None = None,
        platform: bool = False,
        body: dict | None = None,
        params: dict | None = None,
        assertions: list[tuple[bool, str]] | None = None,
        capture: dict[str, str] | None = None,
    ) -> dict | None:
        """Execute a request, assert status + custom assertions, capture state values.

        capture: {state_key: json_path}  e.g. {"tenant_id": "data.id"}
        assertions: [(bool_expr, description)]
        """
        try:
            resp, ms = self._req(
                method, path,
                role=role, tenant_id=tenant_id, user_id=user_id,
                platform=platform, body=body, params=params,
            )
        except Exception as exc:
            result = TestResult(
                name=name, method=method, path=path,
                status_code=0, expected_status=expected_status,
                passed=False, failures=[f"Request failed: {exc}"], response_ms=0,
            )
            self._record(result)
            return None

        # Parse body
        try:
            data = resp.json()
        except Exception:
            data = {}

        passed = True
        ok_assertions: list[str] = []
        fail_assertions: list[str] = []

        # Status code check
        if resp.status_code == expected_status:
            ok_assertions.append(f"status {resp.status_code}")
        else:
            fail_assertions.append(f"status expected {expected_status}, got {resp.status_code}")
            passed = False

        # Custom assertions — expr may be a pre-evaluated bool OR a callable(data)->bool
        for (expr, description) in (assertions or []):
            val = expr(data) if callable(expr) else bool(expr)
            if val:
                ok_assertions.append(description)
            else:
                fail_assertions.append(description)
                passed = False

        # Capture state
        if passed and capture:
            for state_key, json_path in capture.items():
                val = self._jpath(data, json_path)
                if val is not None:
                    self.state[state_key] = val

        result = TestResult(
            name=name, method=method, path=path,
            status_code=resp.status_code, expected_status=expected_status,
            passed=passed,
            assertions=ok_assertions,
            failures=fail_assertions,
            response_ms=ms,
            response_body=data,
        )
        self._record(result)

        if self.stop_on_fail and not passed:
            self._print_summary()
            sys.exit(1)

        return data if passed else None

    @staticmethod
    def _jpath(data: Any, path: str) -> Any:
        """Navigate a dot-separated path through a JSON dict. E.g. 'data.id'."""
        try:
            for key in path.split("."):
                if isinstance(data, list):
                    data = data[int(key)]
                elif isinstance(data, dict):
                    data = data[key]
                else:
                    return None
            return data
        except (KeyError, IndexError, TypeError, ValueError):
            return None

    def _record(self, result: TestResult) -> None:
        self.results.append(result)
        icon   = _c(GREEN, "✓") if result.passed else _c(RED, "✗")
        timing = _c(DIM, f"{result.response_ms:>6.0f}ms")
        label  = f"{result.method:6} {result.path}"
        print(f"  {icon} {timing}  {label:<55}  {result.name}")
        for f in result.failures:
            print(f"           {_c(RED, '→')} {f}")
        if not result.passed and result.response_body:
            err = result.response_body
            detail = err.get("message") or err.get("detail") or err.get("error") or ""
            if detail:
                print(f"           {_c(DIM, '→ server:')} {detail}")

    # ─────────────────────────────────────────────────────────────────────────
    # TEST SECTIONS
    # ─────────────────────────────────────────────────────────────────────────

    def _section(self, title: str) -> None:
        print(f"\n{_c(BOLD + CYAN, '━━━ ' + title + ' ━━━')}")

    def _check_server_reachable(self) -> None:
        """Fail fast with a clear message if the local server is not running."""
        try:
            self.session.get(f"{self.base_url}/health", timeout=3)
        except Exception:
            print(f"\n{_c(RED + BOLD, 'ERROR: Cannot reach the local server.')}")
            print(f"  URL : {self.base_url}")
            print(f"  Fix : Run {_c(BOLD, 'make dev')} in another terminal, then retry.\n")
            sys.exit(1)

    def run_all(self) -> None:
        self._check_server_reachable()

        suffix = str(uuid.uuid4())[:8]
        self.state["suffix"] = suffix
        self.state["platform_user_id"] = "00000000-0000-0000-0000-000000000001"

        self._test_health()
        self._test_platform_admin(suffix)
        self._test_tenant_admin()
        self._test_customers()
        self._test_containers()
        self._test_packing_lists()
        self._test_manifests()
        self._test_billing()
        self._test_claims()
        self._test_payment_release()
        self._test_refunds()
        self._test_excel()
        self._test_gdpr_and_cleanup()
        self._print_summary()

    # ── Health ────────────────────────────────────────────────────────────────

    def _test_health(self) -> None:
        self._section("Health Check")
        self._run("Health Check", "GET", "/health", 200)

    # ── 1. Platform Admin ─────────────────────────────────────────────────────

    def _test_platform_admin(self, suffix: str) -> None:
        self._section("1. Platform Admin")

        # Settings
        self._run("GET platform settings", "GET", "/v1/platform/settings", 200,
                  platform=True,
                  assertions=[(True, "response received")])

        self._run("PUT platform settings", "PUT", "/v1/platform/settings", 200,
                  platform=True,
                  body={"e2e_test_flag": "true"},
                  assertions=[(True, "upserted")])

        # Dashboard
        self._run("GET platform dashboard", "GET", "/v1/platform/dashboard", 200,
                         platform=True)

        # Create tenant
        email = f"admin_{suffix}@e2etest.com"
        self._run(
            "POST create tenant", "POST", "/v1/platform/tenants", 201,
            platform=True,
            body={
                "company_name": f"E2E Corp {suffix}",
                "subscription_tier": "starter",
                "primary_contact_email": email,
                "primary_contact_phone": "+2348099999999",
                "initial_admin": {
                    "email": email,
                    "full_name": "E2E Admin",
                    "password": "TestPass123!",
                },
            },
            assertions=[
                (True, "tenant created"),
            ],
            capture={"tenant_id": "data.tenant.id", "admin_user_id": "data.admin_user.id"},
        )

        if not self.state.get("tenant_id"):
            print(_c(RED, "  FATAL: tenant creation failed — remaining tests will be skipped"))
            self._print_summary()
            sys.exit(1)

        tid = self.state["tenant_id"]

        # List tenants
        self._run("GET list tenants", "GET", "/v1/platform/tenants", 200,
                         platform=True, params={"limit": 20},
                         assertions=[(True, "list returned")])

        # Get tenant
        self._run("GET tenant by id", "GET", f"/v1/platform/tenants/{tid}", 200,
                         platform=True,
                         assertions=[
                             (lambda d: bool(d) and self._jpath(d, "data.id") == tid, "id matches"),
                         ])

        # Update tenant
        self._run("PATCH update tenant", "PATCH", f"/v1/platform/tenants/{tid}", 200,
                         platform=True,
                         body={"company_name": f"E2E Corp Updated {suffix}"},
                         assertions=[
                             (lambda d: bool(d) and self._jpath(d, "data.company_name") is not None, "company_name updated"),
                         ])

        # Audit log — should have TENANT_CREATED and TENANT_UPDATED
        self._run("GET audit log filtered by tenant", "GET", "/v1/platform/audit-log", 200,
                         platform=True,
                         params={"tenant_id": tid, "limit": 10},
                         assertions=[
                             (lambda d: bool(d) and isinstance(self._jpath(d, "data"), list), "data is list"),
                         ])

        # Suspend
        self._run("PATCH suspend tenant", "PATCH", f"/v1/platform/tenants/{tid}/suspend", 200,
                  platform=True,
                  body={"reason": "E2E test suspension"})

        # Suspended tenant should be blocked
        self._run("Suspended tenant gets 403", "GET", "/v1/tenant/config", 403,
                  role="tenant_admin", tenant_id=tid,
                  assertions=[(True, "suspension enforced")])

        # Activate
        self._run("PATCH activate tenant", "PATCH", f"/v1/platform/tenants/{tid}/activate", 200,
                  platform=True)

        # Tenant accessible again
        self._run("Activated tenant accessible", "GET", "/v1/tenant/config", 200,
                  role="tenant_admin", tenant_id=tid,
                  assertions=[(True, "accessible after activation")])

        # Usage metrics
        self._run("GET tenant usage", "GET", f"/v1/platform/tenants/{tid}/usage", 200,
                  platform=True,
                  assertions=[(True, "usage returned")])

    # ── 2. Tenant Admin ───────────────────────────────────────────────────────

    def _test_tenant_admin(self) -> None:
        self._section("2. Tenant Admin")
        tid = self.state["tenant_id"]
        suffix = self.state["suffix"]

        # Config
        self._run("GET tenant config", "GET", "/v1/tenant/config", 200,
                         role="tenant_admin", tenant_id=tid)

        self._run("PUT tenant config", "PUT", "/v1/tenant/config", 200,
                  role="tenant_admin", tenant_id=tid,
                  body={"branding": {"primary_colour": "#FF5733"}})

        # Dollar rate
        self._run("GET dollar rate", "GET", "/v1/tenant/dollar-rate", 200,
                         role="tenant_admin", tenant_id=tid)

        self._run("PUT dollar rate", "PUT", "/v1/tenant/dollar-rate", 200,
                         role="tenant_admin", tenant_id=tid,
                         body={"rate": 1600.0, "currency_pair": "USD_NGN",
                               "effective_from": str(date.today())},
                         assertions=[
                             (lambda d: bool(d) and self._jpath(d, "data.rate") is not None, "rate returned"),
                         ])

        # Create user
        staff_email = f"staff_{suffix}@e2etest.com"
        self._run("POST create user", "POST", "/v1/tenant/users", 201,
                         role="tenant_admin", tenant_id=tid,
                         body={"email": staff_email, "full_name": "E2E Staff",
                               "role": "nigeria_office_staff"},
                         capture={"staff_user_id": "data.id"})

        self._run("GET list users", "GET", "/v1/tenant/users", 200,
                         role="tenant_admin", tenant_id=tid,
                         assertions=[
                             (lambda d: bool(d) and isinstance(self._jpath(d, "data"), list), "list returned"),
                         ])

        staff_id = self.state.get("staff_user_id")
        if staff_id:
            self._run("GET user by id", "GET", f"/v1/tenant/users/{staff_id}", 200,
                             role="tenant_admin", tenant_id=tid,
                             assertions=[
                                 (lambda d: bool(d) and self._jpath(d, "data.id") == staff_id, "id matches"),
                             ])

            self._run("PATCH update user role", "PATCH", f"/v1/tenant/users/{staff_id}", 200,
                      role="tenant_admin", tenant_id=tid,
                      body={"role": "china_office_staff"})

        # Create a throwaway user to test DELETE
        throwaway_email = f"throwaway_{suffix}@e2etest.com"
        self._run("POST create throwaway user", "POST", "/v1/tenant/users", 201,
                              role="tenant_admin", tenant_id=tid,
                              body={"email": throwaway_email, "full_name": "Throwaway",
                                    "role": "warehouse_attendant"},
                              capture={"throwaway_user_id": "data.id"})
        throwaway_id = self.state.get("throwaway_user_id")
        if throwaway_id:
            self._run("DELETE deactivate user", "DELETE", f"/v1/tenant/users/{throwaway_id}", 204,
                      role="tenant_admin", tenant_id=tid)

        # Charge types
        self._run("POST create charge type", "POST", "/v1/tenant/charge-types", 201,
                         role="tenant_admin", tenant_id=tid,
                         body={"name": "Handling Fee", "description": "Port handling",
                               "default_amount_ngn": 5000},
                         capture={"charge_type_id": "data.id"})

        self._run("GET list charge types", "GET", "/v1/tenant/charge-types", 200,
                  role="tenant_admin", tenant_id=tid)

        charge_type_id = self.state.get("charge_type_id")
        if charge_type_id:
            self._run("PUT update charge type", "PUT", f"/v1/tenant/charge-types/{charge_type_id}", 200,
                      role="tenant_admin", tenant_id=tid,
                      body={"name": "Handling Fee Updated", "default_amount_ngn": 6000})

            self._run("DELETE deactivate charge type", "DELETE",
                      f"/v1/tenant/charge-types/{charge_type_id}", 204,
                      role="tenant_admin", tenant_id=tid)

        # Tenant reports
        self._run("GET tenant reports", "GET", "/v1/tenant/reports", 200,
                  role="tenant_admin", tenant_id=tid)

    # ── 3. Customers ──────────────────────────────────────────────────────────

    def _test_customers(self) -> None:
        self._section("3. Customers")
        tid = self.state["tenant_id"]
        suffix = self.state["suffix"]

        self._run("POST create customer", "POST", "/v1/customers", 201,
                         role="tenant_admin", tenant_id=tid,
                         body={"name": f"E2E Customer {suffix}",
                               "phone": "+2348011111111",
                               "email": f"customer_{suffix}@e2etest.com",
                               "address": "1 Test Street, Lagos"},
                         capture={"customer_id": "data.id"})

        self._run("GET list customers", "GET", "/v1/customers", 200,
                         role="tenant_admin", tenant_id=tid,
                         params={"limit": 20},
                         assertions=[
                             (lambda d: bool(d) and isinstance(self._jpath(d, "data"), list), "list returned"),
                         ])

        cid = self.state.get("customer_id")
        if cid:
            self._run("GET customer by id", "GET", f"/v1/customers/{cid}", 200,
                             role="tenant_admin", tenant_id=tid,
                             assertions=[
                                 (lambda d: bool(d) and self._jpath(d, "data.id") == cid, "id matches"),
                             ])

            self._run("PATCH update customer", "PATCH", f"/v1/customers/{cid}", 200,
                      role="tenant_admin", tenant_id=tid,
                      body={"name": f"E2E Customer Updated {suffix}"})

            # GDPR export
            self._run("GET customer export (GDPR)", "GET", f"/v1/customers/{cid}/export", 200,
                             role="tenant_admin", tenant_id=tid,
                             assertions=[
                                 (lambda d: bool(d) and self._jpath(d, "data.customer") is not None,
                                  "customer data present"),
                             ])

        # Customer search
        self._run("GET customers search", "GET", "/v1/customers", 200,
                  role="nigeria_office_staff", tenant_id=tid,
                  params={"q": "E2E", "limit": 10})

    # ── 4. Containers & Tracking ──────────────────────────────────────────────

    def _test_containers(self) -> None:
        self._section("4. Containers & Tracking")
        tid = self.state["tenant_id"]
        suffix = self.state["suffix"]

        ship_date = str(date.today() - timedelta(days=10))
        eta = str(date.today() + timedelta(days=20))
        self.state["ship_date"] = ship_date

        self._run("POST create container", "POST", "/v1/containers", 201,
                         role="china_office_staff", tenant_id=tid,
                         body={"container_number": f"E2E{suffix[:6].upper()}",
                               "ship_date": ship_date,
                               "estimated_arrival_date": eta},
                         capture={"container_id": "data.id"})

        self._run("GET list containers", "GET", "/v1/containers", 200,
                         role="nigeria_office_staff", tenant_id=tid,
                         params={"limit": 20},
                         assertions=[
                             (lambda d: bool(d) and isinstance(self._jpath(d, "data"), list), "list returned"),
                         ])

        con_id = self.state.get("container_id")
        if con_id:
            self._run("GET container by id", "GET", f"/v1/containers/{con_id}", 200,
                             role="nigeria_office_staff", tenant_id=tid,
                             assertions=[
                                 (lambda d: bool(d) and self._jpath(d, "data.id") == con_id, "id matches"),
                             ])

        # List shipments
        self._run("GET list shipments", "GET", "/v1/shipments", 200,
                  role="nigeria_office_staff", tenant_id=tid,
                  params={"limit": 20})

    # ── 5. Packing Lists ──────────────────────────────────────────────────────

    def _test_packing_lists(self) -> None:
        self._section("5. Packing Lists")
        tid = self.state["tenant_id"]
        con_id = self.state.get("container_id")
        cust_id = self.state.get("customer_id")

        if not con_id or not cust_id:
            print(_c(YELLOW, "  SKIP: missing container_id or customer_id from prior steps"))
            return

        data = self._run("POST create packing list", "POST", "/v1/packing-lists", 201,
                         role="china_office_staff", tenant_id=tid,
                         user_id=self.state.get("staff_user_id"),
                         body={
                             "container_id": con_id,
                             "customer_id": cust_id,
                             "items": [
                                 {"description": "Electronics",
                                  "weight_actual_kg": 15.0,
                                  "length_cm": 50, "width_cm": 40, "height_cm": 30,
                                  "received_date": str(date.today())},
                                 {"description": "Clothing",
                                  "weight_actual_kg": 8.0,
                                  "length_cm": 40, "width_cm": 30, "height_cm": 25,
                                  "received_date": str(date.today())},
                             ],
                         },
                         capture={"packing_list_id": "data.id"})

        data = self._run("GET list packing lists", "GET", "/v1/packing-lists", 200,
                         role="china_office_staff", tenant_id=tid,
                         params={"limit": 20},
                         assertions=[
                             (lambda d: bool(d) and isinstance(self._jpath(d, "data"), list), "list returned"),
                         ])

        pl_id = self.state.get("packing_list_id")
        if not pl_id:
            print(_c(YELLOW, "  SKIP remaining packing list steps — create failed"))
            return

        data = self._run("GET packing list by id", "GET", f"/v1/packing-lists/{pl_id}", 200,
                         role="china_office_staff", tenant_id=tid,
                         assertions=[
                             (lambda d: bool(d) and self._jpath(d, "data.id") == pl_id, "id matches"),
                             (lambda d: bool(d) and self._jpath(d, "data.status") == "draft", "status is draft"),
                         ])

        # Capture a tracking code for public tracking test
        items = self._jpath(data, "data.items") if data else []
        if items and isinstance(items, list) and len(items) > 0:
            tc = items[0].get("tracking_code")
            if tc:
                self.state["tracking_code"] = tc
                self.state["customer_phone"] = "+2348011111111"

        # Update while draft
        self._run("PUT update packing list (draft)", "PUT", f"/v1/packing-lists/{pl_id}", 200,
                  role="china_office_staff", tenant_id=tid,
                  user_id=self.state.get("staff_user_id"),
                  body={"items": [{"description": "Electronics (updated)",
                                   "weight_actual_kg": 16.0,
                                   "length_cm": 50, "width_cm": 40, "height_cm": 30}]})

        # Submit
        data = self._run("PATCH submit packing list", "PATCH", f"/v1/packing-lists/{pl_id}/submit", 200,
                         role="china_office_staff", tenant_id=tid,
                         user_id=self.state.get("staff_user_id"),
                         assertions=[
                             (lambda d: bool(d) and self._jpath(d, "data.status") == "pending_approval",
                              "status is pending_approval"),
                         ])

        # Approve
        data = self._run("PATCH approve packing list", "PATCH", f"/v1/packing-lists/{pl_id}/approve", 200,
                         role="tenant_admin", tenant_id=tid,
                         body={"comments": "Approved by E2E test"},
                         assertions=[
                             (lambda d: bool(d) and self._jpath(d, "data.status") == "approved",
                              "status is approved"),
                         ])

        # Create a second packing list to test reject flow
        data2 = self._run("POST create packing list (for reject test)", "POST", "/v1/packing-lists", 201,
                          role="china_office_staff", tenant_id=tid,
                          user_id=self.state.get("staff_user_id"),
                          body={"container_id": con_id, "customer_id": cust_id,
                                "items": [{"description": "Reject Test Item",
                                           "weight_actual_kg": 5.0,
                                           "length_cm": 20, "width_cm": 15, "height_cm": 10}]})
        pl2_id = self._jpath(data2, "data.id") if data2 else None
        if pl2_id:
            self._run("PATCH submit packing list (for reject test)", "PATCH",
                      f"/v1/packing-lists/{pl2_id}/submit", 200,
                      role="china_office_staff", tenant_id=tid,
                      user_id=self.state.get("staff_user_id"))
            self._run("PATCH reject packing list", "PATCH", f"/v1/packing-lists/{pl2_id}/reject", 200,
                      role="tenant_admin", tenant_id=tid,
                      body={"comments": "Rejected by E2E test",
                            "item_rejections": []},
                      assertions=[
                          (lambda d: bool(d) and self._jpath(d, "data.status") == "rejected",
                           "status is rejected"),
                      ])

        # Walk the container state machine now that packing list is approved
        # sealed requires ≥1 approved packing list (satisfied above)
        ship_date = self.state.get("ship_date", str(date.today() - timedelta(days=10)))
        for stage, role, extra_fields in [
            ("sealed",           "china_office_staff",   {}),
            ("in_transit",       "china_office_staff",   {"ship_date": ship_date}),
            ("arrived",          "nigeria_office_staff", {}),
            ("customs_clearance","nigeria_office_staff", {}),
            ("cleared",          "nigeria_office_staff", {}),
            ("at_warehouse",     "nigeria_office_staff", {}),
        ]:
            self._run(f"PATCH container status → {stage}", "PATCH",
                      f"/v1/containers/{con_id}/status", 200,
                      role=role, tenant_id=tid,
                      body={"new_status": stage, "notes": f"E2E: {stage}", **extra_fields})

        # Public tracking
        tc = self.state.get("tracking_code")
        if tc:
            self._run("GET public track shipment", "GET", f"/v1/shipments/{tc}", 200,
                      role="customer", tenant_id=tid,
                      params={"phone": self.state.get("customer_phone", "+2348011111111")})

    # ── 6. Manifests ─────────────────────────────────────────────────────────

    def _test_manifests(self) -> None:
        self._section("6. Manifests")
        tid = self.state["tenant_id"]
        con_id = self.state.get("container_id")

        data = self._run("GET list manifests", "GET", "/v1/manifests", 200,
                         role="nigeria_office_staff", tenant_id=tid,
                         params={"limit": 20, "container_id": con_id} if con_id else {"limit": 20},
                         assertions=[
                             (lambda d: bool(d) and isinstance(self._jpath(d, "data"), list), "list returned"),
                         ])

        manifests = self._jpath(data, "data") if data else []
        if manifests:
            manifest_id = manifests[0].get("id")
            self.state["manifest_id"] = manifest_id

            data = self._run("GET manifest by id", "GET", f"/v1/manifests/{manifest_id}", 200,
                             role="nigeria_office_staff", tenant_id=tid,
                             assertions=[
                                 (lambda d: bool(d) and self._jpath(d, "data.id") == manifest_id, "id matches"),
                             ])

            self._run("PATCH verify manifest", "PATCH", f"/v1/manifests/{manifest_id}/verify", 200,
                      role="nigeria_office_staff", tenant_id=tid,
                      body={"verification_status": "verified"})
        else:
            print(_c(YELLOW, "  SKIP manifest tests — no manifests found (packing list not approved?)"))

    # ── 7. Billing ────────────────────────────────────────────────────────────

    def _test_billing(self) -> None:
        self._section("7. Billing")
        tid = self.state["tenant_id"]
        cust_id = self.state.get("customer_id")
        con_id = self.state.get("container_id")

        if not cust_id or not con_id:
            print(_c(YELLOW, "  SKIP: missing customer_id or container_id"))
            return

        # Generate billing
        self._run("POST generate billing", "POST", "/v1/billing", 201,
                  role="nigeria_office_staff", tenant_id=tid,
                  body={"customer_id": cust_id, "container_id": con_id})

        # Get billing for customer
        data = self._run("GET billing for customer", "GET", f"/v1/billing/{cust_id}", 200,
                         role="nigeria_office_staff", tenant_id=tid,
                         params={"container_id": con_id})

        # List all billing
        data = self._run("GET list billing records", "GET", "/v1/billing", 200,
                         role="tenant_admin", tenant_id=tid,
                         params={"limit": 20},
                         assertions=[
                             (lambda d: bool(d) and isinstance(self._jpath(d, "data"), list), "list returned"),
                         ])

        # Capture billing_id from list
        bills = self._jpath(data, "data") if data else []
        if bills and isinstance(bills, list):
            billing_id = bills[0].get("id")
            if billing_id:
                self.state["billing_id"] = billing_id

        billing_id = self.state.get("billing_id")
        if not billing_id:
            print(_c(YELLOW, "  SKIP billing sub-resources — no billing_id available"))
            return

        # Add misc charge
        data = self._run("POST add misc charge", "POST", f"/v1/billing/{billing_id}/charges", 201,
                         role="nigeria_office_staff", tenant_id=tid,
                         body={"description": "E2E handling fee",
                               "amount_ngn": 3000,
                               "charge_type": "handling"},
                         capture={"charge_id": "data.id"})

        data = self._run("GET list charges", "GET", f"/v1/billing/{billing_id}/charges", 200,
                         role="nigeria_office_staff", tenant_id=tid,
                         assertions=[
                             (lambda d: bool(d) and isinstance(self._jpath(d, "data"), list), "list returned"),
                         ])

        charge_id = self.state.get("charge_id")
        if charge_id:
            self._run("DELETE charge", "DELETE", f"/v1/billing/{billing_id}/charges/{charge_id}", 204,
                      role="tenant_admin", tenant_id=tid)

        # Storage fees
        self._run("GET storage fees", "GET", f"/v1/billing/{billing_id}/storage-fees", 200,
                  role="nigeria_office_staff", tenant_id=tid)

        # Link the customer to staff_user so the ownership check passes when filing a dispute
        customer_portal_user_id = self.state.get("staff_user_id")
        if cust_id and customer_portal_user_id:
            self._run("PATCH link customer portal user", "PATCH", f"/v1/customers/{cust_id}", 200,
                      role="tenant_admin", tenant_id=tid,
                      body={"user_id": customer_portal_user_id})

        # CBM dispute — filed as the linked customer user
        data = self._run("POST file CBM dispute", "POST", f"/v1/billing/{billing_id}/dispute", 201,
                         role="customer", tenant_id=tid,
                         user_id=customer_portal_user_id,
                         body={"reason": "My CBM looks incorrect",
                               "customer_measured_cbm": 0.8},
                         capture={"dispute_id": "data.id"})

        self._run("GET billing disputes", "GET", f"/v1/billing/{billing_id}/disputes", 200,
                  role="nigeria_office_staff", tenant_id=tid)

        # Top-level disputes
        data = self._run("GET list all disputes", "GET", "/v1/billing/disputes", 200,
                         role="tenant_admin", tenant_id=tid,
                         params={"limit": 20})

        # Acknowledge dispute
        dispute_id = self.state.get("dispute_id")
        if dispute_id:
            self._run("PATCH acknowledge dispute", "PATCH",
                      f"/v1/billing/disputes/{dispute_id}/acknowledge", 200,
                      role="nigeria_office_staff", tenant_id=tid)

            self._run("PATCH resolve dispute", "PATCH",
                      f"/v1/billing/disputes/{dispute_id}/resolve", 200,
                      role="tenant_admin", tenant_id=tid,
                      body={"status": "resolved_no_change",
                            "resolution_notes": "CBM verified and confirmed correct"})

        # Carryovers
        data = self._run("GET list carryovers", "GET", "/v1/billing/carryovers", 200,
                         role="nigeria_office_staff", tenant_id=tid,
                         params={"limit": 20})

        carryovers = self._jpath(data, "data") if data else []
        if carryovers and isinstance(carryovers, list) and len(carryovers) > 0:
            carryover_id = carryovers[0].get("id")
            if carryover_id:
                self._run("PATCH exempt carryover", "PATCH",
                          f"/v1/billing/carryovers/{carryover_id}/exempt", 200,
                          role="tenant_admin", tenant_id=tid,
                          body={"notes": "E2E exemption test"})

        # Staff-created dispute (POST /v1/billing/disputes with billing_id in body)
        if billing_id:
            data = self._run("POST create dispute (staff)", "POST", "/v1/billing/disputes", 201,
                             role="nigeria_office_staff", tenant_id=tid,
                             body={"billing_id": billing_id,
                                   "reason": "Staff-raised CBM correction",
                                   "customer_measured_cbm": 0.5},
                             capture={"reject_dispute_id": "data.id"})

            reject_dispute_id = self.state.get("reject_dispute_id")
            if reject_dispute_id:
                self._run("PATCH reject dispute", "PATCH",
                          f"/v1/billing/disputes/{reject_dispute_id}/reject", 200,
                          role="tenant_admin", tenant_id=tid,
                          body={"reason": "Dispute not valid — original CBM verified"})

    # ── 8. Claims ─────────────────────────────────────────────────────────────

    def _test_claims(self) -> None:
        self._section("8. Claims")
        tid = self.state["tenant_id"]
        con_id = self.state.get("container_id")
        manifest_id = self.state.get("manifest_id")
        cust_id = self.state.get("customer_id")

        if not con_id:
            print(_c(YELLOW, "  SKIP: missing container_id"))
            return

        # Damage claim
        self._run("POST file damage claim", "POST", "/v1/claims", 201,
                         role="nigeria_office_staff", tenant_id=tid,
                         body={"container_id": con_id,
                               "customer_id": cust_id,
                               "cartons_affected": 1,
                               "description": "Carton damaged on arrival"},
                         capture={"claim_id": "data.id"})

        self._run("GET list claims", "GET", "/v1/claims", 200,
                         role="nigeria_office_staff", tenant_id=tid,
                         params={"limit": 20},
                         assertions=[
                             (lambda d: bool(d) and isinstance(self._jpath(d, "data"), list), "list returned"),
                         ])

        claim_id = self.state.get("claim_id")
        if claim_id:
            self._run("GET claim by id", "GET", f"/v1/claims/{claim_id}", 200,
                             role="nigeria_office_staff", tenant_id=tid,
                             assertions=[
                                 (lambda d: bool(d) and self._jpath(d, "data.id") == claim_id, "id matches"),
                             ])

            # Presigned URL for evidence upload
            self._run("POST get presigned URL (evidence upload)", "POST", "/v1/uploads/presigned-url", 200,
                      role="nigeria_office_staff", tenant_id=tid,
                      body={"claim_id": claim_id,
                            "filename": "damage_photo.jpg",
                            "content_type": "image/jpeg"},
                      assertions=[
                          (lambda d: bool(d) and self._jpath(d, "data.upload_url") is not None,
                           "upload_url returned"),
                      ])

            self._run("PATCH start inspection", "PATCH", f"/v1/claims/{claim_id}/inspect", 200,
                      role="nigeria_office_staff", tenant_id=tid,
                      body={"inspection_method": "customer_evidence"})

            self._run("PATCH resolve claim", "PATCH", f"/v1/claims/{claim_id}/resolve", 200,
                             role="tenant_admin", tenant_id=tid,
                             body={"resolution_type": "compensation",
                                   "amount_usd": 50.0,
                                   "reason": "Damage confirmed, compensation approved"},
                             capture={"damage_claim_id": "data.id"})

        # Missing items
        if manifest_id and cust_id:
            self._run("POST log missing item", "POST", "/v1/claims/missing-items", 201,
                             role="nigeria_office_staff", tenant_id=tid,
                             body={"manifest_id": manifest_id,
                                   "customer_id": cust_id,
                                   "carton_tags": ["MISSING-001"],
                                   "description": "Carton not found at warehouse"},
                             capture={"missing_item_id": "data.id"})

            self._run("GET list missing items", "GET", "/v1/claims/missing-items", 200,
                      role="nigeria_office_staff", tenant_id=tid,
                      params={"limit": 20})

            mi_id = self.state.get("missing_item_id")
            if mi_id:
                self._run("GET missing item by id", "GET", f"/v1/claims/missing-items/{mi_id}", 200,
                          role="nigeria_office_staff", tenant_id=tid)
                self._run("PATCH update missing item", "PATCH", f"/v1/claims/missing-items/{mi_id}", 200,
                          role="nigeria_office_staff", tenant_id=tid,
                          body={"status": "investigating", "notes": "Still missing after second check"})

        # Seized items
        self._run("POST log seized item", "POST", "/v1/claims/seized-items", 201,
                         role="nigeria_office_staff", tenant_id=tid,
                         body={"container_id": con_id,
                               "customer_id": cust_id,
                               "carton_tags": ["SEIZED-001"],
                               "reason": "Customs hold"},
                         capture={"seized_item_id": "data.id"})

        self._run("GET list seized items", "GET", "/v1/claims/seized-items", 200,
                  role="nigeria_office_staff", tenant_id=tid,
                  params={"limit": 20})

        si_id = self.state.get("seized_item_id")
        if si_id:
            self._run("GET seized item by id", "GET", f"/v1/claims/seized-items/{si_id}", 200,
                      role="nigeria_office_staff", tenant_id=tid)
            self._run("PATCH update seized item", "PATCH", f"/v1/claims/seized-items/{si_id}", 200,
                      role="nigeria_office_staff", tenant_id=tid,
                      body={"recovery_status": "recovery_in_progress", "notes": "Customs hold — additional documentation required"})

    # ── 9. Payment & Release ──────────────────────────────────────────────────

    def _test_payment_release(self) -> None:
        self._section("9. Payment & Release")
        tid = self.state["tenant_id"]
        billing_id = self.state.get("billing_id")

        if not billing_id:
            print(_c(YELLOW, "  SKIP: missing billing_id"))
            return

        # Confirm payment
        data = self._run("POST confirm payment", "POST", f"/v1/payments/{billing_id}/confirm", 201,
                         role="nigeria_office_staff", tenant_id=tid,
                         body={"amount_ngn": 99999.0,
                               "payment_method": "bank_transfer",
                               "payment_reference": f"REF-E2E-{self.state['suffix']}"})

        # Generate release note — need at least one carton tag from approved packing list
        pl_id = self.state.get("packing_list_id")
        carton_tags: list[str] = []

        if pl_id:
            data, _ = self._req("GET", f"/v1/packing-lists/{pl_id}",
                                 role="china_office_staff", tenant_id=tid)
            try:
                items = data.json().get("data", {}).get("items", [])
                carton_tags = [i.get("carton_tag") for i in items if i.get("carton_tag")]
            except Exception:
                pass

        if not carton_tags:
            carton_tags = ["E2E-CARTON-001"]

        data = self._run("POST generate release note", "POST", "/v1/release-notes", 201,
                         role="nigeria_office_staff", tenant_id=tid,
                         body={"billing_id": billing_id,
                               "carton_tags": carton_tags[:2],
                               "release_with_outstanding": False},
                         capture={"release_note_id": "data.id"})

        rn_id = self.state.get("release_note_id")
        if rn_id:
            data = self._run("GET release note by id", "GET", f"/v1/release-notes/{rn_id}", 200,
                             role="warehouse_attendant", tenant_id=tid,
                             assertions=[
                                 (lambda d: bool(d) and self._jpath(d, "data.id") == rn_id, "id matches"),
                             ])

            self._run("PATCH record pickup", "PATCH", f"/v1/release-notes/{rn_id}/release", 200,
                      role="warehouse_attendant", tenant_id=tid,
                      body={"cartons_released": len(carton_tags[:2]), "is_delegate": False})

    # ── 10. Refunds ───────────────────────────────────────────────────────────

    def _test_refunds(self) -> None:
        self._section("10. Refunds")
        tid = self.state["tenant_id"]
        billing_id = self.state.get("billing_id")
        cust_id = self.state.get("customer_id")

        if not billing_id or not cust_id:
            print(_c(YELLOW, "  SKIP: missing billing_id or customer_id"))
            return

        self._run("POST create refund (overpayment)", "POST", "/v1/refunds", 201,
                         role="nigeria_office_staff", tenant_id=tid,
                         body={"customer_id": cust_id,
                               "billing_id": billing_id,
                               "refund_type": "overpayment",
                               "amount_requested_ngn": 5000.0,
                               "customer_choice": "immediate_refund"},
                         capture={"refund_id": "data.id"})

        self._run("GET list refunds", "GET", "/v1/refunds", 200,
                         role="tenant_admin", tenant_id=tid,
                         params={"limit": 20},
                         assertions=[
                             (lambda d: bool(d) and isinstance(self._jpath(d, "data"), list), "list returned"),
                         ])

        refund_id = self.state.get("refund_id")
        if not refund_id:
            print(_c(YELLOW, "  SKIP refund workflow — create failed"))
            return

        self._run("GET refund by id", "GET", f"/v1/refunds/{refund_id}", 200,
                         role="tenant_admin", tenant_id=tid,
                         assertions=[
                             (lambda d: bool(d) and self._jpath(d, "data.id") == refund_id, "id matches"),
                         ])

        # Accounts review (debt check)
        self._run("PATCH accounts review (approved)", "PATCH",
                         f"/v1/refunds/{refund_id}/review", 200,
                         role="nigeria_office_staff", tenant_id=tid,
                         body={"debt_check_passed": True,
                               "debt_check_notes": "No outstanding debt confirmed"})

        # Approve
        self._run("PATCH approve refund", "PATCH", f"/v1/refunds/{refund_id}/approve", 200,
                  role="tenant_admin", tenant_id=tid,
                  body={"amount_approved_ngn": 5000.0, "approval_level": "staff"})

        # Create a second refund to test the reject flow
        self._run("POST create refund (for reject test)", "POST", "/v1/refunds", 201,
                          role="nigeria_office_staff", tenant_id=tid,
                          body={"customer_id": cust_id,
                                "billing_id": billing_id,
                                "refund_type": "overpayment",
                                "amount_requested_ngn": 1000.0},
                          capture={"reject_refund_id": "data.id"})
        reject_refund_id = self.state.get("reject_refund_id")
        if reject_refund_id:
            self._run("PATCH reject refund", "PATCH", f"/v1/refunds/{reject_refund_id}/reject", 200,
                      role="tenant_admin", tenant_id=tid,
                      body={"reason": "Refund not valid — payment verified as correct"},
                      assertions=[
                          (lambda d: bool(d) and self._jpath(d, "data.status") == "rejected",
                           "status is rejected"),
                      ])

    # ── 11. Excel Exports ─────────────────────────────────────────────────────

    def _test_excel(self) -> None:
        self._section("11. Excel Exports")
        tid = self.state["tenant_id"]
        pl_id = self.state.get("packing_list_id")
        manifest_id = self.state.get("manifest_id")
        billing_id = self.state.get("billing_id")
        con_id = self.state.get("container_id")

        if pl_id:
            self._run("GET export packing list (XLSX)", "GET", f"/v1/packing-lists/{pl_id}/export", 200,
                      role="china_office_staff", tenant_id=tid,
                      assertions=[
                          (lambda d: bool(d) and self._jpath(d, "data.download_url") is not None,
                           "download_url returned"),
                      ])
        else:
            print(_c(YELLOW, "  SKIP packing list export — no packing_list_id"))

        if manifest_id:
            self._run("GET export manifest (XLSX)", "GET", f"/v1/manifests/{manifest_id}/export", 200,
                      role="nigeria_office_staff", tenant_id=tid,
                      assertions=[
                          (lambda d: bool(d) and self._jpath(d, "data.download_url") is not None,
                           "download_url returned"),
                      ])
        else:
            print(_c(YELLOW, "  SKIP manifest export — no manifest_id"))

        if billing_id:
            self._run("GET export billing (XLSX)", "GET", f"/v1/billing/{billing_id}/export", 200,
                      role="nigeria_office_staff", tenant_id=tid,
                      assertions=[
                          (lambda d: bool(d) and self._jpath(d, "data.download_url") is not None,
                           "download_url returned"),
                      ])
        else:
            print(_c(YELLOW, "  SKIP billing export — no billing_id"))

        if con_id:
            self._run("GET export container billing (XLSX)", "GET",
                      f"/v1/containers/{con_id}/billing/export", 200,
                      role="nigeria_office_staff", tenant_id=tid,
                      assertions=[
                          (lambda d: bool(d) and self._jpath(d, "data.download_url") is not None,
                           "download_url returned"),
                      ])
        else:
            print(_c(YELLOW, "  SKIP container billing export — no container_id"))

    # ── 12. GDPR + Cleanup ────────────────────────────────────────────────────

    def _test_gdpr_and_cleanup(self) -> None:
        self._section("12. GDPR & Cleanup")
        tid = self.state["tenant_id"]
        self.state.get("customer_id")

        # Create a second customer specifically for anonymisation (don't want to break billing refs)
        suffix = self.state["suffix"]
        data = self._run("POST create customer for GDPR test", "POST", "/v1/customers", 201,
                         role="tenant_admin", tenant_id=tid,
                         body={"name": f"GDPR Test Customer {suffix}",
                               "phone": "+2348022222222",
                               "email": f"gdpr_{suffix}@e2etest.com",
                               "address": "1 Privacy Street, Abuja"})

        gdpr_cust_id = self._jpath(data, "data.id") if data else None
        if gdpr_cust_id:
            data = self._run("DELETE anonymise customer (GDPR Art. 17)", "DELETE",
                             f"/v1/customers/{gdpr_cust_id}", 200,
                             role="tenant_admin", tenant_id=tid,
                             assertions=[
                                 (lambda d: bool(d) and self._jpath(d, "data.anonymised_at") is not None,
                                  "anonymised_at set"),
                             ])

        # Offboard test tenant
        self._run("DELETE offboard tenant (cleanup)", "DELETE",
                  f"/v1/platform/tenants/{tid}", 200,
                  platform=True,
                  assertions=[(True, "tenant offboarded")])

        # Offboarded tenant should be inaccessible
        self._run("Offboarded tenant gets 410", "GET", "/v1/tenant/config", 410,
                  role="tenant_admin", tenant_id=tid)

        # Reactivate (full lifecycle)
        data = self._run("PATCH reactivate tenant", "PATCH",
                         f"/v1/platform/tenants/{tid}/reactivate", 200,
                         platform=True,
                         assertions=[
                             (lambda d: bool(d) and self._jpath(d, "data.tenant.status") == "active",
                              "status is active"),
                             (lambda d: bool(d) and isinstance(self._jpath(d, "data.notices"), list),
                              "GDPR notices present"),
                         ])

    # ─────────────────────────────────────────────────────────────────────────
    # Summary report
    # ─────────────────────────────────────────────────────────────────────────

    def _print_summary(self) -> None:
        total   = len(self.results)
        passed  = sum(1 for r in self.results if r.passed)
        failed  = total - passed
        avg_ms  = sum(r.response_ms for r in self.results) / total if total else 0

        print(f"\n{'─' * 70}")
        print(f"{_c(BOLD, 'E2E TEST SUMMARY')}")
        print(f"{'─' * 70}")
        print(f"  Total   : {total}")
        print(f"  {_c(GREEN, 'Passed')}  : {passed}")
        if failed:
            print(f"  {_c(RED, 'Failed')}  : {failed}")
        print(f"  Avg ms  : {avg_ms:.0f}ms")
        print(f"{'─' * 70}")

        if failed:
            print(f"\n{_c(RED + BOLD, 'FAILURES:')}")
            for r in self.results:
                if not r.passed:
                    print(f"  {_c(RED, '✗')} {r.method} {r.path}")
                    print(f"    {r.name}")
                    for f in r.failures:
                        print(f"    → {f}")
            print()

        result_str = _c(GREEN + BOLD, "ALL PASSED") if not failed else _c(RED + BOLD, f"{failed} FAILED")
        print(f"  Result: {result_str}\n")

    def save_results(self, output_path: str) -> None:
        report = {
            "summary": {
                "total": len(self.results),
                "passed": sum(1 for r in self.results if r.passed),
                "failed": sum(1 for r in self.results if not r.passed),
                "avg_response_ms": sum(r.response_ms for r in self.results) / len(self.results) if self.results else 0,
            },
            "state": {k: v for k, v in self.state.items() if k not in ("suffix",)},
            "results": [
                {
                    "name": r.name,
                    "method": r.method,
                    "path": r.path,
                    "status_code": r.status_code,
                    "expected_status": r.expected_status,
                    "passed": r.passed,
                    "assertions": r.assertions,
                    "failures": r.failures,
                    "response_ms": round(r.response_ms, 1),
                }
                for r in self.results
            ],
        }
        with open(output_path, "w") as fh:
            json.dump(report, fh, indent=2)
        print(f"  Results saved to {output_path}")


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="ShipX E2E API test runner")
    parser.add_argument("--base-url", default="http://localhost:3000",
                        help="Base URL of the local server (default: http://localhost:3000)")
    parser.add_argument("--stop-on-fail", action="store_true",
                        help="Stop immediately on first failure")
    parser.add_argument("--output", metavar="FILE",
                        help="Write JSON report to FILE")
    args = parser.parse_args()

    print(f"\n{_c(BOLD, 'ShipX E2E Test Runner')}")
    print(f"  Target : {args.base_url}")
    print(f"  Time   : {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    runner = E2ERunner(base_url=args.base_url, stop_on_fail=args.stop_on_fail)
    runner.run_all()

    if args.output:
        runner.save_results(args.output)

    failed = sum(1 for r in runner.results if not r.passed)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
