"""Unit tests for services.excel.service — packing-list import presigned upload
and billing export (incl. the customer-facing "download invoice" path)."""

from unittest.mock import patch

import pytest

from services.excel import service
from services.excel.service import generate_import_presigned_url
from shared.exceptions import BusinessRuleViolationError, ResourceNotFoundError

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


class TestGenerateImportPresignedUrl:
    def test_rejects_non_xlsx_content_type(self):
        with pytest.raises(BusinessRuleViolationError) as exc_info:
            generate_import_presigned_url(TENANT_ID, "application/pdf")
        assert exc_info.value.error_code == "BUSINESS_RULE_VIOLATION"

    def test_rejects_csv_content_type(self):
        """Only the real .xlsx MIME type is accepted — import_packing_list() only parses xlsx."""
        with pytest.raises(BusinessRuleViolationError):
            generate_import_presigned_url(TENANT_ID, "text/csv")


class TestExportBilling:
    """GET /v1/billing/{id}/export — also the customer's "Download invoice"
    action once ctx.role == CUSTOMER is allowed (services/excel/handler.py)."""

    BILLING_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    OWN_CUSTOMER_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    OTHER_CUSTOMER_ID = "dddddddd-dddd-dddd-dddd-dddddddddddd"

    def _billing_row(self, customer_id: str) -> dict:
        return {
            "id": self.BILLING_ID,
            "customer_id": customer_id,
            "customer_name": "Ngozi Adeyemi",
            "container_number": "ACME001001",
            "total_ngn": "39500.00",
            "balance_ngn": "0.00",
            "status": "paid",
            "billed_at": "2026-07-18",
            "created_at": "2026-07-18",
        }

    def test_staff_export_needs_no_ownership_check(self):
        with (
            patch.object(service.repo, "get_billing_for_export", return_value=self._billing_row(self.OTHER_CUSTOMER_ID)),
            patch.object(service.repo, "get_misc_charges_for_export", return_value=[]),
            patch.object(service.repo, "get_tenant_display_name", return_value="Acme Shipping Ltd"),
            patch.object(service, "_upload_and_presign", return_value={"download_url": "https://example.com/x.xlsx"}),
        ):
            result = service.export_billing(TENANT_ID, self.BILLING_ID, fmt="xlsx")
        assert result["download_url"]

    def test_customer_can_export_own_billing(self):
        with (
            patch.object(service.repo, "get_billing_for_export", return_value=self._billing_row(self.OWN_CUSTOMER_ID)),
            patch.object(service.repo, "get_customer_id_for_user", return_value=self.OWN_CUSTOMER_ID),
            patch.object(service.repo, "get_misc_charges_for_export", return_value=[]),
            patch.object(service.repo, "get_tenant_display_name", return_value="Acme Shipping Ltd"),
            patch.object(service, "_upload_and_presign", return_value={"download_url": "https://example.com/x.pdf"}),
        ):
            result = service.export_billing(TENANT_ID, self.BILLING_ID, fmt="csv", customer_user_id="cognito-sub-1")
        assert result["download_url"]

    def test_invoice_names_each_fee_instead_of_a_bare_total(self):
        """Ground-truth gap found live: the customer's downloadable invoice
        used to be 7 bare columns (customer_name, container_number, total_ngn,
        balance_ngn, status, billed_at, created_at) with zero breakdown — a
        customer had no way to see what made up either total. Confirms the
        itemized fee string actually names each charge, not just a sum."""
        with (
            patch.object(service.repo, "get_billing_for_export", return_value=self._billing_row(self.OWN_CUSTOMER_ID)),
            patch.object(service.repo, "get_customer_id_for_user", return_value=self.OWN_CUSTOMER_ID),
            patch.object(
                service.repo,
                "get_misc_charges_for_export",
                return_value=[
                    {"description": "Customs clearance fee", "amount_ngn": "5000.00"},
                    {"description": "Documentation fee", "amount_ngn": "2000.00"},
                ],
            ),
            patch.object(service.repo, "get_tenant_display_name", return_value="Acme Shipping Ltd"),
            patch.object(service, "_rows_to_csv", wraps=service._rows_to_csv) as mock_csv,
            patch.object(service, "_upload_and_presign", return_value={"download_url": "https://example.com/x.csv"}),
        ):
            service.export_billing(TENANT_ID, self.BILLING_ID, fmt="csv", customer_user_id="cognito-sub-1")

        exported_row = mock_csv.call_args.args[0][0]
        assert exported_row["misc_fees_itemized"] == "Customs clearance fee: NGN 5,000.00; Documentation fee: NGN 2,000.00"
        # Full breakdown columns present — not the old 7-column bare total.
        assert "total_cbm" in service._BILLING_COLUMNS
        assert "cbm_rate_usd" in service._BILLING_COLUMNS
        assert "subtotal_ngn" in service._BILLING_COLUMNS
        assert "amount_paid_ngn" in service._BILLING_COLUMNS

    def test_customer_cannot_export_another_customers_billing(self):
        """The core tenant-isolation guarantee: a customer_id mismatch must 404,
        not leak whether the billing record exists (same pattern as
        export_packing_list_pdf)."""
        with (
            patch.object(service.repo, "get_billing_for_export", return_value=self._billing_row(self.OTHER_CUSTOMER_ID)),
            patch.object(service.repo, "get_customer_id_for_user", return_value=self.OWN_CUSTOMER_ID),
        ):
            with pytest.raises(ResourceNotFoundError):
                service.export_billing(TENANT_ID, self.BILLING_ID, fmt="csv", customer_user_id="cognito-sub-1")

    def test_customer_with_no_customer_row_is_rejected(self):
        """A CUSTOMER-role caller with no linked customer row must 404, not
        fall through to an unscoped export."""
        with (
            patch.object(service.repo, "get_billing_for_export", return_value=self._billing_row(self.OWN_CUSTOMER_ID)),
            patch.object(service.repo, "get_customer_id_for_user", return_value=None),
        ):
            with pytest.raises(ResourceNotFoundError):
                service.export_billing(TENANT_ID, self.BILLING_ID, fmt="csv", customer_user_id="cognito-sub-orphan")

    def test_unknown_billing_id_404s_before_ownership_check(self):
        with patch.object(service.repo, "get_billing_for_export", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.export_billing(TENANT_ID, self.BILLING_ID, fmt="csv", customer_user_id="cognito-sub-1")
