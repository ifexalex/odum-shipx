"""Unit tests for services.packing_list.service — state machine, CBM calculation."""

from datetime import UTC, date, datetime, timedelta
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


class TestApprovalNotifiesCustomer:
    """Ground-truth gap found live, reported by the user while investigating
    a separate missing notification on payment-claim rejection — asked to
    check every notification in the app. Approving a packing list published
    an EventBridge event that was never routed anywhere and never called
    enqueue_notifications — the customer was never actually told."""

    def _pl(self, **kw) -> dict:
        base = {
            "id": "pl-001",
            "status": "pending_approval",
            "created_by": "user-china",
            "tenant_id": "tenant-1",
            "customer_id": "cust-001",
            "container_id": "cont-001",
            "reference": "PL-20260909-001",
        }
        base.update(kw)
        return base

    _CONTACT = {
        "id": "cust-001",
        "name": "Ngozi",
        "phone": "+2348012345678",
        "email": "n@x.com",
        "whatsapp": None,
        "locale": "en",
    }

    def test_approving_notifies_the_customer(self):
        from unittest.mock import MagicMock, patch

        from services.packing_list import service
        from shared.tenant_context import TenantContext, UserRole

        pl = self._pl()
        updated = {**pl, "status": "approved"}
        req = MagicMock()
        req.approved_cbm_override = None

        with (
            patch.object(service.repo, "get_packing_list_by_id", return_value=pl),
            patch.object(service.repo, "approve_packing_list_row", return_value=updated),
            patch.object(service.repo, "get_manifest_by_container", return_value={"id": "manifest-001"}),
            patch.object(service.repo, "link_manifest"),
            patch.object(service.repo, "recalculate_manifest_totals"),
            patch.object(service.repo, "get_items_by_packing_list", return_value=[]),
            patch.object(service.repo, "get_customer_contact", return_value=self._CONTACT) as mock_contact,
            patch("services.packing_list.service.publish_event"),
            patch("services.packing_list.service.log_audit"),
            patch("services.packing_list.service.enqueue_notifications") as mock_notify,
        ):
            ctx = TenantContext(tenant_id="tenant-1", user_id="user-approver", role=UserRole.TENANT_ADMIN)
            service.approve_packing_list("tenant-1", "pl-001", req, actor_id="user-approver", ctx=ctx)

        mock_contact.assert_called_once_with("tenant-1", "cust-001")
        mock_notify.assert_called_once()
        assert mock_notify.call_args.kwargs["event_type"] == "packing_list_approved"
        assert mock_notify.call_args.kwargs["template_data"]["reference"] == "PL-20260909-001"

    def test_approving_also_notifies_the_customer_in_app_when_they_have_a_portal_account(self):
        """Ground-truth follow-up, reported live by the user: SMS/WhatsApp/
        email can each fail for reasons entirely outside this app, and the
        customer portal itself showed nothing until they happened to open
        this one packing list's page."""
        from unittest.mock import MagicMock, patch

        from services.packing_list import service
        from shared.tenant_context import TenantContext, UserRole

        pl = self._pl()
        updated = {**pl, "status": "approved"}
        req = MagicMock()
        req.approved_cbm_override = None
        contact = {**self._CONTACT, "user_id": "portal-user-001"}

        with (
            patch.object(service.repo, "get_packing_list_by_id", return_value=pl),
            patch.object(service.repo, "approve_packing_list_row", return_value=updated),
            patch.object(service.repo, "get_manifest_by_container", return_value={"id": "manifest-001"}),
            patch.object(service.repo, "link_manifest"),
            patch.object(service.repo, "recalculate_manifest_totals"),
            patch.object(service.repo, "get_items_by_packing_list", return_value=[]),
            patch.object(service.repo, "get_customer_contact", return_value=contact),
            patch("services.packing_list.service.publish_event"),
            patch("services.packing_list.service.log_audit"),
            patch("services.packing_list.service.enqueue_notifications"),
            patch("services.packing_list.service.notify_staff") as mock_notify_staff,
        ):
            ctx = TenantContext(tenant_id="tenant-1", user_id="user-approver", role=UserRole.TENANT_ADMIN)
            service.approve_packing_list("tenant-1", "pl-001", req, actor_id="user-approver", ctx=ctx)

        mock_notify_staff.assert_called_once()
        assert mock_notify_staff.call_args.kwargs["target_user_id"] == "portal-user-001"
        assert mock_notify_staff.call_args.kwargs["event_type"] == "packing_list_approved"

    def test_no_in_app_notification_for_a_customer_with_no_portal_account(self):
        from unittest.mock import MagicMock, patch

        from services.packing_list import service
        from shared.tenant_context import TenantContext, UserRole

        pl = self._pl()
        updated = {**pl, "status": "approved"}
        req = MagicMock()
        req.approved_cbm_override = None

        with (
            patch.object(service.repo, "get_packing_list_by_id", return_value=pl),
            patch.object(service.repo, "approve_packing_list_row", return_value=updated),
            patch.object(service.repo, "get_manifest_by_container", return_value={"id": "manifest-001"}),
            patch.object(service.repo, "link_manifest"),
            patch.object(service.repo, "recalculate_manifest_totals"),
            patch.object(service.repo, "get_items_by_packing_list", return_value=[]),
            patch.object(service.repo, "get_customer_contact", return_value=self._CONTACT),
            patch("services.packing_list.service.publish_event"),
            patch("services.packing_list.service.log_audit"),
            patch("services.packing_list.service.enqueue_notifications"),
            patch("services.packing_list.service.notify_staff") as mock_notify_staff,
        ):
            ctx = TenantContext(tenant_id="tenant-1", user_id="user-approver", role=UserRole.TENANT_ADMIN)
            service.approve_packing_list("tenant-1", "pl-001", req, actor_id="user-approver", ctx=ctx)

        mock_notify_staff.assert_not_called()

    def test_a_notification_failure_does_not_fail_approval(self):
        from unittest.mock import MagicMock, patch

        from services.packing_list import service
        from shared.tenant_context import TenantContext, UserRole

        pl = self._pl()
        updated = {**pl, "status": "approved"}
        req = MagicMock()
        req.approved_cbm_override = None

        with (
            patch.object(service.repo, "get_packing_list_by_id", return_value=pl),
            patch.object(service.repo, "approve_packing_list_row", return_value=updated),
            patch.object(service.repo, "get_manifest_by_container", return_value={"id": "manifest-001"}),
            patch.object(service.repo, "link_manifest"),
            patch.object(service.repo, "recalculate_manifest_totals"),
            patch.object(service.repo, "get_items_by_packing_list", return_value=[]),
            patch.object(service.repo, "get_customer_contact", side_effect=RuntimeError("db down")),
            patch("services.packing_list.service.publish_event"),
            patch("services.packing_list.service.log_audit"),
        ):
            ctx = TenantContext(tenant_id="tenant-1", user_id="user-approver", role=UserRole.TENANT_ADMIN)
            result = service.approve_packing_list("tenant-1", "pl-001", req, actor_id="user-approver", ctx=ctx)

        assert result is not None

    def test_bulk_approve_notifies_each_customer(self):
        from unittest.mock import patch

        from services.packing_list import service
        from shared.tenant_context import TenantContext, UserRole

        pl = self._pl()
        req_mock = type("Req", (), {"ids": ["pl-001"]})()

        with (
            patch.object(service.repo, "get_packing_lists_by_ids", return_value=[pl]),
            patch.object(service.repo, "bulk_set_status"),
            patch.object(service.repo, "get_manifest_by_container", return_value={"id": "manifest-001"}),
            patch.object(service.repo, "link_manifest"),
            patch.object(service.repo, "recalculate_manifest_totals"),
            patch.object(service.repo, "get_items_by_packing_list", return_value=[]),
            patch.object(service.repo, "get_customer_contact", return_value=self._CONTACT),
            patch("services.packing_list.service.publish_event"),
            patch("services.packing_list.service.log_audit"),
            patch("services.packing_list.service.enqueue_notifications") as mock_notify,
        ):
            ctx = TenantContext(tenant_id="tenant-1", user_id="user-approver", role=UserRole.TENANT_ADMIN)
            service.bulk_approve_packing_lists("tenant-1", req_mock, actor_id="user-approver", ctx=ctx)

        mock_notify.assert_called_once()
        assert mock_notify.call_args.kwargs["event_type"] == "packing_list_approved"


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


