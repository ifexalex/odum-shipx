"""The invoice-list and container-list exports against a real database.

The mocked tests show the exports share the lists' filter and refuse what is too large. Only a database shows the
queries are valid against the real schema, that an export returns exactly the rows the list shows for the same
filters, that the aggregated columns (carryover, storage fees, packing-list counts) are right, and that every
exported column key is a real column (a wrong key exports blank, silently).
"""

import io
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

import openpyxl
import pytest

from services.billing import repository as billing_repo
from services.excel import repository as excel_repo
from services.excel import service
from services.tracking import repository as tracking_repo
from tests.db.support import _make_invoice

pytestmark = pytest.mark.db


def _ids(rows) -> list[str]:
    return [str(r["id"]) for r in rows]


@pytest.fixture
def invoices(world, admin):
    """Three invoices, differing in status, customer, container and billing date."""
    made = [_make_invoice(admin, world, total=total, index=i) for i, total in enumerate(("100000.00", "250000.00", "75000.50"))]
    with admin.cursor() as cur:
        cur.execute("UPDATE customer SET name = 'Ngozi Okonkwo' WHERE id = %s", (world["customers"][0],))
        cur.execute(
            "UPDATE billing SET status = 'paid', amount_paid_ngn = total_ngn, billed_at = %s WHERE id = %s",
            (datetime(2026, 1, 10, tzinfo=UTC), made[1]),
        )
        cur.execute("UPDATE billing SET billed_at = %s WHERE id = %s", (datetime(2026, 3, 10, tzinfo=UTC), made[2]))
        cur.execute("UPDATE billing SET billed_at = %s WHERE id = %s", (datetime(2026, 2, 10, tzinfo=UTC), made[0]))
    return made


class TestInvoiceExportMatchesTheList:
    @pytest.mark.parametrize(
        "filters",
        [
            {},
            {"status": "paid"},
            {"status": ["unpaid", "paid"]},
            {"q": "Ngozi"},
            {"q": "MNY0002"},
            {"q": "TST-INV"},
            {"created_after": "2026-02-01"},
            {"created_before": "2026-02-15"},
            {"created_after": "2026-02-01", "created_before": "2026-03-31", "status": "unpaid"},
            {"q": "zzz-nothing"},
        ],
        ids=lambda f: ",".join(f) or "no filter",
    )
    def test_same_filters_same_rows_same_order(self, world, invoices, filters):
        listed, _, _ = billing_repo.list_billing_all(world["tenant"], filters, 100)
        exported, truncated = excel_repo.list_billing_for_export(world["tenant"], filters, 100)
        assert _ids(exported) == _ids(listed)
        assert truncated is False

    @pytest.mark.parametrize("sort_field", ["invoice_number", "billed_at", "created_at"])
    @pytest.mark.parametrize("direction", ["ASC", "DESC"])
    def test_same_sort_same_order(self, world, invoices, sort_field, direction):
        listed, _, _ = billing_repo.list_billing_all(world["tenant"], {}, 100, None, sort_field, direction)
        exported, _ = excel_repo.list_billing_for_export(world["tenant"], {}, 100, sort_field, direction)
        assert _ids(exported) == _ids(listed)

    def test_the_filter_really_filters(self, world, invoices):
        exported, _ = excel_repo.list_billing_for_export(world["tenant"], {"status": "paid"}, 100)
        assert _ids(exported) == [invoices[1]]

    def test_more_rows_than_the_limit_is_flagged(self, world, invoices):
        exported, truncated = excel_repo.list_billing_for_export(world["tenant"], {}, 2)
        assert len(exported) == 2 and truncated is True

    def test_another_tenant_sees_none_of_them(self, world, invoices):
        exported, _ = excel_repo.list_billing_for_export(str(uuid.uuid4()), {}, 100)
        assert exported == []


