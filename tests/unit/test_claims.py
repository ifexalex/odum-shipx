"""Unit tests for services.claims.service — lifecycle, approval thresholds."""

import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from shared.exceptions import (
    ApprovalThresholdExceededError,
    IllegalTransitionError,
    InsufficientPermissionsError,
    ResourceNotFoundError,
)
from shared.tenant_context import TenantContext, UserRole

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

# $50 staff threshold (default)
_THRESHOLD_USD = Decimal("50")


def _ctx(role: UserRole, user_id: str = "user-1") -> TenantContext:
    return TenantContext(tenant_id=TENANT_ID, user_id=user_id, role=role)


def _claim(**kwargs) -> dict:
    base = {
        "id": "claim-001",
        "tenant_id": TENANT_ID,
        "customer_id": "customer-001",
        "container_id": "container-001",
        "cartons_affected": [3, 4, 5],
        "description": "Water damage",
        "status": "filed",
        "submitted_by": "user-nigeria",
        "created_at": None,
    }
    base.update(kwargs)
    return base


class TestApprovalThresholds:
    """Verify the $50 approval threshold is enforced correctly."""

    def test_amount_below_threshold_staff_can_approve(self):
        """Refund claims ≤ $50 can be approved by nigeria_office_staff."""
        from services.claims import service

        claim = _claim(status="under_inspection")
        updated = _claim(status="resolved")
        req = MagicMock()
        req.resolution_type = MagicMock()
        req.resolution_type.value = "refund"
        req.amount_usd = Decimal("30")
        req.amount_ngn = Decimal("46500")
        req.reason = "Approved"
        req.discount_percentage = None

        with (
            patch.object(service.repo, "get_damage_claim_by_id", return_value=claim),
            patch.object(service.repo, "get_tenant_config_value", return_value={"staff_limit": 50}),
            patch.object(service, "get_effective_dollar_rate", return_value={"rate": Decimal("1550")}),
            patch.object(service.repo, "create_refund_request_for_claim", return_value={"id": "ref-001"}),
            patch.object(
                service.repo,
                "create_claim_resolution",
                return_value={
                    "id": "res-001",
                    "resolution_type": "refund",
                    "resolution_amount_ngn": None,
                    "approval_level": "nigeria_staff",
                    "refund_request_id": None,
                },
            ),
            patch.object(service.repo, "update_claim_status", return_value=updated),
            patch("services.claims.service.publish_event"),
            patch("services.claims.service.log_audit"),
        ):
            ctx = _ctx(UserRole.NIGERIA_OFFICE_STAFF)
            result = service.resolve_claim(TENANT_ID, "claim-001", req, actor_id="user-1", ctx=ctx)
            assert result["status"] == "resolved"

    def test_amount_above_threshold_staff_cannot_approve(self):
        """Refund claims > $50 cannot be approved by nigeria_office_staff."""
        from services.claims import service

        claim = _claim(status="under_inspection")
        req = MagicMock()
        req.resolution_type = MagicMock()
        req.resolution_type.value = "refund"
        req.amount_usd = Decimal("75")  # above threshold
        req.amount_ngn = Decimal("116250")

        with (
            patch.object(service.repo, "get_damage_claim_by_id", return_value=claim),
            patch.object(service.repo, "get_tenant_config_value", return_value={"staff_limit": 50}),
            patch.object(service, "get_effective_dollar_rate", return_value={"rate": Decimal("1550")}),
        ):
            ctx = _ctx(UserRole.NIGERIA_OFFICE_STAFF)
            with pytest.raises((ApprovalThresholdExceededError, InsufficientPermissionsError)):
                service.resolve_claim(TENANT_ID, "claim-001", req, actor_id="user-1", ctx=ctx)

    def test_amount_above_threshold_admin_can_approve(self):
        """Refund claims > $50 can be approved by tenant_admin."""
        from services.claims import service

        claim = _claim(status="under_inspection")
        updated = _claim(status="resolved")
        req = MagicMock()
        req.resolution_type = MagicMock()
        req.resolution_type.value = "refund"
        req.amount_usd = Decimal("100")
        req.amount_ngn = Decimal("155000")
        req.reason = "Approved by head of finance"
        req.discount_percentage = None

        with (
            patch.object(service.repo, "get_damage_claim_by_id", return_value=claim),
            patch.object(service.repo, "get_tenant_config_value", return_value={"staff_limit": 50}),
            patch.object(service, "get_effective_dollar_rate", return_value={"rate": Decimal("1550")}),
            patch.object(service.repo, "create_refund_request_for_claim", return_value={"id": "ref-001"}),
            patch.object(
                service.repo,
                "create_claim_resolution",
                return_value={
                    "id": "res-001",
                    "resolution_type": "refund",
                    "resolution_amount_ngn": None,
                    "approval_level": "tenant_admin",
                    "refund_request_id": None,
                },
            ),
            patch.object(service.repo, "update_claim_status", return_value=updated),
            patch("services.claims.service.publish_event"),
            patch("services.claims.service.log_audit"),
        ):
            ctx = _ctx(UserRole.TENANT_ADMIN)
            result = service.resolve_claim(TENANT_ID, "claim-001", req, actor_id="user-1", ctx=ctx)
            assert result["status"] == "resolved"


class TestCreateRefundRequestForClaimSetsRefundType:
    """Ground-truth regression: create_refund_request_for_claim's INSERT
    never set refund_type, though migration 009 added the column (and its
    CHECK constraint) with exactly this case in mind — 'damage_or_loss' is
    one of its three allowed values. Every claim-triggered refund had
    refund_type NULL in the real database, and the frontend's
    refundTypeLabel() switch had no fallback for that, so RefundDetail.tsx's
    page title silently rendered blank for every one of them. Found live:
    5 real refund_request rows, all with refund_type NULL.

    Asserts the actual SQL text (repository tests here mock execute_write_
    with_tenant entirely, so the query string is the only thing that can
    catch a regression in what's actually sent to Postgres) rather than the
    service-level tests above, which mock this function itself and would
    stay green even if its SQL silently dropped the column again.
    """

    def test_insert_sets_damage_or_loss_refund_type(self):
        from services.claims import repository

        with patch("services.claims.repository.execute_write_with_tenant") as mock_write:
            repository.create_refund_request_for_claim(
                TENANT_ID,
                {
                    "tenant_id": TENANT_ID,
                    "customer_id": "c-1",
                    "billing_id": None,
                    "amount_ngn": Decimal("500000"),
                    "reason": "test",
                },
            )

        query = mock_write.call_args.args[1]
        assert "refund_type" in query
        assert "'damage_or_loss'" in query


class TestRefundThresholdUsesRealFrontendContract:
    """Ground-truth regression: the threshold check read req.amount_usd, a
    field ResolveClaimInput (the real frontend request body) never sends —
    only amount_ngn exists on it. `if ... req.amount_usd:` was therefore
    always falsy on the one call site that actually reaches this code, and
    the entire staff-approval-threshold enforcement was dead: confirmed live,
    a ₦500,000 refund resolved cleanly as nigeria_office_staff with no
    rejection. Fixed by converting the NGN amount actually sent to USD via
    the tenant's configured dollar rate."""

    def _req_without_amount_usd(self, amount_ngn: str) -> MagicMock:
        """A MagicMock req matching what the real ResolveClaimRequest pydantic
        model actually produces from the frontend's ResolveClaimInput body:
        amount_usd genuinely present but None (its declared default — the
        frontend never sends the field). A bare MagicMock().amount_usd
        returns a truthy child mock, which would wrongly make the *old*,
        buggy `if ... req.amount_usd:` check look like it still works."""
        req = MagicMock()
        req.resolution_type = MagicMock()
        req.resolution_type.value = "refund"
        req.amount_usd = None
        req.amount_ngn = Decimal(amount_ngn)
        req.discount_percentage = None
        req.reason = "e2e test"
        return req

    def test_over_threshold_ngn_refund_is_rejected_for_staff(self):
        from services.claims import service

        claim = _claim(status="under_inspection")
        # ₦500,000 / ₦1550 per $ ≈ $322.58 — well above the $50 staff limit.
        req = self._req_without_amount_usd("500000")

        with (
            patch.object(service.repo, "get_damage_claim_by_id", return_value=claim),
            patch.object(service.repo, "get_tenant_config_value", return_value={"staff_limit": 50}),
            patch.object(service, "get_effective_dollar_rate", return_value={"rate": Decimal("1550")}),
            patch.object(service.repo, "create_refund_request_for_claim") as mock_create_refund,
        ):
            ctx = _ctx(UserRole.NIGERIA_OFFICE_STAFF)
            with pytest.raises((ApprovalThresholdExceededError, InsufficientPermissionsError)):
                service.resolve_claim(TENANT_ID, "claim-001", req, actor_id="u", ctx=ctx)

        mock_create_refund.assert_not_called()

    def test_over_threshold_ngn_refund_is_allowed_for_admin(self):
        from services.claims import service

        claim = _claim(status="under_inspection")
        updated = _claim(status="resolved")
        req = self._req_without_amount_usd("500000")

        with (
            patch.object(service.repo, "get_damage_claim_by_id", return_value=claim),
            patch.object(service.repo, "get_tenant_config_value", return_value={"staff_limit": 50}),
            patch.object(service, "get_effective_dollar_rate", return_value={"rate": Decimal("1550")}),
            patch.object(service.repo, "create_refund_request_for_claim", return_value={"id": "ref-001"}),
            patch.object(
                service.repo,
                "create_claim_resolution",
                return_value={
                    "id": "res-001",
                    "resolution_type": "refund",
                    "resolution_amount_ngn": None,
                    "approval_level": "tenant_admin",
                    "refund_request_id": None,
                },
            ),
            patch.object(service.repo, "update_claim_status", return_value=updated),
            patch("services.claims.service.publish_event"),
            patch("services.claims.service.log_audit"),
        ):
            ctx = _ctx(UserRole.TENANT_ADMIN)
            result = service.resolve_claim(TENANT_ID, "claim-001", req, actor_id="u", ctx=ctx)
            assert result["status"] == "resolved"


