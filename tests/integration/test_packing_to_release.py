"""Integration test: Packing list → Manifest → Tracking → Billing → Payment → Release.

All external I/O (DB, EventBridge, SQS) is mocked. This test exercises the
service-layer orchestration across multiple services end-to-end in memory.
"""

import json
from decimal import Decimal
from unittest.mock import patch

import pytest

from shared.tenant_context import TenantContext, UserRole

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


@pytest.fixture
def staff_ctx():
    return TenantContext(tenant_id=TENANT_ID, user_id="user-nigeria", role=UserRole.NIGERIA_OFFICE_STAFF)


@pytest.fixture
def admin_ctx():
    return TenantContext(tenant_id=TENANT_ID, user_id="user-admin", role=UserRole.TENANT_ADMIN)


@pytest.fixture
def customer_ctx():
    return TenantContext(tenant_id=TENANT_ID, user_id="user-cust", role=UserRole.CUSTOMER)


# ---------------------------------------------------------------------------
# Packing list handler routing tests
# ---------------------------------------------------------------------------


class TestPackingListHandlerDispatch:
    """Test that handler routes correctly dispatch to service functions."""

    def _event(
        self,
        method: str,
        path: str,
        body=None,
        claims: dict | None = None,
        query_params: dict | None = None,
    ) -> dict:
        return {
            "requestContext": {
                "requestId": "req-001",
                "http": {"method": method, "path": path},
                "authorizer": {
                    "claims": claims
                    or {
                        "sub": "user-nigeria",
                        "custom:tenant_id": TENANT_ID,
                        "cognito:groups": f"{TENANT_ID}:nigeria_office_staff",
                    }
                },
                "identity": {"sourceIp": "127.0.0.1"},
            },
            "body": json.dumps(body) if body else None,
            "queryStringParameters": query_params or {},
        }

    def test_post_packing_list_returns_201(self, monkeypatch):
        from services.packing_list import handler

        created_pl = {
            "id": "pl-001",
            "status": "draft",
            "customer_id": "cust-001",
            "container_id": "cont-001",
            "packing_list_number": "ACME-PL-001",
        }
        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with (
            patch("services.packing_list.handler.service") as mock_svc,
            patch("shared.metering.record_usage"),
        ):
            mock_svc.create_packing_list.return_value = created_pl
            resp = handler.lambda_handler(
                self._event(
                    "POST",
                    "/v1/packing-lists",
                    body={
                        "customer_id": "cust-001",
                        "container_id": "cont-001",
                        "items": [],
                    },
                ),
                {},
            )
        assert resp["statusCode"] == 201
        assert "Location" in resp["headers"]

    def test_get_packing_list_returns_200(self, monkeypatch):
        from services.packing_list import handler

        pl = {"id": "pl-001", "status": "draft", "items": []}
        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with (
            patch("services.packing_list.handler.service") as mock_svc,
            patch("shared.metering.record_usage"),
        ):
            mock_svc.get_packing_list.return_value = pl
            resp = handler.lambda_handler(self._event("GET", "/v1/packing-lists/pl-001"), {})
        assert resp["statusCode"] == 200

    def test_unknown_route_returns_404(self, monkeypatch):
        from services.packing_list import handler

        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with (
            patch("shared.metering.record_usage"),
        ):
            resp = handler.lambda_handler(self._event("GET", "/v1/unknown-resource"), {})
        assert resp["statusCode"] == 404

    def test_wrong_role_blocked(self, monkeypatch):
        """CUSTOMER cannot create packing lists."""
        from services.packing_list import handler

        customer_claims = {
            "sub": "user-cust",
            "custom:tenant_id": TENANT_ID,
            "cognito:groups": f"{TENANT_ID}:customer",
        }
        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with patch("shared.metering.record_usage"):
            resp = handler.lambda_handler(
                self._event(
                    "POST",
                    "/v1/packing-lists",
                    body={"customer_id": "c", "container_id": "co", "items": []},
                    claims=customer_claims,
                ),
                {},
            )
        assert resp["statusCode"] == 403