class TestInvoiceExportColumns:
    def test_carryover_storage_fees_and_balance(self, admin, world, invoices):
        target = invoices[0]
        with admin.cursor() as cur:
            cur.execute(
                "INSERT INTO carryover_ledger (tenant_id, customer_id, source_billing_id, target_billing_id, carryover_amount_ngn, status) "
                "VALUES (%s, %s, %s, %s, 5000, 'applied')",
                (world["tenant"], world["customers"][0], invoices[2], target),
            )
            cur.execute(
                "INSERT INTO storage_fee_log (tenant_id, billing_id, customer_id, container_id, accrual_date, daily_rate_ngn, amount_ngn) "
                "VALUES (%s, %s, %s, %s, '2026-02-01', 100, 700)",
                (world["tenant"], target, world["customers"][0], world["containers"][0]),
            )
            # A waived fee is not owed, so it must not be counted.
            cur.execute(
                "INSERT INTO storage_fee_log (tenant_id, billing_id, customer_id, container_id, accrual_date, daily_rate_ngn, amount_ngn, waived_at) "
                "VALUES (%s, %s, %s, %s, '2026-02-02', 100, 9999, now())",
                (world["tenant"], target, world["customers"][0], world["containers"][0]),
            )
        rows, _ = excel_repo.list_billing_for_export(world["tenant"], {"q": "Ngozi"}, 100)
        row = rows[0]
        assert row["customer_name"] == "Ngozi Okonkwo" and row["container_number"] == "MNY0000"
        assert Decimal(str(row["carryover_ngn"])) == Decimal("5000")
        assert Decimal(str(row["storage_fees_ngn"])) == Decimal("700")
        assert Decimal(str(row["balance_ngn"])) == Decimal(str(row["total_ngn"])) - Decimal(str(row["amount_paid_ngn"]))


def _exported_sheet(fmt_fn, *args, **kwargs):
    """Run an export through the real service with only S3 replaced, and open the workbook it produced."""
    stored: dict = {}

    def upload(tenant_id, filename, buf, fmt="xlsx"):
        stored["bytes"] = buf.getvalue()
        stored["filename"] = filename
        return {"filename": filename, "download_url": "https://example.test/f", "format": fmt}

    with patch.object(service, "_upload_and_presign", side_effect=upload):
        result = fmt_fn(*args, **kwargs)
    return result, stored


class TestInvoiceExportEndToEnd:
    def test_a_real_workbook_with_real_values(self, world, invoices):
        result, stored = _exported_sheet(
            service.export_billing_list,
            world["tenant"],
            {},
            fmt="xlsx",
            sort_field="invoice_number",
            sort_direction="asc",
            actor_id=world["user"],
            actor_role="nigeria_office_staff",
        )
        sheet = openpyxl.load_workbook(BytesIO(stored["bytes"])).active
        headers = [c.value for c in sheet[1]]
        assert result["row_count"] == 3 and sheet.max_row == 4
        total_due = headers.index("Total Due (NGN)") + 1
        assert sorted(sheet.cell(row=r, column=total_due).value for r in range(2, 5)) == [75000.5, 100000.0, 250000.0]
        # Every column is real: none came back blank for every row (a wrong key exports empty, silently).
        for index, header in enumerate(headers, 1):
            column = [sheet.cell(row=r, column=index).value for r in range(2, 5)]
            optional = {"Billed At (UTC)", "Carryover (NGN)", "Storage Fees (NGN)", "Dollar Rate (NGN)"}
            if header not in optional:
                assert any(v not in (None, "") for v in column), f"column {header!r} is blank for every invoice"

    def test_a_customer_named_like_a_formula_is_text_in_the_file(self, admin, world, invoices):
        evil = '=HYPERLINK("http://evil.example","Click")'
        with admin.cursor() as cur:
            cur.execute("UPDATE customer SET name = %s WHERE id = %s", (evil, world["customers"][0]))
        _, stored = _exported_sheet(
            service.export_billing_list,
            world["tenant"],
            {"q": "HYPERLINK"},
            fmt="xlsx",
            sort_field="created_at",
            sort_direction="desc",
            actor_id=world["user"],
            actor_role="nigeria_office_staff",
        )
        cell = openpyxl.load_workbook(BytesIO(stored["bytes"])).active["B2"]
        assert cell.value == evil and cell.data_type == "s"

    def test_csv_carries_exact_money(self, world, invoices):
        _, stored = _exported_sheet(
            service.export_billing_list,
            world["tenant"],
            {"status": "unpaid", "created_after": "2026-03-01"},
            fmt="csv",
            sort_field="created_at",
            sort_direction="desc",
            actor_id=world["user"],
            actor_role="tenant_admin",
        )
        text = stored["bytes"].decode("utf-8-sig")
        assert "75000.50" in text and "250000" not in text

    def test_the_export_is_audited(self, admin, world, invoices):
        _exported_sheet(
            service.export_billing_list,
            world["tenant"],
            {"q": "Ngozi"},
            fmt="csv",
            sort_field="created_at",
            sort_direction="desc",
            actor_id=world["user"],
            actor_role="nigeria_office_staff",
        )
        with admin.cursor() as cur:
            cur.execute(
                "SELECT action, after_state FROM audit_log WHERE tenant_id = %s AND entity_type = 'billing' AND action = 'EXPORT'",
                (world["tenant"],),
            )
            rows = cur.fetchall()
        assert len(rows) == 1
        assert "Ngozi" not in str(rows[0][1])