class TestApprovalLevelRecorded:
    """Verify the correct approval_level is recorded in claim_resolution."""

    def _make_req(self, resolution_type: str, amount_usd: str) -> MagicMock:
        req = MagicMock()
        req.resolution_type = MagicMock()
        req.resolution_type.value = resolution_type
        req.amount_usd = Decimal(amount_usd)
        req.reason = "Test"
        req.amount_ngn = Decimal(amount_usd) * Decimal("1550")
        req.discount_percentage = None
        return req

    def test_small_refund_records_nigeria_staff_approval_level(self):
        """A refund below $50 should record approval_level='nigeria_staff'."""
        from services.claims import service

        claim = _claim(status="under_inspection")
        updated = _claim(status="resolved")

        req = self._make_req("refund", "30")

        with (
            patch.object(service.repo, "get_damage_claim_by_id", return_value=claim),
            patch.object(service.repo, "get_tenant_config_value", return_value={"staff_limit": 50}),
            patch.object(service, "get_effective_dollar_rate", return_value={"rate": Decimal("1550")}),
            patch.object(service.repo, "create_refund_request_for_claim", return_value={"id": "ref-001"}),
            patch.object(
                service.repo,
                "create_claim_resolution",
                return_value={
                    "id": "res-001",
                    "resolution_type": "refund",
                    "resolution_amount_ngn": None,
                    "approval_level": "nigeria_staff",
                    "refund_request_id": None,
                },
            ) as mock_resolution,
            patch.object(service.repo, "update_claim_status", return_value=updated),
            patch("services.claims.service.publish_event"),
            patch("services.claims.service.log_audit"),
        ):
            ctx = _ctx(UserRole.NIGERIA_OFFICE_STAFF)
            service.resolve_claim(TENANT_ID, "claim-001", req, actor_id="u", ctx=ctx)

        mock_resolution.assert_called_once()
        resolution_data = mock_resolution.call_args[0][1]
        assert resolution_data["approval_level"] in (
            "nigeria_staff",
            "staff",
        ), f"Expected staff-level approval, got {resolution_data['approval_level']!r}"

    def test_large_refund_by_admin_records_tenant_admin_approval_level(self):
        """A refund above $50 approved by tenant_admin records approval_level='tenant_admin'."""
        from services.claims import service

        claim = _claim(status="under_inspection")
        updated = _claim(status="resolved")

        req = self._make_req("refund", "100")

        with (
            patch.object(service.repo, "get_damage_claim_by_id", return_value=claim),
            patch.object(service.repo, "get_tenant_config_value", return_value={"staff_limit": 50}),
            patch.object(service, "get_effective_dollar_rate", return_value={"rate": Decimal("1550")}),
            patch.object(service.repo, "create_refund_request_for_claim", return_value={"id": "ref-001"}),
            patch.object(
                service.repo,
                "create_claim_resolution",
                return_value={
                    "id": "res-001",
                    "resolution_type": "refund",
                    "resolution_amount_ngn": None,
                    "approval_level": "tenant_admin",
                    "refund_request_id": None,
                },
            ) as mock_resolution,
            patch.object(service.repo, "update_claim_status", return_value=updated),
            patch("services.claims.service.publish_event"),
            patch("services.claims.service.log_audit"),
        ):
            ctx = _ctx(UserRole.TENANT_ADMIN)
            service.resolve_claim(TENANT_ID, "claim-001", req, actor_id="u", ctx=ctx)

        mock_resolution.assert_called_once()
        resolution_data = mock_resolution.call_args[0][1]
        assert resolution_data["approval_level"] == "tenant_admin", (
            f"Expected tenant_admin approval, got {resolution_data['approval_level']!r}"
        )

    def test_approved_by_field_matches_actor_id(self):
        """The approved_by field in the resolution record must equal the actor_id."""
        from services.claims import service

        claim = _claim(status="under_inspection")
        updated = _claim(status="resolved")

        req = self._make_req("compensation", "30")

        with (
            patch.object(service.repo, "get_damage_claim_by_id", return_value=claim),
            patch.object(service.repo, "get_tenant_config_value", return_value={"staff_limit": 50}),
            patch.object(service, "get_effective_dollar_rate", return_value={"rate": Decimal("1550")}),
            patch.object(service.repo, "create_refund_request_for_claim", return_value={"id": "ref-001"}),
            patch.object(
                service.repo,
                "create_claim_resolution",
                return_value={
                    "id": "res-001",
                    "resolution_type": "compensation",
                    "resolution_amount_ngn": None,
                    "approval_level": "nigeria_staff",
                    "refund_request_id": None,
                },
            ) as mock_resolution,
            patch.object(service.repo, "update_claim_status", return_value=updated),
            patch("services.claims.service.publish_event"),
            patch("services.claims.service.log_audit"),
        ):
            ctx = _ctx(UserRole.NIGERIA_OFFICE_STAFF)
            service.resolve_claim(TENANT_ID, "claim-001", req, actor_id="the-approver", ctx=ctx)

        resolution_data = mock_resolution.call_args[0][1]
        assert resolution_data["approved_by"] == "the-approver"


