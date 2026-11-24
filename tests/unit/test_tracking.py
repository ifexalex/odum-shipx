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

    def test_persists_capacity_snapshot(self):
        from services.tracking import service

        row = _container()
        with (
            patch.object(service.repo, "create_container", return_value=row) as m,
            patch("services.tracking.service.log_audit"),
            patch("services.tracking.service.check_container_limit"),
        ):
            service.create_container(
                TENANT_ID,
                {
                    "container_number": "CONT-001",
                    "container_type": "40' High Cube (HC)",
                    "capacity_cbm": 76,
                    "recommended_cbm": 70,
                },
                actor_id="u",
            )
        sent = m.call_args[0][1]
        assert sent["capacity_cbm"] == 76.0
        assert sent["recommended_cbm"] == 70.0
        assert sent["container_type"] == "40' High Cube (HC)"

    def test_blank_capacity_stored_as_none(self):
        from services.tracking import service

        row = _container()
        with (
            patch.object(service.repo, "create_container", return_value=row) as m,
            patch("services.tracking.service.log_audit"),
            patch("services.tracking.service.check_container_limit"),
        ):
            service.create_container(
                TENANT_ID,
                {"container_number": "CONT-001", "capacity_cbm": "", "recommended_cbm": 0},
                actor_id="u",
            )
        sent = m.call_args[0][1]
        # Guards the NUMERIC(>0) CHECK — blank/zero becomes NULL, not a 422.
        assert sent["capacity_cbm"] is None
        assert sent["recommended_cbm"] is None


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
            patch.object(
                service.repo, "get_manifest_for_container", return_value={"id": "m-001", "verification_status": "verified"}
            ),
            patch.object(service.repo, "bulk_update_tracking_status"),
            patch.object(service.repo, "bulk_insert_tracking_events"),
            patch.object(service.repo, "get_customers_for_container", return_value=[]),
            patch.object(service.repo, "insert_container_event"),
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
        created_rows = [
            {"customer_id": "cust-001", "customer_name": "Alice", "status": "created", "reason": None},
            {"customer_id": "cust-002", "customer_name": "Bob", "status": "created", "reason": None},
        ]

        with (
            patch.object(service.repo, "get_container_by_id", return_value=container),
            patch.object(service.repo, "update_container_status", return_value=updated),
            patch.object(service.repo, "bulk_update_tracking_status"),
            patch.object(service.repo, "bulk_insert_tracking_events"),
            patch.object(service.repo, "get_customers_for_container", return_value=customers),
            patch.object(service.repo, "insert_container_event"),
            patch("services.tracking.service.publish_event") as mock_publish,
            patch("services.tracking.service.generate_container_invoices", return_value=created_rows) as mock_generate,
            patch("services.tracking.service.log_audit"),
        ):
            result = service.update_container_status(
                TENANT_ID, "container-001", "cleared", extra={}, actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
            )

        # PaymentDue for each customer + ContainerStatusUpdated
        event_types = [c[1]["detail_type"] for c in mock_publish.call_args_list]
        assert event_types.count("PaymentDue") == 2
        assert "ContainerStatusUpdated" in event_types

        # Ground-truth fix: billing must be generated synchronously here — the
        # EventBridge PaymentDue event above is never wired to invoke the
        # billing Lambda (infrastructure/aws/modules/eventbridge/main.tf only
        # fans it out to SMS/WhatsApp queues), so without this direct call a
        # cleared container would carry zero billing records forever.
        mock_generate.assert_called_once()
        kwargs = mock_generate.call_args.kwargs
        assert kwargs["tenant_id"] == TENANT_ID
        assert kwargs["container_id"] == "container-001"
        assert [c["id"] for c in kwargs["customers"]] == ["cust-001", "cust-002"]

        # The per-customer outcome is returned so staff see it at the moment of clearing.
        assert result["billing_summary"] == created_rows

    def test_cleared_reports_unbilled_customers_and_only_announces_the_invoiced(self):
        """A customer whose invoice could not be created is reported in the
        response and gets no PaymentDue event; the other customer is unaffected."""
        from services.tracking import service

        container = _container(status="customs_clearance")
        updated = {**container, "status": "cleared"}
        customers = [{"id": "cust-001", "name": "Alice"}, {"id": "cust-002", "name": "Bob"}]
        rows = [
            {"customer_id": "cust-001", "customer_name": "Alice", "status": "created", "reason": None},
            {"customer_id": "cust-002", "customer_name": "Bob", "status": "failed", "reason": "GENERATION_ERROR"},
        ]

        with (
            patch.object(service.repo, "get_container_by_id", return_value=container),
            patch.object(service.repo, "update_container_status", return_value=updated),
            patch.object(service.repo, "bulk_update_tracking_status"),
            patch.object(service.repo, "bulk_insert_tracking_events"),
            patch.object(service.repo, "get_customers_for_container", return_value=customers),
            patch.object(service.repo, "insert_container_event"),
            patch("services.tracking.service.publish_event") as mock_publish,
            patch("services.tracking.service.generate_container_invoices", return_value=rows),
            patch("services.tracking.service.log_audit"),
        ):
            result = service.update_container_status(
                TENANT_ID, "container-001", "cleared", extra={}, actor_id="u", ctx=_ctx(UserRole.NIGERIA_OFFICE_STAFF)
            )

        payment_due = [c[1]["payload"]["customer_id"] for c in mock_publish.call_args_list if c[1]["detail_type"] == "PaymentDue"]
        assert payment_due == ["cust-001"]
        assert result["billing_summary"][1]["status"] == "failed"
        assert result["status"] == "cleared"


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