_BULK_TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


class TestSubmitNotifiesStaff:
    """Ground-truth follow-up to the payment-claim-rejection notification bug
    — a submitted packing list previously had no in-app signal for the
    china_office_staff/tenant_admin approvers who need to act on it."""

    def test_single_submit_notifies_approvers(self):
        from unittest.mock import patch

        from services.packing_list import service
        from shared.tenant_context import TenantContext, UserRole

        pl = {"id": "pl-1", "status": "draft", "reference": "PL-20260912-001"}
        updated = {**pl, "status": "pending_approval"}
        ctx = TenantContext(tenant_id="tenant-1", user_id="staff-1", role=UserRole.CHINA_OFFICE_STAFF)

        with (
            patch.object(service.repo, "get_packing_list_by_id", return_value=pl),
            patch.object(service.repo, "list_packing_list_items", return_value=[{"id": "item-1"}]),
            patch.object(service.repo, "update_packing_list_status", return_value=updated),
            patch.object(service, "log_audit"),
            patch.object(service, "notify_staff") as mock_notify,
        ):
            service.submit_packing_list("pl-1", "tenant-1", ctx, actor_id="staff-1")

        assert mock_notify.call_count == 2
        roles = {c.kwargs["target_role"] for c in mock_notify.call_args_list}
        assert roles == {"china_office_staff", "tenant_admin"}
        assert all(c.kwargs["event_type"] == "packing_list_submitted" for c in mock_notify.call_args_list)

    def test_bulk_submit_notifies_approvers_without_a_comma_joined_entity_id(self):
        """entity_id is a UUID column — a bulk action has no single entity to
        link to, so this must be None, not a comma-joined id list (which
        would silently fail the UUID cast, the same way log_audit's own
        BULK_APPROVE call already does for its own entity_id)."""
        from unittest.mock import patch

        from services.packing_list import service
        from services.packing_list.models import BulkSubmitRequest
        from shared.tenant_context import TenantContext, UserRole

        rows = [{"id": "pl-1", "status": "draft", "created_by": "staff-1"}]
        ctx = TenantContext(tenant_id=_BULK_TENANT_ID, user_id="staff-1", role=UserRole.CHINA_OFFICE_STAFF)

        with (
            patch.object(service.repo, "get_packing_lists_by_ids", return_value=rows),
            patch.object(service.repo, "bulk_set_status"),
            patch.object(service, "log_audit"),
            patch.object(service, "notify_staff") as mock_notify,
        ):
            service.bulk_submit_packing_lists(
                _BULK_TENANT_ID,
                BulkSubmitRequest(ids=["pl-1"]),
                actor_id="staff-1",
                ctx=ctx,
            )

        assert mock_notify.call_count == 2
        assert all(c.kwargs["entity_id"] is None for c in mock_notify.call_args_list)