class TestClaimStateMachine:
    def test_file_claim_creates_with_filed_status(self):
        from services.claims import service

        req = MagicMock()
        req.container_id = "container-001"
        req.cartons_affected = 3
        req.description = "Damage"
        req.customer_id = None

        created = _claim(status="filed")
        customer = {"id": "customer-001"}

        with (
            patch.object(service.repo, "get_customer_by_user_id", return_value=customer),
            patch.object(service.repo, "resolve_container_id", return_value="container-uuid-001"),
            patch.object(service.repo, "customer_has_cargo_in_container", return_value=True),
            patch.object(service.repo, "get_container_status", return_value="at_warehouse"),
            patch.object(service.repo, "get_next_claim_reference", return_value="DC-20260709-001"),
            patch.object(service.repo, "create_damage_claim", return_value=created),
            patch("services.claims.service.log_audit"),
            patch("services.claims.service.publish_event"),
        ):
            ctx = _ctx(UserRole.CUSTOMER, user_id="user-customer")
            result = service.file_claim(TENANT_ID, req, actor_id="user-customer", ctx=ctx)
            assert result["status"] == "filed"

    def test_customer_filing_a_claim_notifies_staff(self):
        """Follow-up to the payment-claim-rejection notification bug — a new
        damage claim previously had no in-app signal for staff at all."""
        from services.claims import service

        req = MagicMock()
        req.container_id = "container-001"
        req.cartons_affected = 3
        req.description = "Damage"
        req.customer_id = None
        created = _claim(status="filed", reference="DC-20260709-001")

        with (
            patch.object(service.repo, "get_customer_by_user_id", return_value={"id": "customer-001"}),
            patch.object(service.repo, "resolve_container_id", return_value="container-uuid-001"),
            patch.object(service.repo, "customer_has_cargo_in_container", return_value=True),
            patch.object(service.repo, "get_container_status", return_value="at_warehouse"),
            patch.object(service.repo, "get_next_claim_reference", return_value="DC-20260709-001"),
            patch.object(service.repo, "create_damage_claim", return_value=created),
            patch("services.claims.service.log_audit"),
            patch("services.claims.service.publish_event"),
            patch("services.claims.service.notify_staff") as mock_notify,
        ):
            ctx = _ctx(UserRole.CUSTOMER, user_id="user-customer")
            service.file_claim(TENANT_ID, req, actor_id="user-customer", ctx=ctx)

        assert mock_notify.call_count == 2
        roles = {c.kwargs["target_role"] for c in mock_notify.call_args_list}
        assert roles == {"nigeria_office_staff", "tenant_admin"}
        assert all(c.kwargs["event_type"] == "damage_claim_filed" for c in mock_notify.call_args_list)

    def test_staff_filing_a_claim_on_a_customers_behalf_does_not_self_notify(self):
        from services.claims import service

        req = MagicMock()
        req.container_id = "container-001"
        req.cartons_affected = 3
        req.description = "Damage"
        created = _claim(status="filed")

        with (
            patch.object(service.repo, "resolve_container_id", return_value="container-uuid-001"),
            patch.object(service.repo, "get_container_status", return_value="at_warehouse"),
            patch.object(service.repo, "get_next_claim_reference", return_value="DC-20260709-001"),
            patch.object(service.repo, "create_damage_claim", return_value=created),
            patch("services.claims.service.log_audit"),
            patch("services.claims.service.publish_event"),
            patch("services.claims.service.notify_staff") as mock_notify,
        ):
            ctx = _ctx(UserRole.NIGERIA_OFFICE_STAFF, user_id="staff-1")
            service.file_claim(
                TENANT_ID,
                req,
                actor_id="staff-1",
                ctx=ctx,
                customer_id_override="customer-001",
            )

        mock_notify.assert_not_called()

    def test_files_by_container_number_not_only_uuid(self):
        """Ground-truth regression: FileDamageClaimRequest.container_id used
        to go straight into a `uuid` column unresolved — a customer typing
        the container number they actually see (never its internal UUID)
        crashed the whole request with InvalidTextRepresentation, despite
        the frontend's own field explicitly promising number support."""
        from services.claims import service

        req = MagicMock()
        req.container_id = "ACME-001"
        req.cartons_affected = []
        req.description = "Damage"

        created = _claim(status="filed")
        customer = {"id": "customer-001"}

        with (
            patch.object(service.repo, "get_customer_by_user_id", return_value=customer),
            patch.object(service.repo, "resolve_container_id", return_value="container-uuid-001") as mock_resolve,
            patch.object(service.repo, "customer_has_cargo_in_container", return_value=True),
            patch.object(service.repo, "get_container_status", return_value="at_warehouse"),
            patch.object(service.repo, "get_next_claim_reference", return_value="DC-20260709-001"),
            patch.object(service.repo, "create_damage_claim", return_value=created) as mock_create,
            patch("services.claims.service.log_audit"),
            patch("services.claims.service.publish_event"),
        ):
            ctx = _ctx(UserRole.CUSTOMER, user_id="user-customer")
            service.file_claim(TENANT_ID, req, actor_id="user-customer", ctx=ctx)

        mock_resolve.assert_called_once_with(TENANT_ID, "ACME-001")
        # The *resolved* container UUID reaches the write, not the raw
        # user-typed reference — this is exactly what crashed before.
        assert mock_create.call_args.args[1]["container_id"] == "container-uuid-001"

    def test_customer_cannot_file_against_a_container_they_have_no_cargo_in(self):
        """Without this check, a customer could file (and staff would then
        investigate) a claim against any container in the tenant by
        guessing or enumerating container numbers."""
        from services.claims import service
        from shared.exceptions import ResourceNotFoundError

        req = MagicMock()
        req.container_id = "ACME-999"
        req.cartons_affected = []
        req.description = "Damage"

        with (
            patch.object(service.repo, "get_customer_by_user_id", return_value={"id": "customer-001"}),
            patch.object(service.repo, "resolve_container_id", return_value="container-uuid-999"),
            patch.object(service.repo, "customer_has_cargo_in_container", return_value=False),
            patch.object(service.repo, "create_damage_claim") as mock_create,
        ):
            ctx = _ctx(UserRole.CUSTOMER, user_id="user-customer")
            with pytest.raises(ResourceNotFoundError):
                service.file_claim(TENANT_ID, req, actor_id="user-customer", ctx=ctx)

        mock_create.assert_not_called()

    @pytest.mark.parametrize("pre_arrival_status", ["loading", "sealed", "in_transit"])
    def test_cannot_file_claim_before_container_arrives(self, pre_arrival_status):
        """Ground-truth gap found live: nothing stopped a claim being filed
        against cargo still loading or at sea — damage/loss can't be
        assessed before the container is even in Nigeria."""
        from services.claims import service
        from shared.exceptions import BusinessRuleViolationError

        req = MagicMock()
        req.container_id = "ACME-001"
        req.cartons_affected = []
        req.description = "Damage"

        with (
            patch.object(service.repo, "get_customer_by_user_id", return_value={"id": "customer-001"}),
            patch.object(service.repo, "resolve_container_id", return_value="container-uuid-001"),
            patch.object(service.repo, "customer_has_cargo_in_container", return_value=True),
            patch.object(service.repo, "get_container_status", return_value=pre_arrival_status),
            patch.object(service.repo, "create_damage_claim") as mock_create,
        ):
            ctx = _ctx(UserRole.CUSTOMER, user_id="user-customer")
            with pytest.raises(BusinessRuleViolationError):
                service.file_claim(TENANT_ID, req, actor_id="user-customer", ctx=ctx)

        mock_create.assert_not_called()

    @pytest.mark.parametrize(
        "arrived_status",
        ["arrived", "customs_clearance", "cleared", "at_warehouse", "fully_released"],
    )
    def test_can_file_claim_once_container_has_arrived(self, arrived_status):
        from services.claims import service

        req = MagicMock()
        req.container_id = "ACME-001"
        req.cartons_affected = []
        req.description = "Damage"

        with (
            patch.object(service.repo, "get_customer_by_user_id", return_value={"id": "customer-001"}),
            patch.object(service.repo, "resolve_container_id", return_value="container-uuid-001"),
            patch.object(service.repo, "customer_has_cargo_in_container", return_value=True),
            patch.object(service.repo, "get_container_status", return_value=arrived_status),
            patch.object(service.repo, "get_next_claim_reference", return_value="DC-20260709-001"),
            patch.object(service.repo, "create_damage_claim", return_value=_claim(status="filed")) as mock_create,
            patch("services.claims.service.log_audit"),
            patch("services.claims.service.publish_event"),
        ):
            ctx = _ctx(UserRole.CUSTOMER, user_id="user-customer")
            service.file_claim(TENANT_ID, req, actor_id="user-customer", ctx=ctx)

        mock_create.assert_called_once()

    def test_unknown_container_reference_raises_not_found_not_a_500(self):
        from services.claims import service
        from shared.exceptions import ResourceNotFoundError

        req = MagicMock()
        req.container_id = "does-not-exist"
        req.cartons_affected = []
        req.description = "Damage"

        with (
            patch.object(service.repo, "get_customer_by_user_id", return_value={"id": "customer-001"}),
            patch.object(service.repo, "resolve_container_id", return_value=None),
            patch.object(service.repo, "create_damage_claim") as mock_create,
        ):
            ctx = _ctx(UserRole.CUSTOMER, user_id="user-customer")
            with pytest.raises(ResourceNotFoundError):
                service.file_claim(TENANT_ID, req, actor_id="user-customer", ctx=ctx)

        mock_create.assert_not_called()

    def test_resolve_from_invalid_state_raises(self):
        from services.claims import service

        claim = _claim(status="filed")  # Cannot resolve from 'filed'
        req = MagicMock()
        req.resolution_type = MagicMock()
        req.resolution_type.value = "compensation"
        req.amount_usd = Decimal("30")

        with patch.object(service.repo, "get_damage_claim_by_id", return_value=claim):
            ctx = _ctx(UserRole.NIGERIA_OFFICE_STAFF)
            with pytest.raises(IllegalTransitionError):
                service.resolve_claim(TENANT_ID, "claim-001", req, actor_id="user-1", ctx=ctx)

    def test_get_claim_not_found_raises(self):
        from services.claims import service

        with patch.object(service.repo, "get_damage_claim_by_id", return_value=None):
            ctx = _ctx(UserRole.NIGERIA_OFFICE_STAFF)
            with pytest.raises(ResourceNotFoundError):
                service.get_claim(TENANT_ID, "nonexistent", ctx)

    def test_customer_cannot_see_others_claim(self):
        from services.claims import service

        claim = _claim(customer_id="customer-999")
        customer = {"id": "customer-001"}

        with (
            patch.object(service.repo, "get_damage_claim_by_id", return_value=claim),
            patch.object(service.repo, "get_customer_by_user_id", return_value=customer),
        ):
            ctx = _ctx(UserRole.CUSTOMER, user_id="user-cust-001")
            # A 404, not a 403: another customer's claim must look the same as one that does not exist.
            with pytest.raises(ResourceNotFoundError):
                service.get_claim(TENANT_ID, "claim-001", ctx)


