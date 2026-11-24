"""The dispute detail read a China user resolves a dispute on, against a real database (audit UX-01).

It joins a dispute to its invoice, customer, container and the packing-list lines the CBM was summed from.
Only a database can show the SQL is right, and that the response carries no payment data.
"""

import uuid
from decimal import Decimal

import pytest

from tests.db.support import _make_invoice

pytestmark = pytest.mark.db


def _dispute_with_lines(admin, world, cbms: list[str], status: str = "escalated_china") -> tuple[str, str]:
    billing_id = _make_invoice(admin, world, index=0)
    dispute_id, pl_id = str(uuid.uuid4()), str(uuid.uuid4())
    with admin.cursor() as cur:
        cur.execute(
            "INSERT INTO packing_list (id, tenant_id, container_id, customer_id, reference, status) VALUES (%s, %s, %s, %s, 'PL-X', 'approved')",
            (pl_id, world["tenant"], world["containers"][0], world["customers"][0]),
        )
        for i, cbm in enumerate(cbms):
            cur.execute(
                "INSERT INTO packing_list_item (packing_list_id, description, carton_tag, tracking_code, cbm, quantity) "
                "VALUES (%s, 'goods', %s, %s, %s, 2)",
                (pl_id, f"TAG-{i}", f"TRK-{i}", cbm),
            )
        cur.execute(
            "INSERT INTO cbm_dispute (id, tenant_id, billing_id, customer_id, disputed_cbm, customer_measured_cbm, dispute_reason, status) "
            "VALUES (%s, %s, %s, %s, 1.5, 1.2, 'Smaller than billed', %s)",
            (dispute_id, world["tenant"], billing_id, world["customers"][0], status),
        )
    return dispute_id, billing_id


class TestDisputeDetail:
    def test_it_returns_the_dispute_with_its_measurement_lines(self, world, admin):
        from services.billing import service

        dispute_id, _ = _dispute_with_lines(admin, world, ["0.500", "0.750"])
        detail = service.get_dispute_detail(world["tenant"], dispute_id)

        assert detail["customer_name"] == "Customer 0"
        assert detail["container_number"] == "MNY0000"
        assert detail["reason"] == "Smaller than billed"
        assert detail["customer_measured_cbm"] == Decimal("1.200000")
        assert [ln["carton_tag"] for ln in detail["lines"]] == ["TAG-0", "TAG-1"]
        assert sum(ln["cbm"] for ln in detail["lines"]) == Decimal("1.250000")
        assert detail["status"] == "escalated_china"

    def test_it_carries_no_payment_data(self, world, admin):
        from services.billing import service

        dispute_id, _ = _dispute_with_lines(admin, world, ["1.0"])
        detail = service.get_dispute_detail(world["tenant"], dispute_id)
        assert not {"total_ngn", "subtotal_ngn", "subtotal_usd", "amount_paid_ngn", "balance_ngn", "cbm_rate_usd"} & set(detail)

    def test_only_approved_lists_for_that_customer_and_container_count(self, world, admin):
        from services.billing import service

        dispute_id, _ = _dispute_with_lines(admin, world, ["1.0"])
        with admin.cursor() as cur:
            # Same container, another customer; and a draft list of the same customer: neither is part of this invoice.
            for n, (customer, status) in enumerate(((world["customers"][1], "approved"), (world["customers"][0], "draft"))):
                other = str(uuid.uuid4())
                cur.execute(
                    "INSERT INTO packing_list (id, tenant_id, container_id, customer_id, reference, status) VALUES (%s, %s, %s, %s, %s, %s)",
                    (other, world["tenant"], world["containers"][0], customer, f"PL-OTHER-{n}", status),
                )
                cur.execute(
                    "INSERT INTO packing_list_item (packing_list_id, description, carton_tag, tracking_code, cbm) VALUES (%s, 'x', %s, %s, 9)",
                    (other, f"OTHER-{n}", f"OTRK-{n}"),
                )
        detail = service.get_dispute_detail(world["tenant"], dispute_id)
        assert [ln["reference"] for ln in detail["lines"]] == ["PL-X"]

    def test_another_tenants_dispute_is_a_404(self, world, admin):
        from services.billing import service
        from shared.exceptions import ResourceNotFoundError

        dispute_id, _ = _dispute_with_lines(admin, world, ["1.0"])
        with pytest.raises(ResourceNotFoundError):
            service.get_dispute_detail(str(uuid.uuid4()), dispute_id)
