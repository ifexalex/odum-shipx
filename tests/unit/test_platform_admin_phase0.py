"""Platform admin audit, Phase 0 (PA-01 … PA-10): the console must not tell the operator anything untrue.

See the "ShipX Platform Admin Console: Audit and Redesign Plan" doc and ``07_api_tenant_management.md``.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

# Imported at collection time, before tests/conftest.py's autouse fixture stubs it out for handler suites.
from shared.auth import _check_maintenance_mode as real_check_maintenance_mode
from shared.exceptions import MaintenanceModeError, ServiceUnavailableError
from shared.seats import staff_seat_condition
from shared.tenant_context import TenantContext, UserRole

TENANT_ID = "11111111-1111-1111-1111-111111111111"


def _platform_event(method: str, path: str, query: dict | None = None, body: dict | None = None) -> dict:
    return {
        "requestContext": {
            "requestId": "req-pa-1",
            "http": {"method": method, "path": path},
            "authorizer": {"claims": {"sub": "platform-admin-1", "custom:tenant_id": "PLATFORM"}},
            "identity": {"sourceIp": "127.0.0.1"},
        },
        "headers": {},
        "body": json.dumps(body) if body is not None else None,
        "queryStringParameters": query or {},
        "pathParameters": {},
    }


def _platform_ctx() -> TenantContext:
    return TenantContext(
        tenant_id="PLATFORM",
        user_id="platform-admin-1",
        role=UserRole.PLATFORM_ADMIN,
        platform_user_id="pu-1",
        platform_role="owner",
    )


def _call(event: dict) -> dict:
    from services.tenant_management import handler

    with patch("services.tenant_management.handler.get_tenant_context", return_value=_platform_ctx()):
        return handler.lambda_handler(event, None)


# ---------------------------------------------------------------------------
# PA-01 — maintenance mode answers with its own code
# ---------------------------------------------------------------------------


class TestMaintenanceModeCode:
    def test_the_error_is_a_503_with_its_own_code(self):
        err = MaintenanceModeError()
        assert err.status_code == 503
        assert err.error_code == "MAINTENANCE_MODE"
        assert isinstance(err, ServiceUnavailableError)

    def test_the_check_raises_it_when_maintenance_is_on(self):
        cache = MagicMock()
        cache.get.return_value = None
        with (
            patch("shared.auth._maintenance_cache", cache),
            patch("shared.db.execute_with_tenant", return_value=[{"value": True}]),
        ):
            with pytest.raises(MaintenanceModeError):
                real_check_maintenance_mode()

    def test_a_cached_flag_raises_it_too(self):
        cache = MagicMock()
        cache.get.return_value = "1"
        with patch("shared.auth._maintenance_cache", cache), pytest.raises(MaintenanceModeError):
            real_check_maintenance_mode()

    def test_nothing_is_raised_when_maintenance_is_off(self):
        cache = MagicMock()
        cache.get.return_value = "0"
        with patch("shared.auth._maintenance_cache", cache):
            real_check_maintenance_mode()


# ---------------------------------------------------------------------------
# PA-02 — the tenant list pages, filters and searches on the server
# ---------------------------------------------------------------------------


class TestTenantListRoute:
    def test_returns_the_paginated_envelope_with_a_total(self):
        page = [{"id": TENANT_ID, "company_name": "Acme", "subscription_tier": "starter"}]
        with patch(
            "services.tenant_management.handler.service.list_tenants",
            return_value=(page, "next-cursor", True, 120),
        ) as list_tenants:
            resp = _call(_platform_event("GET", "/v1/platform/tenants", {"limit": "50"}))

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["data"] == page
        assert body["meta"]["pagination"] == {"has_more": True, "next_cursor": "next-cursor", "total_count": 120}
        assert list_tenants.call_args.kwargs["limit"] == 50

    def test_passes_status_tier_and_search_through(self):
        with patch("services.tenant_management.handler.service.list_tenants", return_value=([], None, False, 0)) as list_tenants:
            _call(_platform_event("GET", "/v1/platform/tenants", {"status": "suspended", "tier": "business", "q": " acme "}))

        kwargs = list_tenants.call_args.kwargs
        assert (kwargs["status"], kwargs["tier"], kwargs["q"]) == ("suspended", "business", "acme")

    def test_an_unknown_status_is_refused(self):
        with patch("services.tenant_management.handler.service.list_tenants") as list_tenants:
            resp = _call(_platform_event("GET", "/v1/platform/tenants", {"status": "deleted"}))
        assert resp["statusCode"] == 422
        list_tenants.assert_not_called()


class TestTenantListQuery:
    def _run(self, **filters):
        from services.tenant_management import repository as repo

        calls: list[tuple[str, dict]] = []

        def fake(_tenant, query, params=None):
            calls.append((" ".join(query.split()), params or {}))
            return [{"cnt": 3}] if "COUNT(*) AS cnt" in query and "LATERAL" not in query else []

        with patch.object(repo, "execute_with_tenant", side_effect=fake):
            result = repo.list_tenants(limit=50, **filters)
        return result, calls

    def test_counts_staff_seats_only(self):
        _, calls = self._run()
        assert staff_seat_condition("tu") in calls[0][0]

    def test_filters_apply_to_both_the_page_and_the_total(self):
        (_, _, _, total), calls = self._run(status="active", tier="starter", q="acme")
        page_sql, page_params = calls[0]
        count_sql, count_params = calls[1]
        for sql in (page_sql, count_sql):
            assert "t.status = %(status)s" in sql
            assert "t.subscription_tier = %(tier)s" in sql
            assert "t.company_name ILIKE %(q)s ESCAPE" in sql
        assert page_params["q"] == count_params["q"] == "%acme%"
        assert total == 3

    def test_search_wildcards_are_matched_literally(self):
        from services.tenant_management.repository import _like_pattern

        assert _like_pattern("50%_off\\") == "%50\\%\\_off\\\\%"


# ---------------------------------------------------------------------------
# PA-03 — one seat rule everywhere
# ---------------------------------------------------------------------------


class TestStaffSeats:
    def test_the_condition_excludes_customers_and_inactive_users(self):
        assert staff_seat_condition("tu") == "tu.status = 'active' AND tu.role <> 'customer'"

    def test_a_non_identifier_alias_is_refused(self):
        with pytest.raises(ValueError):
            staff_seat_condition("tu; DROP TABLE tenant")

    def test_metering_usage_counts_staff_seats(self):
        from services.metering import repository as metering_repo

        with patch.object(metering_repo, "execute_with_tenant", return_value=[{"cnt": 4}]) as execute:
            assert metering_repo.count_active_tenant_users(TENANT_ID) == 4
        assert staff_seat_condition() in execute.call_args.args[1]

    def test_the_dashboard_counts_staff_seats(self):
        from services.tenant_management import repository as repo

        queries: list[str] = []

        def fake(_tenant, query, params=None):
            queries.append(query)
            return [{"total_users": 0, "total_containers": 0}]

        with patch.object(repo, "execute_with_tenant", side_effect=fake):
            repo.get_dashboard_stats()
        assert any("total_users" in q and staff_seat_condition() in q for q in queries)


# ---------------------------------------------------------------------------
# PA-04 — the offboarding reason is required and stored
# ---------------------------------------------------------------------------


class TestOffboardingReason:
    def test_a_missing_reason_is_refused(self):
        with patch("services.tenant_management.handler.service.offboard_tenant") as offboard:
            resp = _call(_platform_event("DELETE", f"/v1/platform/tenants/{TENANT_ID}", body={}))
        assert resp["statusCode"] == 422
        offboard.assert_not_called()

    def test_a_blank_reason_is_refused(self):
        with patch("services.tenant_management.handler.service.offboard_tenant") as offboard:
            resp = _call(_platform_event("DELETE", f"/v1/platform/tenants/{TENANT_ID}", body={"reason": "   "}))
        assert resp["statusCode"] == 422
        offboard.assert_not_called()

    def test_the_reason_reaches_the_approval_request(self):
        # Since Phase 1 an offboarding goes through a two-person approval (decision D4); the reason travels with it.
        tenant = {"id": TENANT_ID, "status": "active", "company_name": "Acme", "slug": "acme"}
        with (
            patch("services.tenant_management.handler.service.get_tenant", return_value=tenant),
            patch("services.tenant_management.handler.step_up.require_step_up"),
            patch(
                "services.tenant_management.handler.approvals.request_protected_action",
                return_value={"outcome": "pending_approval", "approval": {"id": "a-1"}},
            ) as request,
        ):
            resp = _call(_platform_event("DELETE", f"/v1/platform/tenants/{TENANT_ID}", body={"reason": " Contract ended "}))
        assert resp["statusCode"] == 202
        protected = request.call_args.args[1]
        assert protected.reason == "Contract ended"
        assert protected.payload == {"tenant_id": TENANT_ID, "reason": "Contract ended"}


# ---------------------------------------------------------------------------
# PA-02 / PA-06 — audit rows name their tenant and actor
# ---------------------------------------------------------------------------


class TestAuditLogRows:
    def test_each_row_carries_its_tenant_name(self):
        from services.tenant_management import repository as repo

        with patch.object(repo, "execute_with_tenant", return_value=[]) as execute:
            repo.list_platform_audit_log(limit=50, target_tenant_id=TENANT_ID, action="TENANT_SUSPENDED")
        sql = " ".join(execute.call_args.args[1].split())
        assert "t.company_name AS target_tenant_name" in sql
        assert "LEFT JOIN tenant t ON t.id = pal.target_tenant_id" in sql
        params = execute.call_args.args[2]
        assert params["target_tenant_id"] == TENANT_ID
        assert params["action"] == "TENANT_SUSPENDED"


# ---------------------------------------------------------------------------
# PA-10 — metering no longer answers for the dashboard
# ---------------------------------------------------------------------------


class TestMeteringDashboardPlaceholderIsGone:
    def test_metering_returns_404_for_the_dashboard(self):
        from services.metering import handler as metering_handler

        event = _platform_event("GET", "/v1/platform/dashboard")
        with patch("services.metering.handler.get_tenant_context", return_value=_platform_ctx()):
            resp = metering_handler.lambda_handler(event, None)
        assert resp["statusCode"] == 404
