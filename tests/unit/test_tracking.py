"""Unit tests for services.tracking.service — container state machine, shipment tracking."""
from unittest.mock import patch

import pytest

from shared.exceptions import (
    BusinessRuleViolationError,
    IllegalTransitionError,
    InsufficientPermissionsError,
    ResourceNotFoundError,
)
from shared.tenant_context import TenantContext, UserRole

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _ctx(role: UserRole) -> TenantContext:
    return TenantContext(tenant_id=TENANT_ID, user_id="user-1", role=role)


def _container(**kw) -> dict:
    base = {
        "id": "container-001",
        "tenant_id": TENANT_ID,
        "container_number": "CONT-001",
        "status": "loading",
        "origin": "China",
        "destination": "Nigeria",
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# State machine constants
# ---------------------------------------------------------------------------


class TestNextStateMap:
    """Verify the linear state machine is correctly defined."""

    def test_full_chain(self):
        from services.tracking.service import _NEXT_STATE

        chain = [
            ("loading", "sealed"),
            ("sealed", "in_transit"),
            ("in_transit", "arrived"),
            ("arrived", "customs_clearance"),
            ("customs_clearance", "cleared"),
            ("cleared", "at_warehouse"),
            ("at_warehouse", "fully_released"),
        ]
        for current, expected_next in chain:
            assert _NEXT_STATE[current] == expected_next

    def test_fully_released_has_no_next(self):
        from services.tracking.service import _NEXT_STATE

        assert "fully_released" not in _NEXT_STATE


# ---------------------------------------------------------------------------
# create_container
# ---------------------------------------------------------------------------


class TestCreateContainer:
    def test_missing_container_number_raises(self):
        from services.tracking import service

        with pytest.raises(BusinessRuleViolationError):
            service.create_container(TENANT_ID, {}, actor_id="u")

    def test_creates_and_returns_row(self):
        from services.tracking import service

        row = _container()
        with (
            patch.object(service.repo, "create_container", return_value=row),
            patch("services.tracking.service.log_audit"),
            patch("services.tracking.service.check_container_limit"),
        ):
            result = service.create_container(
                TENANT_ID,
                {"container_number": "CONT-001", "origin": "China"},
                actor_id="u",
            )

        assert result["container_number"] == "CONT-001"


# ---------------------------------------------------------------------------
# get_container
# ---------------------------------------------------------------------------


class TestGetContainer:
    def test_not_found_raises(self):
        from services.tracking import service

        with patch.object(service.repo, "get_container_by_id", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.get_container(TENANT_ID, "nonexistent")

    def test_returns_container(self):
        from services.tracking import service

        container = _container()
        with patch.object(service.repo, "get_container_by_id", return_value=container):
            result = service.get_container(TENANT_ID, "container-001")

        assert result["id"] == "container-001"


# ---------------------------------------------------------------------------
# update_container_status — state machine transitions
# ---------------------------------------------------------------------------


class TestUpdateContainerStatus:
    def _update(self, current_status: str, new_status: str, ctx: TenantContext, extra=None):
        from services.tracking import service

        container = _container(status=current_status)
        updated = {**container, "status": new_status}

        with (
            patch.object(service.repo, "get_container_by_id", return_value=container),
            patch.object(service.repo, "update_container_status", return_value=updated),
            patch.object(service.repo, "count_approved_packing_lists", return_value=1),
            patch.object(service.repo, "get_manifest_for_container", return_value={"id": "m-001"}),
            patch.object(service.repo, "bulk_update_tracking_status"),
            patch.object(service.repo, "bulk_insert_tracking_events"),
            patch.object(service.repo, "get_customers_for_container", return_value=[]),
            patch("services.tracking.service.publish_event"),
            patch("services.tracking.service.log_audit"),
        ):
            return service.update_container_status(
                TENANT_ID, "container-001", new_status, extra=extra or {}, actor_id="u", ctx=ctx
            )

    def test_invalid_transition_raises(self):
        from services.tracking import service

        container = _container(status="loading")
        with (
            patch.object(service.repo, "get_container_by_id", return_value=container),
        ):
            with pytest.raises(IllegalTransitionError):
                service.update_container_status(
                    TENANT_ID, "container-001", "cleared", extra={}, actor_id="u", ctx=_ctx(UserRole.CHINA_OFFICE_STAFF)
                )

    def test_not_found_raises(self):
        from services.tracking import service

        with patch.object(service.repo, "get_container_by_id", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.update_container_status(
                    TENANT_ID, "nonexistent", "sealed", extra={}, actor_id="u", ctx=_ctx(UserRole.CHINA_OFFICE_STAFF)
                )

    def test_china_staff_can_seal(self):
        """loading → sealed requires CHINA_OFFICE_STAFF."""
        result = self._update("loading", "sealed", _ctx(UserRole.CHINA_OFFICE_STAFF))
        assert result["status"] == "sealed"

    def test_nigeria_staff_cannot_seal(self):
        """Nigeria staff cannot transition from loading stage."""
        from services.tracking import service

        container = _container(status="loading")
        with (
            patch.object(service.repo, "get_container_by_id", return_value=container),
        ):
            with pytest.raises(InsufficientPermissionsError):
                service.update_container_status(
                    TENANT_ID, "container-001", "sealed", extra={}, actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
                )

    def test_nigeria_staff_can_advance_in_transit(self):
        """in_transit → arrived requires NIGERIA_OFFICE_STAFF."""
        result = self._update("in_transit", "arrived", _ctx(UserRole.NIGERIA_OFFICE_STAFF))
        assert result["status"] == "arrived"

    def test_china_staff_cannot_advance_from_in_transit(self):
        from services.tracking import service

        container = _container(status="in_transit")
        with (
            patch.object(service.repo, "get_container_by_id", return_value=container),
        ):
            with pytest.raises(InsufficientPermissionsError):
                service.update_container_status(
                    TENANT_ID, "container-001", "arrived", extra={}, actor_id="u", ctx=_ctx(UserRole.CHINA_OFFICE_STAFF)
                )

    def test_tenant_admin_can_perform_any_stage(self):
        """TENANT_ADMIN is allowed for all stages."""
        result = self._update("loading", "sealed", _ctx(UserRole.TENANT_ADMIN))
        assert result["status"] == "sealed"

    def test_sealing_requires_approved_packing_list(self):
        from services.tracking import service

        container = _container(status="loading")
        with (
            patch.object(service.repo, "get_container_by_id", return_value=container),
            patch.object(service.repo, "count_approved_packing_lists", return_value=0),
        ):
            with pytest.raises(BusinessRuleViolationError) as exc_info:
                service.update_container_status(
                    TENANT_ID, "container-001", "sealed", extra={}, actor_id="u", ctx=_ctx(UserRole.CHINA_OFFICE_STAFF)
                )
            assert "NO_APPROVED_PACKING_LISTS" in str(exc_info.value.rule_id)

    def test_sealing_requires_manifest(self):
        from services.tracking import service

        container = _container(status="loading")
        with (
            patch.object(service.repo, "get_container_by_id", return_value=container),
            patch.object(service.repo, "count_approved_packing_lists", return_value=1),
            patch.object(service.repo, "get_manifest_for_container", return_value=None),
        ):
            with pytest.raises(BusinessRuleViolationError) as exc_info:
                service.update_container_status(
                    TENANT_ID, "container-001", "sealed", extra={}, actor_id="u", ctx=_ctx(UserRole.CHINA_OFFICE_STAFF)
                )
            assert "NO_MANIFEST" in str(exc_info.value.rule_id)

    def test_in_transit_requires_ship_date(self):
        from services.tracking import service

        container = _container(status="sealed")
        with (
            patch.object(service.repo, "get_container_by_id", return_value=container),
        ):
            with pytest.raises(BusinessRuleViolationError) as exc_info:
                service.update_container_status(
                    TENANT_ID,
                    "container-001",
                    "in_transit",
                    extra={},  # no ship_date
                    actor_id="u",
                    ctx=_ctx(UserRole.CHINA_OFFICE_STAFF),
                )
            assert "MISSING_SHIP_DATE" in str(exc_info.value.rule_id)

    def test_in_transit_with_ship_date_succeeds(self):
        result = self._update("sealed", "in_transit", _ctx(UserRole.CHINA_OFFICE_STAFF), extra={"ship_date": "2026-01-15"})
        assert result["status"] == "in_transit"

    def test_cleared_publishes_payment_due_per_customer(self):
        from services.tracking import service

        container = _container(status="customs_clearance")
        updated = {**container, "status": "cleared"}
        customers = [{"id": "cust-001", "name": "Alice"}, {"id": "cust-002", "name": "Bob"}]

        with (
            patch.object(service.repo, "get_container_by_id", return_value=container),
            patch.object(service.repo, "update_container_status", return_value=updated),
            patch.object(service.repo, "bulk_update_tracking_status"),
            patch.object(service.repo, "bulk_insert_tracking_events"),
            patch.object(service.repo, "get_customers_for_container", return_value=customers),
            patch("services.tracking.service.publish_event") as mock_publish,
            patch("services.tracking.service.log_audit"),
        ):
            service.update_container_status(
                TENANT_ID, "container-001", "cleared", extra={}, actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
            )

        # PaymentDue for each customer + ContainerStatusUpdated
        event_types = [c[1]["detail_type"] for c in mock_publish.call_args_list]
        assert event_types.count("PaymentDue") == 2
        assert "ContainerStatusUpdated" in event_types


# ---------------------------------------------------------------------------
# Tracking status → TrackingStage mapping
# ---------------------------------------------------------------------------


class TestTrackingStageMapping:
    def test_status_to_stage_covers_all_db_statuses(self):
        from services.tracking.service import _STATUS_TO_STAGE

        expected_db_statuses = {
            "received",
            "in_transit",
            "arrived_port",
            "customs_clearance",
            "at_warehouse",
            "ready_for_pickup",
            "released",
        }
        assert set(_STATUS_TO_STAGE.keys()) == expected_db_statuses

    def test_container_to_tracking_status_keys(self):
        from services.tracking.service import _CONTAINER_TO_TRACKING_STATUS

        # These container statuses should produce tracking status updates
        transitioned = {"in_transit", "arrived", "customs_clearance", "cleared", "at_warehouse", "fully_released"}
        assert set(_CONTAINER_TO_TRACKING_STATUS.keys()) == transitioned


# ---------------------------------------------------------------------------
# list_shipments — customer isolation
# ---------------------------------------------------------------------------


class TestListShipments:
    def test_customer_scoped_to_own_shipments(self):
        from services.tracking import service

        customer = {"id": "cust-001"}
        rows = [{"tracking_code": "TK-001", "status": "received"}]

        with (
            patch.object(service.repo, "get_customer_by_user_id", return_value=customer),
            patch.object(service.repo, "list_customer_shipments", return_value=(rows, None, False)) as mock_list,
        ):
            ctx = _ctx(UserRole.CUSTOMER)
            service.list_shipments(TENANT_ID, {}, 20, None, ctx)

        mock_list.assert_called_once_with(TENANT_ID, "cust-001", 20, None)

    def test_customer_with_no_record_returns_empty(self):
        from services.tracking import service

        with patch.object(service.repo, "get_customer_by_user_id", return_value=None):
            ctx = _ctx(UserRole.CUSTOMER)
            rows, cursor, has_more = service.list_shipments(TENANT_ID, {}, 20, None, ctx)

        assert rows == []
        assert cursor is None
        assert not has_more

    def test_staff_sees_all_shipments(self):
        from services.tracking import service

        rows = [{"tracking_code": "TK-001"}]
        with patch.object(service.repo, "list_shipments", return_value=(rows, None, False)) as mock_list:
            ctx = _ctx(UserRole.NIGERIA_OFFICE_STAFF)
            service.list_shipments(TENANT_ID, {}, 20, None, ctx)

        mock_list.assert_called_once()


# ---------------------------------------------------------------------------
# get_shipment_by_code_and_phone — public tracking
# ---------------------------------------------------------------------------


class TestGetShipmentByCodeAndPhone:
    def test_not_found_raises(self):
        from services.tracking import service

        with patch.object(service.repo, "get_shipment_by_tracking_code_and_phone", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.get_shipment_by_code_and_phone("UNKNOWN-CODE", "+2348012345678")

    def test_returns_stage_history(self):
        from datetime import datetime

        from services.tracking import service

        row = {
            "id": "ship-001",
            "tracking_code": "TK-001",
            "status": "in_transit",
            "company_name": "ACME Logistics",
            "branding_config": None,
        }
        events = [
            {"to_status": "in_transit", "created_at": datetime(2026, 1, 10), "description": "Departed China"},
        ]

        with (
            patch.object(service.repo, "get_shipment_by_tracking_code_and_phone", return_value=row),
            patch.object(service.repo, "get_tracking_events", return_value=events),
        ):
            result = service.get_shipment_by_code_and_phone("TK-001", "+234801")

        assert result["tracking_code"] == "TK-001"
        assert result["current_stage"] == "in_transit"
        assert len(result["stage_history"]) == 1
        assert result["stage_history"][0]["notes"] == "Departed China"

    def test_branding_config_overrides_company_name(self):
        from services.tracking import service

        row = {
            "id": "ship-001",
            "tracking_code": "TK-001",
            "status": "received",
            "company_name": "Old Name",
            "branding_config": {"display_name": "Branded Logistics"},
        }

        with (
            patch.object(service.repo, "get_shipment_by_tracking_code_and_phone", return_value=row),
            patch.object(service.repo, "get_tracking_events", return_value=[]),
        ):
            result = service.get_shipment_by_code_and_phone("TK-001", "+234801")

        assert result["company_name"] == "Branded Logistics"