class TestListContainersRepository:
    """Regression coverage for services/tracking/repository.py::list_containers
    SQL construction. The `q` free-text filter used to be folded into the
    blanket-prefixed `conditions` list, producing invalid SQL of the shape
    `c.(c.container_number ILIKE ...)` — a syntax error on every request that
    used the container search box (table search bar and header search alike).
    """

    def test_q_filter_produces_valid_where_clause(self):
        from services.tracking import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            repository.list_containers(TENANT_ID, {"q": "MSCU"}, limit=50, cursor=None)

        query = mock_exec.call_args[0][1]
        assert "c.(c." not in query
        assert "(c.container_number ILIKE %(q)s" in query
        assert "OR c.vessel_name ILIKE %(q)s" in query
        assert "OR c.voyage_number ILIKE %(q)s" in query

    def test_status_filter_scoped_to_alias(self):
        from services.tracking import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            repository.list_containers(TENANT_ID, {"status": "sealed"}, limit=50, cursor=None)

        query = mock_exec.call_args[0][1]
        params = mock_exec.call_args[0][2]
        assert "c.status = ANY(%(statuses)s)" in query
        assert params["statuses"] == ["sealed"]

    def test_status_filter_accepts_a_list_for_the_filters_panel_multi_select(self):
        """Filters panel status multi-select sends several statuses at once —
        handler.py splits the comma-separated `status` query param into a list
        before it reaches the repo. Must produce a single parameterized
        ANY(...) clause, never a string-interpolated IN (...)."""
        from services.tracking import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            repository.list_containers(TENANT_ID, {"status": ["sealed", "in_transit", "cleared"]}, limit=50, cursor=None)

        query = mock_exec.call_args[0][1]
        params = mock_exec.call_args[0][2]
        assert "c.status = ANY(%(statuses)s)" in query
        assert params["statuses"] == ["sealed", "in_transit", "cleared"]

    def test_created_after_and_before_filters_added(self):
        from services.tracking import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            repository.list_containers(
                TENANT_ID,
                {"created_after": "2026-06-01", "created_before": "2026-07-01"},
                limit=50,
                cursor=None,
            )

        query = mock_exec.call_args[0][1]
        params = mock_exec.call_args[0][2]
        assert "c.created_at >= %(created_after)s" in query
        assert "c.created_at <= %(created_before)s" in query
        assert params["created_after"] == "2026-06-01"
        assert params["created_before"] == "2026-07-01"

    def test_eta_after_and_before_filters_added(self):
        """Filters panel's "Arriving" preset — ETA range is distinct from the
        `created_after`/`created_before` "date created" filter (row 7.36)."""
        from services.tracking import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            repository.list_containers(
                TENANT_ID,
                {"eta_after": "2026-07-19", "eta_before": "2026-08-18"},
                limit=50,
                cursor=None,
            )

        query = mock_exec.call_args[0][1]
        params = mock_exec.call_args[0][2]
        assert "c.estimated_arrival_date >= %(eta_after)s" in query
        assert "c.estimated_arrival_date <= %(eta_before)s" in query
        assert params["eta_after"] == "2026-07-19"
        assert params["eta_before"] == "2026-08-18"

    def test_sort_field_defaults_to_created_at(self):
        from services.tracking import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            repository.list_containers(TENANT_ID, {}, limit=50, cursor=None)

        query = mock_exec.call_args[0][1]
        assert "ORDER BY created_at DESC" in query

    def test_sort_field_container_number_ascending(self):
        from services.tracking import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            repository.list_containers(
                TENANT_ID,
                {},
                limit=50,
                cursor=None,
                sort_field="container_number",
                sort_direction="asc",
            )

        query = mock_exec.call_args[0][1]
        assert "ORDER BY container_number ASC" in query

    def test_sort_field_estimated_arrival_date(self):
        from services.tracking import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            repository.list_containers(
                TENANT_ID,
                {},
                limit=50,
                cursor=None,
                sort_field="estimated_arrival_date",
                sort_direction="asc",
            )

        query = mock_exec.call_args[0][1]
        assert "ORDER BY estimated_arrival_date ASC" in query

    def test_invalid_sort_field_rejected(self):
        from services.tracking import repository
        from shared.exceptions import ValidationError

        with patch.object(repository, "execute_with_tenant", return_value=[]):
            with pytest.raises(ValidationError):
                repository.list_containers(TENANT_ID, {}, limit=50, cursor=None, sort_field="notes")


