"""Unit tests for services.packing_list.service — state machine, CBM calculation."""
from decimal import Decimal

import pytest

from shared.exceptions import (
    IllegalTransitionError,
    SelfApprovalForbiddenError,
)


class TestComputeCbm:
    def test_standard_calculation(self):
        from services.packing_list.service import _compute_cbm

        # 100cm × 80cm × 60cm / 1,000,000 = 0.48 m³
        result = _compute_cbm(Decimal("100"), Decimal("80"), Decimal("60"))
        assert result == Decimal("0.48")

    def test_none_dimension_returns_zero(self):
        from services.packing_list.service import _compute_cbm

        assert _compute_cbm(None, Decimal("80"), Decimal("60")) == Decimal("0")
        assert _compute_cbm(Decimal("100"), None, Decimal("60")) == Decimal("0")
        assert _compute_cbm(Decimal("100"), Decimal("80"), None) == Decimal("0")

    def test_all_none_returns_zero(self):
        from services.packing_list.service import _compute_cbm

        assert _compute_cbm(None, None, None) == Decimal("0")

    def test_small_carton(self):
        from services.packing_list.service import _compute_cbm

        # 30 × 20 × 15 = 9000 cm³ = 0.009 m³
        result = _compute_cbm(Decimal("30"), Decimal("20"), Decimal("15"))
        assert result == Decimal("0.009")

    def test_zero_dimension(self):
        from services.packing_list.service import _compute_cbm

        assert _compute_cbm(Decimal("0"), Decimal("80"), Decimal("60")) == Decimal("0")


class TestAssertTransition:
    def test_draft_to_pending_approval_valid(self):
        from services.packing_list.service import _assert_transition

        _assert_transition("draft", "pending_approval", "pl-001")  # no exception

    def test_pending_approval_to_approved_valid(self):
        from services.packing_list.service import _assert_transition

        _assert_transition("pending_approval", "approved", "pl-001")

    def test_pending_approval_to_rejected_valid(self):
        from services.packing_list.service import _assert_transition

        _assert_transition("pending_approval", "rejected", "pl-001")

    def test_rejected_to_draft_valid(self):
        from services.packing_list.service import _assert_transition

        _assert_transition("rejected", "draft", "pl-001")

    def test_draft_to_approved_invalid(self):
        from services.packing_list.service import _assert_transition

        with pytest.raises(IllegalTransitionError) as exc_info:
            _assert_transition("draft", "approved", "pl-001")
        assert exc_info.value.status_code == 409

    def test_approved_to_draft_invalid(self):
        from services.packing_list.service import _assert_transition

        with pytest.raises(IllegalTransitionError):
            _assert_transition("approved", "draft", "pl-001")

    def test_approved_to_rejected_invalid(self):
        from services.packing_list.service import _assert_transition

        with pytest.raises(IllegalTransitionError):
            _assert_transition("approved", "rejected", "pl-001")


class TestCartonTagFormat:
    """Verify carton tag format: {TENANT_SHORT}-{CONTAINER_NUMBER}-{seq:03d}."""

    def test_carton_tag_format_string(self):
        tenant_short = "ACME"
        container_number = "CONT001"
        seq = 1
        tag = f"{tenant_short}-{container_number}-{seq:03d}"
        assert tag == "ACME-CONT001-001"

    def test_carton_tag_sequence_zero_padded_to_three_digits(self):
        tenant_short = "XYZ"
        container_number = "C99"

        assert f"{tenant_short}-{container_number}-{1:03d}".endswith("-001")
        assert f"{tenant_short}-{container_number}-{42:03d}".endswith("-042")
        assert f"{tenant_short}-{container_number}-{999:03d}".endswith("-999")

    def test_carton_seq_start_offsets_avoid_duplicate_tags(self):
        """Sequential packing lists use different seq_start values to avoid duplicates."""
        tenant_short = "TEST"
        container_number = "C001"
        # First PL: cartons 1-10
        tags_pl1 = {f"{tenant_short}-{container_number}-{s:03d}" for s in range(1, 11)}
        # Second PL: starts at 11
        tags_pl2 = {f"{tenant_short}-{container_number}-{s:03d}" for s in range(11, 21)}
        assert tags_pl1.isdisjoint(tags_pl2), "Carton tags from different PLs must not overlap"


