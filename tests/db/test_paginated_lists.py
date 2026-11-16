"""Paginated lists that join other tables, walked page by page on a real database.

`tests/unit/test_pagination_walk.py` proves the cursor logic by running the generated SQL in SQLite. This runs the
real list queries on Postgres. The defect it guards: the cursor condition sat in WHERE with a bare `id`, which is
ambiguous the moment a list joins another table, so page one worked and every later page failed. A test that only
fetched the first page could never have noticed.
"""

import uuid

import pytest

from services.billing import repository as billing_repo
from services.tracking import repository as tracking_repo
from tests.db.support import _make_invoice

pytestmark = pytest.mark.db

PAGE = 2


def _walk(list_page, **kwargs) -> list[dict]:
    """Every row of a list, `PAGE` at a time, exactly as the endpoint serves them."""
    from shared.pagination import decode_cursor

    rows, cursor = [], None
    for _ in range(20):
        page, next_cursor, has_more = list_page(limit=PAGE, cursor=cursor, **kwargs)
        rows.extend(page)
        if not has_more:
            return rows
        cursor = decode_cursor(next_cursor)
    raise AssertionError("pagination never finished")


@pytest.fixture
def disputes(world, admin):
    """Three invoices, each with a dispute, for three different customers."""
    made = []
    for i in range(3):
        billing_id = _make_invoice(admin, world, index=i)
        dispute_id = str(uuid.uuid4())
        with admin.cursor() as cur:
            cur.execute("UPDATE customer SET name = %s WHERE id = %s", (f"Dispute Customer {i}", world["customers"][i]))
            cur.execute(
                "INSERT INTO cbm_dispute (id, tenant_id, billing_id, customer_id, disputed_cbm, customer_measured_cbm, dispute_reason, status) "
                "VALUES (%s, %s, %s, %s, 1.5, 1.2, 'Smaller than billed', 'submitted')",
                (dispute_id, world["tenant"], billing_id, world["customers"][i]),
            )
        made.append((dispute_id, billing_id))
    return made


class TestDisputeList:
    def test_each_dispute_names_its_customer_invoice_and_container(self, world, disputes):
        rows, _, _ = billing_repo.list_all_disputes(world["tenant"], {}, 50)
        by_id = {str(r["id"]): r for r in rows}
        for i, (dispute_id, _) in enumerate(disputes):
            row = by_id[dispute_id]
            assert row["customer_name"] == f"Dispute Customer {i}"
            assert row["container_number"] == f"MNY{i:04d}"
            assert row["invoice_number"].startswith("TST-INV-")

    def test_every_page_loads_not_just_the_first(self, world, disputes):
        walked = _walk(lambda **kw: billing_repo.list_all_disputes(world["tenant"], {}, **kw))
        assert {str(r["id"]) for r in walked} == {d for d, _ in disputes}
        assert len(walked) == 3

    def test_the_status_filter_still_applies(self, world, disputes):
        rows, _, _ = billing_repo.list_all_disputes(world["tenant"], {"status": "closed"}, 50)
        assert rows == []


class TestInvoiceListSortedByAColumn:
    @pytest.mark.parametrize("direction", ["ASC", "DESC"])
    def test_paging_through_a_sort_that_is_not_created_at(self, admin, world, direction):
        for i in range(5):
            _make_invoice(admin, world, index=i)
        one_shot, _, _ = billing_repo.list_billing_all(world["tenant"], {}, 50, None, "invoice_number", direction)
        walked = _walk(
            lambda **kw: billing_repo.list_billing_all(
                world["tenant"], {}, sort_field="invoice_number", sort_direction=direction, **kw
            )
        )
        assert [str(r["id"]) for r in walked] == [str(r["id"]) for r in one_shot]
        assert len(walked) == 5


class TestContainerListSortedByAColumn:
    @pytest.mark.parametrize("direction", ["ASC", "DESC"])
    def test_paging_through_a_sort_that_is_not_created_at(self, world, direction):
        one_shot, _, _ = tracking_repo.list_containers(world["tenant"], {}, 50, None, "container_number", direction)
        walked = _walk(
            lambda **kw: tracking_repo.list_containers(
                world["tenant"], {}, sort_field="container_number", sort_direction=direction, **kw
            )
        )
        assert [str(r["id"]) for r in walked] == [str(r["id"]) for r in one_shot]
        assert len(walked) == 12  # the world fixture's containers