class TestGetClaimForTheCustomer:
    """GET /v1/claims/{id}: what a customer sees of their own claim (audit UX-07)."""

    CLAIM_ID = "claim-001"
    PREFIX = f"{TENANT_ID}/claims/{CLAIM_ID}/"

    @staticmethod
    def _patches(*, claim=None, customer=None, evidence=(), outcome=None, url="https://files.example/get"):
        from services.claims import service

        storage = MagicMock()
        storage.presigned_get_url.return_value = url
        return (
            patch.object(service.repo, "get_damage_claim_by_id", return_value=claim if claim is not None else _claim()),
            patch.object(service.repo, "get_customer_by_user_id", return_value=customer or {"id": "customer-001"}),
            patch.object(service.repo, "list_claim_evidence", return_value=list(evidence)),
            patch.object(service.repo, "get_claim_outcome", return_value=outcome),
            patch.object(service, "get_storage_provider", return_value=storage),
        ), storage

    def _get(self, role=UserRole.CUSTOMER, **kw):
        from services.claims import service

        patches, storage = self._patches(**kw)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            return service.get_claim(TENANT_ID, self.CLAIM_ID, _ctx(role, user_id="user-cust-001")), storage

    @staticmethod
    def _file(name="photo.jpg", key=None, **kw):
        return {
            "id": "e1",
            "file_key": key or f"{TENANT_ID}/claims/claim-001/{name}",
            "file_name": name,
            "file_type": "image/jpeg",
            "file_size_bytes": 1024,
            "created_at": "2026-11-10T10:00:00Z",
            **kw,
        }

    def test_a_customer_reads_their_own_claim(self):
        result, _ = self._get()
        assert result["id"] == "claim-001"
        assert result["evidence"] == [] and result["resolution"] is None and result["refund"] is None

    def test_a_customer_with_no_customer_record_gets_a_404(self):
        from services.claims import service

        patches, _ = self._patches()
        with (
            patches[0],
            patch.object(service.repo, "get_customer_by_user_id", return_value=None),
            patches[2],
            patches[3],
            patches[4],
        ):
            with pytest.raises(ResourceNotFoundError):
                service.get_claim(TENANT_ID, self.CLAIM_ID, _ctx(UserRole.CUSTOMER))

    def test_another_customers_claim_is_a_404_and_reads_nothing_about_it(self):
        from services.claims import service

        patches, storage = self._patches(claim=_claim(customer_id="customer-999"))
        with (
            patches[0],
            patches[1],
            patch.object(service.repo, "list_claim_evidence") as evidence,
            patch.object(service.repo, "get_claim_outcome") as outcome,
            patches[4],
        ):
            with pytest.raises(ResourceNotFoundError):
                service.get_claim(TENANT_ID, self.CLAIM_ID, _ctx(UserRole.CUSTOMER))
        assert not evidence.called and not outcome.called and not storage.presigned_get_url.called

    @pytest.mark.parametrize("role", [UserRole.NIGERIA_OFFICE_STAFF, UserRole.TENANT_ADMIN])
    def test_staff_read_any_claim(self, role):
        result, _ = self._get(role=role, claim=_claim(customer_id="customer-999"))
        assert result["id"] == "claim-001"

    def test_each_evidence_file_has_a_short_lived_download_link(self):
        result, storage = self._get(evidence=[self._file("photo.jpg"), self._file("video.mp4", id="e2")])
        assert [f["file_name"] for f in result["evidence"]] == ["photo.jpg", "video.mp4"]
        assert all(f["download_url"] == "https://files.example/get" for f in result["evidence"])
        keys = [call.args[0] for call in storage.presigned_get_url.call_args_list]
        assert keys == [f"{self.PREFIX}photo.jpg", f"{self.PREFIX}video.mp4"]
        assert all(call.kwargs["expires_in"] == 300 for call in storage.presigned_get_url.call_args_list)

    @pytest.mark.parametrize(
        "key",
        [
            "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb/claims/claim-001/photo.jpg",  # another tenant
            f"{TENANT_ID}/claims/claim-002/photo.jpg",  # another claim of this tenant
            f"{TENANT_ID}/exports/2026-11-10/secret.xlsx",  # not claim evidence at all
            f"{TENANT_ID}/claims/claim-001/../../other/x",  # starts with the prefix, then climbs out of it
            f"{TENANT_ID}/claims/claim-001/sub/photo.jpg",  # an upload is one flat filename
            f"{TENANT_ID}/claims/claim-001/",  # no filename
        ],
    )
    def test_a_key_outside_the_claims_own_prefix_never_becomes_a_link(self, key):
        result, storage = self._get(evidence=[self._file(key=key)])
        assert result["evidence"] == []
        assert not storage.presigned_get_url.called

    def test_a_file_whose_link_cannot_be_made_is_still_listed(self):
        from services.claims import service

        patches, storage = self._patches(evidence=[self._file()])
        storage.presigned_get_url.side_effect = RuntimeError("no storage configured")
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = service.get_claim(TENANT_ID, self.CLAIM_ID, _ctx(UserRole.CUSTOMER))
        assert result["evidence"][0]["file_name"] == "photo.jpg" and result["evidence"][0]["download_url"] is None

    def test_the_outcome_is_the_decision_and_the_refund_status(self):
        outcome = {
            "resolution_type": "refund",
            "resolution_amount_ngn": Decimal("25000.00"),
            "discount_percentage": None,
            "resolved_at": "2026-11-12T09:00:00Z",
            "refund_id": "r1",
            "refund_status": "pending_review",
            "refund_amount_ngn": Decimal("25000.00"),
        }
        result, _ = self._get(outcome=outcome)
        assert result["resolution"] == {
            "resolution_type": "refund",
            "amount_ngn": Decimal("25000.00"),
            "discount_percentage": None,
            "resolved_at": "2026-11-12T09:00:00Z",
        }
        assert result["refund"] == {"id": "r1", "status": "pending_review", "amount_ngn": Decimal("25000.00")}

    def test_a_resolution_with_no_refund_has_none(self):
        outcome = {
            "resolution_type": "no_action",
            "resolution_amount_ngn": None,
            "discount_percentage": None,
            "resolved_at": "x",
            "refund_id": None,
        }
        result, _ = self._get(outcome=outcome)
        assert result["resolution"]["resolution_type"] == "no_action" and result["refund"] is None

    def test_staffs_internal_record_of_the_decision_is_never_in_the_response(self):
        outcome = {
            "resolution_type": "refund",
            "resolution_amount_ngn": Decimal("1"),
            "discount_percentage": None,
            "resolved_at": "x",
            "refund_id": None,
            # what a careless query could hand through:
            "notes": "customer is a repeat claimant, be careful",
            "approval_level": "admin",
            "approved_by": "staff-uuid",
        }
        result, _ = self._get(outcome=outcome)
        flat = str(result)
        assert (
            "repeat claimant" not in flat
            and "approved_by" not in flat
            and "approval_level" not in flat
            and "staff-uuid" not in flat
        )

    def test_the_response_carries_no_uploader_or_storage_key(self):
        result, _ = self._get(evidence=[self._file(uploaded_by="staff-uuid")])
        assert "uploaded_by" not in result["evidence"][0] and "file_key" not in result["evidence"][0]


class TestClaimReadSql:
    @staticmethod
    def _sql(fn, *args):
        from services.claims import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            getattr(repository, fn)(*args)
        scope, query, params = mock_exec.call_args[0]
        return scope, " ".join(query.split()), params

    def test_the_claim_read_is_tenant_scoped_through_every_join(self):
        scope, query, params = self._sql("get_damage_claim_by_id", TENANT_ID, "claim-001")
        assert scope == TENANT_ID and params == (TENANT_ID, "claim-001")
        assert "dc.tenant_id = %s" in query
        assert "cu.tenant_id = dc.tenant_id" in query and "c.tenant_id = dc.tenant_id" in query

    def test_the_outcome_query_is_tenant_scoped_and_selects_no_internal_columns(self):
        scope, query, params = self._sql("get_claim_outcome", TENANT_ID, "claim-001")
        assert scope == TENANT_ID and params == (TENANT_ID, "claim-001")
        assert "cr.tenant_id = %s" in query and "rr.tenant_id = cr.tenant_id" in query
        select_list = query.split("FROM")[0]
        assert "notes" not in select_list and "approved_by" not in select_list and "approval_level" not in select_list

    def test_the_evidence_query_selects_the_claim_by_bound_id_and_no_uploader(self):
        from shared.tenant_context import PLATFORM_TENANT_ID

        scope, query, params = self._sql("list_claim_evidence", "claim-001")
        assert scope == PLATFORM_TENANT_ID  # claim_evidence has no RLS; the service checks the claim's tenant first
        assert params == ("claim-001",) and "damage_claim_id = %s" in query
        assert "uploaded_by" not in query.split("FROM")[0]


# ---------------------------------------------------------------------------
# Missing item compensation link
# ---------------------------------------------------------------------------


def _missing_item(**kwargs) -> dict:
    base = {
        "id": "missing-001",
        "tenant_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "customer_id": "customer-001",
        "manifest_id": "manifest-001",
        "description": "Lost carton",
        "status": "investigating",
        "carton_tag": "TAG-001",
        "tracking_code": None,
        "notes": None,
        "resolved_at": None,
        "created_at": None,
        "updated_at": None,
    }
    base.update(kwargs)
    return base


def _seized_item(**kwargs) -> dict:
    base = {
        "id": "seized-001",
        "tenant_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "customer_id": "customer-001",
        "container_id": "container-001",
        "description": "Seized by customs",
        "recovery_status": "seized",
        "carton_tag": "TAG-002",
        "tracking_code": None,
        "seizure_date": None,
        "recovery_date": None,
        "notes": None,
        "created_at": None,
        "updated_at": None,
    }
    base.update(kwargs)
    return base


TENANT_ID_C = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


class TestMissingItemCompensation:
    def test_confirmed_lost_with_amount_creates_refund_and_links(self):
        from decimal import Decimal

        from services.claims import service

        item = _missing_item()
        updated = {**item, "status": "confirmed_lost"}
        refund_row = {"id": "refund-new-001"}
        linked = {**updated, "refund_request_id": "refund-new-001"}

        with (
            patch.object(service.repo, "get_missing_item_by_id", return_value=item),
            patch.object(service.repo, "update_missing_item_status", return_value=updated),
            patch.object(service.refund_repo, "create_refund_request", return_value=refund_row),
            patch.object(service.repo, "link_refund_to_missing_item", return_value=linked),
        ):
            result = service.update_missing_item(
                TENANT_ID_C,
                "missing-001",
                "confirmed_lost",
                notes=None,
                actor_id="u",
                ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF),
                refund_amount_ngn=Decimal("10000"),
            )
            assert result["refund_request_id"] == "refund-new-001"

    def test_confirmed_lost_without_amount_skips_refund(self):
        from services.claims import service

        item = _missing_item()
        updated = {**item, "status": "confirmed_lost"}

        with (
            patch.object(service.repo, "get_missing_item_by_id", return_value=item),
            patch.object(service.repo, "update_missing_item_status", return_value=updated),
            patch.object(service.refund_repo, "create_refund_request") as mock_create,
        ):
            service.update_missing_item(
                TENANT_ID_C,
                "missing-001",
                "confirmed_lost",
                notes=None,
                actor_id="u",
                ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF),
            )
            mock_create.assert_not_called()

    def test_other_status_with_amount_skips_refund(self):
        """refund_amount_ngn is ignored for statuses other than 'confirmed_lost'."""
        from decimal import Decimal

        from services.claims import service

        item = _missing_item()
        updated = {**item, "status": "investigating"}

        with (
            patch.object(service.repo, "get_missing_item_by_id", return_value=item),
            patch.object(service.repo, "update_missing_item_status", return_value=updated),
            patch.object(service.refund_repo, "create_refund_request") as mock_create,
        ):
            service.update_missing_item(
                TENANT_ID_C,
                "missing-001",
                "investigating",
                notes=None,
                actor_id="u",
                ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF),
                refund_amount_ngn=Decimal("5000"),
            )
            mock_create.assert_not_called()

    def test_missing_item_not_found_raises(self):
        from services.claims import service
        from shared.exceptions import ResourceNotFoundError

        with patch.object(service.repo, "get_missing_item_by_id", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.update_missing_item(
                    TENANT_ID_C,
                    "nonexistent",
                    "confirmed_lost",
                    notes=None,
                    actor_id="u",
                    ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF),
                )


