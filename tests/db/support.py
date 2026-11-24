"""Shared helpers for the real-database tests: invoice data, parallel workers, small queries."""

import time
import uuid
from concurrent.futures import ProcessPoolExecutor
from decimal import Decimal
from multiprocessing import get_context

INVOICE_PREFIX = "TST-INV-20261114"
RECEIPT_PREFIX = "TST-RCT-20261114"
TOLERANCE = Decimal("0.01")


# ---------------------------------------------------------------------------
# Workers — top level so a spawned process can import them
# ---------------------------------------------------------------------------


def _invoice_data(tenant_id: str, customer_id: str, container_id: str, total: str = "100000.00") -> dict:
    return {
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "container_id": container_id,
        "total_cartons": 1,
        "total_cbm": Decimal("1.000"),
        "cbm_rate_usd": Decimal("45.0000"),
        "cbm_rate_currency": "USD",
        "cbm_rate_mode": "flat",
        "cbm_breakdown": "[]",
        "subtotal_usd": Decimal("45.00"),
        "exchange_rate_ngn": Decimal("1550.0000"),
        "subtotal_ngn": Decimal(total),
        "misc_charges_ngn": Decimal("0"),
        "total_ngn": Decimal(total),
        "amount_paid_ngn": Decimal("0"),
        "status": "unpaid",
        "billed_at": None,
        "created_by": None,
    }


def _wait_for(start_at: float) -> None:
    """Line the workers up so they actually overlap instead of running one by one."""
    delay = start_at - time.time()
    if delay > 0:
        time.sleep(delay)


def _worker_create_invoice(args: tuple) -> tuple[str, str, bool]:
    tenant_id, customer_id, container_id, start_at = args
    from services.billing import repository as repo

    _wait_for(start_at)
    invoice, created = repo.create_invoice(tenant_id, _invoice_data(tenant_id, customer_id, container_id), INVOICE_PREFIX, [], [])
    return str(invoice["id"]), invoice["invoice_number"], created


def _worker_record_payment(args: tuple) -> tuple[str, str]:
    tenant_id, billing_id, amount, start_at = args
    from services.payment_release import repository as repo

    _wait_for(start_at)
    recorded = repo.record_payment(
        tenant_id,
        billing_id,
        Decimal(amount),
        {"payment_method": "bank_transfer", "reference_number": f"REF-{uuid.uuid4().hex[:8]}", "payment_date": "2026-11-14"},
        tolerance=TOLERANCE,
        receipt_prefix=RECEIPT_PREFIX,
    )
    return str(recorded.payment["receipt_number"]), str(recorded.billing["status"])


def _run_parallel(worker, jobs: list[tuple]) -> list:
    # spawn, not fork: each worker must open its own database connection.
    with ProcessPoolExecutor(max_workers=len(jobs), mp_context=get_context("spawn")) as pool:
        return list(pool.map(worker, jobs))


def _rows(admin, sql: str, params: tuple) -> list[tuple]:
    with admin.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _make_invoice(admin, world, total: str = "100000.00", index: int = 0) -> str:
    from services.billing import repository as repo

    invoice, created = repo.create_invoice(
        world["tenant"],
        _invoice_data(world["tenant"], world["customers"][index], world["containers"][index], total),
        INVOICE_PREFIX,
        [],
        [],
    )
    assert created
    return str(invoice["id"])


def _start_soon() -> float:
    return time.time() + 3.0