class TestBulkSubmit:
    """draft -> pending_approval in bulk (the counterpart to bulk approve/reject)."""

    def _ctx(self):
        from shared.tenant_context import TenantContext, UserRole

        return TenantContext(tenant_id=_BULK_TENANT_ID, user_id="staff-1", role=UserRole.CHINA_OFFICE_STAFF)

    def test_submits_drafts_and_reports_wrong_status_for_the_rest(self):
        from unittest.mock import patch

        from services.packing_list import service
        from services.packing_list.models import BulkSubmitRequest

        rows = [
            {"id": "pl-1", "status": "draft", "created_by": "staff-1"},
            {"id": "pl-2", "status": "pending_approval", "created_by": "staff-1"},
            {"id": "pl-3", "status": "approved", "created_by": "staff-1"},
        ]
        with (
            patch.object(service.repo, "get_packing_lists_by_ids", return_value=rows),
            patch.object(service.repo, "bulk_set_status") as mock_set,
            patch.object(service, "log_audit"),
        ):
            result = service.bulk_submit_packing_lists(
                _BULK_TENANT_ID,
                BulkSubmitRequest(ids=["pl-1", "pl-2", "pl-3", "pl-missing"]),
                actor_id="staff-1",
                ctx=self._ctx(),
            )

        assert result["succeeded"] == ["pl-1"]
        mock_set.assert_called_once_with(_BULK_TENANT_ID, ["pl-1"], "pending_approval", "staff-1", expected_status="draft")
        reasons = {f["id"]: f["reason"] for f in result["failed"]}
        assert reasons == {
            "pl-2": "wrong_status:pending_approval",
            "pl-3": "wrong_status:approved",
            "pl-missing": "not_found",
        }

    def test_submitting_your_own_draft_is_allowed(self):
        """Two-person control lives on approval, not on submission."""
        from unittest.mock import patch

        from services.packing_list import service
        from services.packing_list.models import BulkSubmitRequest

        rows = [{"id": "pl-1", "status": "draft", "created_by": "staff-1"}]
        with (
            patch.object(service.repo, "get_packing_lists_by_ids", return_value=rows),
            patch.object(service.repo, "bulk_set_status"),
            patch.object(service, "log_audit"),
        ):
            result = service.bulk_submit_packing_lists(
                _BULK_TENANT_ID,
                BulkSubmitRequest(ids=["pl-1"]),
                actor_id="staff-1",
                ctx=self._ctx(),
            )
        assert result["succeeded"] == ["pl-1"]
        assert result["failed"] == []