class TestChinaOfficeAndMissingItems:
    """The China office records the supply and loading check on a missing item, and nothing financial (audit UX-08)."""

    @staticmethod
    def _update(role, status, *, amount=None, current="reported"):
        from services.claims import service

        item = _missing_item(status=current)
        with (
            patch.object(service.repo, "get_missing_item_by_id", return_value=item),
            patch.object(service.repo, "update_missing_item_status", return_value={**item, "status": status}) as update,
            patch.object(service.refund_repo, "create_refund_request") as refund,
            patch("services.claims.service.log_audit"),
        ):
            result = service.update_missing_item(
                TENANT_ID_C,
                "missing-001",
                status,
                notes="Loaded 12 cartons; 3 not on the dock",
                actor_id="u",
                ctx=_ctx(role),
                refund_amount_ngn=amount,
            )
        return result, update, refund

    @pytest.mark.parametrize("status", ["investigating", "found_and_shipping"])
    def test_china_can_record_an_investigation_result_with_notes(self, status):
        result, update, refund = self._update(UserRole.CHINA_OFFICE_STAFF, status)
        assert result["status"] == status
        assert update.call_args.kwargs["notes"] == "Loaded 12 cartons; 3 not on the dock"
        assert not refund.called

    def test_china_cannot_set_a_refund_amount(self):
        from decimal import Decimal

        from services.claims import service

        with pytest.raises(InsufficientPermissionsError):
            self._update(UserRole.CHINA_OFFICE_STAFF, "investigating", amount=Decimal("5000"))
        with pytest.raises(InsufficientPermissionsError):
            self._update(UserRole.CHINA_OFFICE_STAFF, "confirmed_lost", amount=Decimal("5000"))
        assert service  # imported for the patch targets above

    @pytest.mark.parametrize("status", ["confirmed_lost", "resolved", "reported"])
    def test_china_cannot_decide_a_missing_item(self, status):
        with pytest.raises(InsufficientPermissionsError):
            self._update(UserRole.CHINA_OFFICE_STAFF, status)

    @pytest.mark.parametrize("current", ["confirmed_lost", "resolved"])
    def test_china_cannot_reopen_an_item_that_has_been_decided(self, current):
        from shared.exceptions import BusinessRuleViolationError

        with pytest.raises(BusinessRuleViolationError) as caught:
            self._update(UserRole.CHINA_OFFICE_STAFF, "investigating", current=current)
        assert caught.value.rule_id == "MISSING_ITEM_ALREADY_DECIDED"

    def test_a_refused_china_update_changes_nothing(self):
        from services.claims import service

        with (
            patch.object(service.repo, "get_missing_item_by_id", return_value=_missing_item()),
            patch.object(service.repo, "update_missing_item_status") as update,
            patch.object(service.refund_repo, "create_refund_request") as refund,
            patch("services.claims.service.log_audit") as audit,
        ):
            with pytest.raises(InsufficientPermissionsError):
                service.update_missing_item(
                    TENANT_ID_C, "missing-001", "confirmed_lost", None, actor_id="u", ctx=_ctx(UserRole.CHINA_OFFICE_STAFF)
                )
        assert not update.called and not refund.called and not audit.called

    def test_nigeria_staff_keep_every_status_and_compensation(self):
        from decimal import Decimal

        from services.claims import service

        item = _missing_item()
        with (
            patch.object(service.repo, "get_missing_item_by_id", return_value=item),
            patch.object(service.repo, "update_missing_item_status", return_value={**item, "status": "confirmed_lost"}),
            patch.object(service.refund_repo, "create_refund_request", return_value={"id": "r1"}),
            patch.object(
                service.repo,
                "link_refund_to_missing_item",
                return_value={**item, "status": "confirmed_lost", "refund_request_id": "r1"},
            ),
            patch("services.claims.service.log_audit"),
        ):
            result = service.update_missing_item(
                TENANT_ID_C,
                "missing-001",
                "confirmed_lost",
                None,
                actor_id="u",
                ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF),
                refund_amount_ngn=Decimal("10000"),
            )
        assert result["refund_request_id"] == "r1"

    def test_logging_a_missing_item_tells_the_china_office_in_app(self):
        from services.claims import service

        req = MagicMock(
            manifest_id="manifest-1", customer_id="customer-001", carton_tags=["T1", "T2"], description="Never arrived"
        )
        with (
            patch.object(service.repo, "create_missing_item", return_value=_missing_item()),
            patch("services.claims.service.log_audit"),
            patch("services.claims.service.notify_staff") as notify,
        ):
            service.log_missing_item(TENANT_ID_C, req, actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF))
        notify.assert_called_once()
        kwargs = notify.call_args.kwargs
        assert kwargs["target_role"] == "china_office_staff"
        assert (kwargs["event_type"], kwargs["entity_type"]) == ("missing_item_logged", "missing_item")
        assert "2 carton(s)" in kwargs["body"]
        assert "Never arrived" not in str(kwargs) and "customer-001" not in str(kwargs)  # no customer detail in the bell


class TestChinaOfficeMissingItemRoutes:
    """Who may call which missing-item route."""

    @staticmethod
    def _call(role, method, path, body=None):
        from services.claims import handler, service

        event = {
            "requestContext": {
                "requestId": "r1",
                "http": {"method": method, "path": path},
                "authorizer": {"claims": {"sub": "user-1", "custom:tenant_id": TENANT_ID}},
                "identity": {"sourceIp": "127.0.0.1"},
            },
            "headers": {},
            "body": json.dumps(body) if body is not None else None,
            "queryStringParameters": {},
            "pathParameters": {},
        }
        with (
            patch("services.claims.handler.get_tenant_context", return_value=_ctx(role)),
            patch.object(service, "list_missing_items", return_value=([], None, False)),
            patch.object(service, "get_missing_item", return_value={"id": "i1"}),
            patch.object(service, "update_missing_item", return_value={"id": "i1"}) as update,
            patch.object(service, "log_missing_item", return_value={"id": "i1"}) as log,
            patch.object(service, "list_seized_items", return_value=([], None, False)),
        ):
            return handler.lambda_handler(event, None), update, log

    def test_china_can_list_and_open_missing_items(self):
        assert self._call(UserRole.CHINA_OFFICE_STAFF, "GET", "/v1/claims/missing-items")[0]["statusCode"] == 200
        assert self._call(UserRole.CHINA_OFFICE_STAFF, "GET", "/v1/claims/missing-items/i1")[0]["statusCode"] == 200

    def test_china_can_update_one(self):
        response, update, _ = self._call(
            UserRole.CHINA_OFFICE_STAFF, "PATCH", "/v1/claims/missing-items/i1", {"status": "investigating"}
        )
        assert response["statusCode"] == 200 and update.called

    def test_a_refund_amount_from_china_reaches_the_service_to_be_refused(self):
        _, update, _ = self._call(
            UserRole.CHINA_OFFICE_STAFF,
            "PATCH",
            "/v1/claims/missing-items/i1",
            {"status": "investigating", "refund_amount_ngn": "100"},
        )
        assert update.call_args.kwargs["refund_amount_ngn"] is not None  # the service, not the route, enforces the limit

    def test_china_cannot_log_a_missing_item(self):
        response, _, log = self._call(
            UserRole.CHINA_OFFICE_STAFF,
            "POST",
            "/v1/claims/missing-items",
            {
                "manifest_id": "11111111-1111-1111-1111-111111111111",
                "customer_id": "22222222-2222-2222-2222-222222222222",
                "carton_tags": ["T1"],
                "description": "x",
            },
        )
        assert response["statusCode"] == 403 and not log.called

    def test_china_still_cannot_read_seized_items(self):
        assert self._call(UserRole.CHINA_OFFICE_STAFF, "GET", "/v1/claims/seized-items")[0]["statusCode"] == 403

    @pytest.mark.parametrize("role", [UserRole.WAREHOUSE_ATTENDANT, UserRole.CUSTOMER])
    def test_others_are_still_refused(self, role):
        assert self._call(role, "GET", "/v1/claims/missing-items")[0]["statusCode"] == 403
        assert self._call(role, "PATCH", "/v1/claims/missing-items/i1", {"status": "investigating"})[0]["statusCode"] == 403


