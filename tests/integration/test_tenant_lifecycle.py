"""Integration test: Tenant creation → config → users → suspend → activate."""

import json
from unittest.mock import patch

import pytest

PLATFORM_ID = "PLATFORM"


def _platform_event(method: str, path: str, body=None) -> dict:
    return {
        "requestContext": {
            "requestId": "req-tenant-001",
            "http": {"method": method, "path": path},
            "authorizer": {
                "claims": {
                    "sub": "platform-admin",
                    "custom:tenant_id": PLATFORM_ID,
                    "cognito:groups": "platform_admin",
                }
            },
            "identity": {"sourceIp": "127.0.0.1"},
        },
        "body": json.dumps(body) if body else None,
        "queryStringParameters": {},
    }


class TestTenantHandlerDispatch:
    def test_create_tenant_returns_201(self, monkeypatch):
        from services.tenant_management import handler

        tenant = {
            "id": "new-tenant-001",
            "name": "Test Tenant",
            "status": "active",
            "short_code": "TEST",
        }
        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with (
            patch("services.tenant_management.handler.service") as mock_svc,
            patch("shared.metering.record_usage"),
        ):
            mock_svc.create_tenant.return_value = tenant
            resp = handler.lambda_handler(
                _platform_event(
                    "POST",
                    "/v1/tenants",
                    body={
                        "company_name": "Test Tenant",
                        "primary_contact_email": "admin@test.com",
                        "subscription_tier": "starter",
                        "initial_admin": {
                            "email": "admin@test.com",
                            "full_name": "Test Admin",
                        },
                    },
                ),
                {},
            )
        assert resp["statusCode"] == 201

    def test_list_tenants_returns_200(self, monkeypatch):
        from services.tenant_management import handler

        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with (
            patch("services.tenant_management.handler.service") as mock_svc,
            patch("shared.metering.record_usage"),
        ):
            mock_svc.list_tenants.return_value = ([], None, False, 0)
            resp = handler.lambda_handler(_platform_event("GET", "/v1/tenants"), {})
        assert resp["statusCode"] == 200

    def test_suspend_tenant_returns_200(self, monkeypatch):
        from services.tenant_management import handler

        suspended = {"id": "tenant-001", "status": "suspended"}
        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with (
            patch("services.tenant_management.handler.service") as mock_svc,
            patch("services.tenant_management.handler.step_up.require_step_up"),  # re-authenticated (Phase 1)
            patch("shared.metering.record_usage"),
        ):
            mock_svc.suspend_tenant.return_value = suspended
            resp = handler.lambda_handler(
                _platform_event(
                    "PATCH",
                    "/v1/tenants/tenant-001/suspend",
                    body={"reason": "Non-payment"},
                ),
                {},
            )
        assert resp["statusCode"] == 200

    def test_activate_tenant_returns_200(self, monkeypatch):
        from services.tenant_management import handler

        active = {"id": "tenant-001", "status": "active"}
        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with (
            patch("services.tenant_management.handler.service") as mock_svc,
            patch("shared.metering.record_usage"),
        ):
            mock_svc.activate_tenant.return_value = active
            resp = handler.lambda_handler(
                _platform_event("PATCH", "/v1/tenants/tenant-001/activate", body={}),
                {},
            )
        assert resp["statusCode"] == 200

    def test_non_platform_admin_cannot_create_tenant(self, monkeypatch):
        from services.tenant_management import handler

        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        non_platform_event = {
            "requestContext": {
                "requestId": "req-001",
                "http": {"method": "POST", "path": "/v1/tenants"},
                "authorizer": {
                    "claims": {
                        "sub": "regular-user",
                        "custom:tenant_id": "tenant-001",
                        "cognito:groups": "tenant-001:tenant_admin",
                    }
                },
                "identity": {"sourceIp": "127.0.0.1"},
            },
            "body": json.dumps({"name": "Hack", "short_code": "HCK"}),
            "queryStringParameters": {},
        }
        with patch("shared.metering.record_usage"):
            resp = handler.lambda_handler(non_platform_event, {})
        assert resp["statusCode"] == 403


class TestTenantSuspensionEffect:
    """Verify that suspended tenants are blocked from API access."""

    def test_suspended_tenant_blocked_on_api_call(self, monkeypatch):
        """After suspension, any subsequent API call from this tenant → 403."""
        from shared.auth import get_tenant_context
        from shared.exceptions import TenantSuspendedError

        # Simulate the DB returning 'suspended' status for the tenant
        def _mock_suspended(tenant_id, query, params=None):
            return [{"status": "suspended"}]

        monkeypatch.setattr("shared.db.execute_with_tenant", _mock_suspended)

        event = {
            "requestContext": {
                "authorizer": {
                    "claims": {
                        "sub": "user-1",
                        "custom:tenant_id": "tenant-suspended",
                        "cognito:groups": "tenant-suspended:customer",
                    }
                },
                "http": {"method": "GET", "path": "/v1/billing"},
            }
        }

        # Clear the tenant status cache so the DB is actually queried
        from shared import auth

        auth._tenant_status_cache.clear()

        with pytest.raises(TenantSuspendedError):
            get_tenant_context(event)
