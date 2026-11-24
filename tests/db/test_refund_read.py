"""The refund detail read names what a refund is about, against a real database (audit FD-17).

The refund page showed the customer, the invoice and the claim as three UUIDs. The read now joins the customer's
name, the invoice number and the claim reference, each scoped to the refund's own tenant. Only a database shows the
joins are valid against the real schema and that a row of another tenant is never joined in.
"""

import uuid

import pytest

from services.refunds import repository as repo

pytestmark = pytest.mark.db


@pytest.fixture
def refund(world, admin):
    """A refund raised against an invoice and a damage claim of the same customer."""
    ids = {"refund": str(uuid.uuid4()), "billing": str(uuid.uuid4()), "claim": str(uuid.uuid4())}
    with admin.cursor() as cur:
        cur.execute(
            "INSERT INTO billing (id, tenant_id, customer_id, container_id, invoice_number, cbm_rate_usd, exchange_rate_ngn, "
            "total_ngn, status) VALUES (%s, %s, %s, %s, 'INV-T-042', 1, 1, 1000, 'unpaid')",
            (ids["billing"], world["tenant"], world["customers"][0], world["containers"][0]),
        )
        cur.execute(
            "INSERT INTO damage_claim (id, tenant_id, customer_id, container_id, description, status, reference) "
            "VALUES (%s, %s, %s, %s, 'Wet cartons', 'resolved', 'DC-20261120-007')",
            (ids["claim"], world["tenant"], world["customers"][0], world["containers"][0]),
        )
        cur.execute(
            "INSERT INTO refund_request (id, tenant_id, customer_id, billing_id, damage_claim_id, amount_ngn, reason, "
            "status, refund_type) VALUES (%s, %s, %s, %s, %s, 5000, 'Wet cartons', 'pending_review', 'damage_or_loss')",
            (ids["refund"], world["tenant"], world["customers"][0], ids["billing"], ids["claim"]),
        )
    yield ids
    # The shared teardown removes claims before refunds; this refund points at a claim, so it goes first.
    with admin.cursor() as cur:
        cur.execute("DELETE FROM refund_request WHERE id = %s", (ids["refund"],))


def test_the_detail_read_names_the_customer_the_invoice_and_the_claim(world, refund):
    row = repo.get_refund_request_by_id(world["tenant"], refund["refund"])
    assert row is not None
    assert (row["customer_name"], row["invoice_number"], row["claim_reference"]) == (
        "Customer 0",
        "INV-T-042",
        "DC-20261120-007",
    )
    assert str(row["id"]) == refund["refund"]  # the refund's own id, not a joined row's


def test_a_refund_with_no_invoice_or_claim_reads_with_those_names_empty(world, admin):
    refund_id = str(uuid.uuid4())
    with admin.cursor() as cur:
        cur.execute(
            "INSERT INTO refund_request (id, tenant_id, customer_id, amount_ngn, reason, status, refund_type) "
            "VALUES (%s, %s, %s, 100, 'Overpaid', 'pending_review', 'overpayment')",
            (refund_id, world["tenant"], world["customers"][1]),
        )
    row = repo.get_refund_request_by_id(world["tenant"], refund_id)
    assert row["customer_name"] == "Customer 1"
    assert row["invoice_number"] is None and row["claim_reference"] is None


def test_another_tenant_cannot_read_it(world, refund):
    assert repo.get_refund_request_by_id(str(uuid.uuid4()), refund["refund"]) is None