class TestSeizedItemCompensation:
    def test_permanently_lost_with_amount_creates_refund_and_links(self):
        from decimal import Decimal

        from services.claims import service

        item = _seized_item()
        updated = {**item, "recovery_status": "permanently_lost"}
        refund_row = {"id": "refund-sz-001"}
        linked = {**updated, "refund_request_id": "refund-sz-001"}

        with (
            patch.object(service.repo, "get_seized_item_by_id", return_value=item),
            patch.object(service.repo, "update_seized_item_status", return_value=updated),
            patch.object(service.refund_repo, "create_refund_request", return_value=refund_row),
            patch.object(service.repo, "link_refund_to_seized_item", return_value=linked),
        ):
            result = service.update_seized_item(
                TENANT_ID_C,
                "seized-001",
                "permanently_lost",
                notes=None,
                actor_id="u",
                ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF),
                refund_amount_ngn=Decimal("20000"),
            )
            assert result["refund_request_id"] == "refund-sz-001"

    @pytest.mark.parametrize("status", ["recovered", "recovery_in_progress"])
    def test_other_statuses_with_an_amount_open_no_refund(self, status):
        """Compensation is owed when goods are permanently lost, not when they are recovered."""
        from decimal import Decimal

        from services.claims import service

        item = _seized_item()
        with (
            patch.object(service.repo, "get_seized_item_by_id", return_value=item),
            patch.object(service.repo, "update_seized_item_status", return_value={**item, "recovery_status": status}),
            patch.object(service.refund_repo, "create_refund_request") as mock_create,
        ):
            service.update_seized_item(
                TENANT_ID_C,
                "seized-001",
                status,
                notes=None,
                actor_id="u",
                ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF),
                refund_amount_ngn=Decimal("20000"),
            )
        mock_create.assert_not_called()

    def test_seized_status_with_amount_skips_refund(self):
        """Status 'seized' (no resolution yet) must not trigger a refund."""
        from decimal import Decimal

        from services.claims import service

        item = _seized_item()
        updated = {**item, "recovery_status": "under_review"}

        with (
            patch.object(service.repo, "get_seized_item_by_id", return_value=item),
            patch.object(service.repo, "update_seized_item_status", return_value=updated),
            patch.object(service.refund_repo, "create_refund_request") as mock_create,
        ):
            service.update_seized_item(
                TENANT_ID_C,
                "seized-001",
                "under_review",
                notes=None,
                actor_id="u",
                ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF),
                refund_amount_ngn=Decimal("5000"),
            )
            mock_create.assert_not_called()

    def test_seized_item_not_found_raises(self):
        from services.claims import service
        from shared.exceptions import ResourceNotFoundError

        with patch.object(service.repo, "get_seized_item_by_id", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.update_seized_item(
                    TENANT_ID_C, "nonexistent", "recovered", notes=None, actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
                )


class TestMissingSeizedItemAuditLogging:
    """Ground-truth gap found while auditing log coverage across services:
    log_missing_item/update_missing_item/log_seized_item/update_seized_item
    (all money-or-goods-affecting) had no log_audit call at all — a tenant
    admin's activity view had zero trail for a reported/seized item ever
    being created or resolved, or for the refund it can trigger."""

    def test_log_missing_item_writes_audit_entry(self):
        from services.claims import service

        req = MagicMock()
        req.manifest_id = "manifest-1"
        req.customer_id = "customer-001"
        req.carton_tags = ["TAG-1"]
        req.description = "Never arrived"

        with (
            patch.object(service.repo, "create_missing_item", return_value=_missing_item()),
            patch("services.claims.service.log_audit") as mock_audit,
            patch("services.claims.service.notify_staff"),
        ):
            service.log_missing_item(TENANT_ID_C, req, actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF))

        assert mock_audit.call_args.kwargs["entity_type"] == "missing_item"
        assert mock_audit.call_args.kwargs["action"] == "CREATE"

    def test_update_missing_item_writes_audit_entry(self):
        from services.claims import service

        item = _missing_item()
        updated = {**item, "status": "investigating"}
        with (
            patch.object(service.repo, "get_missing_item_by_id", return_value=item),
            patch.object(service.repo, "update_missing_item_status", return_value=updated),
            patch("services.claims.service.log_audit") as mock_audit,
        ):
            service.update_missing_item(
                TENANT_ID_C,
                "missing-001",
                "investigating",
                notes=None,
                actor_id="u",
                ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF),
            )

        assert mock_audit.call_args.kwargs["entity_type"] == "missing_item"
        assert mock_audit.call_args.kwargs["action"] == "UPDATE"

    def test_compensation_refund_from_missing_item_is_audited(self):
        from decimal import Decimal

        from services.claims import service

        item = _missing_item()
        updated = {**item, "status": "confirmed_lost"}
        with (
            patch.object(service.repo, "get_missing_item_by_id", return_value=item),
            patch.object(service.repo, "update_missing_item_status", return_value=updated),
            patch.object(service.refund_repo, "create_refund_request", return_value={"id": "refund-new-001"}),
            patch.object(service.repo, "link_refund_to_missing_item", return_value=None),
            patch("services.claims.service.log_audit") as mock_audit,
        ):
            service.update_missing_item(
                TENANT_ID_C,
                "missing-001",
                "confirmed_lost",
                notes=None,
                actor_id="u",
                ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF),
                refund_amount_ngn=Decimal("10000"),
            )

        refund_calls = [c for c in mock_audit.call_args_list if c.kwargs["entity_type"] == "refund_request"]
        assert len(refund_calls) == 1
        assert refund_calls[0].kwargs["entity_id"] == "refund-new-001"

    def test_log_seized_item_writes_audit_entry(self):
        from services.claims import service

        req = MagicMock()
        req.container_id = "container-1"
        req.customer_id = "customer-001"
        req.carton_tags = ["TAG-2"]
        req.reason = "Seized by customs"

        with (
            patch.object(service.repo, "create_seized_item", return_value=_seized_item()),
            patch("services.claims.service.log_audit") as mock_audit,
        ):
            service.log_seized_item(TENANT_ID_C, req, actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF))

        assert mock_audit.call_args.kwargs["entity_type"] == "seized_item"
        assert mock_audit.call_args.kwargs["action"] == "CREATE"

    def test_compensation_refund_from_seized_item_is_audited(self):
        from decimal import Decimal

        from services.claims import service

        item = _seized_item()
        updated = {**item, "recovery_status": "permanently_lost"}
        with (
            patch.object(service.repo, "get_seized_item_by_id", return_value=item),
            patch.object(service.repo, "update_seized_item_status", return_value=updated),
            patch.object(service.refund_repo, "create_refund_request", return_value={"id": "refund-sz-001"}),
            patch.object(service.repo, "link_refund_to_seized_item", return_value=None),
            patch("services.claims.service.log_audit") as mock_audit,
        ):
            service.update_seized_item(
                TENANT_ID_C,
                "seized-001",
                "permanently_lost",
                notes=None,
                actor_id="u",
                ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF),
                refund_amount_ngn=Decimal("20000"),
            )

        refund_calls = [c for c in mock_audit.call_args_list if c.kwargs["entity_type"] == "refund_request"]
        assert len(refund_calls) == 1
        assert refund_calls[0].kwargs["entity_id"] == "refund-sz-001"


# ---------------------------------------------------------------------------
# GET /v1/claims — customer_id filter (audit gap A2: admin Customer Profile
# Claims tab). Handler passes the query param through for staff; for the
# customer role the service always overwrites it with the caller's own record.
# ---------------------------------------------------------------------------


class TestListClaimsCustomerFilter:
    def _event(self, query: dict | None = None) -> dict:
        return {
            "requestContext": {
                "requestId": "req-claims-001",
                "http": {"method": "GET", "path": "/v1/claims"},
                "authorizer": {"claims": {"sub": "user-1", "custom:tenant_id": TENANT_ID}},
                "identity": {"sourceIp": "127.0.0.1"},
            },
            "headers": {},
            "body": "{}",
            "queryStringParameters": query or {},
            "pathParameters": {},
        }

    def test_staff_customer_id_param_reaches_the_repo_filter(self):
        from services.claims import handler, service

        with (
            patch("services.claims.handler.get_tenant_context", return_value=_ctx(UserRole.TENANT_ADMIN)),
            patch.object(service.repo, "list_damage_claims", return_value=([], None, False)) as mock_list,
        ):
            resp = handler.lambda_handler(self._event({"customer_id": "customer-001"}), None)

        assert resp["statusCode"] == 200
        filters = mock_list.call_args[0][1]
        assert filters["customer_id"] == "customer-001"

    def test_customer_role_cannot_widen_scope_with_customer_id_param(self):
        from services.claims import handler, service

        with (
            patch("services.claims.handler.get_tenant_context", return_value=_ctx(UserRole.CUSTOMER, "cust-user-9")),
            patch.object(service.repo, "get_customer_by_user_id", return_value={"id": "customer-own"}),
            patch.object(service.repo, "list_damage_claims", return_value=([], None, False)) as mock_list,
        ):
            resp = handler.lambda_handler(self._event({"customer_id": "customer-somebody-else"}), None)

        assert resp["statusCode"] == 200
        filters = mock_list.call_args[0][1]
        # Service overwrote the caller-supplied value with their own record.
        assert filters["customer_id"] == "customer-own"


# ---------------------------------------------------------------------------
# GET /v1/claims — sort param (ClaimList's 'Claim ID'/'Filed' sortable columns)
# ---------------------------------------------------------------------------


