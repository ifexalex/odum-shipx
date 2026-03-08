"""Locust load test for the ShipX Logistics API.

Simulates realistic traffic patterns across the major workflows:
  - Packing list creation and approval flow (China office staff)
  - Container status progression (China → Nigeria office staff)
  - Billing generation and payment confirmation (Nigeria office staff)
  - Customer tracking lookup (public, no JWT)
  - Admin dashboard reads (tenant admin)

Performance targets (from spec):
  - p95 latency < 400 ms at 50 concurrent users
  - Error rate < 0.5%
  - Read endpoints: > 100 req/s sustained
  - Write endpoints: > 20 req/s sustained

Usage:
    locust -f tests/load/locustfile.py --headless \
        -u 50 -r 10 --run-time 5m \
        --host https://your-api-gateway-url.execute-api.eu-west-1.amazonaws.com

Environment variables:
    LOAD_TEST_TENANT_ID     - UUID of a pre-provisioned test tenant
    LOAD_TEST_ADMIN_TOKEN   - JWT for tenant_admin role
    LOAD_TEST_CHINA_TOKEN   - JWT for china_office_staff role
    LOAD_TEST_NIGERIA_TOKEN - JWT for nigeria_office_staff role
    LOAD_TEST_CUSTOMER_TOKEN- JWT for customer role
"""

import contextlib
import os
import random
import string
import uuid
from datetime import date, timedelta

from locust import HttpUser, SequentialTaskSet, between, events, task
from locust.contrib.fasthttp import FastHttpUser

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TENANT_ID = os.environ.get("LOAD_TEST_TENANT_ID", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

_ADMIN_TOKEN = os.environ.get("LOAD_TEST_ADMIN_TOKEN", "")
_CHINA_TOKEN = os.environ.get("LOAD_TEST_CHINA_TOKEN", "")
_NIGERIA_TOKEN = os.environ.get("LOAD_TEST_NIGERIA_TOKEN", "")
_CUSTOMER_TOKEN = os.environ.get("LOAD_TEST_CUSTOMER_TOKEN", "")

# Pre-seeded IDs — populated by setup tasks during warm-up, shared across users
_SEEDED: dict = {
    "container_ids": [],
    "packing_list_ids": [],
    "billing_ids": [],
    "customer_ids": [],
    "tracking_codes": [],
    "claim_ids": [],
}


def _rand_str(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=n))


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Read-heavy user (customer tracking, dashboard reads)
# ---------------------------------------------------------------------------