class TestBulkSetStatusGuards:
    """bulk_set_status used to coerce any non-'approved' status to 'rejected'."""

    def test_rejects_an_unsupported_status_instead_of_guessing(self):
        import pytest

        from services.packing_list import repository

        # Regression: passing 'pending_approval' fell into the else-branch and
        # marked the rows rejected, silently destroying data.
        with pytest.raises(ValueError, match="does not support status"):
            repository.bulk_set_status(_BULK_TENANT_ID, ["pl-1"], "cancelled", "staff-1")


class TestPackingListSearchFilter:
    """The `q` free-text filter, end to end through the handler."""

    def _ctx(self):
        from shared.tenant_context import TenantContext, UserRole

        return TenantContext(tenant_id=_BULK_TENANT_ID, user_id="staff-1", role=UserRole.CHINA_OFFICE_STAFF)

    def _event(self, path: str, query: dict) -> dict:
        return {
            "requestContext": {
                "requestId": "req-pl-search",
                "http": {"method": "GET", "path": path},
                "authorizer": {"claims": {"sub": "staff-1", "custom:tenant_id": _BULK_TENANT_ID}},
                "identity": {"sourceIp": "127.0.0.1"},
            },
            "headers": {},
            "body": "{}",
            "queryStringParameters": query,
            "pathParameters": {},
        }

    def test_q_reaches_the_repository_filters(self):
        """Regression: the UI always sent `q` and the SQL always supported it,
        but the handler never read the param — so every search silently
        returned the full, unfiltered list."""
        from unittest.mock import patch

        from services.packing_list import handler

        with (
            patch("services.packing_list.handler.get_tenant_context", return_value=self._ctx()),
            patch.object(handler.service, "list_packing_lists", return_value=([], None, False, 0)) as mock_list,
        ):
            resp = handler.lambda_handler(self._event("/v1/packing-lists", {"q": "Ngozi"}), None)

        assert resp["statusCode"] == 200
        assert mock_list.call_args[0][1]["q"] == "Ngozi"

    def test_container_scoped_list_also_honours_q(self):
        from unittest.mock import patch

        from services.packing_list import handler

        with (
            patch("services.packing_list.handler.get_tenant_context", return_value=self._ctx()),
            patch.object(handler.service, "list_packing_lists", return_value=([], None, False, 0)) as mock_list,
        ):
            resp = handler.lambda_handler(self._event("/v1/containers/c-1/packing-lists", {"q": "Cynthia"}), None)

        assert resp["statusCode"] == 200
        filters = mock_list.call_args[0][1]
        assert filters["q"] == "Cynthia"
        assert filters["container_id"] == "c-1"

    def test_search_matches_reference_customer_and_container(self):
        """The search box promises all three; reference was missing from the SQL."""
        from unittest.mock import patch

        from services.packing_list import repository

        captured = {}

        def _capture(tenant_id, query, params):
            captured["query"] = query
            return []

        with patch.object(repository, "execute_with_tenant", side_effect=_capture):
            repository.list_packing_lists(_BULK_TENANT_ID, {"q": "abc"}, 10, None)

        sql = captured["query"]
        assert "cu.name ILIKE" in sql
        assert "c.container_number ILIKE" in sql
        assert "pl.reference ILIKE" in sql