class TestListClaimsSort:
    def _event(self, query: dict | None = None) -> dict:
        return {
            "requestContext": {
                "requestId": "req-claims-sort-001",
                "http": {"method": "GET", "path": "/v1/claims"},
                "authorizer": {"claims": {"sub": "user-1", "custom:tenant_id": TENANT_ID}},
                "identity": {"sourceIp": "127.0.0.1"},
            },
            "headers": {},
            "body": "{}",
            "queryStringParameters": query or {},
            "pathParameters": {},
        }

    def test_sort_and_direction_query_params_reach_the_repo(self):
        from services.claims import handler, service

        with (
            patch("services.claims.handler.get_tenant_context", return_value=_ctx(UserRole.TENANT_ADMIN)),
            patch.object(service.repo, "list_damage_claims", return_value=([], None, False)) as mock_list,
        ):
            resp = handler.lambda_handler(self._event({"sort": "reference", "direction": "asc"}), None)

        assert resp["statusCode"] == 200
        assert mock_list.call_args.kwargs["sort_field"] == "reference"
        assert mock_list.call_args.kwargs["sort_direction"] == "asc"

    def test_defaults_to_created_at_desc_when_no_sort_param(self):
        from services.claims import handler, service

        with (
            patch("services.claims.handler.get_tenant_context", return_value=_ctx(UserRole.TENANT_ADMIN)),
            patch.object(service.repo, "list_damage_claims", return_value=([], None, False)) as mock_list,
        ):
            resp = handler.lambda_handler(self._event(), None)

        assert resp["statusCode"] == 200
        assert mock_list.call_args.kwargs["sort_field"] == "created_at"
        assert mock_list.call_args.kwargs["sort_direction"] == "desc"


class TestListClaimsDateRange:
    """GET /v1/claims — `created_after`/`created_before`, added alongside the
    same fix for GET /v1/billing (row 7.63) after the user asked to check
    every page whose "calendar" filter button was actually dead UI."""

    def _event(self, query: dict | None = None) -> dict:
        return {
            "requestContext": {
                "requestId": "req-claims-daterange-001",
                "http": {"method": "GET", "path": "/v1/claims"},
                "authorizer": {"claims": {"sub": "user-1", "custom:tenant_id": TENANT_ID}},
                "identity": {"sourceIp": "127.0.0.1"},
            },
            "headers": {},
            "body": "{}",
            "queryStringParameters": query or {},
            "pathParameters": {},
        }

    def test_created_after_and_before_reach_the_repo_filter(self):
        from services.claims import handler, service

        with (
            patch("services.claims.handler.get_tenant_context", return_value=_ctx(UserRole.TENANT_ADMIN)),
            patch.object(service.repo, "list_damage_claims", return_value=([], None, False)) as mock_list,
        ):
            resp = handler.lambda_handler(
                self._event({"created_after": "2026-09-01", "created_before": "2026-09-07"}),
                None,
            )

        assert resp["statusCode"] == 200
        filters = mock_list.call_args.args[1]
        assert filters["created_after"] == "2026-09-01"
        assert filters["created_before"] == "2026-09-07"

    def test_repository_filters_on_created_at(self):
        from services.claims import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            repository.list_damage_claims(
                TENANT_ID,
                {"created_after": "2026-09-01", "created_before": "2026-09-07"},
                limit=50,
                cursor=None,
            )

        query, params = mock_exec.call_args[0][1], mock_exec.call_args[0][2]
        assert "dc.created_at >= %(created_after)s" in query
        assert "dc.created_at <= %(created_before)s" in query
        assert params["created_after"] == "2026-09-01"
        assert params["created_before"] == "2026-09-07"


class TestListDamageClaimsRepositorySort:
    """services/claims/repository.py::list_damage_claims — sort_field is prefixed
    with the `dc.` table alias (query sorts against the aliased `damage_claim dc`
    table directly)."""

    def test_sorts_by_reference_for_the_claim_id_column(self):
        from services.claims import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            repository.list_damage_claims(
                TENANT_ID,
                {},
                limit=50,
                cursor=None,
                sort_field="reference",
                sort_direction="asc",
            )

        query = mock_exec.call_args[0][1]
        assert "ORDER BY dc.reference ASC" in query

    def test_default_sort_is_created_at_desc(self):
        from services.claims import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            repository.list_damage_claims(TENANT_ID, {}, limit=50, cursor=None)

        query = mock_exec.call_args[0][1]
        assert "ORDER BY dc.created_at DESC" in query


class TestClaimStatusChangeNotifications:
    """Ground-truth gap found live, reported by the user while investigating
    a separate missing notification on payment-claim rejection — asked to
    check every notification in the app. A damage claim's status transitions
    (start_inspection, resolve) had no customer-facing notification at all."""

    _CONTACT = {
        "id": "customer-001",
        "name": "Ngozi",
        "phone": "+2348012345678",
        "email": "n@x.com",
        "whatsapp": None,
        "locale": "en",
    }

    def test_start_inspection_notifies_the_customer(self):
        from services.claims import service

        claim = _claim(status="filed")
        updated = _claim(status="under_inspection", reference="DC-20260909-001")
        req = MagicMock()
        req.inspection_method = MagicMock()
        req.inspection_method.value = "delegate_visit"

        with (
            patch.object(service.repo, "get_damage_claim_by_id", return_value=claim),
            patch.object(service.repo, "update_claim_status", return_value=updated),
            patch.object(service.repo, "get_customer_contact", return_value=self._CONTACT) as mock_contact,
            patch("services.claims.service.log_audit"),
            patch("services.claims.service.enqueue_notifications") as mock_notify,
        ):
            service.start_inspection(TENANT_ID, "claim-001", req, actor_id="staff-1")

        mock_contact.assert_called_once_with(TENANT_ID, "customer-001")
        mock_notify.assert_called_once()
        assert mock_notify.call_args.kwargs["event_type"] == "damage_claim_update"
        assert mock_notify.call_args.kwargs["template_data"]["status"] == "under_inspection"
        assert mock_notify.call_args.kwargs["template_data"]["claim_reference"] == "DC-20260909-001"

    def test_start_inspection_also_notifies_the_customer_in_app_when_they_have_a_portal_account(self):
        """Ground-truth follow-up, reported live by the user: SMS/WhatsApp/
        email can each fail for reasons entirely outside this app, and the
        customer portal itself showed nothing until they happened to open
        the specific claim page."""
        from services.claims import service

        claim = _claim(status="filed")
        updated = _claim(status="under_inspection", reference="DC-20260909-001")
        req = MagicMock()
        req.inspection_method = MagicMock()
        req.inspection_method.value = "delegate_visit"
        contact = {**self._CONTACT, "user_id": "portal-user-001"}

        with (
            patch.object(service.repo, "get_damage_claim_by_id", return_value=claim),
            patch.object(service.repo, "update_claim_status", return_value=updated),
            patch.object(service.repo, "get_customer_contact", return_value=contact),
            patch("services.claims.service.log_audit"),
            patch("services.claims.service.enqueue_notifications"),
            patch("services.claims.service.notify_staff") as mock_notify_staff,
        ):
            service.start_inspection(TENANT_ID, "claim-001", req, actor_id="staff-1")

        mock_notify_staff.assert_called_once()
        assert mock_notify_staff.call_args.kwargs["target_user_id"] == "portal-user-001"
        assert mock_notify_staff.call_args.kwargs["event_type"] == "damage_claim_update"

    def test_no_in_app_notification_for_a_customer_with_no_portal_account(self):
        from services.claims import service

        claim = _claim(status="filed")
        updated = _claim(status="under_inspection")
        req = MagicMock()
        req.inspection_method = MagicMock()
        req.inspection_method.value = "delegate_visit"

        with (
            patch.object(service.repo, "get_damage_claim_by_id", return_value=claim),
            patch.object(service.repo, "update_claim_status", return_value=updated),
            patch.object(service.repo, "get_customer_contact", return_value=self._CONTACT),
            patch("services.claims.service.log_audit"),
            patch("services.claims.service.enqueue_notifications"),
            patch("services.claims.service.notify_staff") as mock_notify_staff,
        ):
            service.start_inspection(TENANT_ID, "claim-001", req, actor_id="staff-1")

        mock_notify_staff.assert_not_called()

    def test_a_notification_failure_does_not_fail_start_inspection(self):
        from services.claims import service

        claim = _claim(status="filed")
        updated = _claim(status="under_inspection")
        req = MagicMock()
        req.inspection_method = MagicMock()
        req.inspection_method.value = "delegate_visit"

        with (
            patch.object(service.repo, "get_damage_claim_by_id", return_value=claim),
            patch.object(service.repo, "update_claim_status", return_value=updated),
            patch.object(service.repo, "get_customer_contact", side_effect=RuntimeError("db down")),
            patch("services.claims.service.log_audit"),
        ):
            result = service.start_inspection(TENANT_ID, "claim-001", req, actor_id="staff-1")

        assert result["status"] == "under_inspection"

    def test_resolve_claim_old_style_notifies_the_customer(self):
        from services.claims import service

        claim = _claim(status="under_inspection")
        updated = _claim(status="resolved", reference="DC-20260909-001")
        req = MagicMock()
        req.resolution_type = MagicMock()
        req.resolution_type.value = "refund"
        req.amount_usd = Decimal("30")
        req.amount_ngn = Decimal("46500")
        req.reason = "Approved"
        req.discount_percentage = None

        with (
            patch.object(service.repo, "get_damage_claim_by_id", return_value=claim),
            patch.object(service.repo, "get_tenant_config_value", return_value={"staff_limit": 50}),
            patch.object(service, "get_effective_dollar_rate", return_value={"rate": Decimal("1550")}),
            patch.object(service.repo, "create_refund_request_for_claim", return_value={"id": "ref-001"}),
            patch.object(
                service.repo,
                "create_claim_resolution",
                return_value={
                    "id": "res-001",
                    "resolution_type": "refund",
                    "resolution_amount_ngn": None,
                    "approval_level": "nigeria_staff",
                    "refund_request_id": None,
                },
            ),
            patch.object(service.repo, "update_claim_status", return_value=updated),
            patch.object(service.repo, "get_customer_contact", return_value=self._CONTACT) as mock_contact,
            patch("services.claims.service.publish_event"),
            patch("services.claims.service.log_audit"),
            patch("services.claims.service.enqueue_notifications") as mock_notify,
        ):
            ctx = _ctx(UserRole.NIGERIA_OFFICE_STAFF)
            service.resolve_claim(TENANT_ID, "claim-001", req, actor_id="user-1", ctx=ctx)

        mock_contact.assert_called_once_with(TENANT_ID, "customer-001")
        mock_notify.assert_called_once()
        assert mock_notify.call_args.kwargs["event_type"] == "damage_claim_update"
        assert mock_notify.call_args.kwargs["template_data"]["status"] == "resolved"

    def test_resolve_claim_new_style_notifies_the_customer(self):
        from services.claims import service

        claim = _claim(status="under_inspection", billing_id="billing-001")
        updated = _claim(status="resolved", reference="DC-20260909-001")
        req = MagicMock()
        req.resolution_type = MagicMock()
        req.resolution_type.value = "goodwill_credit"
        req.settlement_amount_usd = Decimal("20")
        req.notes = "Goodwill credit"

        with (
            patch.object(service.repo, "get_damage_claim_by_id", return_value=claim),
            patch.object(service, "get_effective_dollar_rate", return_value={"rate": Decimal("1550")}),
            patch.object(service.repo, "get_billing_by_id", return_value=None),
            patch.object(service.repo, "update_claim_status", return_value=updated),
            patch.object(service.repo, "get_customer_contact", return_value=self._CONTACT) as mock_contact,
            patch("services.claims.service.publish_event"),
            patch("services.claims.service.log_audit"),
            patch("services.claims.service.enqueue_notifications") as mock_notify,
        ):
            ctx = _ctx(UserRole.NIGERIA_OFFICE_STAFF)
            service.resolve_claim(TENANT_ID, "claim-001", req, actor_id="user-1", ctx=ctx)

        mock_contact.assert_called_once_with(TENANT_ID, "customer-001")
        mock_notify.assert_called_once()
        assert mock_notify.call_args.kwargs["event_type"] == "damage_claim_update"