class TestContainersHandlerQueryParams:
    """GET /v1/containers — handler-level parsing of the Filters panel's
    comma-separated multi-status param and the Table sort/direction params."""

    def _event(self, query: dict | None = None) -> dict:
        return {
            "requestContext": {
                "requestId": "req-containers-001",
                "http": {"method": "GET", "path": "/v1/containers"},
                "authorizer": {"claims": {"sub": "user-1", "custom:tenant_id": TENANT_ID}},
                "identity": {"sourceIp": "127.0.0.1"},
            },
            "headers": {},
            "body": "{}",
            "queryStringParameters": query or {},
            "pathParameters": {},
        }

    def test_comma_separated_status_becomes_a_list_filter(self):
        from services.tracking import handler, service

        with (
            patch("services.tracking.handler.get_tenant_context", return_value=_ctx(UserRole.CHINA_OFFICE_STAFF)),
            patch.object(service.repo, "list_containers", return_value=([], None, False)) as mock_list,
        ):
            resp = handler.lambda_handler(self._event({"status": "sealed,in_transit,cleared"}), None)

        assert resp["statusCode"] == 200
        filters = mock_list.call_args[0][1]
        assert filters["status"] == ["sealed", "in_transit", "cleared"]

    def test_sort_and_direction_query_params_reach_the_repo(self):
        from services.tracking import handler, service

        with (
            patch("services.tracking.handler.get_tenant_context", return_value=_ctx(UserRole.CHINA_OFFICE_STAFF)),
            patch.object(service.repo, "list_containers", return_value=([], None, False)) as mock_list,
        ):
            resp = handler.lambda_handler(self._event({"sort": "container_number", "direction": "asc"}), None)

        assert resp["statusCode"] == 200
        assert mock_list.call_args.args[4] == "container_number"
        assert mock_list.call_args.args[5] == "asc"

    def test_eta_range_query_params_reach_the_repo(self):
        from services.tracking import handler, service

        with (
            patch("services.tracking.handler.get_tenant_context", return_value=_ctx(UserRole.CHINA_OFFICE_STAFF)),
            patch.object(service.repo, "list_containers", return_value=([], None, False)) as mock_list,
        ):
            resp = handler.lambda_handler(self._event({"eta_after": "2026-07-19", "eta_before": "2026-08-18"}), None)

        assert resp["statusCode"] == 200
        filters = mock_list.call_args[0][1]
        assert filters["eta_after"] == "2026-07-19"
        assert filters["eta_before"] == "2026-08-18"


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
    # Reported/found 2026-11-02: the lookup matched the submitted phone against
    # customer.phone as one exact string, with no normalisation. Customer phones
    # are stored E.164, so a customer entering their own number the way they
    # always write it — 08012345678 — got "not found". Public tracking was
    # effectively unusable unless you happened to type the full +234 form.

    def test_a_local_format_number_matches_a_stored_e164_customer(self):
        from services.tracking import service

        with (
            patch.object(
                service.repo,
                "get_shipment_by_tracking_code_and_phone",
                return_value={
                    "id": "s1",
                    "tracking_code": "TK-001",
                    "status": "in_transit",
                    "company_name": "ACME",
                    "branding_config": None,
                },
            ) as mock_lookup,
            patch.object(service.repo, "get_tracking_events", return_value=[]),
        ):
            service.get_shipment_by_code_and_phone("TK-001", "08012345678")

        candidates = mock_lookup.call_args.args[1]
        assert "+2348012345678" in candidates, "the local-format number must be normalised to E.164 before matching"

    def test_the_raw_input_is_also_offered_as_a_candidate(self):
        """Rows written before normalisation existed may still hold a
        local-format value, and a foreign number would be mangled by the default
        Nigerian dial code — so the untouched input stays a candidate."""
        from services.tracking import service

        with (
            patch.object(service.repo, "get_shipment_by_tracking_code_and_phone", return_value=None) as mock_lookup,
            pytest.raises(ResourceNotFoundError),
        ):
            service.get_shipment_by_code_and_phone("TK-001", "08012345678")

        candidates = mock_lookup.call_args.args[1]
        assert "08012345678" in candidates

    def test_an_e164_number_is_passed_through_unchanged(self):
        from services.tracking import service

        with (
            patch.object(service.repo, "get_shipment_by_tracking_code_and_phone", return_value=None) as mock_lookup,
            pytest.raises(ResourceNotFoundError),
        ):
            service.get_shipment_by_code_and_phone("TK-001", "+2348012345678")

        assert mock_lookup.call_args.args[1] == ["+2348012345678"]

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
        assert result["brand_color"] is None

    @pytest.mark.parametrize(
        ("configured", "returned"),
        [
            ("#1B5E20", "#1B5E20"),
            ("#1b5e20", "#1b5e20"),
            ("red", None),
            ("#fff", None),
            ("#1B5E20; background:url(x)", None),
            (123, None),
        ],
    )
    def test_brand_color_is_returned_only_as_a_plain_hex(self, configured, returned):
        # FD-28: the public page puts this in a style, so anything but #rrggbb is dropped.
        from services.tracking import service

        row = {
            "id": "ship-001",
            "tracking_code": "TK-001",
            "status": "received",
            "company_name": "ACME",
            "branding_config": {"primary_color": configured},
        }

        with (
            patch.object(service.repo, "get_shipment_by_tracking_code_and_phone", return_value=row),
            patch.object(service.repo, "get_tracking_events", return_value=[]),
        ):
            result = service.get_shipment_by_code_and_phone("TK-001", "+234801")

        assert result["brand_color"] == returned