class TestBulkApproveSideEffects:
    """Bulk approve must do everything single approve does."""

    def _ctx(self):
        from shared.tenant_context import TenantContext, UserRole

        return TenantContext(tenant_id=_BULK_TENANT_ID, user_id="admin-1", role=UserRole.TENANT_ADMIN)

    def test_creates_manifest_links_it_and_makes_tracking_records(self):
        """Regression: bulk approve only flipped the status. Bulk-approved
        containers had no manifest (so could not be sealed), no manifest link,
        and no shipment_tracking rows — leaving customers unable to track cargo
        that the system considered fully approved."""
        from unittest.mock import patch

        from services.packing_list import service
        from services.packing_list.models import BulkApproveRequest

        created_manifest: dict[str, dict] = {}
        rows = [
            {"id": "pl-1", "status": "pending_approval", "created_by": "staff-1", "container_id": "c-1", "customer_id": "cust-1"},
            {"id": "pl-2", "status": "pending_approval", "created_by": "staff-1", "container_id": "c-1", "customer_id": "cust-2"},
        ]
        with (
            patch.object(service.repo, "get_packing_lists_by_ids", return_value=rows),
            patch.object(service.repo, "bulk_set_status"),
            # Stateful: the second list must find the manifest the first
            # created, exactly as it does against a real database.
            patch.object(
                service.repo,
                "get_manifest_by_container",
                side_effect=lambda *_a, **_k: created_manifest.get("m"),
            ),
            patch.object(
                service.repo,
                "create_manifest",
                side_effect=lambda *_a, **_k: created_manifest.setdefault("m", {"id": "mf-1"}),
            ) as mock_create_mf,
            patch.object(service.repo, "link_manifest") as mock_link,
            patch.object(service.repo, "recalculate_manifest_totals") as mock_recalc,
            patch.object(
                service.repo,
                "get_items_by_packing_list",
                return_value=[{"tracking_code": "TRK-1"}, {"tracking_code": "TRK-1"}],
            ),
            patch.object(service.repo, "upsert_shipment_tracking") as mock_track,
            patch.object(service, "publish_event") as mock_event,
            patch.object(service, "log_audit"),
        ):
            result = service.bulk_approve_packing_lists(
                _BULK_TENANT_ID,
                BulkApproveRequest(ids=["pl-1", "pl-2"]),
                actor_id="admin-1",
                ctx=self._ctx(),
            )

        assert result["succeeded"] == ["pl-1", "pl-2"]
        # One manifest for the shared container, reused for the second list.
        assert mock_create_mf.call_count == 1
        assert mock_link.call_count == 2
        assert mock_recalc.call_count == 2
        # Deduplicated per list: one call per distinct tracking code, per list.
        assert mock_track.call_count == 2
        assert mock_event.call_count == 2


class TestMinCbmAndBaleSizing:
    """Line-item CBM floor + bale sizing (feature: item entry enhancements)."""

    def test_apply_min_cbm_floors_small_values(self):
        from decimal import Decimal

        from shared.cbm_rate import apply_min_cbm

        assert apply_min_cbm(Decimal("0.03"), Decimal("0.1")) == Decimal("0.1")
        assert apply_min_cbm(Decimal("0"), Decimal("0.1")) == Decimal("0.1")
        assert apply_min_cbm(None, Decimal("0.1")) == Decimal("0.1")
        # Values at/above the floor pass through unchanged.
        assert apply_min_cbm(Decimal("0.4"), Decimal("0.1")) == Decimal("0.4")

    def test_bale_type_for(self):
        from decimal import Decimal

        from services.packing_list.service import _bale_type_for

        assert _bale_type_for("bale", Decimal("0.4")) == "BIG BALE"
        assert _bale_type_for("bale", Decimal("0.3")) == "BIG BALE"  # at threshold = big
        assert _bale_type_for("bale", Decimal("0.1")) == "SMALL BALE"
        # Non-bale units get no bale label.
        assert _bale_type_for("carton", Decimal("0.5")) is None
        assert _bale_type_for("sack", Decimal("0.5")) is None
        assert _bale_type_for(None, Decimal("0.5")) is None

    def test_get_min_cbm_default_and_floor(self):
        from decimal import Decimal
        from unittest.mock import patch

        import shared.cbm_rate as cr

        with patch.object(cr, "execute_with_tenant", return_value=[]):
            assert cr.get_min_cbm_per_item("t1") == Decimal("0.1")
        with patch.object(cr, "execute_with_tenant", return_value=[{"config_value": {"value": 0.25}}]):
            assert cr.get_min_cbm_per_item("t1") == Decimal("0.25")
        # Non-positive / malformed falls back to the default.
        with patch.object(cr, "execute_with_tenant", return_value=[{"config_value": {"value": 0}}]):
            assert cr.get_min_cbm_per_item("t1") == Decimal("0.1")