class TestClaimStats:
    """GET /v1/claims/stats service delegation (SQL aggregation lives in the repo)."""

    def test_delegates_with_tenant_id(self):
        from unittest.mock import patch

        from services.claims import service

        stub = {
            "total": 5,
            "open": 2,
            "under_inspection": 1,
            "resolved_30d": 1,
            "filed": 1,
            "pending_resolution": 1,
            "resolved": 2,
            "closed": 1,
        }
        with patch.object(service.repo, "get_claim_stats", return_value=stub) as m:
            result = service.get_claim_stats(TENANT_ID)
        assert m.call_args[0][0] == TENANT_ID
        assert result["total"] == 5


class TestClaimsWritesAreGuarded:
    """The guards that stop a second request opening a second refund.

    That they hold under real concurrency is proved in tests/db/test_atomic_writes.py;
    these pin the service-level contract with the repository mocked.
    """

    def test_an_item_that_already_carries_a_refund_does_not_get_another(self):
        from decimal import Decimal

        from services.claims import service

        item = _seized_item()
        already = {**item, "recovery_status": "permanently_lost", "refund_request_id": "refund-existing"}

        with (
            patch.object(service.repo, "get_seized_item_by_id", return_value=item),
            patch.object(service.repo, "update_seized_item_status", return_value=already),
            patch.object(service.refund_repo, "create_refund_request") as mock_create,
            patch.object(service.repo, "link_refund_to_seized_item") as mock_link,
        ):
            result = service.update_seized_item(
                TENANT_ID_C,
                "seized-001",
                "permanently_lost",
                notes=None,
                actor_id="u",
                ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF),
                refund_amount_ngn=Decimal("20000"),
            )

        mock_create.assert_not_called()
        mock_link.assert_not_called()
        assert "refund_request_id" not in result or result["refund_request_id"] == "refund-existing"

    def test_resolving_a_claim_that_was_resolved_by_someone_else_is_refused_with_no_side_effects(self):
        from decimal import Decimal
        from types import SimpleNamespace

        from services.claims import service
        from shared.exceptions import IllegalTransitionError

        claim = {"id": "claim-001", "status": "pending_resolution", "customer_id": "cust-1", "tenant_id": TENANT_ID_C}
        req = SimpleNamespace(
            resolution_type=SimpleNamespace(value="refund"),
            settlement_amount_usd=None,
            amount_ngn=Decimal("1000"),
            reason="wet",
            discount_percentage=None,
        )

        with (
            patch.object(service.repo, "get_damage_claim_by_id", return_value=claim),
            patch.object(service.repo, "get_tenant_config_value", return_value={}),
            patch.object(service, "get_effective_dollar_rate", return_value={"rate": Decimal("1500")}),
            patch.object(service.repo, "update_claim_status", return_value=None) as mock_status,
            patch.object(service.repo, "create_refund_request_for_claim") as mock_refund,
            patch.object(service.repo, "create_claim_resolution") as mock_resolution,
            patch.object(service, "publish_event") as mock_publish,
        ):
            with pytest.raises(IllegalTransitionError):
                service.resolve_claim(TENANT_ID_C, "claim-001", req, actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF))

        assert mock_status.call_args.kwargs["allowed_from"]  # the guard is passed to the repo
        mock_refund.assert_not_called()
        mock_resolution.assert_not_called()
        mock_publish.assert_not_called()


# ---------------------------------------------------------------------------
# PATCH /v1/claims/missing-items/{id} and /seized-items/{id} — input validation
#
# The compensation amount and the status are the two inputs that turn into a refund, so a
# bad value must be a 422 here, not a 500 from a CHECK constraint after the status saved.
# ---------------------------------------------------------------------------


class TestItemUpdateValidation:
    @staticmethod
    def _event(kind: str, body: dict) -> dict:
        return {
            "requestContext": {
                "requestId": "req-item-001",
                "http": {"method": "PATCH", "path": f"/v1/claims/{kind}/item-001"},
                "authorizer": {"claims": {"sub": "user-1", "custom:tenant_id": TENANT_ID}},
                "identity": {"sourceIp": "127.0.0.1"},
            },
            "headers": {},
            "body": json.dumps(body),
            "queryStringParameters": {},
            "pathParameters": {},
        }

    def _patch_missing(self, body: dict, update_result: dict | None = None) -> tuple[dict, MagicMock]:
        from services.claims import handler, service

        with (
            patch("services.claims.handler.get_tenant_context", return_value=_ctx(UserRole.NIGERIA_OFFICE_STAFF)),
            patch.object(service, "update_missing_item", return_value=update_result or {"id": "item-001"}) as mock_update,
        ):
            resp = handler.lambda_handler(self._event("missing-items", body), None)
        return resp, mock_update

    def test_confirmed_lost_with_amount_reaches_the_service_as_a_decimal(self):
        resp, mock_update = self._patch_missing({"status": "confirmed_lost", "refund_amount_ngn": "7500.50"})

        assert resp["statusCode"] == 200
        assert mock_update.call_args.kwargs["refund_amount_ngn"] == Decimal("7500.50")

    def test_no_amount_is_passed_as_none(self):
        resp, mock_update = self._patch_missing({"status": "confirmed_lost"})

        assert resp["statusCode"] == 200
        assert mock_update.call_args.kwargs["refund_amount_ngn"] is None

    @pytest.mark.parametrize("bad_amount", ["abc", "0", "-5", "NaN", "Infinity"])
    def test_an_unusable_amount_is_a_422_and_nothing_is_updated(self, bad_amount):
        resp, mock_update = self._patch_missing({"status": "confirmed_lost", "refund_amount_ngn": bad_amount})

        assert resp["statusCode"] == 422
        mock_update.assert_not_called()

    def test_a_status_the_database_does_not_allow_is_a_422(self):
        resp, mock_update = self._patch_missing({"status": "compensated"})

        assert resp["statusCode"] == 422
        mock_update.assert_not_called()

    def test_a_seized_status_the_database_does_not_allow_is_a_422(self):
        from services.claims import handler, service

        with (
            patch("services.claims.handler.get_tenant_context", return_value=_ctx(UserRole.NIGERIA_OFFICE_STAFF)),
            patch.object(service, "update_seized_item") as mock_update,
        ):
            resp = handler.lambda_handler(self._event("seized-items", {"recovery_status": "forfeited"}), None)
        assert resp["statusCode"] == 422
        mock_update.assert_not_called()

    def test_seized_item_amount_is_validated_the_same_way(self):
        from services.claims import handler, service

        with (
            patch("services.claims.handler.get_tenant_context", return_value=_ctx(UserRole.NIGERIA_OFFICE_STAFF)),
            patch.object(service, "update_seized_item") as mock_update,
        ):
            resp = handler.lambda_handler(
                self._event("seized-items", {"recovery_status": "recovered", "refund_amount_ngn": "-1"}), None
            )

        assert resp["statusCode"] == 422
        mock_update.assert_not_called()