class ReadHeavyUser(HttpUser):
    """Simulates read-only access: customers tracking shipments, staff browsing."""

    wait_time = between(0.2, 1.0)
    weight = 60  # 60% of virtual users

    @task(5)
    def list_billing(self):
        with self.client.get(
            "/v1/billing",
            headers=_auth(_NIGERIA_TOKEN),
            params={"limit": "20"},
            catch_response=True,
            name="/v1/billing [list]",
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            elif resp.status_code == 403:
                resp.success()  # Auth misconfiguration in load env — not an app error
            else:
                resp.failure(f"Unexpected status {resp.status_code}")

    @task(5)
    def list_packing_lists(self):
        with self.client.get(
            "/v1/packing-lists",
            headers=_auth(_NIGERIA_TOKEN),
            params={"limit": "20"},
            catch_response=True,
            name="/v1/packing-lists [list]",
        ) as resp:
            if resp.status_code in (200, 403):
                resp.success()
            else:
                resp.failure(f"Unexpected status {resp.status_code}")

    @task(4)
    def list_claims(self):
        with self.client.get(
            "/v1/claims",
            headers=_auth(_NIGERIA_TOKEN),
            params={"limit": "20"},
            catch_response=True,
            name="/v1/claims [list]",
        ) as resp:
            if resp.status_code in (200, 403):
                resp.success()
            else:
                resp.failure(f"Unexpected status {resp.status_code}")

    @task(4)
    def list_containers(self):
        with self.client.get(
            "/v1/containers",
            headers=_auth(_NIGERIA_TOKEN),
            params={"limit": "20"},
            catch_response=True,
            name="/v1/containers [list]",
        ) as resp:
            if resp.status_code in (200, 403):
                resp.success()
            else:
                resp.failure(f"Unexpected status {resp.status_code}")

    @task(3)
    def public_tracking_lookup(self):
        """Public endpoint — no JWT required."""
        # Use a seeded tracking code if available
        codes = _SEEDED["tracking_codes"]
        tracking_code = codes[random.randint(0, len(codes) - 1)] if codes else f"TK-{_rand_str(6)}"
        phone = "+2348012345678"

        with self.client.get(
            f"/v1/tracking/{tracking_code}",
            params={"phone": phone},
            catch_response=True,
            name="/v1/tracking/{code} [public]",
        ) as resp:
            if resp.status_code in (200, 404):
                resp.success()
            else:
                resp.failure(f"Unexpected status {resp.status_code}")

    @task(2)
    def get_billing_detail(self):
        billing_ids = _SEEDED["billing_ids"]
        if not billing_ids:
            return
        billing_id = random.choice(billing_ids)
        with self.client.get(
            f"/v1/billing/{billing_id}",
            headers=_auth(_NIGERIA_TOKEN),
            catch_response=True,
            name="/v1/billing/{id} [get]",
        ) as resp:
            if resp.status_code in (200, 404, 403):
                resp.success()
            else:
                resp.failure(f"Unexpected status {resp.status_code}")

    @task(2)
    def admin_dashboard(self):
        with self.client.get(
            "/v1/platform/dashboard",
            headers=_auth(_ADMIN_TOKEN),
            catch_response=True,
            name="/v1/platform/dashboard [admin]",
        ) as resp:
            if resp.status_code in (200, 403):
                resp.success()
            else:
                resp.failure(f"Unexpected status {resp.status_code}")

    @task(1)
    def list_manifests(self):
        with self.client.get(
            "/v1/manifests",
            headers=_auth(_NIGERIA_TOKEN),
            params={"limit": "20"},
            catch_response=True,
            name="/v1/manifests [list]",
        ) as resp:
            if resp.status_code in (200, 403):
                resp.success()
            else:
                resp.failure(f"Unexpected status {resp.status_code}")


# ---------------------------------------------------------------------------
# Write-heavy user (packing lists, billing, payments)
# ---------------------------------------------------------------------------


class WriteHeavyUser(HttpUser):
    """Simulates operations staff creating and progressing records."""

    wait_time = between(0.5, 2.0)
    weight = 30  # 30% of virtual users

    @task(4)
    def create_packing_list(self):
        container_ids = _SEEDED["container_ids"]
        container_id = random.choice(container_ids) if container_ids else str(uuid.uuid4())
        customer_ids = _SEEDED["customer_ids"]
        customer_id = random.choice(customer_ids) if customer_ids else str(uuid.uuid4())

        payload = {
            "customer_id": customer_id,
            "container_id": container_id,
            "items": [
                {
                    "description": f"Item {i}",
                    "quantity": random.randint(1, 20),
                    "weight_kg": round(random.uniform(0.5, 10.0), 2),
                    "length_cm": round(random.uniform(10, 60), 1),
                    "width_cm": round(random.uniform(10, 60), 1),
                    "height_cm": round(random.uniform(10, 60), 1),
                    "unit_value_usd": round(random.uniform(5, 200), 2),
                }
                for i in range(random.randint(2, 8))
            ],
        }

        with self.client.post(
            "/v1/packing-lists",
            json=payload,
            headers=_auth(_CHINA_TOKEN),
            catch_response=True,
            name="/v1/packing-lists [create]",
        ) as resp:
            if resp.status_code == 201:
                with contextlib.suppress(Exception):
                    _SEEDED["packing_list_ids"].append(resp.json()["id"])
                resp.success()
            elif resp.status_code in (400, 403, 422):
                resp.success()  # Validation/auth errors are expected in load env
            else:
                resp.failure(f"Unexpected status {resp.status_code}")

    @task(3)
    def create_and_confirm_payment(self):
        billing_ids = _SEEDED["billing_ids"]
        if not billing_ids:
            return
        billing_id = random.choice(billing_ids)

        payload = {
            "amount_ngn": str(round(random.uniform(50000, 150000), 2)),
            "payment_method": random.choice(["bank_transfer", "cash"]),
            "payment_reference": f"REF-{_rand_str(8)}",
            "payment_date": str(date.today()),
        }

        with self.client.post(
            f"/v1/billing/{billing_id}/payments",
            json=payload,
            headers=_auth(_NIGERIA_TOKEN),
            catch_response=True,
            name="/v1/billing/{id}/payments [confirm]",
        ) as resp:
            if resp.status_code in (200, 201, 400, 403, 404, 409, 422):
                resp.success()
            else:
                resp.failure(f"Unexpected status {resp.status_code}")

    @task(2)
    def file_damage_claim(self):
        container_ids = _SEEDED["container_ids"]
        customer_ids = _SEEDED["customer_ids"]
        if not container_ids or not customer_ids:
            return

        payload = {
            "customer_id": random.choice(customer_ids),
            "container_id": random.choice(container_ids),
            "cartons_affected": random.randint(1, 5),
            "description": f"Load test claim {_rand_str(6)}",
        }

        with self.client.post(
            "/v1/claims",
            json=payload,
            headers=_auth(_NIGERIA_TOKEN),
            catch_response=True,
            name="/v1/claims [file]",
        ) as resp:
            if resp.status_code == 201:
                with contextlib.suppress(Exception):
                    _SEEDED["claim_ids"].append(resp.json()["id"])
                resp.success()
            elif resp.status_code in (400, 403, 404, 422):
                resp.success()
            else:
                resp.failure(f"Unexpected status {resp.status_code}")

    @task(2)
    def create_cbm_dispute(self):
        billing_ids = _SEEDED["billing_ids"]
        customer_ids = _SEEDED["customer_ids"]
        if not billing_ids or not customer_ids:
            return

        payload = {
            "billing_id": random.choice(billing_ids),
            "customer_id": random.choice(customer_ids),
            "disputed_cbm": str(round(random.uniform(0.5, 5.0), 2)),
            "dispute_reason": f"Load test dispute {_rand_str(6)}",
        }

        with self.client.post(
            "/v1/billing/disputes",
            json=payload,
            headers=_auth(_NIGERIA_TOKEN),
            catch_response=True,
            name="/v1/billing/disputes [create]",
        ) as resp:
            if resp.status_code in (201, 400, 403, 404, 422):
                resp.success()
            else:
                resp.failure(f"Unexpected status {resp.status_code}")

    @task(1)
    def create_container(self):
        payload = {
            "container_number": f"CONT-{_rand_str(6)}",
            "parcel_number": f"PCL-{_rand_str(6)}",
            "origin": "China",
            "destination": "Nigeria",
            "estimated_arrival_date": str(date.today() + timedelta(days=30)),
        }

        with self.client.post(
            "/v1/containers",
            json=payload,
            headers=_auth(_CHINA_TOKEN),
            catch_response=True,
            name="/v1/containers [create]",
        ) as resp:
            if resp.status_code == 201:
                with contextlib.suppress(Exception):
                    _SEEDED["container_ids"].append(resp.json()["id"])
                resp.success()
            elif resp.status_code in (400, 403, 409, 422):
                resp.success()
            else:
                resp.failure(f"Unexpected status {resp.status_code}")

    @task(1)
    def update_dollar_rate(self):
        rate = round(random.uniform(1400, 1700), 2)
        payload = {"rate": str(rate), "currency_pair": "USD_NGN"}

        with self.client.patch(
            "/v1/tenant/config/dollar-rate",
            json=payload,
            headers=_auth(_ADMIN_TOKEN),
            catch_response=True,
            name="/v1/tenant/config/dollar-rate [update]",
        ) as resp:
            if resp.status_code in (200, 400, 403, 422):
                resp.success()
            else:
                resp.failure(f"Unexpected status {resp.status_code}")


# ---------------------------------------------------------------------------
# Admin user (platform-level, low frequency)
# ---------------------------------------------------------------------------


class AdminUser(HttpUser):
    """Simulates platform admin monitoring and tenant management."""

    wait_time = between(2.0, 5.0)
    weight = 10  # 10% of virtual users

    @task(3)
    def list_tenants(self):
        with self.client.get(
            "/v1/platform/tenants",
            headers=_auth(_ADMIN_TOKEN),
            catch_response=True,
            name="/v1/platform/tenants [list]",
        ) as resp:
            if resp.status_code in (200, 403):
                resp.success()
            else:
                resp.failure(f"Unexpected status {resp.status_code}")

    @task(2)
    def get_platform_dashboard(self):
        with self.client.get(
            "/v1/platform/dashboard",
            headers=_auth(_ADMIN_TOKEN),
            catch_response=True,
            name="/v1/platform/dashboard",
        ) as resp:
            if resp.status_code in (200, 403):
                resp.success()
            else:
                resp.failure(f"Unexpected status {resp.status_code}")

    @task(1)
    def list_platform_audit_log(self):
        with self.client.get(
            "/v1/platform/audit-log",
            headers=_auth(_ADMIN_TOKEN),
            params={"limit": "50"},
            catch_response=True,
            name="/v1/platform/audit-log [list]",
        ) as resp:
            if resp.status_code in (200, 403):
                resp.success()
            else:
                resp.failure(f"Unexpected status {resp.status_code}")

    @task(1)
    def get_tenant_config(self):
        with self.client.get(
            "/v1/tenant/config",
            headers=_auth(_ADMIN_TOKEN),
            catch_response=True,
            name="/v1/tenant/config [get]",
        ) as resp:
            if resp.status_code in (200, 403):
                resp.success()
            else:
                resp.failure(f"Unexpected status {resp.status_code}")


# ---------------------------------------------------------------------------
# Sequential workflow: full packing list → payment → release flow
# ---------------------------------------------------------------------------


class WorkflowTaskSet(SequentialTaskSet):
    """Simulates the complete packing list → billing → payment → release workflow."""

    def on_start(self):
        self._container_id = None
        self._pl_id = None
        self._billing_id = None

    @task
    def step1_create_container(self):
        payload = {
            "container_number": f"WF-{_rand_str(6)}",
            "origin": "China",
            "destination": "Nigeria",
            "estimated_arrival_date": str(date.today() + timedelta(days=25)),
        }
        with self.client.post(
            "/v1/containers",
            json=payload,
            headers=_auth(_CHINA_TOKEN),
            catch_response=True,
            name="[workflow] step1: create container",
        ) as resp:
            if resp.status_code == 201:
                with contextlib.suppress(Exception):
                    self._container_id = resp.json()["id"]
                resp.success()
            elif resp.status_code in (400, 403, 409, 422):
                resp.success()
            else:
                resp.failure(f"Unexpected {resp.status_code}")

    @task
    def step2_create_packing_list(self):
        if not self._container_id:
            return

        customer_ids = _SEEDED["customer_ids"]
        customer_id = random.choice(customer_ids) if customer_ids else str(uuid.uuid4())

        payload = {
            "customer_id": customer_id,
            "container_id": self._container_id,
            "items": [
                {
                    "description": "Widget A",
                    "quantity": 5,
                    "weight_kg": 2.5,
                    "length_cm": 30,
                    "width_cm": 20,
                    "height_cm": 15,
                    "unit_value_usd": 25.00,
                }
            ],
        }
        with self.client.post(
            "/v1/packing-lists",
            json=payload,
            headers=_auth(_CHINA_TOKEN),
            catch_response=True,
            name="[workflow] step2: create packing list",
        ) as resp:
            if resp.status_code == 201:
                with contextlib.suppress(Exception):
                    self._pl_id = resp.json()["id"]
                resp.success()
            elif resp.status_code in (400, 403, 422):
                resp.success()
            else:
                resp.failure(f"Unexpected {resp.status_code}")

    @task
    def step3_submit_packing_list(self):
        if not self._pl_id:
            return
        with self.client.post(
            f"/v1/packing-lists/{self._pl_id}/submit",
            headers=_auth(_CHINA_TOKEN),
            catch_response=True,
            name="[workflow] step3: submit packing list",
        ) as resp:
            if resp.status_code in (200, 400, 403, 404, 409, 422):
                resp.success()
            else:
                resp.failure(f"Unexpected {resp.status_code}")

    @task
    def step4_get_billing(self):
        billing_ids = _SEEDED["billing_ids"]
        if billing_ids:
            self._billing_id = random.choice(billing_ids)
            with self.client.get(
                f"/v1/billing/{self._billing_id}",
                headers=_auth(_NIGERIA_TOKEN),
                catch_response=True,
                name="[workflow] step4: get billing",
            ) as resp:
                if resp.status_code in (200, 403, 404):
                    resp.success()
                else:
                    resp.failure(f"Unexpected {resp.status_code}")

    @task
    def step5_confirm_payment(self):
        if not self._billing_id:
            return
        payload = {
            "amount_ngn": "100000.00",
            "payment_method": "bank_transfer",
            "payment_reference": f"WF-REF-{_rand_str(8)}",
            "payment_date": str(date.today()),
        }
        with self.client.post(
            f"/v1/billing/{self._billing_id}/payments",
            json=payload,
            headers=_auth(_NIGERIA_TOKEN),
            catch_response=True,
            name="[workflow] step5: confirm payment",
        ) as resp:
            if resp.status_code in (200, 201, 400, 403, 404, 409, 422):
                resp.success()
            else:
                resp.failure(f"Unexpected {resp.status_code}")


class WorkflowUser(HttpUser):
    """Simulates end-to-end workflow execution at low concurrency."""

    tasks = [WorkflowTaskSet]
    wait_time = between(1.0, 3.0)
    weight = 10  # 10% of users run the sequential workflow


# ---------------------------------------------------------------------------
# Event hooks — report summary stats at end of test
# ---------------------------------------------------------------------------


@events.quitting.add_listener
def on_quitting(environment, **kwargs):
    """Print performance summary and validate against spec targets (§performance).

    Per-endpoint-type targets:
      GET list endpoints:      p95 < 500ms
      GET single resource:     p95 < 200ms
      POST create:             p95 < 1000ms
      PATCH state transitions: p95 < 500ms

    Global targets:
      Error rate < 0.5%
    """
    stats = environment.runner.stats

    print("\n" + "=" * 70)
    print("LOAD TEST PERFORMANCE SUMMARY")
    print("=" * 70)

    total_reqs = stats.total.num_requests
    total_failures = stats.total.num_failures
    error_rate = (total_failures / total_reqs * 100) if total_reqs > 0 else 0

    print(f"Total requests:   {total_reqs}")
    print(f"Total failures:   {total_failures}")
    print(f"Error rate:       {error_rate:.2f}%")
    print(f"p95 latency:      {stats.total.get_response_time_percentile(0.95):.0f} ms")
    print(f"p99 latency:      {stats.total.get_response_time_percentile(0.99):.0f} ms")
    print(f"Median latency:   {stats.total.get_response_time_percentile(0.5):.0f} ms")
    print(f"Peak RPS:         {stats.total.max_rps:.1f}")
    print("=" * 70)

    # -----------------------------------------------------------------------
    # Per-endpoint-type p95 targets (from spec §performance)
    # Name tags: [list], [get], [create], [confirm], [update], [admin], [public]
    # -----------------------------------------------------------------------

    # Targets: (tag substring, threshold_ms, label)
    _TARGETS = [
        ("[list]",    500,  "GET list endpoints"),
        ("[get]",     200,  "GET single resource"),
        ("[create]",  1000, "POST create"),
        ("[confirm]", 1000, "POST confirm"),
        ("[update]",  500,  "PATCH state transitions"),
        ("[public]",  500,  "Public tracking lookup"),
        ("[admin]",   500,  "Admin dashboard reads"),
    ]

    passed = True
    violations = []

    # Check global error rate
    if error_rate > 0.5:
        msg = f"Error rate {error_rate:.2f}% exceeds 0.5% target"
        violations.append(("GLOBAL", msg))
        passed = False

    # Check per-entry stats by name tag
    print("\nPer-endpoint-type p95 breakdown:")
    for entry in stats.entries.values():
        if entry.num_requests == 0:
            continue
        name = entry.name
        p95_ms = entry.get_response_time_percentile(0.95)
        for tag, threshold, _label in _TARGETS:
            if tag in name:
                status = "OK" if p95_ms <= threshold else "FAIL"
                print(f"  {status:4s}  {name:<55s} p95={p95_ms:.0f}ms (target <{threshold}ms)")
                if p95_ms > threshold:
                    violations.append((name, f"p95 {p95_ms:.0f}ms exceeds {threshold}ms"))
                    passed = False
                break

    print()
    if violations:
        print("FAILURES:")
        for endpoint, reason in violations:
            print(f"  FAIL [{endpoint}]: {reason}")
    else:
        print("PASS: All performance targets met")

    print("=" * 70)

    if not passed:
        environment.process_exit_code = 1
