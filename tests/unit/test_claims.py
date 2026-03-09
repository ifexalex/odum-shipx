"""Unit tests for services.claims.service — lifecycle, approval thresholds."""
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
        assert (
            resolution_data["approval_level"] == "tenant_admin"
        ), f"Expected tenant_admin approval, got {resolution_data['approval_level']!r}"

    def test_approved_by_field_matches_actor_id(self):
        """The approved_by field in the resolution record must equal the actor_id."""
        from services.claims import service

        claim = _claim(status="under_inspection")
        updated = _claim(status="resolved")

        req = self._make_req("compensation", "30")

        with (
            patch.object(service.repo, "get_damage_claim_by_id", return_value=claim),
            patch.object(service.repo, "get_tenant_config_value", return_value={"staff_limit": 50}),
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
            patch.object(service.repo, "create_damage_claim", return_value=created),
            patch("services.claims.service.log_audit"),
            patch("services.claims.service.publish_event"),
        ):
            ctx = _ctx(UserRole.CUSTOMER, user_id="user-customer")
            result = service.file_claim(TENANT_ID, req, actor_id="user-customer", ctx=ctx)
            assert result["status"] == "filed"

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
            with pytest.raises((ResourceNotFoundError, InsufficientPermissionsError)):
                service.get_claim(TENANT_ID, "claim-001", ctx)
