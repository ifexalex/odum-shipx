"""Unit tests for services.excel.export_receipt_pdf.

Regression guard for a QR-code rendering bug found while auditing the sibling
export_release_note_pdf.py module: _qr_image set `.transform` on the
QrCodeWidget itself, but reportlab's AttrMap validation only allows that
attribute on the Drawing — every call to generate_receipt_pdf raised
AttributeError before this fix, meaning the cash-receipt PDF export has never
actually worked.
"""
from datetime import date
from decimal import Decimal

from services.excel.export_receipt_pdf import generate_receipt_pdf


def _payment(**overrides) -> dict:
    base = {
        "id": "pay-001",
        "receipt_number": "RCP-20260913-0001",
        "payer_name": "Ibrahim Musa",
        "amount_ngn": Decimal("139500.00"),
        "payment_method": "bank_transfer",
        "bank_name": "GTBank",
        "cheque_number": None,
        "warehouse_name": "Main Warehouse",
        "billing_reference": "ACM-INV-20260906-0004",
        "payment_date": date(2026, 9, 13),
    }
    base.update(overrides)
    return base


class TestGenerateReceiptPdf:
    def test_renders_a_valid_pdf_for_a_fully_populated_payment(self):
        buf = generate_receipt_pdf({"company_name": "Dollarman Global Shipping"}, _payment())
        data = buf.read()
        assert data.startswith(b"%PDF")
        assert len(data) > 500

    def test_renders_for_a_bare_payment_with_missing_optional_fields(self):
        buf = generate_receipt_pdf(
            {"company_name": "ShipX"},
            _payment(bank_name=None, cheque_number=None, warehouse_name=None, billing_reference=None),
        )
        assert buf.read().startswith(b"%PDF")
