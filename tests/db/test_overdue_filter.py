"""The invoice list's `overdue` filter against a real database (audit FD-18).

The billing list's "Overdue (30+ days)" stat now opens the overdue invoices. The count and the list share one SQL
definition (`shared.list_filters.overdue_condition`); this checks that on the real schema they agree, row for row.
"""

import uuid

import pytest

from services.billing import repository as repo

pytestmark = pytest.mark.db


@pytest.fixture
def invoices(world, admin):
    """Three invoices: owed and 40 days old (overdue), owed but recent, and 40 days old but paid."""
    made = {name: str(uuid.uuid4()) for name in ("overdue", "recent", "paid")}
    rows = [
        (made["overdue"], 0, "unpaid", 1000, 40),
        (made["recent"], 1, "unpaid", 1000, 5),
        (made["paid"], 2, "paid", 0, 40),
    ]
    with admin.cursor() as cur:
        for invoice_id, index, status, balance, days_ago in rows:
            cur.execute(
                "INSERT INTO billing (id, tenant_id, customer_id, container_id, invoice_number, cbm_rate_usd, "
                "exchange_rate_ngn, total_ngn, amount_paid_ngn, status, billed_at) "
                "VALUES (%s, %s, %s, %s, %s, 1, 1, 1000, %s, %s, now() - make_interval(days => %s))",
                (
                    invoice_id,
                    world["tenant"],
                    world["customers"][index],
                    world["containers"][index],
                    f"OVD-{index}",
                    1000 - balance,
                    status,
                    days_ago,
                ),
            )
    return made


def test_the_overdue_list_is_exactly_what_the_overdue_stat_counts(world, invoices):
    page, _cursor, _more = repo.list_billing_all(world["tenant"], {"overdue": True})
    assert [str(row["id"]) for row in page] == [invoices["overdue"]]
    assert repo.get_billing_stats(world["tenant"])["overdue"] == 1


def test_without_the_filter_every_invoice_is_listed(world, invoices):
    page, _cursor, _more = repo.list_billing_all(world["tenant"], {})
    assert {str(row["id"]) for row in page} == set(invoices.values())