# ---------------------------------------------------------------------------
# Container event audit trail
# ---------------------------------------------------------------------------

import sys
from unittest.mock import MagicMock as _MagicMock

# Stub metering so tracking.service can be imported without the full services/ tree
_metering_stub = _MagicMock()
_metering_stub.service.check_container_limit = _MagicMock(return_value=None)
sys.modules.setdefault("metering", _metering_stub)
sys.modules.setdefault("metering.service", _metering_stub.service)


class TestContainerEvents:
    def test_get_container_events_returns_ordered_history(self):
        from services.tracking import service

        container = {"id": "container-001", "status": "cleared"}
        events = [
            {"id": "ev-1", "from_status": "loading", "to_status": "sealed", "actor_id": "u", "created_at": None},
            {"id": "ev-2", "from_status": "sealed", "to_status": "in_transit", "actor_id": "u", "created_at": None},
        ]

        with (
            patch.object(service.repo, "get_container_by_id", return_value=container),
            patch.object(service.repo, "get_container_events", return_value=events),
        ):
            result = service.get_container_events("tenant-1", "container-001")
            assert len(result) == 2
            assert result[0]["to_status"] == "sealed"
            assert result[1]["to_status"] == "in_transit"

    def test_get_container_events_container_not_found_raises(self):
        from services.tracking import service
        from shared.exceptions import ResourceNotFoundError

        with patch.object(service.repo, "get_container_by_id", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.get_container_events("tenant-1", "nonexistent")

    def test_update_container_status_writes_event(self):
        """Every successful status transition must append a container_event row."""
        from services.tracking import service
        from shared.tenant_context import TenantContext, UserRole

        ctx = TenantContext(tenant_id="tenant-1", user_id="actor-1", role=UserRole.CHINA_OFFICE_STAFF)
        container = {"id": "container-001", "status": "loading", "container_number": "ACME-001"}
        updated = {**container, "status": "sealed"}

        with (
            patch.object(service.repo, "get_container_by_id", return_value=container),
            patch.object(service.repo, "count_approved_packing_lists", return_value=1),
            patch.object(
                service.repo, "get_manifest_for_container", return_value={"id": "manifest-1", "verification_status": "verified"}
            ),
            patch.object(service.repo, "update_container_status", return_value=updated),
            patch.object(service.repo, "insert_container_event") as mock_event,
            patch.object(service.repo, "bulk_update_tracking_status"),
            patch.object(service.repo, "bulk_insert_tracking_events"),
            patch("services.tracking.service.publish_event"),
            patch("services.tracking.service.log_audit"),
        ):
            service.update_container_status("tenant-1", "container-001", "sealed", {}, actor_id="actor-1", ctx=ctx)
            mock_event.assert_called_once_with(
                tenant_id="tenant-1",
                container_id="container-001",
                from_status="loading",
                to_status="sealed",
                actor_id="actor-1",
                notes=None,
            )

    def test_update_container_status_event_captures_notes(self):
        """Notes from extra dict are forwarded to insert_container_event."""
        from services.tracking import service
        from shared.tenant_context import TenantContext, UserRole

        ctx = TenantContext(tenant_id="tenant-1", user_id="actor-1", role=UserRole.NIGERIA_OFFICE_STAFF)
        container = {"id": "container-001", "status": "arrived", "container_number": "ACME-001"}
        updated = {**container, "status": "customs_clearance"}

        with (
            patch.object(service.repo, "get_container_by_id", return_value=container),
            patch.object(service.repo, "update_container_status", return_value=updated),
            patch.object(service.repo, "insert_container_event") as mock_event,
            patch.object(service.repo, "bulk_update_tracking_status"),
            patch.object(service.repo, "bulk_insert_tracking_events"),
            patch("services.tracking.service.publish_event"),
            patch("services.tracking.service.log_audit"),
        ):
            service.update_container_status(
                "tenant-1", "container-001", "customs_clearance", {"notes": "Passed inspection"}, actor_id="actor-1", ctx=ctx
            )
            _, kwargs = mock_event.call_args
            assert kwargs["notes"] == "Passed inspection"


class TestShipmentUpdateNotification:
    """Ground-truth gap found live, reported by the user while investigating
    a separate missing notification on payment-claim rejection — asked to
    check every notification in the app. `shipment_update` had full SMS/
    WhatsApp/email templates defined but no call site ever used it — the
    customer-visible status transitions (in_transit, arrived,
    customs_clearance, fully_released) sent no notification at all."""

    def _transition(self, from_status: str, new_status: str):
        from services.tracking import service
        from shared.tenant_context import TenantContext, UserRole

        # TENANT_ADMIN is allowed to transition from any stage — avoids
        # threading the right china/nigeria/warehouse role per from_status.
        ctx = TenantContext(tenant_id="tenant-1", user_id="actor-1", role=UserRole.TENANT_ADMIN)
        container = {"id": "container-001", "status": from_status, "container_number": "ACME-001"}
        updated = {**container, "status": new_status}
        customer = {
            "id": "cust-1",
            "name": "Ngozi",
            "phone": "+2348012345678",
            "email": "n@x.com",
            "whatsapp": None,
            "locale": "en",
        }
        extra = {"ship_date": "2026-09-09"} if new_status == "in_transit" else {}

        with (
            patch.object(service.repo, "get_container_by_id", return_value=container),
            patch.object(service.repo, "update_container_status", return_value=updated),
            patch.object(service.repo, "insert_container_event"),
            patch.object(service.repo, "bulk_update_tracking_status"),
            patch.object(service.repo, "bulk_insert_tracking_events"),
            patch.object(service.repo, "get_customers_for_container", return_value=[customer]) as mock_customers,
            patch("services.tracking.service.publish_event"),
            patch("services.tracking.service.log_audit"),
            patch("services.tracking.service.enqueue_notifications") as mock_notify,
        ):
            service.update_container_status("tenant-1", "container-001", new_status, extra, actor_id="actor-1", ctx=ctx)
        return mock_customers, mock_notify

    def test_in_transit_notifies_the_customer(self):
        _, mock_notify = self._transition("sealed", "in_transit")
        mock_notify.assert_called_once()
        assert mock_notify.call_args.kwargs["event_type"] == "shipment_update"
        assert mock_notify.call_args.kwargs["template_data"]["status"] == "in transit"
        assert mock_notify.call_args.kwargs["customer_id"] == "cust-1"

    def test_customs_clearance_notifies_the_customer(self):
        _, mock_notify = self._transition("arrived", "customs_clearance")
        mock_notify.assert_called_once()
        assert mock_notify.call_args.kwargs["template_data"]["status"] == "customs clearance"

    def test_fully_released_notifies_the_customer(self):
        _, mock_notify = self._transition("at_warehouse", "fully_released")
        mock_notify.assert_called_once()
        assert mock_notify.call_args.kwargs["template_data"]["status"] == "fully released"

    def test_cleared_does_not_send_a_redundant_shipment_update(self):
        """`cleared` is covered by handle_payment_due's own payment_due
        notification (called separately) — a bare "status changed" ping
        here would be redundant with "here's what you owe"."""

        with patch("services.tracking.service.generate_container_invoices", return_value=[]):
            _, mock_notify = self._transition("customs_clearance", "cleared")
        mock_notify.assert_not_called()

    def test_a_customer_fetch_failure_does_not_fail_the_transition(self):
        from services.tracking import service
        from shared.tenant_context import TenantContext, UserRole

        ctx = TenantContext(tenant_id="tenant-1", user_id="actor-1", role=UserRole.TENANT_ADMIN)
        container = {"id": "container-001", "status": "sealed", "container_number": "ACME-001"}
        updated = {**container, "status": "in_transit"}

        with (
            patch.object(service.repo, "get_container_by_id", return_value=container),
            patch.object(service.repo, "update_container_status", return_value=updated),
            patch.object(service.repo, "insert_container_event"),
            patch.object(service.repo, "bulk_update_tracking_status"),
            patch.object(service.repo, "bulk_insert_tracking_events"),
            patch.object(service.repo, "get_customers_for_container", side_effect=RuntimeError("db down")),
            patch("services.tracking.service.publish_event"),
            patch("services.tracking.service.log_audit"),
        ):
            result = service.update_container_status(
                "tenant-1",
                "container-001",
                "in_transit",
                {"ship_date": "2026-09-09"},
                actor_id="actor-1",
                ctx=ctx,
            )

        assert result["status"] == "in_transit"

    def test_shipment_update_also_notifies_the_customer_in_app_when_they_have_a_portal_account(self):
        """Ground-truth follow-up, reported live by the user: SMS/WhatsApp/
        email can each fail for reasons entirely outside this app, and the
        customer portal itself showed nothing until they happened to open
        the specific shipment page."""
        from services.tracking import service
        from shared.tenant_context import TenantContext, UserRole

        ctx = TenantContext(tenant_id="tenant-1", user_id="actor-1", role=UserRole.TENANT_ADMIN)
        container = {"id": "container-001", "status": "sealed", "container_number": "ACME-001"}
        updated = {**container, "status": "in_transit"}
        customer = {
            "id": "cust-1",
            "user_id": "portal-user-001",
            "name": "Ngozi",
            "phone": "+2348012345678",
            "email": "n@x.com",
            "whatsapp": None,
            "locale": "en",
        }

        with (
            patch.object(service.repo, "get_container_by_id", return_value=container),
            patch.object(service.repo, "update_container_status", return_value=updated),
            patch.object(service.repo, "insert_container_event"),
            patch.object(service.repo, "bulk_update_tracking_status"),
            patch.object(service.repo, "bulk_insert_tracking_events"),
            patch.object(service.repo, "get_customers_for_container", return_value=[customer]),
            patch("services.tracking.service.publish_event"),
            patch("services.tracking.service.log_audit"),
            patch("services.tracking.service.enqueue_notifications"),
            patch("services.tracking.service.notify_staff") as mock_notify_staff,
        ):
            service.update_container_status(
                "tenant-1",
                "container-001",
                "in_transit",
                {"ship_date": "2026-09-09"},
                actor_id="actor-1",
                ctx=ctx,
            )

        mock_notify_staff.assert_called_once()
        assert mock_notify_staff.call_args.kwargs["target_user_id"] == "portal-user-001"
        assert mock_notify_staff.call_args.kwargs["event_type"] == "shipment_update"

    def test_no_in_app_shipment_update_for_a_customer_with_no_portal_account(self):
        with patch("services.tracking.service.notify_staff") as mock_notify_staff:
            self._transition("sealed", "in_transit")

        mock_notify_staff.assert_not_called()


class TestContainerArrivedNotification:
    """Ground-truth follow-up, reported live by the user: SMS/WhatsApp/email
    can each fail for reasons entirely outside this app, and the customer
    portal itself showed nothing until they happened to open the specific
    shipment page — same gap class as shipment_update above."""

    def test_arrival_notifies_the_customer_in_app_when_they_have_a_portal_account(self):
        from services.tracking import service
        from shared.tenant_context import TenantContext, UserRole

        ctx = TenantContext(tenant_id="tenant-1", user_id="actor-1", role=UserRole.TENANT_ADMIN)
        container = {"id": "container-001", "status": "cleared", "container_number": "ACME-001"}
        updated = {**container, "status": "at_warehouse"}
        customer = {
            "id": "cust-1",
            "user_id": "portal-user-001",
            "name": "Ngozi",
            "phone": "+2348012345678",
            "email": "n@x.com",
            "whatsapp": None,
            "locale": "en",
        }

        with (
            patch.object(service.repo, "get_container_by_id", return_value=container),
            patch.object(service.repo, "update_container_status", return_value=updated),
            patch.object(service.repo, "insert_container_event"),
            patch.object(service.repo, "bulk_update_tracking_status"),
            patch.object(service.repo, "bulk_insert_tracking_events"),
            patch.object(service.repo, "get_customers_for_container", return_value=[customer]),
            patch("services.tracking.service.publish_event"),
            patch("services.tracking.service.log_audit"),
            patch("services.tracking.service.enqueue_notifications"),
            patch("services.tracking.service.notify_staff") as mock_notify_staff,
        ):
            service.update_container_status(
                "tenant-1",
                "container-001",
                "at_warehouse",
                {},
                actor_id="actor-1",
                ctx=ctx,
            )

        mock_notify_staff.assert_called_once()
        assert mock_notify_staff.call_args.kwargs["target_user_id"] == "portal-user-001"
        assert mock_notify_staff.call_args.kwargs["event_type"] == "container_arrived"

    def test_no_in_app_notification_for_a_customer_with_no_portal_account(self):
        from services.tracking import service
        from shared.tenant_context import TenantContext, UserRole

        ctx = TenantContext(tenant_id="tenant-1", user_id="actor-1", role=UserRole.TENANT_ADMIN)
        container = {"id": "container-001", "status": "cleared", "container_number": "ACME-001"}
        updated = {**container, "status": "at_warehouse"}
        customer = {
            "id": "cust-1",
            "name": "Ngozi",
            "phone": "+2348012345678",
            "email": "n@x.com",
            "whatsapp": None,
            "locale": "en",
        }

        with (
            patch.object(service.repo, "get_container_by_id", return_value=container),
            patch.object(service.repo, "update_container_status", return_value=updated),
            patch.object(service.repo, "insert_container_event"),
            patch.object(service.repo, "bulk_update_tracking_status"),
            patch.object(service.repo, "bulk_insert_tracking_events"),
            patch.object(service.repo, "get_customers_for_container", return_value=[customer]),
            patch("services.tracking.service.publish_event"),
            patch("services.tracking.service.log_audit"),
            patch("services.tracking.service.enqueue_notifications"),
            patch("services.tracking.service.notify_staff") as mock_notify_staff,
        ):
            service.update_container_status(
                "tenant-1",
                "container-001",
                "at_warehouse",
                {},
                actor_id="actor-1",
                ctx=ctx,
            )

        mock_notify_staff.assert_not_called()


class TestContainerStats:
    """GET /v1/containers/stats + /v1/billing/report-style aggregation delegation."""

    def test_container_stats_delegates_with_tenant_id(self):
        from unittest.mock import patch

        from services.tracking import service

        stub = {
            "total": 205,
            "loading": 25,
            "sealed": 16,
            "in_transit": 40,
            "arrived": 17,
            "customs_clearance": 20,
            "cleared": 30,
            "at_warehouse": 36,
            "fully_released": 17,
            "cancelled": 4,
            "cleared_30d": 83,
        }
        with patch.object(service.repo, "get_container_stats", return_value=stub) as m:
            result = service.get_container_stats("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        assert m.call_args[0][0] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        assert result["total"] == 205
