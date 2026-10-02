"""Unit tests for services.excel.export_release_note_pdf.

get_release_note_for_pdf's query joins far more than generate_release_note_pdf
used to read (customer_phone, warehouse_name/address/city/state, the billing
totals, payment_status, receipt_number) — the same class of "data captured but
silently dropped" bug already fixed twice elsewhere in this task
(_fmt_release_note, create_split_release_note). build_meta_pairs is the pure
field-completeness logic extracted so it's testable without rendering a PDF.
"""
from datetime import datetime

from services.excel.export_release_note_pdf import build_meta_pairs, generate_release_note_pdf


def _note(**overrides) -> dict:
    base = {
        "id": "rn-001",
        "reference_number": "ACME-RN-20260913-0001",
        "customer_name": "Ibrahim Musa",
        "customer_phone": "+2348169760253",
        "container_number": "ACME001001",
        "billing_reference": "ACM-INV-20260906-0004",
        "carton_count": 5,
        "status": "active",
        "created_at": datetime(2026, 9, 13, 10, 0, 0),
        "warehouse_name": None,
        "warehouse_address": None,
        "warehouse_city": None,
        "warehouse_state": None,
        "physical_document_number": None,
        "packing_list_invoice_numbers": [],
        "packages_balance": None,
        "is_on_credit": False,
        "credit_granted_by_name": None,
        "receipt_number": None,
        "billing_amount_paid_ngn": None,
        "billing_balance_ngn": None,
        "billing_total_ngn": None,
    }
    base.update(overrides)
    return base


def _labels(pairs: list[tuple[str, str]]) -> set[str]:
    return {label for label, _ in pairs}


class TestBuildMetaPairsFieldCompleteness:
    def test_bare_note_only_has_the_core_fields(self):
        pairs = build_meta_pairs(_note())
        labels = _labels(pairs)
        assert labels == {
            "Customer",
            "Phone",
            "Container",
            "Payment Reference",
            "Carton Count",
            "Status",
            "Valid From",
        }
        assert dict(pairs)["Customer"] == "Ibrahim Musa"
        assert dict(pairs)["Phone"] == "+2348169760253"

    def test_surfaces_warehouse_when_linked(self):
        pairs = build_meta_pairs(
            _note(
                warehouse_name="Main Warehouse",
                warehouse_address="12 Marina Rd",
                warehouse_city="Lagos",
                warehouse_state="Lagos",
            )
        )
        assert dict(pairs)["Warehouse"] == "Main Warehouse, 12 Marina Rd, Lagos, Lagos"

    def test_omits_warehouse_when_not_linked(self):
        pairs = build_meta_pairs(_note())
        assert "Warehouse" not in _labels(pairs)

    def test_surfaces_document_number_and_invoice_numbers(self):
        pairs = build_meta_pairs(
            _note(
                physical_document_number="GRN-4471",
                packing_list_invoice_numbers=["INV-1", "INV-2"],
            )
        )
        result = dict(pairs)
        assert result["Document No."] == "GRN-4471"
        assert result["Invoice No(s)."] == "INV-1, INV-2"

    def test_surfaces_cartons_balance_only_when_nonzero(self):
        assert "Cartons Balance" not in _labels(build_meta_pairs(_note(packages_balance=0)))
        assert "Cartons Balance" not in _labels(build_meta_pairs(_note(packages_balance=None)))
        pairs = build_meta_pairs(_note(packages_balance=2))
        assert dict(pairs)["Cartons Balance"] == "2"

    def test_on_credit_shows_granted_by_instead_of_amounts(self):
        pairs = build_meta_pairs(
            _note(
                is_on_credit=True,
                credit_granted_by_name="Adaeze Okafor",
                billing_amount_paid_ngn="0.00",
                billing_balance_ngn="139500.00",
            )
        )
        result = dict(pairs)
        assert result["Payment Status"] == "ON CREDIT — granted by Adaeze Okafor"
        assert "Amount Paid" not in result
        assert "Balance Outstanding" not in result

    def test_on_credit_still_shows_receipt_number_if_present(self):
        pairs = build_meta_pairs(
            _note(
                is_on_credit=True,
                credit_granted_by_name="Adaeze Okafor",
                receipt_number="RCP-99",
            )
        )
        assert dict(pairs)["Receipt No."] == "RCP-99"

    def test_paid_note_shows_amount_paid_and_receipt(self):
        pairs = build_meta_pairs(
            _note(
                billing_amount_paid_ngn="139500.00",
                billing_total_ngn="139500.00",
                billing_balance_ngn="0.00",
                receipt_number="RCP-100",
            )
        )
        result = dict(pairs)
        assert result["Amount Paid"] == "NGN 139500.00 of NGN 139500.00"
        assert "Balance Outstanding" not in result
        assert result["Receipt No."] == "RCP-100"

    def test_partial_payment_shows_balance_outstanding(self):
        pairs = build_meta_pairs(
            _note(
                billing_amount_paid_ngn="133700.00",
                billing_total_ngn="139500.00",
                billing_balance_ngn="5800.00",
            )
        )
        result = dict(pairs)
        assert result["Amount Paid"] == "NGN 133700.00 of NGN 139500.00"
        assert result["Balance Outstanding"] == "NGN 5800.00"

    def test_zero_balance_is_falsy_but_correctly_treated_as_a_string_check(self):
        # Regression guard: _fmt_release_note elsewhere in this task had a bug
        # where Decimal("0.00") was treated as falsy and silently defaulted.
        # Here the check is on the *string* "0.00", which is truthy, so it
        # must be excluded explicitly — confirm it actually is.
        pairs = build_meta_pairs(
            _note(
                billing_amount_paid_ngn="139500.00",
                billing_total_ngn="139500.00",
                billing_balance_ngn="0.00",
            )
        )
        assert "Balance Outstanding" not in dict(pairs)

    def test_omits_payment_block_entirely_when_nothing_paid_owed_or_credited(self):
        pairs = build_meta_pairs(_note())
        labels = _labels(pairs)
        assert "Amount Paid" not in labels
        assert "Balance Outstanding" not in labels
        assert "Payment Status" not in labels


class TestGenerateReleaseNotePdf:
    def test_renders_a_valid_pdf_for_a_fully_populated_note(self):
        branding = {"company_name": "Dollarman Global Shipping", "primary_color": "#1a56db"}
        buf = generate_release_note_pdf(
            branding,
            _note(
                warehouse_name="Main Warehouse",
                warehouse_address="12 Marina Rd",
                physical_document_number="GRN-4471",
                packing_list_invoice_numbers=["INV-1"],
                is_on_credit=True,
                credit_granted_by_name="Adaeze Okafor",
            ),
        )
        data = buf.read()
        assert data.startswith(b"%PDF")
        assert len(data) > 500

    def test_renders_for_a_bare_note_with_no_optional_fields(self):
        buf = generate_release_note_pdf({"company_name": "ShipX"}, _note())
        assert buf.read().startswith(b"%PDF")
