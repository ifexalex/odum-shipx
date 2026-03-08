"""Tenant isolation tests — API layer: JWT claims scope responses to the correct tenant.

These tests verify that the Lambda handlers extract and enforce tenant_id from
the Cognito JWT claims, and that cross-tenant requests either return 404 or
are never routed to another tenant's data.
"""
import json
from decimal import Decimal
from unittest.mock import patch

import pytest

TENANT_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TENANT_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _event(method: str, path: str, tenant_id: str, body=None, role: str = "nigeria_office_staff") -> dict:
    return {
        "requestContext": {
            "requestId": f"req-{tenant_id[:4]}",
            "http": {"method": method, "path": path},
            "authorizer": {
                "claims": {
                    "sub": f"user-{tenant_id[:4]}",
                    "custom:tenant_id": tenant_id,
                    "cognito:groups": f"{tenant_id}:{role}",
                }
            },
            "identity": {"sourceIp": "127.0.0.1"},
        },
        "body": json.dumps(body) if body else None,
        "queryStringParameters": {},
    }


# ---------------------------------------------------------------------------
# Billing handler — tenant_id from JWT scopes the query
# ---------------------------------------------------------------------------


class TestBillingApiTenantIsolation:
    def test_billing_list_uses_jwt_tenant_not_query_param(self, monkeypatch):
        """Handler derives tenant_id from JWT, not from a user-controlled param."""
        from services.billing import handler

        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with (
            patch("services.billing.handler.service") as mock_svc,
            patch("shared.metering.record_usage"),
        ):
            mock_svc.get_billing_for_customer.return_value = []
            # Billing handler: GET /v1/billing/{customer-id}
            resp = handler.lambda_handler(_event("GET", "/v1/billing/customer-001", TENANT_A), {})

        assert resp["statusCode"] == 200
        # The tenant_id passed to the service must come from JWT (TENANT_A)
        call_args = mock_svc.get_billing_for_customer.call_args
        service_tenant_id = call_args[0][0]
        assert service_tenant_id == TENANT_A

    def test_billing_list_for_tenant_b_uses_tenant_b_scope(self, monkeypatch):
        from services.billing import handler

        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with (
            patch("services.billing.handler.service") as mock_svc,
            patch("shared.metering.record_usage"),
        ):
            mock_svc.get_billing_for_customer.return_value = []
            resp = handler.lambda_handler(_event("GET", "/v1/billing/customer-001", TENANT_B), {})

        assert resp["statusCode"] == 200
        call_args = mock_svc.get_billing_for_customer.call_args
        service_tenant_id = call_args[0][0]
        assert service_tenant_id == TENANT_B

    def test_billing_resource_not_found_returns_404_not_200(self, monkeypatch):
        """Getting a billing record that doesn't exist (cross-tenant) returns 404."""
        from services.billing import handler
        from shared.exceptions import ResourceNotFoundError

        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with (
            patch("services.billing.handler.service") as mock_svc,
            patch("shared.metering.record_usage"),
        ):
            mock_svc.get_billing_for_customer.side_effect = ResourceNotFoundError("billing", "billing-B-001")
            resp = handler.lambda_handler(
                _event("GET", "/v1/billing/billing-B-001", TENANT_A), {}
            )

        assert resp["statusCode"] == 404
        body = json.loads(resp["body"])
        # Must not leak that the resource exists but is in another tenant
        assert body["status"] == 404


# ---------------------------------------------------------------------------
# Packing list handler — tenant isolation
# ---------------------------------------------------------------------------


class TestPackingListApiTenantIsolation:
    def test_list_passes_jwt_tenant(self, monkeypatch):
        from services.packing_list import handler

        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with (
            patch("services.packing_list.handler.service") as mock_svc,
            patch("shared.metering.record_usage"),
        ):
            mock_svc.list_packing_lists.return_value = ([], None, False)
            resp = handler.lambda_handler(_event("GET", "/v1/packing-lists", TENANT_A), {})

        assert resp["statusCode"] == 200
        service_tenant_id = mock_svc.list_packing_lists.call_args[0][0]
        assert service_tenant_id == TENANT_A

    def test_cross_tenant_resource_returns_404(self, monkeypatch):
        from services.packing_list import handler
        from shared.exceptions import ResourceNotFoundError

        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with (
            patch("services.packing_list.handler.service") as mock_svc,
            patch("shared.metering.record_usage"),
        ):
            mock_svc.get_packing_list.side_effect = ResourceNotFoundError("packing_list", "pl-B-001")
            resp = handler.lambda_handler(
                _event("GET", "/v1/packing-lists/pl-B-001", TENANT_A), {}
            )

        assert resp["statusCode"] == 404

    def test_tenant_b_jwt_cannot_create_under_tenant_a(self, monkeypatch):
        """A TENANT_B JWT creates packing lists only in TENANT_B's namespace."""
        from services.packing_list import handler

        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with (
            patch("services.packing_list.handler.service") as mock_svc,
            patch("shared.metering.record_usage"),
        ):
            mock_svc.create_packing_list.return_value = {
                "id": "pl-001", "tenant_id": TENANT_B, "status": "draft",
                "packing_list_number": "PL-001",
            }
            resp = handler.lambda_handler(
                _event(
                    "POST", "/v1/packing-lists", TENANT_B,
                    # valid body: items requires min_length=1 with a description
                    body={"customer_id": "cust-001", "container_id": "cont-001",
                          "items": [{"description": "Carton 1"}]},
                    role="china_office_staff",
                ),
                {},
            )

        # Handler validates body and calls service with TENANT_B's tenant_id
        assert resp["statusCode"] == 201
        service_tenant_id = mock_svc.create_packing_list.call_args[0][0]
        assert service_tenant_id == TENANT_B


