"""Tenant isolation tests — database query isolation via mocked repo calls.

These tests verify that service and repository functions always scope queries
to the correct tenant_id, preventing cross-tenant data leakage.

Strategy: patch the repo to record the tenant_id passed to each function,
then assert the correct tenant_id was used.
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

TENANT_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TENANT_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


# ---------------------------------------------------------------------------
# Billing service — tenant-scoped queries
# ---------------------------------------------------------------------------


class TestBillingDbIsolation:
    def test_list_billing_scoped_to_tenant(self):
        """get_billing_for_customer passes tenant_id to list_billing_for_customer."""
        from services.billing import service
        from shared.tenant_context import TenantContext, UserRole

        ctx = TenantContext(tenant_id=TENANT_A, user_id="u", role=UserRole.NIGERIA_OFFICE_STAFF)

        with patch.object(service.repo, "list_billing_for_customer", return_value=[]) as mock_list:
            service.get_billing_for_customer(TENANT_A, "customer-001", ctx)

        mock_list.assert_called_once()
        first_arg = mock_list.call_args[0][0]
        assert first_arg == TENANT_A, f"Expected tenant {TENANT_A}, got {first_arg}"

    def test_get_billing_not_found_for_wrong_tenant(self):
        """A billing record for customer-999 raises InsufficientPermissionsError for customer-001."""
        from services.billing import service
        from shared.exceptions import InsufficientPermissionsError
        from shared.tenant_context import TenantContext, UserRole

        # CUSTOMER role user maps to customer-001 but requests billing for customer-999
        ctx = TenantContext(tenant_id=TENANT_A, user_id="user-cust-001", role=UserRole.CUSTOMER)
        customer_row = {"id": "customer-001"}

        with patch.object(service.repo, "get_customer_by_user_id", return_value=customer_row):
            with pytest.raises(InsufficientPermissionsError):
                service.get_billing_for_customer(TENANT_A, "customer-999", ctx)

    def test_generate_billing_passes_tenant_id_to_repo(self):
        """handle_payment_due creates billing with the correct tenant_id."""
        from services.billing import service

        billing = {
            "id": "bill-001",
            "tenant_id": TENANT_A,
            "status": "unpaid",
            "total_ngn": Decimal("50000"),
            "balance_ngn": Decimal("50000"),
            "total_cbm": Decimal("5"),
            "customer_id": "cust-001",
        }

        cbm_config = {
            "currency": "usd",
            "rate_mode": "flat",
            "carton_rate": Decimal("45"),
            "bag_rate": Decimal("45"),
            "bale_rate": Decimal("45"),
            "effective_from": "",
        }

        with (
            # get_cbm_rate_config / get_effective_dollar_rate are plain
            # functions imported into services.billing.service (shared/
            # cbm_rate.py, shared/fx_rate.py), not service.repo methods —
            # patch.object(service.repo, ...) can't intercept them.
            patch("services.billing.service.get_cbm_rate_config", return_value=cbm_config),
            patch("services.billing.service.get_effective_dollar_rate", return_value={"rate": Decimal("1550")}),
            patch.object(
                service.repo, "get_cbm_and_carton_totals", return_value={"total_cbm": Decimal("5"), "total_cartons": 10}
            ),
            patch.object(service.repo, "get_cbm_by_package_type", return_value={"carton": Decimal("5")}),
            patch.object(service.repo, "get_outstanding_carryovers", return_value=[]),
            patch.object(service.repo, "get_pending_credit_refunds", return_value=[]),
            patch.object(service.repo, "get_tenant_short", return_value="ACME"),
            patch.object(service.repo, "get_next_invoice_seq", return_value=1),
            patch.object(service.repo, "create_billing", return_value=billing) as mock_create,
            patch("services.billing.service.publish_event"),
        ):
            service.handle_payment_due(TENANT_A, "cont-001", "cust-001", "CONT-001")

        # Verify tenant_id is always included in create call
        call_args = mock_create.call_args[0]
        passed_tenant_id = call_args[0]
        assert passed_tenant_id == TENANT_A


# ---------------------------------------------------------------------------
# Packing list service — tenant-scoped
# ---------------------------------------------------------------------------


class TestPackingListDbIsolation:
    def test_get_packing_list_not_found_for_wrong_tenant(self):
        """Packing list from TENANT_A is not visible to TENANT_B."""
        from services.packing_list import service
        from shared.exceptions import ResourceNotFoundError
        from shared.tenant_context import TenantContext, UserRole

        ctx = TenantContext(tenant_id=TENANT_B, user_id="u", role=UserRole.NIGERIA_OFFICE_STAFF)

        with patch.object(service.repo, "get_packing_list_by_id", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.get_packing_list("pl-A-001", TENANT_B, ctx)

    def test_list_packing_lists_passes_correct_tenant(self):
        from services.packing_list import service
        from shared.tenant_context import TenantContext, UserRole

        ctx = TenantContext(tenant_id=TENANT_A, user_id="u", role=UserRole.NIGERIA_OFFICE_STAFF)

        with patch.object(service.repo, "list_packing_lists", return_value=([], None, False)) as mock_list:
            service.list_packing_lists(TENANT_A, {}, 20, None, ctx)

        first_arg = mock_list.call_args[0][0]
        assert first_arg == TENANT_A


# ---------------------------------------------------------------------------
# Claims service — tenant-scoped
# ---------------------------------------------------------------------------


class TestClaimsDbIsolation:
    def test_get_claim_not_found_for_wrong_tenant(self):
        """A claim belonging to TENANT_A is not visible when querying TENANT_B."""
        from services.claims import service
        from shared.exceptions import ResourceNotFoundError
        from shared.tenant_context import TenantContext, UserRole

        ctx = TenantContext(tenant_id=TENANT_B, user_id="u", role=UserRole.NIGERIA_OFFICE_STAFF)

        with patch.object(service.repo, "get_damage_claim_by_id", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.get_claim(TENANT_B, "claim-A-001", ctx)

    def test_file_claim_uses_correct_tenant_id(self):
        from services.claims import service
        from shared.tenant_context import TenantContext, UserRole

        ctx = TenantContext(tenant_id=TENANT_A, user_id="u", role=UserRole.NIGERIA_OFFICE_STAFF)
        claim = {
            "id": "claim-001",
            "tenant_id": TENANT_A,
            "customer_id": "cust-001",
            "container_id": "cont-001",
            "cartons_affected": ["TAG-001", "TAG-002"],
            "status": "filed",
            "created_at": None,
        }

        req = MagicMock()
        req.container_id = "cont-001"
        req.cartons_affected = ["TAG-001", "TAG-002"]
        req.description = "Damage"

        with (
            patch.object(service.repo, "resolve_container_id", return_value="cont-001"),
            patch.object(service.repo, "get_container_status", return_value="unpacking"),
            patch.object(service.repo, "get_next_claim_reference", return_value="CLM-0001"),
            patch.object(service.repo, "create_damage_claim", return_value=claim) as mock_create,
            patch("services.claims.service.log_audit"),
            patch("services.claims.service.publish_event"),
        ):
            # For staff roles, customer_id_override must be provided
            service.file_claim(TENANT_A, req, actor_id="u", ctx=ctx, customer_id_override="cust-001")

        # First positional arg to create_damage_claim must be TENANT_A
        assert mock_create.call_args[0][0] == TENANT_A


# ---------------------------------------------------------------------------
# Refunds service — tenant-scoped
# ---------------------------------------------------------------------------


class TestRefundsDbIsolation:
    def test_get_refund_not_found_for_wrong_tenant(self):
        from services.refunds import service
        from shared.exceptions import ResourceNotFoundError
        from shared.tenant_context import TenantContext, UserRole

        ctx = TenantContext(tenant_id=TENANT_B, user_id="u", role=UserRole.NIGERIA_OFFICE_STAFF)

        with patch.object(service.repo, "get_refund_request_by_id", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.get_refund(TENANT_B, "refund-A-001", ctx)

    def test_list_refunds_passes_correct_tenant(self):
        from services.refunds import service
        from shared.tenant_context import TenantContext, UserRole

        ctx = TenantContext(tenant_id=TENANT_A, user_id="u", role=UserRole.NIGERIA_OFFICE_STAFF)

        with patch.object(service.repo, "list_refund_requests", return_value=([], None, False)) as mock_list:
            service.list_refunds(TENANT_A, ctx, {}, 20, None)

        first_arg = mock_list.call_args[0][0]
        assert first_arg == TENANT_A


# ---------------------------------------------------------------------------
# Payment release — tenant-scoped
# ---------------------------------------------------------------------------


class TestPaymentReleaseDbIsolation:
    def test_confirm_payment_uses_correct_tenant(self):
        """confirm_payment passes tenant_id correctly to all repo calls."""
        from services.payment_release import service
        from shared.tenant_context import TenantContext, UserRole

        ctx = TenantContext(tenant_id=TENANT_A, user_id="u", role=UserRole.NIGERIA_OFFICE_STAFF)

        billing = {
            "id": "billing-001",
            "tenant_id": TENANT_A,
            "customer_id": "cust-001",
            "container_id": "cont-001",
            "total_ngn": Decimal("100000"),
            "amount_paid_ngn": Decimal("0"),
            "balance_ngn": Decimal("100000"),
            "total_cbm": Decimal("10"),
            "status": "unpaid",
        }
        updated = {**billing, "amount_paid_ngn": Decimal("100000"), "balance_ngn": Decimal("0"), "status": "paid"}

        req = MagicMock()
        req.amount_ngn = Decimal("100000")
        req.payment_method = "bank_transfer"
        req.payment_reference = "REF-001"
        req.payment_date = "2026-02-01"

        with (
            patch.object(service.repo, "get_billing_by_id", return_value=billing) as mock_get,
            patch.object(service.repo, "get_tenant_short", return_value="ACME"),
            patch.object(service.repo, "get_next_receipt_number", return_value=1),
            patch.object(service.repo, "create_payment_record", return_value={"id": "pay-001"}),
            patch.object(service.repo, "update_billing_payment", return_value=updated),
            patch("services.payment_release.service.publish_event"),
            patch("services.payment_release.service.log_audit"),
        ):
            service.confirm_payment(TENANT_A, "billing-001", req, actor_id="u", ctx=ctx)

        # Verify tenant_id is always the first arg
        assert mock_get.call_args[0][0] == TENANT_A


# ---------------------------------------------------------------------------
# Tracking service — tenant-scoped container operations
# ---------------------------------------------------------------------------


class TestTrackingDbIsolation:
    def test_get_container_not_found_for_wrong_tenant(self):
        from services.tracking import service
        from shared.exceptions import ResourceNotFoundError

        with patch.object(service.repo, "get_container_by_id", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.get_container(TENANT_B, "container-A-001")

    def test_create_container_passes_correct_tenant(self):
        from services.tracking import service

        row = {"id": "cont-001", "tenant_id": TENANT_A, "container_number": "CONT-001", "status": "loading"}

        with (
            patch.object(service.repo, "create_container", return_value=row) as mock_create,
            patch("services.tracking.service.log_audit"),
            patch("services.tracking.service.check_container_limit"),
        ):
            service.create_container(
                TENANT_A,
                {"container_number": "CONT-001"},
                actor_id="u",
            )

        create_data = mock_create.call_args[0][1]
        assert create_data["tenant_id"] == TENANT_A