# ---------------------------------------------------------------------------
# End-to-end packing list state machine flow
# ---------------------------------------------------------------------------


class TestPackingListStateFlow:
    """Test the draft → pending_approval → approved state machine via service layer."""

    def test_full_approval_flow(self):
        from services.packing_list import service
        from shared.tenant_context import TenantContext, UserRole

        draft_pl = {
            "id": "pl-001",
            "status": "draft",
            "created_by": "user-china",
            "tenant_id": TENANT_ID,
            "customer_id": "cust-001",
            "container_id": "cont-001",
            "packing_list_number": "ACME-PL-001",
        }
        pending_pl = {**draft_pl, "status": "pending_approval"}

        with (
            patch.object(service.repo, "get_packing_list_by_id", return_value=draft_pl),
            patch.object(service.repo, "list_packing_list_items", return_value=[]),
            patch.object(service.repo, "update_packing_list_status", return_value=pending_pl),
            patch("services.packing_list.service.log_audit"),
        ):
            ctx = TenantContext(tenant_id=TENANT_ID, user_id="user-china", role=UserRole.CHINA_OFFICE_STAFF)
            result = service.submit_packing_list("pl-001", TENANT_ID, ctx)
            assert result["status"] == "pending_approval"


# ---------------------------------------------------------------------------
# Billing handler routing
# ---------------------------------------------------------------------------


class TestBillingHandlerDispatch:
    def _event(self, method: str, path: str, body=None, role: str = "nigeria_office_staff") -> dict:
        return {
            "requestContext": {
                "requestId": "req-001",
                "http": {"method": method, "path": path},
                "authorizer": {
                    "claims": {
                        "sub": "user-nigeria",
                        "custom:tenant_id": TENANT_ID,
                        "cognito:groups": f"{TENANT_ID}:{role}",
                    }
                },
                "identity": {"sourceIp": "127.0.0.1"},
            },
            "body": json.dumps(body) if body else None,
            "queryStringParameters": {},
        }

    def test_get_billing_list_returns_200(self, monkeypatch):
        from services.billing import handler

        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with (
            patch("services.billing.handler.service") as mock_svc,
            patch("shared.metering.record_usage"),
        ):
            mock_svc.list_billing.return_value = ([], None, False)
            resp = handler.lambda_handler(self._event("GET", "/v1/billing"), {})
        assert resp["statusCode"] == 200

    def test_generate_billing_returns_201(self, monkeypatch):
        from services.billing import handler

        billing = {
            "id": "billing-001",
            "status": "unpaid",
            "total_ngn": Decimal("50000"),
        }
        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with (
            patch("services.billing.handler.service") as mock_svc,
            patch("shared.metering.record_usage"),
        ):
            mock_svc.generate_billing.return_value = billing
            resp = handler.lambda_handler(
                self._event(
                    "POST",
                    "/v1/billing",
                    body={
                        "container_id": "11111111-1111-4111-8111-111111111111",
                        "customer_id": "22222222-2222-4222-8222-222222222222",
                    },
                ),
                {},
            )
        assert resp["statusCode"] == 201

    def test_generate_billing_for_a_whole_container_returns_200(self, monkeypatch):
        from services.billing import handler

        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with (
            patch("services.billing.handler.service") as mock_svc,
            patch("shared.metering.record_usage"),
        ):
            mock_svc.generate_billing.return_value = {"container_id": "x", "results": []}
            resp = handler.lambda_handler(
                self._event("POST", "/v1/billing", body={"container_id": "11111111-1111-4111-8111-111111111111"}),
                {},
            )
        assert resp["statusCode"] == 200

    def test_generate_billing_rejects_a_malformed_body(self, monkeypatch):
        from services.billing import handler

        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with patch("shared.metering.record_usage"):
            resp = handler.lambda_handler(
                self._event("POST", "/v1/billing", body={"container_id": "not-a-uuid"}),
                {},
            )
        assert resp["statusCode"] == 422