# ---------------------------------------------------------------------------
# Claims handler — tenant isolation
# ---------------------------------------------------------------------------


class TestClaimsApiTenantIsolation:
    def test_list_claims_scoped_to_jwt_tenant(self, monkeypatch):
        from services.claims import handler

        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with (
            patch("services.claims.handler.service") as mock_svc,
            patch("shared.metering.record_usage"),
        ):
            mock_svc.list_claims.return_value = ([], None, False)
            resp = handler.lambda_handler(_event("GET", "/v1/claims", TENANT_A), {})

        assert resp["statusCode"] == 200
        service_tenant_id = mock_svc.list_claims.call_args[0][0]
        assert service_tenant_id == TENANT_A

    def test_cross_tenant_claim_access_returns_404(self, monkeypatch):
        from services.claims import handler
        from shared.exceptions import ResourceNotFoundError

        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with (
            patch("services.claims.handler.service") as mock_svc,
            patch("shared.metering.record_usage"),
        ):
            mock_svc.get_claim.side_effect = ResourceNotFoundError("damage_claim", "claim-B-001")
            resp = handler.lambda_handler(
                _event("GET", "/v1/claims/claim-B-001", TENANT_A), {}
            )

        assert resp["statusCode"] == 404


# ---------------------------------------------------------------------------
# Suspended tenant is blocked at auth middleware
# ---------------------------------------------------------------------------


class TestSuspendedTenantApiBlocked:
    def test_suspended_tenant_gets_403(self, monkeypatch):
        """After suspension, all API calls for that tenant return 403."""
        from services.billing import handler
        from shared.exceptions import TenantSuspendedError

        # Simulate _check_tenant_active raising TenantSuspendedError
        def _raise(tenant_id):
            if tenant_id == TENANT_B:
                raise TenantSuspendedError(TENANT_B)

        monkeypatch.setattr("shared.auth._check_tenant_active", _raise)
        with patch("shared.metering.record_usage"):
            resp = handler.lambda_handler(
                _event("GET", "/v1/billing/customer-001", TENANT_B), {}
            )

        assert resp["statusCode"] == 403

    def test_other_tenant_unaffected_by_suspension(self, monkeypatch):
        """TENANT_A is unaffected when TENANT_B is suspended."""
        from services.billing import handler

        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with (
            patch("services.billing.handler.service") as mock_svc,
            patch("shared.metering.record_usage"),
        ):
            mock_svc.get_billing_for_customer.return_value = []
            resp = handler.lambda_handler(_event("GET", "/v1/billing/customer-001", TENANT_A), {})

        assert resp["statusCode"] == 200


# ---------------------------------------------------------------------------
# Role enforcement — wrong role within same tenant
# ---------------------------------------------------------------------------


class TestRoleEnforcementWithinTenant:
    def test_warehouse_cannot_access_billing(self, monkeypatch):
        """Warehouse attendant cannot read billing records (not in _BILLING_READ_ROLES)."""
        from services.billing import handler

        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with patch("shared.metering.record_usage"):
            resp = handler.lambda_handler(
                _event(
                    "GET", "/v1/billing/customer-001", TENANT_A,
                    role="warehouse_attendant",
                ),
                {},
            )

        assert resp["statusCode"] == 403

    def test_customer_cannot_file_packing_list(self, monkeypatch):
        from services.packing_list import handler

        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with patch("shared.metering.record_usage"):
            resp = handler.lambda_handler(
                _event(
                    "POST", "/v1/packing-lists", TENANT_A,
                    body={"customer_id": "c", "container_id": "co", "items": []},
                    role="customer",
                ),
                {},
            )

        assert resp["statusCode"] == 403