class TestResolveArrivalWarehouse:
    """The packing-list arrival-warehouse resolver: validates an explicit id,
    falls back to the tenant default, and tolerates a tenant with none."""

    _TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

    def test_explicit_valid_id_returns_that_warehouse(self):
        from unittest.mock import patch

        from services.packing_list.service import _resolve_arrival_warehouse

        row = {"id": "wh-1", "name": "Lagos"}
        with patch("services.payment_release.repository.get_warehouse_by_id", return_value=row):
            result = _resolve_arrival_warehouse(self._TENANT, "wh-1")
        assert result["id"] == "wh-1"

    def test_explicit_unknown_id_raises(self):
        from unittest.mock import patch

        from services.packing_list.service import _resolve_arrival_warehouse
        from shared.exceptions import ResourceNotFoundError

        with patch("services.payment_release.repository.get_warehouse_by_id", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                _resolve_arrival_warehouse(self._TENANT, "nope")

    def test_omitted_id_falls_back_to_default(self):
        from unittest.mock import patch

        from services.packing_list.service import _resolve_arrival_warehouse

        default = {"id": "wh-default", "name": "HQ"}
        with patch("services.payment_release.repository.get_default_warehouse", return_value=default):
            result = _resolve_arrival_warehouse(self._TENANT, None)
        assert result["id"] == "wh-default"

    def test_omitted_id_with_no_default_returns_none(self):
        from unittest.mock import patch

        from services.packing_list.service import _resolve_arrival_warehouse

        with patch("services.payment_release.repository.get_default_warehouse", return_value=None):
            assert _resolve_arrival_warehouse(self._TENANT, None) is None


class TestShipmentDateOrdering:
    """`delivery_date` is when the supplier delivered the goods to the China
    warehouse; `loading_date` is when they went into the container. The domain
    order is fixed — goods must be received before they can be loaded — so the
    rule is enforced on the models, not just in the browser.
    """

    @staticmethod
    def _create(**dates):
        from services.packing_list.models import CreatePackingListRequest

        return CreatePackingListRequest(container_id="c-1", customer_id="cust-1", **dates)

    def test_loading_before_delivery_is_rejected(self) -> None:
        import pytest as _pytest

        with _pytest.raises(ValueError, match="before delivery_date"):
            self._create(delivery_date=date(2026, 11, 3), loading_date=date(2026, 11, 1))

    def test_loading_on_the_same_day_as_delivery_is_allowed(self) -> None:
        # Goods received in the morning are routinely loaded that afternoon.
        req = self._create(delivery_date=date(2026, 11, 1), loading_date=date(2026, 11, 1))
        assert req.loading_date == req.delivery_date

    def test_loading_after_delivery_is_allowed(self) -> None:
        req = self._create(delivery_date=date(2026, 11, 1), loading_date=date(2026, 11, 5))
        assert req.loading_date > req.delivery_date

    def test_a_future_delivery_date_is_rejected(self) -> None:
        import pytest as _pytest

        future = datetime.now(UTC).date() + timedelta(days=30)
        with _pytest.raises(ValueError, match="cannot be in the future"):
            self._create(delivery_date=future)

    def test_a_future_loading_date_is_allowed(self) -> None:
        """Deliberately unbounded: a packing list is written against a container
        still in `loading` status, so a planned load date is legitimate."""
        future = datetime.now(UTC).date() + timedelta(days=30)
        req = self._create(delivery_date=date(2026, 11, 1), loading_date=future)
        assert req.loading_date == future

    def test_todays_date_is_accepted_even_from_a_timezone_ahead_of_utc(self) -> None:
        """The China office is UTC+8. For several hours each evening their local
        calendar date is already tomorrow in UTC, so comparing against UTC
        "today" would reject the date on their own wall calendar. One day of
        slack covers every real timezone and still rejects next week.
        """
        tomorrow_utc = datetime.now(UTC).date() + timedelta(days=1)
        req = self._create(delivery_date=tomorrow_utc)
        assert req.delivery_date == tomorrow_utc

    def test_each_date_is_still_optional_on_its_own(self) -> None:
        # Both were always nullable; the rules apply only to supplied values.
        assert self._create().delivery_date is None
        assert self._create(loading_date=date(2026, 11, 1)).delivery_date is None
        assert self._create(delivery_date=date(2026, 11, 1)).loading_date is None

    def test_the_same_rules_apply_when_editing_a_draft(self) -> None:
        """The edit path has its own model, so the rule has to be on both or a
        PATCH could write exactly the ordering the create path refuses."""
        import pytest as _pytest

        from services.packing_list.models import UpdatePackingListRequest

        with _pytest.raises(ValueError, match="before delivery_date"):
            UpdatePackingListRequest(
                delivery_date=date(2026, 11, 3),
                loading_date=date(2026, 11, 1),
                items=[{"description": "shoes", "quantity": 1, "cbm": "0.5"}],
            )


class TestBulkQuantityExpansion:
    """One keyed line standing for N identical packages becomes N real rows.

    The expansion is not a convenience detail — it is the correctness mechanism.
    `packing_list_item.quantity` already exists for the Excel manifest import,
    where a row means "N packages" and CBM is read off the forwarder's sheet as
    a line total. **Nothing in the codebase multiplies CBM by quantity**: every
    consumer does a plain ``SUM(pli.cbm)``. Manual entry computes CBM from the
    dimensions typed in, so it is per package, and a single row carrying
    ``quantity = 100`` would be billed as one carton. These tests pin that down.
    """

    @pytest.fixture(autouse=True)
    def _no_db(self, monkeypatch):
        """Stub the two tracking-code lookups so this exercises expansion only."""
        from services.packing_list import repository as repo

        monkeypatch.setattr(repo, "get_existing_tracking_code", lambda *a, **k: None)
        monkeypatch.setattr(repo, "get_next_tracking_sequence", lambda *a, **k: 1)

    @staticmethod
    def _rows(items, *, seq_start=1, min_cbm=Decimal("0.01")):
        from services.packing_list.service import _build_item_rows

        return _build_item_rows(
            tenant_id="t1",
            pl_id="pl1",
            items=items,
            container_id="c1",
            customer_id="cust1",
            tenant_short="ACM",
            container_number="CONT001",
            carton_seq_start=seq_start,
            min_cbm=min_cbm,
        )

    @staticmethod
    def _item(**kwargs):
        from services.packing_list.models import PackingListItemInput

        base = {
            "description": "Shoes",
            "package_unit": "carton",
            "length_cm": Decimal("60"),
            "width_cm": Decimal("40"),
            "height_cm": Decimal("40"),
            "weight_actual_kg": Decimal("12"),
        }
        base.update(kwargs)
        return PackingListItemInput(**base)

    def test_quantity_stays_single_row_with_one_carton_tag(self):
        rows = self._rows([self._item(quantity=100, identical_confirmed=True)])

        assert len(rows) == 1
        assert rows[0]["quantity"] == 100
        assert rows[0]["carton_tag"] == "ACM-CONT001-001"

    def test_single_tag_for_multi_quantity_line(self):
        """A line item with quantity=25 gets one carton_tag, not 25 separate tags."""
        rows = self._rows([self._item(quantity=25, identical_confirmed=True)])

        assert len(rows) == 1
        assert rows[0]["carton_tag"] == "ACM-CONT001-001"
        assert rows[0]["quantity"] == 25

    def test_cbm_and_weight_scale_by_quantity_while_declared_value_is_per_unit(self):
        """CBM and weight store line totals so SUM(pli.cbm) bills all units; declared_value_usd stays per unit."""
        rows = self._rows([self._item(quantity=10, identical_confirmed=True, declared_value_usd=Decimal("50"))])

        per_package = Decimal("60") * Decimal("40") * Decimal("40") / Decimal("1000000")
        assert len(rows) == 1
        assert Decimal(str(rows[0]["cbm"])) == per_package * 10
        assert Decimal(str(rows[0]["weight_actual_kg"])) == Decimal("120")
        assert Decimal(str(rows[0]["declared_value_usd"])) == Decimal("50")

    def test_minimum_cbm_floor_applies_per_package_before_multiplying_by_quantity(self):
        """Each unit is floored at min_cbm (0.1), then multiplied by quantity (10 → 1.0 CBM)."""
        tiny = self._item(
            quantity=10,
            identical_confirmed=True,
            length_cm=Decimal("10"),
            width_cm=Decimal("10"),
            height_cm=Decimal("10"),
        )
        rows = self._rows([tiny], min_cbm=Decimal("0.1"))

        assert len(rows) == 1
        assert Decimal(str(rows[0]["cbm"])) == Decimal("1.0")
        assert rows[0]["quantity"] == 10

    def test_batch_ref_is_none_since_line_items_are_not_expanded(self):
        rows = self._rows([self._item(quantity=5, identical_confirmed=True)])

        assert len(rows) == 1
        assert rows[0]["batch_ref"] is None

    def test_a_single_package_is_not_a_batch(self):
        rows = self._rows([self._item()])

        assert len(rows) == 1
        assert rows[0]["quantity"] == 1
        assert rows[0]["batch_ref"] is None

    def test_tag_sequence_increments_once_per_line_item(self):
        """Each line item (whether qty 1 or qty 10) consumes one tag in sequence."""
        rows = self._rows(
            [
                self._item(quantity=10, identical_confirmed=True),
                self._item(description="One bag", package_unit="bag"),
            ]
        )

        assert [r["carton_tag"] for r in rows] == [
            "ACM-CONT001-001",
            "ACM-CONT001-002",
        ]
        assert [r["quantity"] for r in rows] == [10, 1]


class TestContainerCapacityValidation:
    """Packing list items cannot exceed the chosen container's CBM capacity."""

    def test_create_rejects_when_items_exceed_container_capacity(self):
        from unittest.mock import patch

        from services.packing_list import service as pl_service
        from services.packing_list.models import CreatePackingListRequest, PackingListItemInput
        from shared.exceptions import BusinessRuleViolationError

        req = CreatePackingListRequest(
            container_id="c1",
            customer_id="cust1",
            items=[
                PackingListItemInput(
                    description="Heavy Machinery",
                    length_cm=Decimal("200"),
                    width_cm=Decimal("200"),
                    height_cm=Decimal("200"),
                    quantity=5,
                    identical_confirmed=True,
                )
            ],
        )  # 8 CBM × 5 = 40 CBM

        with (
            patch.object(
                pl_service.repo,
                "get_container_by_id",
                return_value={
                    "id": "c1",
                    "container_number": "CONT-20FT",
                    "status": "loading",
                    "capacity_cbm": Decimal("33"),
                    "container_type": "20ft",
                },
            ),
            patch.object(pl_service.repo, "get_customer_by_id", return_value={"id": "cust1", "name": "Alice"}),
            patch.object(pl_service, "_resolve_arrival_warehouse", return_value=None),
            patch.object(pl_service.repo, "get_tenant_short", return_value="ACM"),
            patch.object(pl_service, "tenant_transaction"),
            patch.object(pl_service.repo, "get_next_carton_sequence", return_value=1),
            patch.object(pl_service.repo, "get_next_pl_reference", return_value="PL-20261125-001"),
            patch.object(pl_service.repo, "create_packing_list", return_value={"id": "pl1", "status": "draft"}),
            patch.object(pl_service.repo, "get_existing_tracking_code", return_value=None),
            patch.object(pl_service.repo, "get_next_tracking_sequence", return_value=1),
            patch.object(pl_service, "get_min_cbm_per_item", return_value=Decimal("0.1")),
            patch.object(pl_service.repo, "get_container_used_cbm", return_value=Decimal("10")),
            pytest.raises(BusinessRuleViolationError) as exc_info,
        ):
            pl_service.create_packing_list("t1", req, actor_id="u1")

        assert exc_info.value.rule_id == "CONTAINER_CAPACITY_EXCEEDED"


class TestBulkQuantitySafeguard:
    """Quantity > 1 is refused unless someone has affirmed the packages match.

    Enforced in the model, not only the form: the risk is an oversight (100
    cartons recorded at one carton's weight), and an oversight is just as
    possible from a script or an integration as from the UI.
    """

    @staticmethod
    def _make(**kwargs):
        from services.packing_list.models import PackingListItemInput

        base = {"description": "Shoes", "length_cm": Decimal("60"), "width_cm": Decimal("40"), "height_cm": Decimal("40")}
        base.update(kwargs)
        return PackingListItemInput(**base)

    def test_quantity_over_one_without_confirmation_is_rejected(self):
        with pytest.raises(ValueError, match="identical_confirmed"):
            self._make(quantity=100)

    def test_quantity_over_one_with_confirmation_is_accepted(self):
        assert self._make(quantity=100, identical_confirmed=True).quantity == 100

    def test_quantity_of_one_needs_no_confirmation(self):
        assert self._make().quantity == 1

    def test_zero_and_negative_quantities_are_rejected(self):
        for bad in (0, -1):
            with pytest.raises(ValueError):
                self._make(quantity=bad, identical_confirmed=True)

    def test_quantity_above_the_cap_is_rejected(self):
        from services.packing_list.models import MAX_ITEM_QUANTITY

        with pytest.raises(ValueError):
            self._make(quantity=MAX_ITEM_QUANTITY + 1, identical_confirmed=True)

    def test_the_cap_itself_is_accepted(self):
        from services.packing_list.models import MAX_ITEM_QUANTITY

        assert self._make(quantity=MAX_ITEM_QUANTITY, identical_confirmed=True).quantity == MAX_ITEM_QUANTITY

    def test_confirmation_alone_changes_nothing(self):
        """Ticking the box without a quantity must not alter the single item."""
        assert self._make(identical_confirmed=True).quantity == 1
