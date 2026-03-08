"""Integration test: CBM dispute → investigation → resolution → billing adjustment."""
import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from shared.tenant_context import TenantContext, UserRole

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

_CLAIMS_ROLE = "nigeria_office_staff"


def _event(method: str, path: str, body=None, role: str = _CLAIMS_ROLE) -> dict:
    return {
        "requestContext": {
            "requestId": "req-dispute-001",
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


class TestDisputeHandlerFlow:
    def test_list_disputes_returns_200(self, monkeypatch):
        from services.billing import handler

        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with (
            patch("services.billing.handler.service") as mock_svc,
            patch("shared.metering.record_usage"),
        ):
            mock_svc.list_disputes.return_value = ([], None, False)
            resp = handler.lambda_handler(_event("GET", "/v1/billing/disputes"), {})
        assert resp["statusCode"] == 200

    def test_create_dispute_returns_201(self, monkeypatch):
        from services.billing import handler

        dispute = {
            "id": "dispute-001",
            "status": "open",
            "disputed_cbm": Decimal("5.5"),
        }
        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with (
            patch("services.billing.handler.service") as mock_svc,
            patch("shared.metering.record_usage"),
        ):
            mock_svc.create_dispute.return_value = dispute
            resp = handler.lambda_handler(
                _event(
                    "POST",
                    "/v1/billing/disputes",
                    body={
                        "billing_id": "billing-001",
                        "customer_id": "cust-001",
                        "disputed_cbm": "5.5",
                        "dispute_reason": "Wrong measurement",
                    },
                ),
                {},
            )
        assert resp["statusCode"] == 201

    def test_reject_dispute_returns_200(self, monkeypatch):
        from services.billing import handler

        dispute = {"id": "dispute-001", "status": "rejected"}
        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with (
            patch("services.billing.handler.service") as mock_svc,
            patch("shared.metering.record_usage"),
        ):
            mock_svc.reject_dispute.return_value = dispute
            resp = handler.lambda_handler(
                _event(
                    "PATCH",
                    "/v1/billing/disputes/dispute-001/reject",
                    body={"reason": "Measurement confirmed correct"},
                ),
                {},
            )
        assert resp["statusCode"] == 200

    def test_customer_cannot_create_dispute(self, monkeypatch):
        from services.billing import handler

        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with patch("shared.metering.record_usage"):
            resp = handler.lambda_handler(
                _event(
                    "POST",
                    "/v1/billing/disputes",
                    body={
                        "billing_id": "b",
                        "disputed_cbm": "5.5",
                        "dispute_reason": "Wrong",
                    },
                    role="customer",
                ),
                {},
            )
        assert resp["statusCode"] == 403


class TestDisputeServiceFlow:
    """Test dispute service state machine via mocked repo."""

    def test_escalation_changes_status(self):
        from services.billing import service
        from shared.tenant_context import TenantContext, UserRole

        dispute = {
            "id": "dispute-001",
            "tenant_id": TENANT_ID,
            "billing_id": "billing-001",
            "customer_id": "cust-001",
            "status": "under_review",
            "disputed_cbm": Decimal("5.5"),
        }
        escalated = {**dispute, "status": "escalated"}

        with (
            patch.object(service.repo, "get_dispute_by_id", return_value=dispute),
            patch.object(service.repo, "update_dispute_status", return_value=escalated),
            patch("services.billing.service.log_audit"),
        ):
            ctx = TenantContext(
                tenant_id=TENANT_ID,
                user_id="user-nigeria",
                role=UserRole.NIGERIA_OFFICE_STAFF,
            )
            result = service.escalate_dispute(TENANT_ID, "dispute-001", ctx=ctx)
            assert result["status"] == "escalated"