@pytest.fixture
def containers(world, admin):
    """Containers with different statuses, ETAs and creation dates; the first has a packing list with 3 CBM."""
    with admin.cursor() as cur:
        for index, (status, eta, created, vessel) in enumerate(
            (
                ("loading", "2026-05-01", "2026-01-05", "MSC Aurora"),
                ("in_transit", "2026-03-10", "2026-02-05", "Maersk Kiel"),
                ("arrived", "2026-02-01", "2026-03-05", "MSC Aurora"),
            )
        ):
            cur.execute(
                "UPDATE container SET status = %s, estimated_arrival_date = %s, created_at = %s, vessel_name = %s WHERE id = %s",
                (status, eta, created, vessel, world["containers"][index]),
            )
        packing_list = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO packing_list (id, tenant_id, container_id, customer_id, reference, status) VALUES (%s, %s, %s, %s, 'PL-EXP-1', 'approved')",
            (packing_list, world["tenant"], world["containers"][0], world["customers"][0]),
        )
        cur.execute(
            "INSERT INTO packing_list_item (packing_list_id, description, carton_tag, tracking_code, cbm) VALUES (%s, 'goods', 'T1', 'TRK-EXP-1', 3)",
            (packing_list,),
        )
    return world["containers"][:3]


class TestContainerExportMatchesTheList:
    @pytest.mark.parametrize(
        "filters",
        [
            {},
            {"status": "loading"},
            {"status": ["loading", "arrived"]},
            {"q": "MSC"},
            {"q": "MNY0001"},
            {"created_after": "2026-02-01"},
            {"created_before": "2026-02-15"},
            {"eta_after": "2026-03-01"},
            {"eta_before": "2026-03-15"},
            {"eta_after": "2026-02-15", "eta_before": "2026-04-01", "q": "Maersk"},
            {"q": "zzz-nothing"},
        ],
        ids=lambda f: ",".join(f) or "no filter",
    )
    def test_same_filters_same_rows_same_order(self, world, containers, filters):
        # The tenant has 12 containers; the three seeded ones are the ones the filters tell apart.
        listed, _, _ = tracking_repo.list_containers(world["tenant"], filters, 100)
        exported, truncated = excel_repo.list_containers_for_export(world["tenant"], filters, 100)
        assert _ids(exported) == _ids(listed)
        assert truncated is False

    @pytest.mark.parametrize("sort_field", ["container_number", "estimated_arrival_date", "created_at"])
    def test_same_sort_same_order(self, world, containers, sort_field):
        listed, _, _ = tracking_repo.list_containers(world["tenant"], {}, 100, None, sort_field, "ASC")
        exported, _ = excel_repo.list_containers_for_export(world["tenant"], {}, 100, sort_field, "ASC")
        assert _ids(exported) == _ids(listed)

    def test_packing_list_aggregates(self, world, containers):
        rows, _ = excel_repo.list_containers_for_export(world["tenant"], {"q": "MNY0000"}, 100)
        assert len(rows) == 1
        assert rows[0]["packing_list_count"] == 1 and rows[0]["approved_packing_list_count"] == 1
        assert Decimal(str(rows[0]["total_cbm_packed"])) == Decimal("3")

    def test_more_rows_than_the_limit_is_flagged(self, world, containers):
        rows, truncated = excel_repo.list_containers_for_export(world["tenant"], {}, 5)
        assert len(rows) == 5 and truncated is True

    def test_a_real_workbook_with_real_values(self, world, containers):
        result, stored = _exported_sheet(
            service.export_container_list,
            world["tenant"],
            {"q": "MSC"},
            fmt="xlsx",
            sort_field="container_number",
            sort_direction="asc",
            actor_id=world["user"],
            actor_role="china_office_staff",
        )
        sheet = openpyxl.load_workbook(BytesIO(stored["bytes"])).active
        headers = [c.value for c in sheet[1]]
        assert result["row_count"] == 2
        assert [sheet.cell(row=r, column=1).value for r in (2, 3)] == ["MNY0000", "MNY0002"]
        assert sheet.cell(row=2, column=headers.index("CBM Packed") + 1).value == 3.0
        assert sheet.cell(row=2, column=headers.index("ETA") + 1).value == datetime(2026, 5, 1)

    def test_csv(self, world, containers):
        _, stored = _exported_sheet(
            service.export_container_list,
            world["tenant"],
            {"status": "arrived"},
            fmt="csv",
            sort_field="created_at",
            sort_direction="desc",
            actor_id=world["user"],
            actor_role="tenant_admin",
        )
        lines = io.StringIO(stored["bytes"].decode("utf-8-sig")).read().splitlines()
        assert len(lines) == 2 and lines[1].startswith("MNY0002,arrived,MSC Aurora")