class TestApprovalSideEffects:
    """Verify that approving a packing list triggers the correct side effects."""

    def _pl(self, **kw) -> dict:
        base = {
            "id": "pl-001",
            "status": "pending_approval",
            "created_by": "user-china",
            "tenant_id": "tenant-1",
            "customer_id": "cust-001",
            "container_id": "cont-001",
            "packing_list_number": "ACME-PL-001",
        }
        base.update(kw)
        return base

    def _approve(self, manifest_exists, items=None):
        from unittest.mock import MagicMock, patch

        from services.packing_list import service
        from shared.tenant_context import TenantContext, UserRole

        pl = self._pl()
        updated = {**pl, "status": "approved"}
        manifest = {"id": "manifest-001"}

        req = MagicMock()
        req.approved_cbm_override = None

        with (
            patch.object(service.repo, "get_packing_list_by_id", return_value=pl),
            patch.object(service.repo, "approve_packing_list_row", return_value=updated),
            patch.object(service.repo, "get_manifest_by_container", return_value=manifest if manifest_exists else None),
            patch.object(service.repo, "create_manifest", return_value=manifest) as mock_create,
            patch.object(service.repo, "link_manifest") as mock_link,
            patch.object(service.repo, "recalculate_manifest_totals"),
            patch.object(service.repo, "get_items_by_packing_list", return_value=items or []),
            patch.object(service.repo, "upsert_shipment_tracking") as mock_upsert,
            patch("services.packing_list.service.publish_event") as mock_publish,
            patch("services.packing_list.service.log_audit"),
        ):
            ctx = TenantContext(tenant_id="tenant-1", user_id="user-approver", role=UserRole.TENANT_ADMIN)
            service.approve_packing_list("tenant-1", "pl-001", req, actor_id="user-approver", ctx=ctx)
            return mock_create, mock_link, mock_upsert, mock_publish

    def test_creates_manifest_when_none_exists(self):
        mock_create, _, _, _ = self._approve(manifest_exists=False)
        mock_create.assert_called_once()

    def test_does_not_create_manifest_when_one_exists(self):
        mock_create, _, _, _ = self._approve(manifest_exists=True)
        mock_create.assert_not_called()

    def test_links_packing_list_to_manifest(self):
        _, mock_link, _, _ = self._approve(manifest_exists=True)
        mock_link.assert_called_once_with("tenant-1", "pl-001", "manifest-001")

    def test_publishes_packing_list_approved_event(self):
        _, _, _, mock_publish = self._approve(manifest_exists=True)
        event_types = [c[1]["detail_type"] for c in mock_publish.call_args_list]
        assert "PackingListApproved" in event_types

    def test_upserts_tracking_once_per_unique_code(self):
        items = [
            {"tracking_code": "TK-001", "carton_tag": "ACME-C001-001"},
            {"tracking_code": "TK-001", "carton_tag": "ACME-C001-002"},  # same code
            {"tracking_code": "TK-002", "carton_tag": "ACME-C001-003"},
        ]
        _, _, mock_upsert, _ = self._approve(manifest_exists=True, items=items)
        assert mock_upsert.call_count == 2
        codes = {c[0][1] for c in mock_upsert.call_args_list}
        assert codes == {"TK-001", "TK-002"}


class TestPackingListService:
    """Tests for service functions with mocked repository."""

    def test_get_packing_list_not_found_raises(self):
        from unittest.mock import patch

        from services.packing_list import service
        from shared.exceptions import ResourceNotFoundError

        with patch.object(service.repo, "get_packing_list_by_id", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                from shared.tenant_context import TenantContext, UserRole

                ctx = TenantContext(
                    tenant_id="tenant-1",
                    user_id="user-1",
                    role=UserRole.NIGERIA_OFFICE_STAFF,
                )
                service.get_packing_list("tenant-1", "nonexistent", ctx)

    def test_self_approval_forbidden(self):
        """Creator cannot approve their own packing list."""
        from unittest.mock import MagicMock, patch

        from services.packing_list import service
        from shared.tenant_context import TenantContext, UserRole

        pl = {
            "id": "pl-001",
            "status": "pending_approval",
            "created_by": "user-creator",
            "tenant_id": "tenant-1",
            "customer_id": "cust-1",
            "container_id": "cont-1",
            "packing_list_number": "PL-001",
        }

        with patch.object(service.repo, "get_packing_list_by_id", return_value=pl):
            ctx = TenantContext(
                tenant_id="tenant-1",
                user_id="user-creator",  # same as created_by
                role=UserRole.TENANT_ADMIN,
            )
            req = MagicMock()
            req.approved_cbm_override = None
            with pytest.raises(SelfApprovalForbiddenError):
                service.approve_packing_list("tenant-1", "pl-001", req, actor_id="user-creator", ctx=ctx)
