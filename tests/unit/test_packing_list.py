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
            patch.object(service.repo, "list_packing_list_items", return_value=[]),
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
        mock_set.assert_called_once_with(_BULK_TENANT_ID, ["pl-1"], "pending_approval", "staff-1")
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
